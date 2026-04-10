"""End-to-end smoke test for QAOrchestrator using mock executors.

This test exercises:
  - Pre-flight validation (warnings only — no hard failures)
  - GPU allocation with stubbed LocalRuntimeService
  - Mock gladiator execution that writes a canned report.md
  - Report parsing
  - Finding clustering
  - Heuristic synthesis (no judge LLM call)
  - Artifact persistence
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from colosseum.core.models import (
    AgentConfig,
    LocalGpuDevice,
    ProviderConfig,
    ProviderType,
    QACreateRequest,
    QAGladiatorOutcome,
    QAGladiatorStatus,
)
from colosseum.services.qa_finding_clusterer import QAFindingClusterer
from colosseum.services.qa_gpu_allocator import QAGpuAllocator
from colosseum.services.qa_orchestrator import QAOrchestrator
from colosseum.services.qa_report_parser import QAReportParser
from colosseum.services.qa_report_synthesizer import QAReportSynthesizer
from colosseum.services.qa_repository import QARunRepository


CANNED_REPORT_TEMPLATE = """\
# QA Report — smoke test ({gid})

## Summary
- Scope: smoke
- Result: 1 reproduced bug

## Confirmed Bugs (Reproduced)

### G-001: Smoke bug from {gid}
- **Symptom**: AdvancedQuantizer crashes with sym=False
- **Reproduction**: AdvancedQuantizeParameters(sym=False)
- **Error**: ValueError: shape mismatch
- **File**: src/schema.py:142
- **Severity**: High
"""


class _StubLocalRuntime:
    def __init__(self) -> None:
        self._devices = [
            LocalGpuDevice(index=i, backend="nvidia", name=f"GPU {i}", memory_total_mb=24576)
            for i in (0, 1, 2, 3)
        ]

    def detect_gpu_devices(self):
        return list(self._devices)

    def detect_gpu_free_memory_mb(self):
        return {0: 24000, 1: 24000, 2: 24000, 3: 24000}

    def detect_gpu_compute_processes(self):
        return set()


class _MockExecutor:
    """Stand-in for ClaudeQAExecutor / MediatedQAExecutor.

    Writes a canned report.md into the gladiator dir, then returns a
    REPORT_WRITTEN outcome. No subprocess, no claude binary needed.
    """

    def __init__(self, *, gladiator_id, agent_config, gladiator_dir, assigned_gpus, **_):
        self.gladiator_id = gladiator_id
        self.agent_config = agent_config
        self.gladiator_dir = gladiator_dir
        self.assigned_gpus = assigned_gpus

    async def run(self) -> QAGladiatorOutcome:
        self.gladiator_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.gladiator_dir / "report.md"
        report_path.write_text(
            CANNED_REPORT_TEMPLATE.format(gid=self.gladiator_id), encoding="utf-8"
        )
        now = datetime.now(timezone.utc)
        return QAGladiatorOutcome(
            gladiator_id=self.gladiator_id,
            display_name=self.agent_config.display_name,
            provider_type=self.agent_config.provider.type,
            model=self.agent_config.provider.model,
            assigned_gpus=list(self.assigned_gpus),
            status=QAGladiatorStatus.REPORT_WRITTEN,
            report_path=str(report_path),
            raw_report_text=report_path.read_text(encoding="utf-8"),
            started_at=now,
            completed_at=now,
            duration_seconds=0.01,
            cost_usd=0.0,
            token_usage={"total_tokens": 100},
        )


def _mock_executor_factory(*args, **kwargs):
    return _MockExecutor(**kwargs)


def _make_target(tmp_path: Path) -> Path:
    target = tmp_path / "target_project"
    skill_dir = target / ".claude" / "skills" / "qa"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: qa\ndescription: stub\n---\n\n# stub QA skill\n",
        encoding="utf-8",
    )
    (target / "QA").mkdir(exist_ok=True)
    return target


def _make_orchestrator(tmp_path: Path) -> QAOrchestrator:
    return QAOrchestrator(
        gpu_allocator=QAGpuAllocator(local_runtime=_StubLocalRuntime()),
        repository=QARunRepository(root=tmp_path / "qa_runs"),
        report_parser=QAReportParser(),
        clusterer_factory=lambda root: QAFindingClusterer(target_root=root),
        synthesizer=QAReportSynthesizer(provider_runtime=None),  # heuristic only
        provider_runtime=None,  # type: ignore[arg-type]
        local_runtime=_StubLocalRuntime(),  # type: ignore[arg-type]
        executor_factory=_mock_executor_factory,
    )


def _make_request(target: Path) -> QACreateRequest:
    agents = [
        AgentConfig(
            agent_id="claude_a",
            display_name="Claude A",
            provider=ProviderConfig(type=ProviderType.CLAUDE_CLI, model="claude-sonnet-4-6"),
        ),
        AgentConfig(
            agent_id="claude_b",
            display_name="Claude B",
            provider=ProviderConfig(type=ProviderType.CLAUDE_CLI, model="claude-haiku-4-5"),
        ),
    ]
    return QACreateRequest(
        target_description="smoke",
        target_path=str(target),
        qa_args="smoke",
        gladiators=agents,
        judge=None,
        forced_gpus=[0, 1, 2, 3],
        gpus_per_gladiator=2,
        brief=True,  # avoid GPU detection branch entirely
        use_stash_safety=False,  # tmp_path is not a git repo
    )


@pytest.mark.asyncio
async def test_orchestrator_end_to_end_with_mock_executor(tmp_path):
    target = _make_target(tmp_path)
    orch = _make_orchestrator(tmp_path)
    request = _make_request(target)

    run = await orch.run_qa(request)

    assert run.status == "completed"
    assert len(run.gladiators) == 2
    assert all(g.status == QAGladiatorStatus.REPORT_WRITTEN for g in run.gladiators)
    assert all(g.parsed_findings for g in run.gladiators)
    assert run.synthesis is not None
    assert run.synthesis.cluster_count == 1  # both gladiators reported the same bug
    assert len(run.synthesis.canonical_findings) == 1
    canonical = run.synthesis.canonical_findings[0]
    assert "claude_a_0" in canonical.sources
    assert "claude_b_1" in canonical.sources

    # Artifact files exist
    run_dir = tmp_path / "qa_runs" / run.run_id
    assert (run_dir / "qa_run.json").exists()
    assert (run_dir / "gpu_plan.json").exists()
    assert (run_dir / "synthesized_report.md").exists()
    assert (run_dir / "findings.json").exists()
    md = (run_dir / "synthesized_report.md").read_text(encoding="utf-8")
    assert "Confirmed Bugs" in md
    assert "Smoke bug" in md


def test_streaming_emits_lifecycle_events(tmp_path):
    target = _make_target(tmp_path)
    orch = _make_orchestrator(tmp_path)
    request = _make_request(target)

    async def _collect():
        events: list[tuple[str, dict]] = []
        async for ev in orch.run_qa_streaming(request):
            events.append(ev)
        return events

    events = asyncio.run(_collect())
    types = [name for name, _ in events]
    assert "preflight" in types
    assert "gpu_plan" in types
    assert "run_initialized" in types
    assert "reports_parsed" in types
    assert "clusters_built" in types
    assert "run_completed" in types
    assert "qa_run_complete" in types


@pytest.mark.asyncio
async def test_mid_run_save_persists_per_gladiator_state(tmp_path):
    """Each gladiator's state must be persisted as it transitions, not just
    at the end of the run. We assert this by intercepting the executor with
    one that records the qa_run.json contents at the moment its run() is
    invoked."""
    target = _make_target(tmp_path)
    orch_repo_root = tmp_path / "qa_runs"
    snapshots: list[dict] = []

    class _SnapshotExecutor(_MockExecutor):
        async def run(self) -> QAGladiatorOutcome:
            # Snapshot qa_run.json at the moment we start
            for run_dir in orch_repo_root.iterdir():
                qa_path = run_dir / "qa_run.json"
                if qa_path.exists():
                    import json
                    snapshots.append(json.loads(qa_path.read_text()))
            return await super().run()

    def _factory(*args, **kwargs):
        return _SnapshotExecutor(**kwargs)

    orch = QAOrchestrator(
        gpu_allocator=QAGpuAllocator(local_runtime=_StubLocalRuntime()),
        repository=QARunRepository(root=orch_repo_root),
        report_parser=QAReportParser(),
        clusterer_factory=lambda root: QAFindingClusterer(target_root=root),
        synthesizer=QAReportSynthesizer(provider_runtime=None),
        provider_runtime=None,  # type: ignore[arg-type]
        local_runtime=_StubLocalRuntime(),  # type: ignore[arg-type]
        executor_factory=_factory,
    )
    request = _make_request(target)
    await orch.run_qa(request)

    # We should have at least one snapshot per gladiator showing them in
    # RUNNING state at the moment they were spawned. Because executors run
    # in parallel and snapshots are taken at the start of each run(), the
    # exact contents are race-prone but at minimum the file must exist
    # mid-run (not just at the end).
    assert snapshots, "expected at least one mid-run snapshot"


def test_qa_subcommand_supports_monitor_flag():
    """The qa subparser must accept --monitor / --no-monitor."""
    from colosseum.cli import build_parser

    parser = build_parser()
    ns_default = parser.parse_args(
        ["qa", "-t", "smoke", "--target", "/tmp", "-g", "claude:claude-sonnet-4-6"]
    )
    assert ns_default.monitor is True

    ns_off = parser.parse_args(
        [
            "qa",
            "-t",
            "smoke",
            "--target",
            "/tmp",
            "-g",
            "claude:claude-sonnet-4-6",
            "--no-monitor",
        ]
    )
    assert ns_off.monitor is False


def test_cli_wrapper_qa_action_skips_debate_scaffolding():
    """qa_action operation must NOT add fields list / no-fences instructions."""
    from colosseum.providers.cli_wrapper import build_prompt

    payload = {
        "operation": "qa_action",
        "instructions": "FAKE_INSTRUCTIONS_TOKEN",
        "metadata": {"response_language": "auto"},
    }
    prompt = build_prompt(payload)
    assert "FAKE_INSTRUCTIONS_TOKEN" in prompt
    assert "no markdown fences" not in prompt
    assert "Respond with valid JSON containing these fields" not in prompt
    assert "DEBATE TOPIC" not in prompt
    assert "Operation: qa_action" not in prompt


def test_cli_wrapper_debate_operation_still_adds_scaffolding():
    """Make sure we didn't break the existing debate path."""
    from colosseum.providers.cli_wrapper import build_prompt

    payload = {
        "operation": "debate",
        "instructions": "DEBATE TASK",
        "metadata": {"task_title": "Some debate"},
    }
    prompt = build_prompt(payload)
    assert "DEBATE TASK" in prompt
    assert "Respond with valid JSON containing these fields" in prompt
    assert "DEBATE TOPIC" in prompt
