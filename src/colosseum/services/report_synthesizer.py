"""Synthesize a FinalReport from a completed ExperimentRun."""

from __future__ import annotations

import logging

from colosseum.core.models import ExperimentRun, FinalReport, JudgeMode, VerdictType
from colosseum.services.provider_runtime import ProviderRuntimeService

logger = logging.getLogger("colosseum.report_synthesizer")


class ReportSynthesizer:
    def __init__(self, provider_runtime: ProviderRuntimeService) -> None:
        self.provider_runtime = provider_runtime

    async def synthesize(self, run: ExperimentRun) -> FinalReport:
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            try:
                result = await self._ai_synthesize(run)
                if result:
                    return result
            except Exception:
                logger.warning("AI report synthesis failed, falling back to heuristic", exc_info=True)
        return self._automated_synthesize(run)

    def _automated_synthesize(self, run: ExperimentRun) -> FinalReport:
        verdict = run.verdict
        plans = run.plans

        # --- winner info ---
        winner_name = ""
        if verdict and verdict.winning_plan_ids:
            wid = verdict.winning_plan_ids[0]
            match = next((p for p in plans if p.plan_id == wid), None)
            winner_name = match.display_name if match else wid[:8]

        # --- one_line_verdict ---
        if verdict and winner_name:
            one_line = f"{winner_name} wins — {verdict.rationale}"
        elif verdict:
            one_line = f"Verdict: {verdict.verdict_type.value.upper()} — {verdict.rationale}"
        else:
            one_line = f"Debate on '{run.task.title}' ended without a final verdict."

        # --- executive_summary ---
        adopted_count = sum(
            len(rnd.adjudication.adopted_arguments)
            for rnd in run.debate_rounds
            if rnd.adjudication
        )
        summary = (
            f"{winner_name + ' emerged as the winner' if winner_name else 'The debate concluded'} "
            f"after {len(run.debate_rounds)} round(s). "
            f"{adopted_count} argument(s) were formally adopted by the judge. "
            f"{verdict.rationale if verdict else ''}"
        ).strip()

        # --- key_conclusions: per-agent adopted arguments ---
        conclusions: list[str] = []
        for rnd in run.debate_rounds:
            adj = rnd.adjudication
            if adj and adj.adopted_arguments:
                for adopted in adj.adopted_arguments[:2]:
                    conclusions.append(
                        f"[Adopted from {adopted.display_name}] {adopted.summary}"
                    )
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
        verdict_explanation = " ".join(reasoning_parts[-4:]) if reasoning_parts else "No detailed reasoning available."

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
            executive_summary=summary,
            key_conclusions=conclusions,
            debate_highlights=highlights,
            verdict_explanation=verdict_explanation,
            recommendations=recommendations,
        )

    async def _ai_synthesize(self, run: ExperimentRun) -> FinalReport | None:
        winner_name = ""
        if run.verdict and run.verdict.winning_plan_ids:
            wid = run.verdict.winning_plan_ids[0]
            match = next((p for p in run.plans if p.plan_id == wid), None)
            winner_name = match.display_name if match else wid[:8]

        verdict_text = ""
        if run.verdict:
            verdict_text = (
                f" Winner: {winner_name}. "
                f"Rationale: {run.verdict.rationale}"
            )

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
            agent_context += f"\n- {name} (adopted {len(summaries)} argument(s)): {'; '.join(summaries[:2])}"

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
                "verdict_type": run.verdict.verdict_type.value if run.verdict else "none",
                "verdict_rationale": run.verdict.rationale if run.verdict else "",
                "round_count": len(run.debate_rounds),
            },
        )
        payload = execution.result.json_payload
        if not payload:
            return None
        return FinalReport(
            one_line_verdict=str(payload.get("one_line_verdict", "")),
            executive_summary=str(payload.get("executive_summary", "")),
            key_conclusions=[str(i) for i in payload.get("key_conclusions", [])],
            debate_highlights=[str(i) for i in payload.get("debate_highlights", [])],
            verdict_explanation=str(payload.get("verdict_explanation", "")),
            recommendations=[str(i) for i in payload.get("recommendations", [])],
        )
