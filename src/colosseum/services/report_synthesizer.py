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

        # --- executive_summary ---
        if verdict:
            winner_names = []
            for wid in verdict.winning_plan_ids:
                match = next((p for p in plans if p.plan_id == wid), None)
                winner_names.append(match.display_name if match else wid[:8])
            vtype = verdict.verdict_type.value.upper()
            summary = (
                f"The debate concluded with verdict {vtype}. "
                f"{'Winners: ' + ', '.join(winner_names) + '. ' if winner_names else ''}"
                f"{verdict.rationale}"
            )
        else:
            summary = f"The debate on '{run.task.title}' ended without a verdict."

        # --- key_conclusions ---
        conclusions: list[str] = []
        for rnd in run.debate_rounds:
            adj = rnd.adjudication
            if adj and adj.adopted_arguments:
                for adopted in adj.adopted_arguments[:2]:
                    conclusions.append(
                        f"[{adopted.claim_kind}] {adopted.display_name}: {adopted.summary}"
                    )
        if verdict and verdict.selected_strengths:
            for s in verdict.selected_strengths[:3]:
                conclusions.append(s)
        conclusions = conclusions[:6]

        # --- debate_highlights ---
        highlights: list[str] = []
        for rnd in run.debate_rounds:
            s = rnd.summary
            for d in s.key_disagreements[:1]:
                highlights.append(f"Round {rnd.index}: {d}")
            adj = rnd.adjudication
            if adj and adj.resolution:
                highlights.append(f"Round {rnd.index} resolution: {adj.resolution}")
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
            executive_summary=summary,
            key_conclusions=conclusions,
            debate_highlights=highlights,
            verdict_explanation=verdict_explanation,
            recommendations=recommendations,
        )

    async def _ai_synthesize(self, run: ExperimentRun) -> FinalReport | None:
        instructions = (
            "Synthesize a final executive report for this debate. "
            "Return JSON with keys: executive_summary (str), key_conclusions (list[str]), "
            "debate_highlights (list[str]), verdict_explanation (str), recommendations (list[str])."
        )
        if run.response_language and run.response_language != "auto":
            instructions += f" Write all content in {run.response_language}."

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
                "verdict_type": run.verdict.verdict_type.value if run.verdict else "none",
                "round_count": len(run.debate_rounds),
            },
        )
        payload = execution.result.json_payload
        if not payload:
            return None
        return FinalReport(
            executive_summary=str(payload.get("executive_summary", "")),
            key_conclusions=[str(i) for i in payload.get("key_conclusions", [])],
            debate_highlights=[str(i) for i in payload.get("debate_highlights", [])],
            verdict_explanation=str(payload.get("verdict_explanation", "")),
            recommendations=[str(i) for i in payload.get("recommendations", [])],
        )
