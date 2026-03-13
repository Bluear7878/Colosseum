from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from colosseum.core.models import (
    AgentConfig,
    ExperimentRun,
    HumanJudgeActionRequest,
    JudgeActionType,
    JudgeMode,
    JudgeVerdict,
    RunListItem,
    RunCreateRequest,
    RunStatus,
    RoundType,
    VerdictType,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.report_synthesizer import ReportSynthesizer
from colosseum.services.repository import FileRunRepository
from colosseum.core.config import build_evidence_policy


class ColosseumOrchestrator:
    def __init__(
        self,
        repository: FileRunRepository,
        context_service: ContextBundleService,
        debate_engine: DebateEngine,
        judge_service: JudgeService,
        budget_manager: BudgetManager,
        normalizer: ResponseNormalizer,
        provider_runtime: ProviderRuntimeService,
        report_synthesizer: ReportSynthesizer | None = None,
    ) -> None:
        self.repository = repository
        self.context_service = context_service
        self.debate_engine = debate_engine
        self.judge_service = judge_service
        self.budget_manager = budget_manager
        self.normalizer = normalizer
        self.provider_runtime = provider_runtime
        self.report_synthesizer = report_synthesizer or ReportSynthesizer(provider_runtime)

    async def create_run(self, request: RunCreateRequest) -> ExperimentRun:
        self.provider_runtime.validate_agents_selectable(request.agents)
        if request.judge.mode == JudgeMode.AI:
            if not request.judge.provider:
                raise ValueError("AI judge mode requires a judge provider.")
            self.provider_runtime.validate_provider_selectable(request.judge.provider, "AI judge")
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
        self.repository.save_run(run)
        try:
            run.status = RunStatus.PLANNING
            run.context_bundle = self.context_service.freeze(request.context_sources)
            self.repository.save_run(run)
            await self._generate_plans(run)
            run.plan_evaluations = self.judge_service.evaluate_plans(run.plans)

            if run.judge.mode == JudgeMode.HUMAN:
                run.status = RunStatus.AWAITING_HUMAN_JUDGE
                run.human_judge_packet = self.judge_service.build_human_packet(run)
                self._touch(run)
                self.repository.save_run(run)
                return run

            run = await self._run_until_complete(run)
            return run
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error_message = str(exc)
            run.stop_reason = "run_failed"
            self._touch(run)
            self.repository.save_run(run)
            raise

    async def continue_human_run(
        self,
        run_id: str,
        action: HumanJudgeActionRequest,
    ) -> ExperimentRun:
        run = self.repository.load_run(run_id)
        if run.status != RunStatus.AWAITING_HUMAN_JUDGE:
            raise ValueError(f"Run {run_id} is not awaiting a human judge.")

        if action.action == "request_round":
            round_type = action.round_type or RoundType.CRITIQUE
            if not self.budget_manager.can_start_round(
                run.budget_policy,
                run.budget_ledger,
                len(run.debate_rounds) + 1,
            ):
                run.verdict = await self.judge_service.finalize(run)
                run.status = RunStatus.COMPLETED
                run.stop_reason = run.budget_ledger.stop_reason or "budget_stop"
            else:
                decision = self.judge_service.build_human_round_decision(
                    run,
                    round_type,
                    instructions=action.instructions,
                )
                run.judge_trace.append(decision)
                run.status = RunStatus.DEBATING
                debate_round = await self.debate_engine.run_round(
                    run,
                    round_type=round_type,
                    agenda=decision.agenda,
                    instructions=action.instructions,
                )
                debate_round.adjudication = self.judge_service.adjudicate_round(run, debate_round)
                run.debate_rounds.append(debate_round)
                run.status = RunStatus.AWAITING_HUMAN_JUDGE
                run.human_judge_packet = self.judge_service.build_human_packet(run)

        elif action.action == "select_winner":
            winning_ids = action.winning_plan_ids
            if not winning_ids:
                raise ValueError("select_winner requires at least one winning plan id.")
            run.verdict = JudgeVerdict(
                judge_mode=run.judge.mode,
                verdict_type=VerdictType.WINNER,
                winning_plan_ids=winning_ids[:1],
                rationale=action.instructions or "Human judge selected the winning plan.",
                selected_strengths=[],
                rejected_risks=[],
                stop_reason="human_selected_winner",
                confidence=1.0,
            )
            run.final_report = await self.report_synthesizer.synthesize(run)
            run.status = RunStatus.COMPLETED
            run.stop_reason = "human_selected_winner"

        elif action.action == "merge_plans":
            if len(action.winning_plan_ids) < 2:
                raise ValueError("merge_plans requires at least two plan ids.")
            chosen = [plan for plan in run.plans if plan.plan_id in action.winning_plan_ids]
            if len(chosen) < 2:
                raise ValueError("Could not find the requested plans to merge.")
            merged = self.judge_service._build_merged_plan(chosen[0], chosen[1])
            run.verdict = JudgeVerdict(
                judge_mode=run.judge.mode,
                verdict_type=VerdictType.MERGED,
                winning_plan_ids=action.winning_plan_ids[:2],
                synthesized_plan=merged,
                rationale=action.instructions or "Human judge requested a merged final plan.",
                selected_strengths=merged.strengths,
                rejected_risks=[risk.title for risk in merged.risks],
                stop_reason="human_merged_plans",
                confidence=1.0,
            )
            run.final_report = await self.report_synthesizer.synthesize(run)
            run.status = RunStatus.COMPLETED
            run.stop_reason = "human_merged_plans"

        elif action.action == "request_revision":
            if not self.budget_manager.can_start_round(
                run.budget_policy,
                run.budget_ledger,
                len(run.debate_rounds) + 1,
            ):
                run.verdict = await self.judge_service.finalize(run)
                run.status = RunStatus.COMPLETED
                run.stop_reason = run.budget_ledger.stop_reason or "budget_stop"
            else:
                decision = self.judge_service.build_human_round_decision(
                    run,
                    RoundType.TARGETED_REVISION,
                    instructions=action.instructions,
                )
                run.judge_trace.append(decision)
                run.status = RunStatus.DEBATING
                debate_round = await self.debate_engine.run_round(
                    run,
                    round_type=RoundType.TARGETED_REVISION,
                    agenda=decision.agenda,
                    instructions=action.instructions,
                )
                debate_round.adjudication = self.judge_service.adjudicate_round(run, debate_round)
                run.debate_rounds.append(debate_round)
                run.status = RunStatus.AWAITING_HUMAN_JUDGE
                run.human_judge_packet = self.judge_service.build_human_packet(run)

        self._touch(run)
        self.repository.save_run(run)
        return run

    def load_run(self, run_id: str) -> ExperimentRun:
        return self.repository.load_run(run_id)

    def list_runs(self) -> list[RunListItem]:
        return self.repository.list_runs()

    async def _generate_plans(self, run: ExperimentRun) -> None:
        if not run.context_bundle:
            raise ValueError("Context bundle must be frozen before generating plans.")

        context_text = self.context_service.render_for_prompt(run.context_bundle)
        image_inputs = self.context_service.extract_image_inputs(run.context_bundle)
        image_summary = self.context_service.summarize_image_inputs(run.context_bundle)
        prompts = []
        for agent in run.agents:
            prompts.append(
                self._build_plan_prompt(
                    run,
                    agent,
                    context_text,
                    image_summary=image_summary,
                    has_image_inputs=bool(image_inputs),
                )
            )
        planning_timeout = run.budget_policy.planning_timeout_seconds or 0
        results = await asyncio.gather(
            *[
                self.provider_runtime.execute(
                    run=run,
                    actor_id=agent.agent_id,
                    actor_label=agent.display_name,
                    provider_config=agent.provider,
                    operation="plan",
                    instructions=prompt,
                    timeout_override=planning_timeout,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": agent.agent_id,
                        "task_title": run.task.title,
                        "context_summary": run.context_bundle.bundle_summary,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
                        "encourage_internet_search": run.encourage_internet_search,
                        "search_policy": build_evidence_policy(run.encourage_internet_search),
                    },
                )
                for agent, prompt in zip(run.agents, prompts, strict=True)
            ]
        )

        for agent, execution in zip(run.agents, results, strict=True):
            result = execution.result
            plan = self.normalizer.normalize_plan(
                agent=agent,
                payload=result.json_payload,
                raw_content=result.content,
                usage=result.usage,
            )
            run.plans.append(plan)
            run.budget_ledger.record(agent.agent_id, result.usage, round_index=0)
        self._touch(run)
        self.repository.save_run(run)

    async def _generate_plans_streaming(self, run: ExperimentRun):
        """Yields (event_type, data) tuples as each agent's plan completes.

        Agents that fail (e.g. timeout) are removed from the run instead of
        killing the entire experiment.
        """
        if not run.context_bundle:
            raise ValueError("Context bundle must be frozen before generating plans.")

        context_bundle = run.context_bundle
        context_text = self.context_service.render_for_prompt(context_bundle)
        image_inputs = self.context_service.extract_image_inputs(context_bundle)
        image_summary = self.context_service.summarize_image_inputs(context_bundle)

        task_to_agent: dict[asyncio.Task, AgentConfig] = {}
        for agent in run.agents:
            prompt = self._build_plan_prompt(
                run,
                agent,
                context_text,
                image_summary=image_summary,
                has_image_inputs=bool(image_inputs),
            )

            async def agent_plan(a=agent, p=prompt):
                execution = await self.provider_runtime.execute(
                    run=run,
                    actor_id=a.agent_id,
                    actor_label=a.display_name,
                    provider_config=a.provider,
                    operation="plan",
                    instructions=p,
                    timeout_override=run.budget_policy.planning_timeout_seconds,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": a.agent_id,
                        "task_title": run.task.title,
                        "context_summary": context_bundle.bundle_summary,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
                        "encourage_internet_search": run.encourage_internet_search,
                        "search_policy": build_evidence_policy(run.encourage_internet_search),
                        "persona": a.persona_content or "",
                    },
                )
                return a, execution.result

            task = asyncio.create_task(agent_plan())
            task_to_agent[task] = agent
            yield ("agent_planning", {"agent_id": agent.agent_id, "display_name": agent.display_name})

        pending: set[asyncio.Task] = set(task_to_agent.keys())
        failed_agent_ids: list[str] = []

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                agent = task_to_agent[task]
                try:
                    _, result = task.result()
                    plan = self.normalizer.normalize_plan(
                        agent=agent,
                        payload=result.json_payload,
                        raw_content=result.content,
                        usage=result.usage,
                    )
                    run.plans.append(plan)
                    run.budget_ledger.record(agent.agent_id, result.usage, round_index=0)
                    yield ("plan_ready", {
                        "agent_id": agent.agent_id,
                        "display_name": plan.display_name,
                        "plan_id": plan.plan_id,
                        "summary": plan.summary,
                        "strengths": plan.strengths,
                        "weaknesses": plan.weaknesses,
                    })
                except Exception as exc:
                    failed_agent_ids.append(agent.agent_id)
                    yield ("plan_failed", {
                        "agent_id": agent.agent_id,
                        "display_name": agent.display_name,
                        "error": str(exc),
                    })

        # Remove failed agents from the run
        if failed_agent_ids:
            run.agents = [a for a in run.agents if a.agent_id not in failed_agent_ids]

        if not run.agents:
            raise RuntimeError("All agents failed during planning. Cannot continue.")

        self._touch(run)
        self.repository.save_run(run)

    async def _run_until_complete(self, run: ExperimentRun) -> ExperimentRun:
        while True:
            decision = await self.judge_service.decide(run)
            run.judge_trace.append(decision)

            if decision.action == JudgeActionType.FINALIZE:
                run.verdict = await self.judge_service.finalize(run, decision)
                run.final_report = await self.report_synthesizer.synthesize(run)
                run.status = RunStatus.COMPLETED
                run.stop_reason = decision.reasoning
                self._touch(run)
                self.repository.save_run(run)
                return run

            if not self.budget_manager.can_start_round(
                run.budget_policy,
                run.budget_ledger,
                len(run.debate_rounds) + 1,
            ):
                fallback_decision = await self.judge_service.decide(run)
                run.judge_trace.append(fallback_decision)
                run.verdict = await self.judge_service.finalize(run, fallback_decision)
                run.status = RunStatus.COMPLETED
                run.stop_reason = run.budget_ledger.stop_reason or fallback_decision.reasoning
                self._touch(run)
                self.repository.save_run(run)
                return run

            round_type = decision.next_round_type or RoundType.CRITIQUE
            run.status = RunStatus.DEBATING
            debate_round = await self.debate_engine.run_round(
                run,
                round_type=round_type,
                agenda=decision.agenda,
                instructions="Focus on the current judge agenda only.",
            )
            debate_round.adjudication = self.judge_service.adjudicate_round(run, debate_round)
            run.debate_rounds.append(debate_round)
            self._touch(run)
            self.repository.save_run(run)

    def _build_plan_prompt(
        self,
        run: ExperimentRun,
        agent,
        context_text: str,
        image_summary: str,
        has_image_inputs: bool,
    ) -> str:
        parts = [
            f"Task title: {run.task.title}",
            f"Problem statement: {run.task.problem_statement}",
            f"Success criteria: {run.task.success_criteria}",
            f"Constraints: {run.task.constraints}",
            f"Agent specialty: {agent.specialty or 'generalist'}",
            "Produce an independent plan before seeing any other plan.",
            build_evidence_policy(run.encourage_internet_search),
            "Use this exact section structure: summary, evidence_basis, assumptions, architecture, implementation_strategy, risks, strengths, weaknesses, trade_offs, open_questions.",
            "Every major claim should be tied to objective evidence from the frozen bundle or labeled as inference/uncertainty.",
        ]
        if has_image_inputs:
            parts.extend(
                [
                    f"Shared visual context: {image_summary}",
                    "Use the attached multimodal image package when available. "
                    "If your provider cannot inspect images, explicitly note that limitation instead of guessing visual details.",
                ]
            )
        parts.append(context_text)
        if run.response_language and run.response_language != "auto":
            parts.append(f"IMPORTANT: You MUST write your entire response in {run.response_language}. All sections, analysis, and explanations must be in {run.response_language}.")
        if agent.persona_content:
            parts.insert(0, "=== YOUR PERSONA ===\n" + agent.persona_content + "\n=== END PERSONA ===")
        elif agent.system_prompt:
            parts.insert(0, "System: " + agent.system_prompt)
        return "\n\n".join(parts)

    def _touch(self, run: ExperimentRun) -> None:
        run.updated_at = datetime.now(timezone.utc)
