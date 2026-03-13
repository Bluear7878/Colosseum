from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse

from colosseum.bootstrap import get_orchestrator

logger = logging.getLogger("colosseum.api")
from colosseum.core.models import (
    ExperimentRun,
    GeneratedPersona,
    HumanJudgeActionRequest,
    JudgeActionType,
    JudgeMode,
    JudgeVerdict,
    PersonaProfileRequest,
    ProviderQuotaBatchUpdate,
    ProviderQuotaState,
    RoundType,
    RunCreateRequest,
    RunListItem,
    RunStatus,
    VerdictType,
)


router = APIRouter()

# ── Skip signal registry ──
# Maps run_id → asyncio.Event. The SSE stream registers an event when a
# debate round starts; the POST /runs/{run_id}/skip-round endpoint sets it.
_skip_signals: dict[str, asyncio.Event] = {}
_cancel_signals: dict[str, asyncio.Event] = {}


def _register_skip_signal(run_id: str) -> asyncio.Event:
    event = asyncio.Event()
    _skip_signals[run_id] = event
    return event


def _register_cancel_signal(run_id: str) -> asyncio.Event:
    event = asyncio.Event()
    _cancel_signals[run_id] = event
    return event


def _cleanup_skip_signal(run_id: str) -> None:
    _skip_signals.pop(run_id, None)


def _cleanup_cancel_signal(run_id: str) -> None:
    _cancel_signals.pop(run_id, None)


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/setup/status")
async def setup_status() -> list[dict]:
    """Return install/auth status of all CLI provider tools."""
    from colosseum.cli import get_all_tool_statuses
    return get_all_tool_statuses()


@router.get("/models")
async def list_models() -> list[dict]:
    """Return dynamically discovered model list from installed CLIs."""
    from colosseum.cli import discover_models
    return discover_models()


@router.get("/cli-versions")
async def cli_versions() -> dict:
    """Return cached CLI version info."""
    from colosseum.cli import get_cli_versions
    return get_cli_versions()


@router.post("/models/refresh")
async def refresh_models() -> list[dict]:
    """Force re-probe all provider models."""
    import asyncio
    from colosseum.cli import probe_all_models
    loop = asyncio.get_event_loop()
    models = await loop.run_in_executor(None, probe_all_models)
    return models


@router.post("/setup/install/{tool_name}")
async def install_tool(tool_name: str) -> dict:
    """Attempt to install a CLI tool by name."""
    import shutil
    import subprocess as _sp

    from colosseum.cli import CLI_AUTH_INFO, _check_tool_status, _install_tool

    if tool_name not in CLI_AUTH_INFO:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    info = CLI_AUTH_INFO[tool_name]

    # Check prerequisite
    requires = info.get("install_requires")
    if requires and not shutil.which(requires):
        return {
            "success": False,
            "tool": tool_name,
            "error": f"Prerequisite '{requires}' not found. Install Node.js first: https://nodejs.org/",
        }

    install_cmd = info["install_cmd"]
    try:
        result = _sp.run(install_cmd, shell=True, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and shutil.which(info["cmd"]):
            status = _check_tool_status(tool_name, info)
            return {"success": True, "tool": tool_name, "status": status}
        else:
            return {
                "success": False,
                "tool": tool_name,
                "error": result.stderr.strip()[:300] or "Install failed",
            }
    except _sp.TimeoutExpired:
        return {"success": False, "tool": tool_name, "error": "Install timed out"}
    except Exception as e:
        return {"success": False, "tool": tool_name, "error": str(e)}


@router.post("/runs", response_model=ExperimentRun)
async def create_run(
    request: RunCreateRequest,
    orchestrator=Depends(get_orchestrator),
) -> ExperimentRun:
    logger.info("POST /runs — agents=%s, task=%r", [a.agent_id for a in request.agents], request.task.title)
    try:
        result = await orchestrator.create_run(request)
        logger.info("POST /runs — completed run_id=%s status=%s", result.run_id, result.status)
        return result
    except Exception as exc:  # pragma: no cover - API guard
        logger.error("POST /runs — FAILED\n%s", traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/runs/stream")
async def create_run_stream(
    request: RunCreateRequest,
    orchestrator=Depends(get_orchestrator),
):
    logger.info("POST /runs/stream — agents=%s, task=%r", [a.agent_id for a in request.agents], request.task.title)
    try:
        orchestrator.provider_runtime.validate_agents_selectable(request.agents)
        if request.judge.mode == JudgeMode.AI:
            if not request.judge.provider:
                raise ValueError("AI judge mode requires a judge provider.")
            orchestrator.provider_runtime.validate_provider_selectable(request.judge.provider, "AI judge")
    except Exception as exc:
        logger.error("POST /runs/stream — validation failed\n%s", traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_stream():
        from colosseum.services.event_bus import DebateEventBus

        run = ExperimentRun(
            project_name=request.project_name,
            encourage_internet_search=request.encourage_internet_search,
            response_language=request.response_language,
            task=request.task,
            agents=request.agents,
            judge=request.judge,
            paid_provider_policy=request.paid_provider_policy,
            budget_policy=request.budget_policy,
        )

        bus = DebateEventBus(run.run_id)
        bus.emit("debate_start", {
            "topic": run.task.title,
            "token_budget": run.budget_policy.total_token_budget,
            "max_rounds": run.budget_policy.max_rounds,
            "agents": [
                {"agent_id": a.agent_id, "display_name": a.display_name}
                for a in run.agents
            ],
        })

        # Phase: init
        yield f"data: {json.dumps({'phase': 'init', 'run_id': run.run_id})}\n\n"

        try:
            # Phase: context
            yield f"data: {json.dumps({'phase': 'context', 'message': 'Freezing context...'})}\n\n"
            bus.emit("phase", {"phase": "context", "message": "Freezing context...", "status": "planning"})
            run.context_bundle = orchestrator.context_service.freeze(request.context_sources)
            orchestrator.repository.save_run(run)

            # Phase: planning - stream per-agent
            yield f"data: {json.dumps({'phase': 'planning', 'message': 'Generating plans...'})}\n\n"
            bus.emit("phase", {"phase": "planning", "message": "Generating plans...", "status": "planning"})
            run.status = RunStatus.PLANNING
            async for event_type, event_data in orchestrator._generate_plans_streaming(run):
                bus.emit(event_type, event_data)
                if event_type == "agent_planning":
                    yield f"data: {json.dumps({'phase': 'agent_planning', 'agent_id': event_data['agent_id'], 'display_name': event_data['display_name']})}\n\n"
                elif event_type == "plan_ready":
                    yield f"data: {json.dumps({'phase': 'plan_ready', 'agent_id': event_data['agent_id'], 'display_name': event_data['display_name'], 'plan_id': event_data['plan_id'], 'summary': event_data['summary'], 'strengths': event_data['strengths'], 'weaknesses': event_data['weaknesses']})}\n\n"
                elif event_type == "plan_failed":
                    yield f"data: {json.dumps({'phase': 'plan_failed', 'agent_id': event_data['agent_id'], 'display_name': event_data['display_name'], 'error': event_data['error']})}\n\n"

            run.plan_evaluations = orchestrator.judge_service.evaluate_plans(run.plans)

            # Send plans summary
            plans_data = [{"plan_id": p.plan_id, "display_name": p.display_name, "agent_id": p.agent_id, "summary": p.summary, "strengths": p.strengths, "weaknesses": p.weaknesses, "architecture": p.architecture} for p in run.plans]
            evals_data = [{"plan_id": e.plan_id, "overall_score": e.overall_score} for e in run.plan_evaluations]
            yield f"data: {json.dumps({'phase': 'plans_ready', 'plans': plans_data, 'evaluations': evals_data})}\n\n"

            # ── Single-agent auto-win ──
            if len(run.agents) == 1:
                sole_plan = run.plans[0]
                run.verdict = JudgeVerdict(
                    judge_mode=run.judge.mode,
                    verdict_type=VerdictType.WINNER,
                    winning_plan_ids=[sole_plan.plan_id],
                    rationale=f"{sole_plan.display_name} is the only surviving gladiator after planning. Debate skipped.",
                    selected_strengths=sole_plan.strengths[:4],
                    rejected_risks=[r.title for r in sole_plan.risks[:3]],
                    stop_reason="single_agent_remaining",
                    confidence=1.0,
                )
                run.status = RunStatus.COMPLETED
                run.stop_reason = "single_agent_remaining"
                run.updated_at = datetime.now(timezone.utc)
                orchestrator.repository.save_run(run)

                v = run.verdict
                verdict_data = {
                    "verdict_type": v.verdict_type.value,
                    "winning_plan_ids": v.winning_plan_ids,
                    "rationale": v.rationale,
                    "selected_strengths": v.selected_strengths,
                    "rejected_risks": v.rejected_risks,
                    "stop_reason": v.stop_reason,
                    "confidence": v.confidence,
                }
                budget_by_actor = {
                    aid: {"total_tokens": u.total_tokens, "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens}
                    for aid, u in run.budget_ledger.by_actor.items()
                }
                yield f"data: {json.dumps({'phase': 'single_agent_victory', 'agent_id': run.agents[0].agent_id, 'display_name': sole_plan.display_name})}\n\n"
                yield f"data: {json.dumps({'phase': 'complete', 'verdict': verdict_data, 'budget_total': run.budget_ledger.total.total_tokens, 'budget_by_actor': budget_by_actor})}\n\n"
                return

            if run.judge.mode == JudgeMode.HUMAN:
                run.status = RunStatus.AWAITING_HUMAN_JUDGE
                run.human_judge_packet = orchestrator.judge_service.build_human_packet(run)
                run.updated_at = datetime.now(timezone.utc)
                orchestrator.repository.save_run(run)
                yield f"data: {json.dumps({'phase': 'human_required', 'run_id': run.run_id})}\n\n"
                return

            # Phase: debate rounds
            skip_event = _register_skip_signal(run.run_id)
            cancel_event = _register_cancel_signal(run.run_id)

            try:
              while True:
                # Reset skip event for each round
                skip_event.clear()

                # Check cancel signal
                if cancel_event.is_set():
                    run.status = RunStatus.COMPLETED
                    run.stop_reason = "cancelled_by_user"
                    run.updated_at = datetime.now(timezone.utc)
                    orchestrator.repository.save_run(run)
                    yield f"data: {json.dumps({'phase': 'cancelled', 'message': 'Debate cancelled by user.'})}\n\n"
                    return

                decision = await orchestrator.judge_service.decide(run)
                run.judge_trace.append(decision)

                # Emit judge decision to SSE so UI can show reasoning
                judge_evt = {
                    'phase': 'judge_decision',
                    'action': decision.action.value,
                    'reasoning': decision.reasoning,
                    'confidence': decision.confidence,
                    'disagreement_level': decision.disagreement_level,
                    'budget_pressure': decision.budget_pressure,
                    'next_round_type': decision.next_round_type.value if decision.next_round_type else None,
                    'agenda_title': decision.agenda.title if decision.agenda else "",
                    'agenda_question': decision.agenda.question if decision.agenda else "",
                    'agenda_why_it_matters': decision.agenda.why_it_matters if decision.agenda else "",
                    'focus_areas': decision.focus_areas,
                    'rounds_completed': len(run.debate_rounds),
                    'max_rounds': run.budget_policy.max_rounds,
                }
                bus.emit("judge_decision", {
                    "action": decision.action.value,
                    "confidence": decision.confidence,
                    "disagreement_level": decision.disagreement_level,
                    "focus": ", ".join(decision.focus_areas[:3]) if decision.focus_areas else "",
                    "next_round_type": decision.next_round_type.value if decision.next_round_type else "",
                    "agenda_title": decision.agenda.title if decision.agenda else "",
                    "agenda_question": decision.agenda.question if decision.agenda else "",
                })
                yield f"data: {json.dumps(judge_evt)}\n\n"

                if decision.action == JudgeActionType.FINALIZE:
                    break

                if not orchestrator.budget_manager.can_start_round(
                    run.budget_policy, run.budget_ledger, len(run.debate_rounds) + 1
                ):
                    break

                round_type = decision.next_round_type or RoundType.CRITIQUE
                round_idx = len(run.debate_rounds) + 1
                round_timeout = run.budget_policy.timeout_for_round(round_idx)
                bus.emit("debate_round_start", {"round_index": round_idx, "round_type": round_type.value})
                bus.emit("phase", {"phase": "debate", "message": f"Round {round_idx}: {round_type.value}", "status": "debating"})
                yield f"data: {json.dumps({'phase': 'debate_round', 'round_index': round_idx, 'round_type': round_type.value, 'message': f'Round {round_idx}: {round_type.value}...', 'agenda_title': decision.agenda.title if decision.agenda else '', 'agenda_question': decision.agenda.question if decision.agenda else '', 'timeout_seconds': round_timeout or None})}\n\n"

                run.status = RunStatus.DEBATING
                debate_round = None
                async for event_type, event_data in orchestrator.debate_engine.run_round_streaming(
                    run,
                    round_type=round_type,
                    agenda=decision.agenda,
                    instructions="Focus on the current judge agenda only.",
                    skip_event=skip_event,
                    cancel_event=cancel_event,
                ):
                    if isinstance(event_data, dict):
                        bus.emit(event_type, event_data)
                    if event_type == "agent_thinking":
                        yield f"data: {json.dumps({'phase': 'agent_thinking', 'agent_id': event_data['agent_id'], 'display_name': event_data['display_name'], 'round_index': event_data['round_index']})}\n\n"
                    elif event_type == "agent_message":
                        yield f"data: {json.dumps({'phase': 'agent_message', 'agent_id': event_data['agent_id'], 'display_name': event_data['display_name'], 'content': event_data['content'], 'critique_count': event_data['critique_count'], 'defense_count': event_data['defense_count'], 'concession_count': event_data['concession_count'], 'novelty_score': event_data['novelty_score'], 'usage': event_data['usage'], 'round_index': event_data['round_index']})}\n\n"
                    elif event_type == "round_skipped":
                        yield f"data: {json.dumps({'phase': 'round_skipped', 'round_index': event_data['round_index'], 'messages_collected': event_data['messages_collected']})}\n\n"
                    elif event_type == "round_cancelled":
                        yield f"data: {json.dumps({'phase': 'round_cancelled', 'round_index': event_data['round_index'], 'messages_collected': event_data['messages_collected']})}\n\n"
                    elif event_type == "round_complete":
                        debate_round = event_data

                if debate_round is not None:
                    debate_round.adjudication = orchestrator.judge_service.adjudicate_round(run, debate_round)
                    run.debate_rounds.append(debate_round)

                    # Send round data
                    round_data = {
                        "index": debate_round.index,
                        "round_type": debate_round.round_type.value,
                        "purpose": debate_round.purpose,
                        "agenda": debate_round.agenda.model_dump(mode="json") if debate_round.agenda else None,
                        "adjudication": debate_round.adjudication.model_dump(mode="json") if debate_round.adjudication else None,
                        "usage": {"total_tokens": debate_round.usage.total_tokens, "prompt_tokens": debate_round.usage.prompt_tokens, "completion_tokens": debate_round.usage.completion_tokens},
                        "summary": {
                            "key_disagreements": debate_round.summary.key_disagreements,
                            "strongest_arguments": debate_round.summary.strongest_arguments,
                            "hybrid_opportunities": debate_round.summary.hybrid_opportunities,
                            "moderator_note": debate_round.summary.moderator_note,
                        },
                        "messages": [{"agent_id": m.agent_id, "content": m.content, "novelty_score": m.novelty_score, "usage": {"total_tokens": m.usage.total_tokens}} for m in debate_round.messages],
                    }
                    yield f"data: {json.dumps({'phase': 'round_complete', 'round': round_data})}\n\n"

                run.updated_at = datetime.now(timezone.utc)
                orchestrator.repository.save_run(run)

                # Check cancel signal after round completes
                if cancel_event.is_set():
                    run.status = RunStatus.COMPLETED
                    run.stop_reason = "cancelled_by_user"
                    run.updated_at = datetime.now(timezone.utc)
                    orchestrator.repository.save_run(run)
                    yield f"data: {json.dumps({'phase': 'cancelled', 'message': 'Debate cancelled by user.'})}\n\n"
                    return
            finally:
                _cleanup_skip_signal(run.run_id)
                _cleanup_cancel_signal(run.run_id)

            # Phase: verdict
            bus.emit("phase", {"phase": "verdict", "message": "Rendering final verdict...", "status": "debating"})
            yield f"data: {json.dumps({'phase': 'judging', 'message': 'Rendering final verdict...'})}\n\n"
            last_decision = run.judge_trace[-1] if run.judge_trace else None
            run.verdict = await orchestrator.judge_service.finalize(run, last_decision)

            # Phase: report synthesis
            yield f"data: {json.dumps({'phase': 'synthesizing_report', 'message': 'Synthesizing executive report...'})}\n\n"
            run.final_report = await orchestrator.report_synthesizer.synthesize(run)

            run.status = RunStatus.COMPLETED
            run.stop_reason = last_decision.reasoning if last_decision else "judge_finalize"
            run.updated_at = datetime.now(timezone.utc)
            orchestrator.repository.save_run(run)

            # Send verdict
            v = run.verdict
            verdict_data: dict[str, object] = {}
            if v is not None:
                verdict_data = {
                    "verdict_type": v.verdict_type.value,
                    "winning_plan_ids": v.winning_plan_ids,
                    "rationale": v.rationale,
                    "selected_strengths": v.selected_strengths,
                    "rejected_risks": v.rejected_risks,
                    "stop_reason": v.stop_reason,
                    "confidence": v.confidence,
                }
                if v.synthesized_plan:
                    verdict_data["synthesized_plan"] = {"summary": v.synthesized_plan.summary}

            # Budget per actor
            budget_by_actor = {}
            for actor_id, usage in run.budget_ledger.by_actor.items():
                budget_by_actor[actor_id] = {"total_tokens": usage.total_tokens, "prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens}

            # Final report data
            final_report_data = None
            if run.final_report:
                final_report_data = run.final_report.model_dump(mode="json")

            # Emit verdict + complete to event bus
            winner_names = []
            for wid in (v.winning_plan_ids if v else []):
                plan = next((p for p in run.plans if p.plan_id == wid), None)
                winner_names.append(plan.display_name if plan else wid[:8])
            bus.emit("verdict", {
                "verdict_type": v.verdict_type.value if v else "none",
                "winners": winner_names,
                "confidence": v.confidence if v else 0,
            })
            bus.emit("phase", {"phase": "complete", "status": "completed"})

            yield f"data: {json.dumps({'phase': 'complete', 'verdict': verdict_data, 'budget_total': run.budget_ledger.total.total_tokens, 'budget_by_actor': budget_by_actor, 'final_report': final_report_data})}\n\n"

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("SSE stream error in run %s:\n%s", run.run_id, tb)
            bus.emit("error", {"message": str(exc)})
            yield f"data: {json.dumps({'phase': 'error', 'message': str(exc), 'traceback': tb})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/runs", response_model=list[RunListItem])
async def list_runs(
    orchestrator=Depends(get_orchestrator),
) -> list[RunListItem]:
    return orchestrator.list_runs()


@router.post("/runs/{run_id}/skip-round")
async def skip_round(run_id: str) -> dict:
    """Signal the running debate to skip the current round."""
    event = _skip_signals.get(run_id)
    if not event:
        raise HTTPException(status_code=404, detail="No active debate round for this run.")
    event.set()
    return {"skipped": True, "run_id": run_id}


@router.post("/runs/{run_id}/cancel")
async def cancel_debate(run_id: str) -> dict:
    """Signal the running debate to cancel entirely."""
    cancel_ev = _cancel_signals.get(run_id)
    skip_ev = _skip_signals.get(run_id)
    if not cancel_ev:
        raise HTTPException(status_code=404, detail="No active debate for this run.")
    cancel_ev.set()
    # Also set skip to break out of any in-progress round immediately
    if skip_ev:
        skip_ev.set()
    return {"cancelled": True, "run_id": run_id}


@router.get("/provider-quotas", response_model=list[ProviderQuotaState])
async def list_provider_quotas(
    orchestrator=Depends(get_orchestrator),
) -> list[ProviderQuotaState]:
    return orchestrator.provider_runtime.list_quota_states()


@router.put("/provider-quotas", response_model=list[ProviderQuotaState])
async def update_provider_quotas(
    request: ProviderQuotaBatchUpdate,
    orchestrator=Depends(get_orchestrator),
) -> list[ProviderQuotaState]:
    return orchestrator.provider_runtime.upsert_quota_states(request.states)


@router.get("/runs/{run_id}", response_model=ExperimentRun)
async def get_run(
    run_id: str,
    orchestrator=Depends(get_orchestrator),
) -> ExperimentRun:
    try:
        return orchestrator.load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/pdf")
async def download_run_pdf(
    run_id: str,
    orchestrator=Depends(get_orchestrator),
):
    try:
        run = orchestrator.load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from colosseum.services.pdf_report import generate_pdf

    pdf_bytes = generate_pdf(run)
    filename = f"colosseum-report-{run_id[:8]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/runs/{run_id}/judge-actions", response_model=ExperimentRun)
async def continue_human_run(
    run_id: str,
    request: HumanJudgeActionRequest,
    orchestrator=Depends(get_orchestrator),
) -> ExperimentRun:
    try:
        return await orchestrator.continue_human_run(run_id, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - API guard
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/personas")
async def list_personas():
    from colosseum.personas.loader import PersonaLoader  # type: ignore[import-not-found]
    loader = PersonaLoader()
    return loader.list_personas()


@router.post("/personas/generate", response_model=GeneratedPersona)
async def generate_persona(request: PersonaProfileRequest) -> GeneratedPersona:
    from colosseum.personas.generator import PersonaGenerator  # type: ignore[import-not-found]

    generator = PersonaGenerator()
    return generator.generate(request)


@router.get("/personas/{persona_id}")
async def get_persona(persona_id: str):
    from colosseum.personas.loader import PersonaLoader  # type: ignore[import-not-found]
    loader = PersonaLoader()
    content = loader.load_persona(persona_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    return {"persona_id": persona_id, "content": content}


@router.post("/personas")
async def create_persona(request: dict):
    from colosseum.personas.loader import PersonaLoader  # type: ignore[import-not-found]
    persona_id = request.get("persona_id", "")
    content = request.get("content", "")
    if not persona_id or not content:
        raise HTTPException(status_code=400, detail="persona_id and content are required")
    loader = PersonaLoader()
    meta = loader.save_custom_persona(persona_id, content)
    return meta


@router.delete("/personas/{persona_id}")
async def delete_persona(persona_id: str):
    from colosseum.personas.loader import PersonaLoader  # type: ignore[import-not-found]
    loader = PersonaLoader()
    deleted = loader.delete_custom_persona(persona_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom persona not found")
    return {"deleted": persona_id}
