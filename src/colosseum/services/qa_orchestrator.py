"""Top-level orchestrator for `colosseum qa`.

The orchestrator owns the full lifecycle of a QA ensemble run:

  1. Pre-flight validation (target dir, claude binary, GPU detection,
     dirty worktree, cost estimate)
  2. GPU partitioning across gladiators (disjoint slices)
  3. Per-run artifact directory creation + optional git stash safety net
  4. Parallel gladiator execution via asyncio.gather (Claude or Mediated
     executor depending on provider type)
  5. Per-gladiator report parsing
  6. Cross-gladiator finding clustering
  7. Judge synthesis (single LLM call) into a canonical report
  8. Artifact persistence + stash drift verification

It does NOT wrap ColosseumOrchestrator. Debate state machine semantics
do not apply to QA — gladiators don't produce Plans, don't critique each
other, and don't go through evidence-gated finalization.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from colosseum.core.models import (
    AgentConfig,
    ProviderType,
    QACreateRequest,
    QAGladiatorOutcome,
    QAGladiatorStatus,
    QAGpuPlan,
    QARun,
    QASynthesisReport,
)
from colosseum.services.local_runtime import LocalRuntimeService
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.qa_executor_claude import ClaudeQAExecutor
from colosseum.services.qa_executor_mediated import MediatedQAExecutor
from colosseum.services.qa_finding_clusterer import QAFindingClusterer
from colosseum.services.qa_gpu_allocator import (
    QAGpuAllocationError,
    QAGpuAllocator,
)
from colosseum.services.qa_report_parser import QAReportParser
from colosseum.services.qa_report_synthesizer import (
    QAReportSynthesizer,
    render_markdown_report,
)
from colosseum.services.qa_repository import QARunRepository

logger = logging.getLogger("colosseum.qa.orchestrator")


# Executor factory: produces an executor (any object with `async run() -> QAGladiatorOutcome`)
ExecutorFactory = Callable[..., Any]


def _default_executor_factory(
    *,
    gladiator_id: str,
    agent_config: AgentConfig,
    target_path: Path,
    gladiator_dir: Path,
    run_id: str,
    request: QACreateRequest,
    assigned_gpus: list[int],
    provider_runtime: ProviderRuntimeService,
    on_event: Callable[[str, dict], Awaitable[None]] | None,
) -> Any:
    if agent_config.provider.type == ProviderType.CLAUDE_CLI:
        return ClaudeQAExecutor(
            gladiator_id=gladiator_id,
            agent_config=agent_config,
            target_path=target_path,
            gladiator_dir=gladiator_dir,
            run_id=run_id,
            qa_args=request.qa_args,
            assigned_gpus=assigned_gpus,
            brief=request.brief,
            spec=request.spec,
            keep_bug_outputs=request.keep_bug_outputs,
            response_language=request.response_language,
            max_budget_usd=request.max_budget_usd_per_gladiator,
            max_gladiator_minutes=request.max_gladiator_minutes,
            stall_timeout_minutes=request.stall_timeout_minutes,
            on_event=on_event,
        )
    return MediatedQAExecutor(
        gladiator_id=gladiator_id,
        agent_config=agent_config,
        target_path=target_path,
        gladiator_dir=gladiator_dir,
        run_id=run_id,
        qa_args=request.qa_args,
        assigned_gpus=assigned_gpus,
        provider_runtime=provider_runtime,
        brief=request.brief,
        spec=request.spec,
        keep_bug_outputs=request.keep_bug_outputs,
        response_language=request.response_language,
        max_budget_usd=request.max_budget_usd_per_gladiator,
        max_gladiator_minutes=request.max_gladiator_minutes,
        stall_timeout_minutes=request.stall_timeout_minutes,
        on_event=on_event,
    )


class QAOrchestrator:
    """End-to-end driver for `colosseum qa` runs."""

    def __init__(
        self,
        gpu_allocator: QAGpuAllocator,
        repository: QARunRepository,
        report_parser: QAReportParser,
        clusterer_factory: Callable[[str], QAFindingClusterer],
        synthesizer: QAReportSynthesizer,
        provider_runtime: ProviderRuntimeService,
        local_runtime: LocalRuntimeService,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        self.gpu_allocator = gpu_allocator
        self.repository = repository
        self.report_parser = report_parser
        self.clusterer_factory = clusterer_factory
        self.synthesizer = synthesizer
        self.provider_runtime = provider_runtime
        self.local_runtime = local_runtime
        self.executor_factory = executor_factory or _default_executor_factory

    # ── public API ──────────────────────────────────────────────────

    async def run_qa(self, request: QACreateRequest) -> QARun:
        async def _swallow(_name: str, _payload: dict[str, Any]) -> None:
            return None

        run = QARun(request=request, status="pending")
        await self._drive(run, request, _swallow)
        return run

    async def run_qa_streaming(
        self, request: QACreateRequest
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        run = QARun(request=request, status="pending")
        queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        async def _enqueue(name: str, payload: dict[str, Any]) -> None:
            await queue.put((name, payload))

        async def _drive_task() -> None:
            try:
                await self._drive(run, request, _enqueue)
            finally:
                await queue.put(None)

        task = asyncio.create_task(_drive_task())
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        await task
        yield ("qa_run_complete", {"run_id": run.run_id, "status": run.status})

    # ── core driver ─────────────────────────────────────────────────

    async def _drive(
        self,
        run: QARun,
        request: QACreateRequest,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> None:
        run.status = "running"
        run.touch()

        # ── Pre-flight ──────────────────────────────────────────────
        warnings = self._preflight(request)
        run.preflight_warnings = warnings
        await emit("preflight", {"warnings": warnings})

        # ── GPU allocation ──────────────────────────────────────────
        try:
            eligible, detected, reasons = self.gpu_allocator.detect_eligible_gpus(
                forced_indices=request.forced_gpus,
            )
            gladiator_ids = [self._gladiator_id(g, i) for i, g in enumerate(request.gladiators)]
            plan = self.gpu_allocator.allocate(
                gladiator_ids=gladiator_ids,
                eligible=eligible,
                detected=detected,
                ineligible_reasons=reasons,
                gpus_per_gladiator=request.gpus_per_gladiator,
                sequential=request.sequential,
                forced_indices=request.forced_gpus,
            )
        except QAGpuAllocationError as exc:
            run.status = "failed"
            run.error_message = str(exc)
            await emit("preflight_failed", {"error": str(exc)})
            self.repository.save_run(run)
            return

        run.gpu_plan = plan
        await emit(
            "gpu_plan",
            {
                "detected": plan.detected_devices,
                "eligible": plan.eligible_devices,
                "allocations": plan.allocations,
                "mode": plan.mode,
            },
        )

        # ── Init artifact tree ──────────────────────────────────────
        run.gladiators = [
            QAGladiatorOutcome(
                gladiator_id=gladiator_ids[i],
                display_name=g.display_name,
                provider_type=g.provider.type,
                model=g.provider.model,
                assigned_gpus=plan.allocations.get(gladiator_ids[i], []),
                status=QAGladiatorStatus.PENDING,
            )
            for i, g in enumerate(request.gladiators)
        ]
        self.repository.init_run(run)
        await emit("run_initialized", {"run_id": run.run_id})

        # ── Stash safety net ────────────────────────────────────────
        target_path = Path(request.target_path).resolve()
        if request.use_stash_safety:
            run.stash_ref = self._take_stash(target_path, run.run_id)
            if run.stash_ref:
                await emit("stash_taken", {"ref": run.stash_ref})

        # ── Spawn gladiators ────────────────────────────────────────
        try:
            outcomes = await self._spawn_gladiators(
                run=run,
                request=request,
                target_path=target_path,
                gladiator_ids=gladiator_ids,
                plan=plan,
                emit=emit,
            )
        except Exception as exc:
            run.status = "failed"
            run.error_message = f"gladiator spawn failed: {exc}"
            await emit("run_failed", {"error": run.error_message})
            self.repository.save_run(run)
            return
        run.gladiators = outcomes
        self.repository.save_run(run)

        # ── Parse reports ───────────────────────────────────────────
        for outcome in outcomes:
            if outcome.raw_report_text:
                findings, unstructured, status = self.report_parser.parse(
                    outcome.raw_report_text, outcome.gladiator_id
                )
                outcome.parsed_findings = findings
                outcome.raw_unstructured_sections = unstructured
                outcome.parse_status = status
            else:
                outcome.parse_status = "skipped"
        await emit(
            "reports_parsed",
            {
                "totals": {o.gladiator_id: len(o.parsed_findings) for o in outcomes},
            },
        )
        self.repository.save_run(run)

        # ── Cluster ─────────────────────────────────────────────────
        clusterer = self.clusterer_factory(str(target_path))
        clusters = clusterer.cluster(outcomes)
        await emit("clusters_built", {"count": len(clusters)})

        # ── Synthesize ──────────────────────────────────────────────
        synthesis: QASynthesisReport
        try:
            synthesis = await self.synthesizer.synthesize(
                run_id=run.run_id,
                request=request,
                outcomes=outcomes,
                clusters=clusters,
                judge_provider=request.judge,
            )
        except Exception as exc:
            logger.warning("synthesis failed entirely: %s", exc, exc_info=True)
            synthesis = QASynthesisReport(
                run_id=run.run_id,
                target_description=request.target_description,
                target_path=request.target_path,
                qa_args=request.qa_args,
                cluster_count=len(clusters),
                overall_summary=f"Synthesis failed: {exc}",
            )
        run.synthesis = synthesis

        # ── Render + persist ────────────────────────────────────────
        try:
            markdown = render_markdown_report(synthesis, outcomes)
            self.repository.save_synthesized_markdown(run.run_id, markdown)
        except Exception as exc:
            logger.warning("could not render markdown: %s", exc)

        # ── Stash verify ────────────────────────────────────────────
        drift = []
        if request.use_stash_safety and run.stash_ref:
            drift = self._verify_stash(target_path)
            if drift:
                await emit("stash_drift", {"files": drift})
                logger.warning(
                    "QA run drifted target files outside report path: %s", drift
                )

        run.status = "completed"
        run.touch()
        self.repository.save_run(run)
        await emit(
            "run_completed",
            {
                "run_id": run.run_id,
                "canonical_findings": len(synthesis.canonical_findings),
                "total_cost_usd": run.total_cost_usd(),
            },
        )

    # ── helpers ─────────────────────────────────────────────────────

    async def _spawn_gladiators(
        self,
        run: QARun,
        request: QACreateRequest,
        target_path: Path,
        gladiator_ids: list[str],
        plan: QAGpuPlan,
        emit: Callable[[str, dict[str, Any]], Awaitable[None]],
    ) -> list[QAGladiatorOutcome]:
        async def _on_event(name: str, payload: dict[str, Any]) -> None:
            await emit(name, payload)

        results: list[QAGladiatorOutcome | None] = [None] * len(gladiator_ids)

        def _persist_snapshot() -> None:
            run.gladiators = [
                r if r is not None else run.gladiators[i]
                for i, r in enumerate(results)
            ]
            run.touch()
            try:
                self.repository.save_run(run)
            except Exception as exc:
                logger.warning("mid-run save_run failed: %s", exc)

        async def _run_one(idx: int) -> QAGladiatorOutcome:
            gladiator_id = gladiator_ids[idx]
            agent = request.gladiators[idx]
            gladiator_dir = self.repository.gladiator_dir(run.run_id, gladiator_id)
            assigned = plan.allocations.get(gladiator_id, [])

            # Mark this gladiator as RUNNING in the persisted snapshot so
            # external observers can tell it has actually started.
            run.gladiators[idx].status = QAGladiatorStatus.RUNNING
            run.gladiators[idx].started_at = datetime.now(timezone.utc)
            _persist_snapshot()

            executor = self.executor_factory(
                gladiator_id=gladiator_id,
                agent_config=agent,
                target_path=target_path,
                gladiator_dir=gladiator_dir,
                run_id=run.run_id,
                request=request,
                assigned_gpus=assigned,
                provider_runtime=self.provider_runtime,
                on_event=_on_event,
            )
            try:
                outcome = await executor.run()
            except Exception as exc:
                logger.exception("gladiator %s crashed", gladiator_id)
                outcome = QAGladiatorOutcome(
                    gladiator_id=gladiator_id,
                    display_name=agent.display_name,
                    provider_type=agent.provider.type,
                    model=agent.provider.model,
                    assigned_gpus=assigned,
                    status=QAGladiatorStatus.FAILED,
                    error=str(exc),
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
            results[idx] = outcome
            _persist_snapshot()
            return outcome

        if plan.mode == "sequential":
            for idx in range(len(gladiator_ids)):
                await _run_one(idx)
        else:
            coros = [_run_one(i) for i in range(len(gladiator_ids))]
            await asyncio.gather(*coros)

        return [r if r is not None else run.gladiators[i] for i, r in enumerate(results)]

    def _preflight(self, request: QACreateRequest) -> list[str]:
        warnings: list[str] = []
        target_path = Path(request.target_path)
        if not target_path.exists():
            warnings.append(f"target path does not exist: {target_path}")
        else:
            skill_md = target_path / ".claude" / "skills" / "qa" / "SKILL.md"
            if not skill_md.exists():
                warnings.append(
                    f"target {target_path} has no .claude/skills/qa/SKILL.md — "
                    "Claude gladiators will fail and mediated executor will too"
                )

        # claude binary check
        if any(g.provider.type == ProviderType.CLAUDE_CLI for g in request.gladiators):
            if shutil.which("claude") is None:
                warnings.append(
                    "claude binary not found on PATH — Claude gladiators will fail"
                )

        # Non-Claude provider binary checks. Mediated executor needs the
        # vendor CLI to be installed and on PATH (it shells out via the
        # shared cli_wrapper subprocess).
        provider_binary = {
            ProviderType.GEMINI_CLI: "gemini",
            ProviderType.CODEX_CLI: "codex",
            ProviderType.OLLAMA: "ollama",
            ProviderType.HUGGINGFACE_LOCAL: "ollama",
        }
        for ag in request.gladiators:
            ptype = ag.provider.type
            if ptype == ProviderType.CLAUDE_CLI or ptype == ProviderType.MOCK:
                continue
            binary = provider_binary.get(ptype)
            if binary and shutil.which(binary) is None:
                warnings.append(
                    f"non-Claude gladiator '{ag.display_name}' needs '{binary}' "
                    f"on PATH but it is not installed; mediated executor will fail"
                )

        # Mediated-executor capability warning. Non-Claude gladiators
        # cannot dispatch sub-agents, so they're effectively limited to
        # Layer 1-3 of the QA skill. Surface this once per run.
        non_claude_count = sum(
            1
            for ag in request.gladiators
            if ag.provider.type not in (ProviderType.CLAUDE_CLI, ProviderType.MOCK)
        )
        if non_claude_count > 0:
            warnings.append(
                f"{non_claude_count} non-Claude gladiator(s) will run via the "
                f"mediated executor (no native sub-agent dispatch — Layer 1-3 only). "
                f"QA depth will be reduced for those gladiators."
            )

        # nvidia-smi check
        if not request.brief:
            if shutil.which("nvidia-smi") is None:
                warnings.append(
                    "nvidia-smi not found — running without GPU detection. "
                    "Pass --brief to skip GPU execution explicitly."
                )

        # dirty worktree check
        if target_path.exists() and not request.allow_dirty_target:
            try:
                result = subprocess.run(
                    ["git", "-C", str(target_path), "status", "--porcelain"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    warnings.append(
                        "target git working tree is dirty — uncommitted changes "
                        "may interfere with stash safety net"
                    )
            except (FileNotFoundError, subprocess.SubprocessError):
                pass

        return warnings

    def _take_stash(self, target_path: Path, run_id: str) -> str | None:
        if shutil.which("git") is None:
            return None
        try:
            result = subprocess.run(
                ["git", "-C", str(target_path), "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None
        except (FileNotFoundError, subprocess.SubprocessError):
            return None

        try:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(target_path),
                    "stash",
                    "push",
                    "-u",
                    "-m",
                    f"colosseum-qa-{run_id}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None
            stash_list = subprocess.run(
                ["git", "-C", str(target_path), "stash", "list", "--format=%H %s"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in stash_list.stdout.splitlines():
                if f"colosseum-qa-{run_id}" in line:
                    return line.split()[0]
        except (FileNotFoundError, subprocess.SubprocessError):
            return None
        return None

    def _verify_stash(self, target_path: Path) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(target_path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except (FileNotFoundError, subprocess.SubprocessError):
            return []

    def _gladiator_id(self, agent: AgentConfig, index: int) -> str:
        base = agent.agent_id or agent.display_name.lower().replace(" ", "_")
        # Replace any provider-prefix characters that would break paths.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in base)
        return f"{safe}_{index}"
