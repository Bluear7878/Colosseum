"""Synthesize a FinalReport from a completed or finalizing ExperimentRun."""

from __future__ import annotations

import logging

from colosseum.core.models import ExperimentRun, FinalReport, JudgeMode, JudgeVerdict, VerdictType
from colosseum.services.provider_runtime import ProviderRuntimeService

logger = logging.getLogger("colosseum.report_synthesizer")


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
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            try:
                result = await self._ai_synthesize(run, resolved_verdict)
                if result:
                    return result
            except Exception:
                logger.warning(
                    "AI report synthesis failed, falling back to heuristic", exc_info=True
                )
        return self._automated_synthesize(run, resolved_verdict)

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

        if verdict.selected_strengths:
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
    ) -> FinalReport:
        plans = run.plans
        winner_names = self._winner_names(run, verdict)
        winner_name = winner_names[0] if winner_names else ""

        # --- one_line_verdict ---
        one_line = self._headline_for_verdict(run, verdict)
        final_answer = self._final_answer_for_verdict(run, verdict)

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

    async def _ai_synthesize(
        self,
        run: ExperimentRun,
        verdict: JudgeVerdict | None,
    ) -> FinalReport | None:
        winner_names = self._winner_names(run, verdict)

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

        # Build per-agent adopted/not-adopted summary
        agent_names = {a.agent_id: a.display_name for a in run.agents}
        adopted_by_agent: dict[str, list[str]] = {}
        for rnd in run.debate_rounds:
            if rnd.adjudication:
                for arg in rnd.adjudication.adopted_arguments:
                    adopted_by_agent.setdefault(arg.agent_id, []).append(arg.summary)
        agent_context = ""
        for aid, summaries in adopted_by_agent.items():
            name = agent_names.get(aid, aid)
            agent_context += (
                f"\n- {name} (adopted {len(summaries)} argument(s)): {'; '.join(summaries[:2])}"
            )

        instructions = (
            f"Synthesize a final executive report for this debate. "
            f"Topic: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}.{verdict_text} "
            f"The debate ran for {len(run.debate_rounds)} round(s)."
            f"{f' Agent contributions:{agent_context}' if agent_context else ''} "
            "Write a focused, concise report that speaks directly to this specific topic and problem. "
            "Every section must be grounded in what actually happened — no generic advice or filler. "
            "Return JSON with keys: "
            "one_line_verdict (str, single bold sentence declaring the winner and core reason), "
            "final_answer (str, 2-4 sentences directly answering the user's question based on the debate outcome), "
            "executive_summary (str), key_conclusions (list[str], include per-agent adopted arguments), "
            "debate_highlights (list[str]), verdict_explanation (str), recommendations (list[str])."
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
            provider_config=run.judge.provider,
            operation="report_synthesis",
            instructions=instructions,
            metadata={
                "run_id": run.run_id,
                "task_title": run.task.title,
                "task_problem": run.task.problem_statement,
                "verdict_type": verdict.verdict_type.value if verdict else "none",
                "verdict_rationale": verdict.rationale if verdict else "",
                "round_count": len(run.debate_rounds),
            },
        )
        payload = execution.result.json_payload
        if not payload:
            return None
        return FinalReport(
            one_line_verdict=str(payload.get("one_line_verdict", "")),
            final_answer=str(payload.get("final_answer", ""))
            or self._final_answer_for_verdict(run, verdict),
            executive_summary=str(payload.get("executive_summary", "")),
            key_conclusions=[str(i) for i in payload.get("key_conclusions", [])],
            debate_highlights=[str(i) for i in payload.get("debate_highlights", [])],
            verdict_explanation=str(payload.get("verdict_explanation", "")),
            recommendations=[str(i) for i in payload.get("recommendations", [])],
        )
