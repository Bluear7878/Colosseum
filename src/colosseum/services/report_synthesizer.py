"""Synthesize a FinalReport from a completed or finalizing ExperimentRun."""

from __future__ import annotations

import logging

from colosseum.core.config import MAX_CONTEXT_PROMPT_CHARS, PROMPT_BUDGET_TRUNCATION_MARKER
from colosseum.core.models import (
    ExperimentRun,
    FinalReport,
    JudgeVerdict,
    ProviderConfig,
    VerdictType,
)
from colosseum.services.provider_runtime import ProviderRuntimeService

logger = logging.getLogger("colosseum.report_synthesizer")
_REPORT_TRANSCRIPT_BUDGET = min(MAX_CONTEXT_PROMPT_CHARS, 12000)


class ReportSynthesizer:
    """Build a concise executive report from the debate transcript and verdict."""

    def __init__(self, provider_runtime: ProviderRuntimeService) -> None:
        self.provider_runtime = provider_runtime

    async def synthesize(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None = None,
    ) -> FinalReport:
        """Return a final report for *run* using an explicit verdict when provided.

        Some UI/API paths compute the verdict immediately before persisting it on
        the run object. Accepting the fresh verdict here prevents those callers
        from synthesizing a stale "no verdict" report.
        """
        resolved_verdict = verdict or run.verdict
        provider = self._report_provider_for(run, resolved_verdict)
        synthesized_final_answer = ""
        if provider:
            try:
                synthesized_final_answer = await self._ai_final_answer(
                    run,
                    resolved_verdict,
                    provider,
                )
            except Exception:
                logger.warning(
                    "AI final-answer synthesis failed, falling back to heuristic",
                    exc_info=True,
                )
            try:
                result = await self._ai_synthesize(
                    run,
                    resolved_verdict,
                    provider,
                    final_answer_override=synthesized_final_answer,
                )
                if result:
                    return result
            except Exception:
                logger.warning(
                    "AI report synthesis failed, falling back to heuristic", exc_info=True
                )
        return self._automated_synthesize(
            run,
            resolved_verdict,
            final_answer_override=synthesized_final_answer,
        )

    def _report_provider_for(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> ProviderConfig | None:
        """Choose a non-judge provider when possible for post-debate synthesis."""
        preferred_agent_ids: list[str] = []
        if verdict:
            plan_map = {plan.plan_id: plan for plan in run.plans}
            for winning_id in verdict.winning_plan_ids:
                plan = plan_map.get(winning_id)
                if plan:
                    preferred_agent_ids.append(plan.agent_id)
        preferred_agent_ids.extend(agent.agent_id for agent in run.agents)

        seen: set[str] = set()
        for agent_id in preferred_agent_ids:
            if agent_id in seen:
                continue
            seen.add(agent_id)
            agent = next((item for item in run.agents if item.agent_id == agent_id), None)
            if agent:
                return agent.provider.model_copy(deep=True)
        if run.judge.provider:
            return run.judge.provider.model_copy(deep=True)
        return None

    def _winner_names(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> list[str]:
        if verdict is None:
            return []
        names: list[str] = []
        seen: set[str] = set()
        for winning_id in verdict.winning_plan_ids:
            match = next((plan for plan in run.plans if plan.plan_id == winning_id), None)
            display_name = match.display_name if match else winning_id[:8]
            if display_name not in seen:
                names.append(display_name)
                seen.add(display_name)
        return names

    def _winner_plans(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> list:
        if verdict is None:
            return []
        winning_ids = set(verdict.winning_plan_ids)
        return [plan for plan in run.plans if plan.plan_id in winning_ids]

    def _compact_text(self, text: str, max_chars: int) -> str:
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - len(PROMPT_BUDGET_TRUNCATION_MARKER)].rstrip() + (
            PROMPT_BUDGET_TRUNCATION_MARKER
        )

    def _plan_context(self, run: ExperimentRun) -> str:
        if not run.plans:
            return ""
        lines = ["=== OPENING PLANS ==="]
        for plan in run.plans:
            lines.append(f"- {plan.display_name}: {self._compact_text(plan.summary, 400)}")
            if plan.strengths:
                lines.append(
                    f"  strengths: {self._compact_text('; '.join(plan.strengths[:3]), 220)}"
                )
            if plan.weaknesses:
                lines.append(
                    f"  weaknesses: {self._compact_text('; '.join(plan.weaknesses[:2]), 200)}"
                )
        lines.append("=== END OPENING PLANS ===")
        return "\n".join(lines)

    def _adopted_argument_summaries(self, run: ExperimentRun) -> list[str]:
        summaries: list[str] = []
        for debate_round in run.debate_rounds:
            adj = debate_round.adjudication
            if not adj:
                continue
            for adopted in adj.adopted_arguments[:3]:
                summaries.append(f"{adopted.display_name}: {adopted.summary}")
        return summaries[:8]

    def _debate_resolution_summaries(self, run: ExperimentRun) -> list[str]:
        summaries: list[str] = []
        for debate_round in run.debate_rounds:
            adj = debate_round.adjudication
            if adj and adj.resolution:
                summaries.append(adj.resolution)
        return summaries[:6]

    def _transcript_context(self, run: ExperimentRun) -> str:
        if not run.debate_rounds:
            return ""

        agent_names = {agent.agent_id: agent.display_name for agent in run.agents}
        blocks: list[str] = []
        for debate_round in reversed(run.debate_rounds):
            lines = [f"--- Round {debate_round.index}: {debate_round.round_type.value} ---"]
            if debate_round.agenda and debate_round.agenda.question:
                lines.append(
                    f"Judge question: {self._compact_text(debate_round.agenda.question, 280)}"
                )
            for message in debate_round.messages:
                speaker = agent_names.get(message.agent_id, message.agent_id)
                lines.append(f"{speaker}: {self._compact_text(message.content, 520)}")
            adj = debate_round.adjudication
            if adj and adj.resolution:
                lines.append(f"Judge resolution: {self._compact_text(adj.resolution, 320)}")
            if adj and adj.adopted_arguments:
                for adopted in adj.adopted_arguments[:3]:
                    lines.append(
                        f"Adopted argument from {adopted.display_name}: "
                        f"{self._compact_text(adopted.summary, 240)}"
                    )
            if adj and adj.unresolved_points:
                lines.append(
                    "Remaining caveats: "
                    + self._compact_text("; ".join(adj.unresolved_points[:2]), 220)
                )
            blocks.append("\n".join(lines))

        assembled = ["=== DEBATE TRANSCRIPT ==="]
        total_chars = len(assembled[0])
        for block in reversed(blocks):
            projected = total_chars + len(block) + 2
            if projected > _REPORT_TRANSCRIPT_BUDGET:
                break
            assembled.append(block)
            total_chars = projected
        assembled.append("=== END DEBATE TRANSCRIPT ===")
        return "\n\n".join(assembled)

    def _final_answer_for_verdict(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> str:
        if verdict is None:
            return (
                f"There is not yet a final answer to the user's question: "
                f"{run.task.problem_statement}"
            )

        winner_names = self._winner_names(run, verdict)
        winner_plans = self._winner_plans(run, verdict)
        leading_plan = winner_plans[0] if winner_plans else None
        adopted_points = self._adopted_argument_summaries(run)
        debate_resolutions = self._debate_resolution_summaries(run)
        caveats = verdict.rejected_risks[:2]
        if not caveats and run.debate_rounds:
            latest_adj = run.debate_rounds[-1].adjudication
            if latest_adj:
                caveats = latest_adj.unresolved_points[:2]

        answer_parts: list[str] = []
        if verdict.verdict_type == VerdictType.MERGED and verdict.synthesized_plan:
            label = (
                " + ".join(winner_names) if winner_names else "the strongest ideas from the debate"
            )
            answer_parts.append(
                f"For the user's question, the best answer is a merged approach built from {label}."
            )
            answer_parts.append(verdict.synthesized_plan.summary)
        elif leading_plan is not None:
            winner_name = winner_names[0] if winner_names else leading_plan.display_name
            answer_parts.append(
                f"For the user's question, the best answer is to follow {winner_name}'s approach."
            )
            answer_parts.append(leading_plan.summary)
        else:
            answer_parts.append(
                f"For the user's question, the debate supports this answer: {verdict.rationale}"
            )

        if adopted_points:
            answer_parts.append("Debate-backed reasons: " + "; ".join(adopted_points[:2]) + ".")
        elif debate_resolutions:
            answer_parts.append(
                "What the debate resolved: " + "; ".join(debate_resolutions[:2]) + "."
            )
        elif verdict.selected_strengths:
            answer_parts.append(
                "Why this answer: " + "; ".join(verdict.selected_strengths[:2]) + "."
            )
        if caveats:
            answer_parts.append("Key caveats: " + "; ".join(caveats) + ".")

        cleaned_parts = [part.strip().rstrip(".") + "." for part in answer_parts if part.strip()]
        return " ".join(cleaned_parts)

    def _headline_for_verdict(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> str:
        if verdict is None:
            return f"Debate on '{run.task.title}' ended without a final verdict."

        winner_names = self._winner_names(run, verdict)
        if verdict.verdict_type == VerdictType.MERGED:
            if winner_names:
                return (
                    f"Merged recommendation from {' + '.join(winner_names)} — {verdict.rationale}"
                )
            return f"Merged recommendation — {verdict.rationale}"

        if winner_names:
            return f"{winner_names[0]} wins — {verdict.rationale}"
        return f"Verdict: {verdict.verdict_type.value.upper()} — {verdict.rationale}"

    def _automated_synthesize(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
        final_answer_override: str = "",
    ) -> FinalReport:
        plans = run.plans
        winner_names = self._winner_names(run, verdict)
        winner_name = winner_names[0] if winner_names else ""

        # --- one_line_verdict ---
        one_line = self._headline_for_verdict(run, verdict)
        final_answer = final_answer_override or self._final_answer_for_verdict(run, verdict)

        # --- executive_summary ---
        if verdict and verdict.verdict_type == VerdictType.MERGED:
            lead = (
                f"A merged recommendation from {' + '.join(winner_names)} emerged"
                if winner_names
                else "A merged recommendation emerged"
            )
        elif winner_name:
            lead = f"{winner_name} emerged as the winner"
        else:
            lead = "The debate concluded"
        adopted_count = sum(
            len(rnd.adjudication.adopted_arguments) for rnd in run.debate_rounds if rnd.adjudication
        )
        summary = (
            f"{lead} "
            f"after {len(run.debate_rounds)} round(s). "
            f"{adopted_count} argument(s) were formally adopted by the judge. "
            f"{verdict.rationale if verdict else ''}"
        ).strip()

        # --- key_conclusions: per-agent adopted arguments ---
        conclusions: list[str] = []
        if verdict and verdict.synthesized_plan and verdict.synthesized_plan.summary:
            conclusions.append(f"[Merged plan] {verdict.synthesized_plan.summary}")
        for rnd in run.debate_rounds:
            adj = rnd.adjudication
            if adj and adj.adopted_arguments:
                for adopted in adj.adopted_arguments[:2]:
                    conclusions.append(f"[Adopted from {adopted.display_name}] {adopted.summary}")
        if verdict and verdict.selected_strengths:
            for s in verdict.selected_strengths[:2]:
                conclusions.append(s)
        conclusions = conclusions[:8]

        # --- debate_highlights ---
        highlights: list[str] = []
        for rnd in run.debate_rounds:
            s = rnd.summary
            for d in s.key_disagreements[:1]:
                highlights.append(f"Round {rnd.index}: {d}")
            adj = rnd.adjudication
            if adj and adj.resolution:
                highlights.append(f"Round {rnd.index} resolution: {adj.resolution}")
            # Include hallucination flags if any
            if adj and adj.hallucination_flags:
                for flag in adj.hallucination_flags[:1]:
                    highlights.append(f"[Credibility warning, Round {rnd.index}] {flag}")
            if adj and adj.drift_flags:
                for flag in adj.drift_flags[:1]:
                    highlights.append(f"[Off-topic drift, Round {rnd.index}] {flag}")
        highlights = highlights[:6]

        # --- verdict_explanation ---
        reasoning_parts: list[str] = []
        for decision in run.judge_trace:
            if decision.reasoning:
                reasoning_parts.append(decision.reasoning)
        if verdict:
            reasoning_parts.append(f"Final confidence: {verdict.confidence:.2f}")
        verdict_explanation = (
            " ".join(reasoning_parts[-4:])
            if reasoning_parts
            else "No detailed reasoning available."
        )

        # --- recommendations ---
        recommendations: list[str] = []
        for plan in plans:
            for q in plan.open_questions[:1]:
                recommendations.append(f"Investigate: {q}")
        for rnd in run.debate_rounds:
            adj = rnd.adjudication
            if adj:
                for u in adj.unresolved_points[:1]:
                    recommendations.append(f"Resolve: {u}")
        recommendations = recommendations[:5]

        return FinalReport(
            one_line_verdict=one_line,
            final_answer=final_answer,
            executive_summary=summary,
            key_conclusions=conclusions,
            debate_highlights=highlights,
            verdict_explanation=verdict_explanation,
            recommendations=recommendations,
        )

    async def _ai_final_answer(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
        provider_config: ProviderConfig,
    ) -> str:
        plan_context = self._plan_context(run)
        transcript_context = self._transcript_context(run)
        adopted_points = self._adopted_argument_summaries(run)
        debate_resolutions = self._debate_resolution_summaries(run)
        caveats: list[str] = []
        for debate_round in run.debate_rounds:
            adj = debate_round.adjudication
            if adj:
                caveats.extend(adj.unresolved_points[:1])
        caveats = caveats[:3]

        instructions = (
            "You are the final answering agent for a completed debate. "
            "You are not the judge. Do not score the debaters or announce the winner unless it is necessary to explain the answer. "
            f"User question: {run.task.problem_statement}\n\n"
            f"{plan_context}\n\n"
            f"{transcript_context}\n\n"
            "Synthesize the strongest conclusions from the actual conversation. "
            "Your job is to answer the user's question directly using the best reasoning from across the debate, "
            "including useful points from losing sides when they improve the answer. "
            "Return JSON with keys: final_answer (str, 3-6 sentences), supporting_points (list[str]), caveats (list[str])."
        )
        if run.response_language and run.response_language != "auto":
            instructions = (
                f"MANDATORY LANGUAGE: Write ALL content in {run.response_language}. "
                f"Every field, every sentence must be in {run.response_language}. No other language permitted.\n\n"
                + instructions
            )

        execution = await self.provider_runtime.execute(
            run=run,
            actor_id="answer:synthesis",
            actor_label="Final Answer Synthesizer",
            provider_config=provider_config,
            operation="answer_synthesis",
            instructions=instructions,
            metadata={
                "run_id": run.run_id,
                "task_title": run.task.title,
                "task_problem": run.task.problem_statement,
                "verdict_type": verdict.verdict_type.value if verdict else "none",
                "verdict_rationale": verdict.rationale if verdict else "",
                "plan_summaries": [plan.summary for plan in run.plans],
                "transcript_excerpt": transcript_context,
                "adopted_points": adopted_points,
                "debate_resolutions": debate_resolutions,
                "caveats": caveats,
                "round_count": len(run.debate_rounds),
            },
        )
        payload = execution.result.json_payload
        if not payload:
            return ""
        return str(payload.get("final_answer", "")).strip()

    async def _ai_synthesize(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
        provider_config: ProviderConfig,
        final_answer_override: str = "",
    ) -> FinalReport | None:
        winner_names = self._winner_names(run, verdict)
        plan_context = self._plan_context(run)
        transcript_context = self._transcript_context(run)
        adopted_points = self._adopted_argument_summaries(run)
        debate_resolutions = self._debate_resolution_summaries(run)

        verdict_text = ""
        if verdict:
            subject = (
                " + ".join(winner_names)
                if winner_names
                else verdict.verdict_type.value.replace("_", " ")
            )
            label = (
                "Merged recommendation" if verdict.verdict_type == VerdictType.MERGED else "Winner"
            )
            verdict_text = f" {label}: {subject}. Rationale: {verdict.rationale}"
            if verdict.synthesized_plan and verdict.synthesized_plan.summary:
                verdict_text += f" Synthesized plan summary: {verdict.synthesized_plan.summary}"

        instructions = (
            f"Synthesize a final executive report for this debate. "
            f"Topic: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}.{verdict_text} "
            f"The debate ran for {len(run.debate_rounds)} round(s).\n\n"
            f"{plan_context}\n\n"
            f"{transcript_context}\n\n"
            "Write a focused, concise report that speaks directly to this specific topic and problem. "
            "Every section must be grounded in what actually happened in the conversation — no generic advice or filler. "
            "Do not reduce the answer to a winner announcement. Use the actual debate and judge-adopted points. "
            "Return JSON with keys: "
            "one_line_verdict (str, single bold sentence declaring the winner and core reason), "
            "final_answer (str, 2-4 sentences directly answering the user's question based on the debate outcome), "
            "executive_summary (str), key_conclusions (list[str], include per-agent adopted arguments), "
            "debate_highlights (list[str]), verdict_explanation (str), recommendations (list[str])."
        )
        if final_answer_override:
            instructions += (
                f"\n\nCanonical final answer draft: {final_answer_override}\n"
                "Keep the final_answer aligned with this answer draft and refine it only for clarity."
            )
        if run.response_language and run.response_language != "auto":
            instructions = (
                f"MANDATORY LANGUAGE: Write ALL content in {run.response_language}. "
                f"Every field, every sentence must be in {run.response_language}. No other language permitted.\n\n"
                + instructions
                + f"\n\nREMINDER: The entire report must be in {run.response_language}."
            )

        execution = await self.provider_runtime.execute(
            run=run,
            actor_id="report:synthesis",
            actor_label="Report Synthesizer",
            provider_config=provider_config,
            operation="report_synthesis",
            instructions=instructions,
            metadata={
                "run_id": run.run_id,
                "task_title": run.task.title,
                "task_problem": run.task.problem_statement,
                "verdict_type": verdict.verdict_type.value if verdict else "none",
                "verdict_rationale": verdict.rationale if verdict else "",
                "plan_summaries": [plan.summary for plan in run.plans],
                "transcript_excerpt": transcript_context,
                "adopted_points": adopted_points,
                "debate_resolutions": debate_resolutions,
                "precomputed_final_answer": final_answer_override,
                "round_count": len(run.debate_rounds),
                "report_instructions": run.report_instructions or "",
            },
        )
        payload = execution.result.json_payload
        if not payload:
            return None
        return FinalReport(
            one_line_verdict=str(payload.get("one_line_verdict", "")),
            final_answer=final_answer_override
            or str(payload.get("final_answer", ""))
            or self._final_answer_for_verdict(run, verdict),
            executive_summary=str(payload.get("executive_summary", "")),
            key_conclusions=[str(i) for i in payload.get("key_conclusions", [])],
            debate_highlights=[str(i) for i in payload.get("debate_highlights", [])],
            verdict_explanation=str(payload.get("verdict_explanation", "")),
            recommendations=[str(i) for i in payload.get("recommendations", [])],
        )
