"""Run creation, streaming, inspection, and human-judge endpoints."""

from __future__ import annotations

import asyncio
import logging
import traceback

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from colosseum.bootstrap import get_orchestrator
from colosseum.core.models import (
    DebateRound,
    ExperimentRun,
    HumanJudgeActionRequest,
    JudgeActionType,
    JudgeMode,
    JudgeVerdict,
    RunCreateRequest,
    RunListItem,
    RunStatus,
    RoundType,
    VerdictType,
)
from colosseum.services.event_bus import DebateEventBus

from .signals import run_signal_registry
from .sse import (
    complete_payload,
    encode_sse,
    plan_ready_payload,
    round_complete_payload,
    verdict_payload,
)
from .validation import validate_run_request

logger = logging.getLogger("colosseum.api")
router = APIRouter()


@router.post("/runs", response_model=ExperimentRun)
async def create_run(
    request: RunCreateRequest,
    orchestrator=Depends(get_orchestrator),
) -> ExperimentRun:
    logger.info(
        "POST /runs — agents=%s, task=%r", [a.agent_id for a in request.agents], request.task.title
    )
    try:
        validate_run_request(orchestrator, request)
        result = await orchestrator.create_run(request)
        logger.info("POST /runs — completed run_id=%s status=%s", result.run_id, result.status)
        return result
    except (ValueError, TypeError, ValidationError) as exc:  # pragma: no cover - API guard
        logger.error("POST /runs — FAILED (client error)\n%s", traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - API guard
        logger.error("POST /runs — FAILED (server error)\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/runs/stream")
async def create_run_stream(
    request: RunCreateRequest,
    orchestrator=Depends(get_orchestrator),
):
    logger.info(
        "POST /runs/stream — agents=%s, task=%r",
        [a.agent_id for a in request.agents],
        request.task.title,
    )
    try:
        validate_run_request(orchestrator, request)
    except Exception as exc:
        logger.error("POST /runs/stream — validation failed\n%s", traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return StreamingResponse(
        _event_stream(request=request, orchestrator=orchestrator),
        media_type="text/event-stream",
    )


async def _event_stream(request: RunCreateRequest, orchestrator):
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
    bus.emit(
        "debate_start",
        {
            "topic": run.task.title,
            "token_budget": run.budget_policy.total_token_budget,
            "max_rounds": run.budget_policy.max_rounds,
            "agents": [
                {"agent_id": agent.agent_id, "display_name": agent.display_label}
                for agent in run.agents
            ],
        },
    )

    yield encode_sse({"phase": "init", "run_id": run.run_id})

    try:
        yield encode_sse({"phase": "context", "message": "Freezing context..."})
        bus.emit(
            "phase", {"phase": "context", "message": "Freezing context...", "status": "planning"}
        )
        run.mark_planning(
            await asyncio.to_thread(orchestrator.context_service.freeze, request.context_sources)
        )
        orchestrator.repository.save_run(run)

        yield encode_sse({"phase": "planning", "message": "Generating plans..."})
        bus.emit(
            "phase", {"phase": "planning", "message": "Generating plans...", "status": "planning"}
        )

        async for event_type, event_data in orchestrator._generate_plans_streaming(run):
            bus.emit(event_type, event_data)
            if event_type == "agent_planning":
                yield encode_sse(
                    {
                        "phase": "agent_planning",
                        "agent_id": event_data["agent_id"],
                        "display_name": event_data["display_name"],
                    }
                )
            elif event_type == "plan_ready":
                yield encode_sse(plan_ready_payload(event_data))
            elif event_type == "plan_failed":
                yield encode_sse(
                    {
                        "phase": "plan_failed",
                        "agent_id": event_data["agent_id"],
                        "display_name": event_data["display_name"],
                        "error": event_data["error"],
                    }
                )

        run.plan_evaluations = orchestrator.judge_service.evaluate_plans(
            run.plans,
            use_evidence_based_judging=run.judge.use_evidence_based_judging,
        )
        yield encode_sse(
            {
                "phase": "plans_ready",
                "plans": [
                    {
                        "plan_id": plan.plan_id,
                        "display_name": plan.display_name,
                        "agent_id": plan.agent_id,
                        "summary": plan.summary,
                        "strengths": plan.strengths,
                        "weaknesses": plan.weaknesses,
                        "architecture": plan.architecture,
                    }
                    for plan in run.plans
                ],
                "evaluations": [
                    {"plan_id": evaluation.plan_id, "overall_score": evaluation.overall_score}
                    for evaluation in run.plan_evaluations
                ],
            }
        )

        if len(run.agents) == 1:
            async for chunk in _handle_single_agent_victory(run, orchestrator):
                yield chunk
            return

        if run.judge.mode == JudgeMode.HUMAN:
            run.pause_for_human(orchestrator.judge_service.build_human_packet(run))
            orchestrator.repository.save_run(run)
            yield encode_sse({"phase": "human_required", "run_id": run.run_id})
            return

        async for chunk in _run_debate_loop(run, orchestrator, bus):
            yield chunk

        last_decision = run.judge_trace[-1] if run.judge_trace else None
        async for chunk in _finalize_stream_run(run, orchestrator, bus, last_decision):
            yield chunk
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("SSE stream error in run %s:\n%s", run.run_id, tb)
        bus.emit("error", {"message": str(exc)})
        yield encode_sse({"phase": "error", "message": str(exc), "traceback": tb})


async def _handle_single_agent_victory(run: ExperimentRun, orchestrator):
    if not run.plans:
        yield encode_sse(
            {"phase": "error", "message": "Single agent produced no plan; cannot auto-win."}
        )
        return

    sole_plan = run.plans[0]
    verdict = JudgeVerdict(
        judge_mode=run.judge.mode,
        verdict_type=VerdictType.WINNER,
        winning_plan_ids=[sole_plan.plan_id],
        rationale=f"{sole_plan.display_name} is the only surviving gladiator after planning. Debate skipped.",
        selected_strengths=sole_plan.strengths[:4],
        rejected_risks=[risk.title for risk in sole_plan.risks[:3]],
        stop_reason="single_agent_remaining",
        confidence=1.0,
    )
    run.complete(verdict=verdict, stop_reason="single_agent_remaining")
    orchestrator.repository.save_run(run)
    yield encode_sse(
        {
            "phase": "single_agent_victory",
            "agent_id": run.agents[0].agent_id,
            "display_name": sole_plan.display_name,
        }
    )
    payload = complete_payload(run)
    payload["final_report"] = None
    yield encode_sse(payload)


async def _run_debate_loop(run: ExperimentRun, orchestrator, bus: DebateEventBus):
    skip_event = run_signal_registry.register_skip(run.run_id)
    cancel_event = run_signal_registry.register_cancel(run.run_id)
    try:
        while True:
            skip_event.clear()
            if cancel_event.is_set():
                run.status = RunStatus.COMPLETED
                run.stop_reason = "cancelled_by_user"
                run.touch()
                orchestrator.repository.save_run(run)
                yield encode_sse({"phase": "cancelled", "message": "Debate cancelled by user."})
                return

            decision = await orchestrator.judge_service.decide(run)
            run.judge_trace.append(decision)
            bus.emit(
                "judge_decision",
                {
                    "action": decision.action.value,
                    "confidence": decision.confidence,
                    "disagreement_level": decision.disagreement_level,
                    "focus": ", ".join(decision.focus_areas[:3]) if decision.focus_areas else "",
                    "next_round_type": decision.next_round_type.value
                    if decision.next_round_type
                    else "",
                    "agenda_title": decision.agenda.title if decision.agenda else "",
                    "agenda_question": decision.agenda.question if decision.agenda else "",
                },
            )
            yield encode_sse(
                {
                    "phase": "judge_decision",
                    "action": decision.action.value,
                    "reasoning": decision.reasoning,
                    "confidence": decision.confidence,
                    "disagreement_level": decision.disagreement_level,
                    "budget_pressure": decision.budget_pressure,
                    "next_round_type": decision.next_round_type.value
                    if decision.next_round_type
                    else None,
                    "agenda_title": decision.agenda.title if decision.agenda else "",
                    "agenda_question": decision.agenda.question if decision.agenda else "",
                    "agenda_why_it_matters": decision.agenda.why_it_matters
                    if decision.agenda
                    else "",
                    "focus_areas": decision.focus_areas,
                    "rounds_completed": len(run.debate_rounds),
                    "max_rounds": run.budget_policy.max_rounds,
                }
            )

            if decision.action == JudgeActionType.FINALIZE:
                break

            if not orchestrator.budget_manager.can_start_round(
                run.budget_policy, run.budget_ledger, len(run.debate_rounds) + 1
            ):
                break

            round_type = decision.next_round_type or RoundType.CRITIQUE
            round_idx = len(run.debate_rounds) + 1
            round_timeout = run.budget_policy.timeout_for_round(round_idx)
            bus.emit(
                "debate_round_start", {"round_index": round_idx, "round_type": round_type.value}
            )
            bus.emit(
                "phase",
                {
                    "phase": "debate",
                    "message": f"Round {round_idx}: {round_type.value}",
                    "status": "debating",
                },
            )
            yield encode_sse(
                {
                    "phase": "debate_round",
                    "round_index": round_idx,
                    "round_type": round_type.value,
                    "message": f"Round {round_idx}: {round_type.value}...",
                    "agenda_title": decision.agenda.title if decision.agenda else "",
                    "agenda_question": decision.agenda.question if decision.agenda else "",
                    "timeout_seconds": round_timeout or None,
                }
            )

            run.mark_debating()
            debate_round: DebateRound | None = None
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
                    yield encode_sse(
                        {
                            "phase": "agent_thinking",
                            "agent_id": event_data["agent_id"],
                            "display_name": event_data["display_name"],
                            "round_index": event_data["round_index"],
                        }
                    )
                elif event_type == "agent_message":
                    yield encode_sse(
                        {
                            "phase": "agent_message",
                            "agent_id": event_data["agent_id"],
                            "display_name": event_data["display_name"],
                            "content": event_data["content"],
                            "critique_count": event_data["critique_count"],
                            "defense_count": event_data["defense_count"],
                            "concession_count": event_data["concession_count"],
                            "novelty_score": event_data["novelty_score"],
                            "usage": event_data["usage"],
                            "round_index": event_data["round_index"],
                        }
                    )
                elif event_type == "round_skipped":
                    yield encode_sse(
                        {
                            "phase": "round_skipped",
                            "round_index": event_data["round_index"],
                            "messages_collected": event_data["messages_collected"],
                        }
                    )
                elif event_type == "round_cancelled":
                    yield encode_sse(
                        {
                            "phase": "round_cancelled",
                            "round_index": event_data["round_index"],
                            "messages_collected": event_data["messages_collected"],
                        }
                    )
                elif event_type == "round_complete":
                    assert isinstance(event_data, DebateRound)
                    debate_round = event_data

            if debate_round is not None:
                debate_round.adjudication = orchestrator.judge_service.adjudicate_round(
                    run, debate_round
                )
                run.append_debate_round(debate_round)
                yield encode_sse(round_complete_payload(debate_round))

            orchestrator.repository.save_run(run)

            if cancel_event.is_set():
                run.status = RunStatus.COMPLETED
                run.stop_reason = "cancelled_by_user"
                run.touch()
                orchestrator.repository.save_run(run)
                yield encode_sse({"phase": "cancelled", "message": "Debate cancelled by user."})
                return
    finally:
        run_signal_registry.cleanup(run.run_id)


async def _finalize_stream_run(
    run: ExperimentRun, orchestrator, bus: DebateEventBus, last_decision
):
    bus.emit(
        "phase", {"phase": "verdict", "message": "Rendering final verdict...", "status": "debating"}
    )
    yield encode_sse({"phase": "judging", "message": "Rendering final verdict..."})

    verdict = await orchestrator.judge_service.finalize(run, last_decision)
    yield encode_sse(
        {"phase": "synthesizing_report", "message": "Synthesizing executive report..."}
    )
    final_report = await orchestrator.report_synthesizer.synthesize(run, verdict=verdict)
    run.complete(
        verdict=verdict,
        stop_reason=last_decision.reasoning if last_decision else "judge_finalize",
        final_report=final_report,
    )
    orchestrator.repository.save_run(run)

    winner_names: list[str] = []
    for winning_id in verdict.winning_plan_ids:
        plan = next((plan for plan in run.plans if plan.plan_id == winning_id), None)
        winner_names.append(plan.display_name if plan else winning_id[:8])
    bus.emit(
        "verdict",
        {
            "verdict_type": verdict.verdict_type.value,
            "winners": winner_names,
            "confidence": verdict.confidence,
            "final_answer": final_report.final_answer if final_report else "",
        },
    )
    bus.emit("phase", {"phase": "complete", "status": "completed"})

    payload = complete_payload(run)
    payload["verdict"] = verdict_payload(verdict)
    yield encode_sse(payload)


@router.get("/runs", response_model=list[RunListItem])
async def list_runs(
    orchestrator=Depends(get_orchestrator),
) -> list[RunListItem]:
    return orchestrator.list_runs()


@router.post("/runs/{run_id}/skip-round")
async def skip_round(run_id: str) -> dict:
    """Signal the running debate to skip the current round."""
    event = run_signal_registry.get_skip(run_id)
    if not event:
        raise HTTPException(status_code=404, detail="No active debate round for this run.")
    event.set()
    return {"skipped": True, "run_id": run_id}


@router.post("/runs/{run_id}/cancel")
async def cancel_debate(run_id: str) -> dict:
    """Signal the running debate to cancel entirely."""
    cancel_event = run_signal_registry.get_cancel(run_id)
    skip_event = run_signal_registry.get_skip(run_id)
    if not cancel_event:
        raise HTTPException(status_code=404, detail="No active debate for this run.")
    cancel_event.set()
    if skip_event:
        skip_event.set()
    return {"cancelled": True, "run_id": run_id}


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


@router.get("/runs/{run_id}/markdown")
async def download_run_markdown(
    run_id: str,
    orchestrator=Depends(get_orchestrator),
):
    try:
        run = orchestrator.load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    from colosseum.services.markdown_report import generate_markdown

    markdown_text = generate_markdown(run)
    filename = f"colosseum-report-{run_id[:8]}.md"
    return Response(
        content=markdown_text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
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
