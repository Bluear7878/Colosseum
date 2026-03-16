"""Multi-phase code review orchestrator.

Composes the existing debate infrastructure to run 5 review phases (A–E),
each as a mini-debate via ColosseumOrchestrator.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from colosseum.core.config import REVIEW_PHASE_CONFIG
from colosseum.core.models import (
    ExperimentRun,
    PhaseResult,
    ReviewCreateRequest,
    ReviewFinding,
    ReviewPhase,
    ReviewReport,
    ReviewSeverity,
    RunCreateRequest,
    TaskSpec,
    TaskType,
    UsageMetrics,
)
from colosseum.services.orchestrator import ColosseumOrchestrator
from colosseum.services.review_prompts import build_review_problem_statement


class ReviewOrchestrator:
    """Run a multi-phase code review using the debate engine."""

    def __init__(self, orchestrator: ColosseumOrchestrator) -> None:
        self.orchestrator = orchestrator

    async def run_review(self, request: ReviewCreateRequest) -> ReviewReport:
        """Run all requested review phases sequentially and aggregate results."""
        # Freeze context once
        bundle = self.orchestrator.context_service.freeze(request.context_sources)

        phase_results: list[PhaseResult] = []
        for phase in request.phases:
            phase_request = self._build_phase_request(request, phase)
            try:
                run = await self.orchestrator.create_run_with_bundle(phase_request, bundle)
                result = self._extract_phase_result(phase, run)
            except Exception as exc:
                result = PhaseResult(
                    phase=phase,
                    phase_label=REVIEW_PHASE_CONFIG[phase.value]["label"],
                    run_id="",
                    phase_summary=f"Phase failed: {exc}",
                )
            phase_results.append(result)

        return self._synthesize_review_report(request, phase_results)

    # Inner event types forwarded during review phases for live display.
    _DISPLAY_EVENTS = frozenset({
        "agent_planning", "plan_ready", "agent_thinking",
        "agent_message", "judge_decision", "debate_round_start",
    })

    async def run_review_streaming(
        self, request: ReviewCreateRequest
    ) -> AsyncIterator[tuple[str, Any]]:
        """Run review phases, yielding events for each phase."""
        bundle = self.orchestrator.context_service.freeze(request.context_sources)
        yield ("review_start", {"target": request.target_description, "phases": [p.value for p in request.phases]})

        phase_results: list[PhaseResult] = []
        for i, phase in enumerate(request.phases):
            config = REVIEW_PHASE_CONFIG[phase.value]
            yield ("phase_start", {"phase": phase.value, "label": config["label"], "index": i + 1, "total": len(request.phases)})

            phase_request = self._build_phase_request(request, phase)
            try:
                run = None
                async for event_type, event_data in self.orchestrator.create_run_with_bundle_streaming(phase_request, bundle):
                    if event_type == "_run_complete":
                        run = event_data
                    elif event_type in self._DISPLAY_EVENTS and isinstance(event_data, dict):
                        yield ("inner_" + event_type, event_data)
                if run is None:
                    raise RuntimeError("Phase run did not complete")
                result = self._extract_phase_result(phase, run)
                yield ("phase_complete", {
                    "phase": phase.value,
                    "label": config["label"],
                    "findings_count": len(result.findings),
                    "summary": result.phase_summary,
                    "run_id": result.run_id,
                    "usage": {"total_tokens": result.usage.total_tokens, "estimated_cost_usd": result.usage.estimated_cost_usd},
                })
            except Exception as exc:
                result = PhaseResult(
                    phase=phase,
                    phase_label=config["label"],
                    run_id="",
                    phase_summary=f"Phase failed: {exc}",
                )
                yield ("phase_failed", {"phase": phase.value, "label": config["label"], "error": str(exc)})
            phase_results.append(result)

        report = self._synthesize_review_report(request, phase_results)
        yield ("review_complete", {
            "review_id": report.review_id,
            "total_findings": report.total_findings,
            "critical_count": report.critical_count,
            "high_count": report.high_count,
            "medium_count": report.medium_count,
            "low_count": report.low_count,
            "overall_summary": report.overall_summary,
        })
        yield ("_review_report", report)

    def _build_phase_request(
        self, request: ReviewCreateRequest, phase: ReviewPhase
    ) -> RunCreateRequest:
        """Build a RunCreateRequest for a single review phase."""
        config = REVIEW_PHASE_CONFIG[phase.value]
        criteria = config["criteria"]

        problem_statement = build_review_problem_statement(
            phase=phase,
            target_description=request.target_description,
            criteria=criteria,
            rules_context=request.rules_context,
            git_diff=request.git_diff,
            response_language=request.response_language,
        )

        task = TaskSpec(
            title=f"{config['task_title_prefix']} {request.target_description[:100]}",
            problem_statement=problem_statement,
            task_type=TaskType.TECHNICAL_REVIEW,
            success_criteria=criteria,
        )

        return RunCreateRequest(
            project_name=request.project_name,
            response_language=request.response_language,
            task=task,
            context_sources=request.context_sources,
            agents=request.agents,
            judge=request.judge,
            budget_policy=request.budget_policy,
        )

    def _extract_phase_result(
        self, phase: ReviewPhase, run: ExperimentRun
    ) -> PhaseResult:
        """Extract findings from a completed review phase run."""
        config = REVIEW_PHASE_CONFIG[phase.value]
        findings = self._extract_findings(phase, run)

        # Build phase summary from the run's final report or verdict
        phase_summary = ""
        if run.final_report:
            phase_summary = run.final_report.executive_summary
        elif run.verdict:
            phase_summary = run.verdict.rationale

        usage = run.budget_ledger.total
        return PhaseResult(
            phase=phase,
            phase_label=config["label"],
            run_id=run.run_id,
            findings=findings,
            phase_summary=phase_summary,
            verdict_type=run.verdict.verdict_type if run.verdict else None,
            confidence=run.verdict.confidence if run.verdict else 0.0,
            usage=usage,
        )

    def _extract_findings(
        self, phase: ReviewPhase, run: ExperimentRun
    ) -> list[ReviewFinding]:
        """Extract structured review findings from run artifacts."""
        findings: list[ReviewFinding] = []

        # Extract from plans (weaknesses -> findings)
        for plan in run.plans:
            for weakness in plan.weaknesses:
                severity = self._infer_severity(weakness)
                findings.append(ReviewFinding(
                    phase=phase,
                    severity=severity,
                    title=weakness[:120],
                    description=weakness,
                    recommendation="",
                    agent_consensus=0.5,
                ))
            for risk in plan.risks:
                severity = self._map_risk_severity(risk.severity)
                findings.append(ReviewFinding(
                    phase=phase,
                    severity=severity,
                    title=risk.title[:120],
                    description=risk.mitigation,
                    recommendation=risk.mitigation,
                    agent_consensus=0.6,
                ))

        # Extract from verdict strengths/risks
        if run.verdict:
            for risk_text in run.verdict.rejected_risks:
                findings.append(ReviewFinding(
                    phase=phase,
                    severity=ReviewSeverity.MEDIUM,
                    title=risk_text[:120],
                    description=risk_text,
                    agent_consensus=0.7,
                ))

        # Deduplicate by title similarity
        seen_titles: set[str] = set()
        unique: list[ReviewFinding] = []
        for f in findings:
            key = f.title.lower().strip()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                unique.append(f)
        return unique

    @staticmethod
    def _infer_severity(text: str) -> ReviewSeverity:
        """Infer severity from free-text description."""
        lower = text.lower()
        if any(w in lower for w in ("critical", "vulnerability", "injection", "exploit")):
            return ReviewSeverity.CRITICAL
        if any(w in lower for w in ("high", "serious", "major", "security")):
            return ReviewSeverity.HIGH
        if any(w in lower for w in ("medium", "moderate", "should")):
            return ReviewSeverity.MEDIUM
        if any(w in lower for w in ("low", "minor", "nitpick", "style")):
            return ReviewSeverity.LOW
        return ReviewSeverity.MEDIUM

    @staticmethod
    def _map_risk_severity(severity: str) -> ReviewSeverity:
        mapping = {"high": ReviewSeverity.HIGH, "medium": ReviewSeverity.MEDIUM, "low": ReviewSeverity.LOW}
        return mapping.get(severity, ReviewSeverity.MEDIUM)

    def _synthesize_review_report(
        self, request: ReviewCreateRequest, phase_results: list[PhaseResult]
    ) -> ReviewReport:
        """Aggregate all phase results into a final ReviewReport."""
        all_findings: list[ReviewFinding] = []
        total_usage = UsageMetrics()
        reviewed_paths: set[str] = set()

        for pr in phase_results:
            all_findings.extend(pr.findings)
            total_usage.add(pr.usage)
            for f in pr.findings:
                if f.file_path:
                    reviewed_paths.add(f.file_path)

        critical = sum(1 for f in all_findings if f.severity == ReviewSeverity.CRITICAL)
        high = sum(1 for f in all_findings if f.severity == ReviewSeverity.HIGH)
        medium = sum(1 for f in all_findings if f.severity == ReviewSeverity.MEDIUM)
        low = sum(1 for f in all_findings if f.severity == ReviewSeverity.LOW)

        # Build overall summary
        summaries = [pr.phase_summary for pr in phase_results if pr.phase_summary]
        overall_summary = " | ".join(summaries) if summaries else "Review completed."

        # Top recommendations: high-severity findings' recommendations
        top_recs: list[str] = []
        for f in sorted(all_findings, key=lambda x: list(ReviewSeverity).index(x.severity)):
            if f.recommendation and f.recommendation not in top_recs:
                top_recs.append(f.recommendation)
            if len(top_recs) >= 5:
                break

        return ReviewReport(
            target_description=request.target_description,
            phase_results=phase_results,
            total_findings=len(all_findings),
            critical_count=critical,
            high_count=high,
            medium_count=medium,
            low_count=low,
            overall_summary=overall_summary,
            top_recommendations=top_recs,
            total_usage=total_usage,
            git_diff_included=bool(request.git_diff),
            reviewed_paths=sorted(reviewed_paths),
        )
