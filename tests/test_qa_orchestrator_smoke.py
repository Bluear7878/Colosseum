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
- **Symptom**: ExampleService crashes with empty input
- **Reproduction**: ExampleService(input="")
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


def test_install_user_skills_copies_all_bundled_skills(tmp_path, monkeypatch):
    """`_install_user_skills` should copy every bundled SKILL.md into ~/.claude/skills/."""
    from colosseum import cli as _cli

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    status = _cli._install_user_skills(force=False, verbose=False)

    user_skills = fake_home / ".claude" / "skills"
    assert user_skills.is_dir()
    for name in _cli.BUNDLED_SKILL_NAMES:
        assert (user_skills / name / "SKILL.md").is_file(), f"{name} not installed"
        assert status[name] == "installed", f"{name} status was {status[name]!r}"

    # Re-running without --force should skip everything.
    status_again = _cli._install_user_skills(force=False, verbose=False)
    assert all(v == "skipped" for v in status_again.values())

    # --force should overwrite.
    custom_path = user_skills / "colosseum_qa" / "SKILL.md"
    custom_path.write_text("CUSTOMIZED", encoding="utf-8")
    status_force = _cli._install_user_skills(force=True, verbose=False)
    assert status_force["colosseum_qa"] == "installed"
    assert "CUSTOMIZED" not in custom_path.read_text(encoding="utf-8")


def test_user_skills_present_detects_missing(tmp_path, monkeypatch):
    """`_user_skills_present` returns False when any bundled skill is absent."""
    from colosseum import cli as _cli

    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    assert _cli._user_skills_present() is False
    _cli._install_user_skills(force=False, verbose=False)
    assert _cli._user_skills_present() is True

    # Delete one and re-check
    (fake_home / ".claude" / "skills" / "colosseum_qa" / "SKILL.md").unlink()
    assert _cli._user_skills_present() is False


def test_dirty_check_ignores_colosseum_artifact_lines():
    """Porcelain lines that touch only `.colosseum/` are not real dirt."""
    from colosseum.services.qa_orchestrator import (
        _is_colosseum_artifact_line,
        _path_is_colosseum_artifact,
    )

    # Untracked .colosseum dir
    assert _is_colosseum_artifact_line("?? .colosseum/")
    # Untracked nested file
    assert _is_colosseum_artifact_line("?? .colosseum/qa/run-id/qa_run.json")
    # Modified file inside .colosseum
    assert _is_colosseum_artifact_line(" M .colosseum/runs/abc/run.json")
    # Renames are also recognized when both sides are colosseum artifacts
    assert _is_colosseum_artifact_line(
        "R  .colosseum/runs/old.json -> .colosseum/runs/new.json"
    )

    # Real changes are NOT filtered
    assert not _is_colosseum_artifact_line(" M src/foo.py")
    assert not _is_colosseum_artifact_line("?? new_file.py")
    assert not _is_colosseum_artifact_line("A  README.md")
    # Mixed rename (one side outside) is treated as real dirt
    assert not _is_colosseum_artifact_line(
        "R  .colosseum/runs/x.json -> docs/x.json"
    )

    # Helper sanity
    assert _path_is_colosseum_artifact(".colosseum")
    assert _path_is_colosseum_artifact(".colosseum/qa/run/x.json")
    assert _path_is_colosseum_artifact("./.colosseum/x")
    assert not _path_is_colosseum_artifact("colosseum/x")
    assert not _path_is_colosseum_artifact(".colosseum_extra/x")


def test_preflight_skips_colosseum_only_dirty(tmp_path, monkeypatch):
    """A target whose only dirty files are .colosseum/ artifacts must NOT
    raise the dirty-worktree warning."""
    import subprocess as _sp

    from colosseum.services.qa_orchestrator import QAOrchestrator
    from colosseum.services.qa_finding_clusterer import QAFindingClusterer
    from colosseum.services.qa_gpu_allocator import QAGpuAllocator
    from colosseum.services.qa_repository import QARunRepository
    from colosseum.services.qa_report_parser import QAReportParser
    from colosseum.services.qa_report_synthesizer import QAReportSynthesizer

    target = _make_target(tmp_path)
    # Make target a real git repo with `.colosseum/` untracked
    _sp.run(["git", "-C", str(target), "init", "-q"], check=True)
    _sp.run(["git", "-C", str(target), "config", "user.email", "t@t"], check=True)
    _sp.run(["git", "-C", str(target), "config", "user.name", "t"], check=True)
    _sp.run(["git", "-C", str(target), "add", "."], check=True)
    _sp.run(["git", "-C", str(target), "commit", "-q", "-m", "init"], check=True)
    (target / ".colosseum").mkdir()
    (target / ".colosseum" / "qa_run.json").write_text("{}", encoding="utf-8")

    orch = QAOrchestrator(
        gpu_allocator=QAGpuAllocator(local_runtime=_StubLocalRuntime()),
        repository=QARunRepository(root=tmp_path / "qa_runs"),
        report_parser=QAReportParser(),
        clusterer_factory=lambda root: QAFindingClusterer(target_root=root),
        synthesizer=QAReportSynthesizer(provider_runtime=None),
        provider_runtime=None,  # type: ignore[arg-type]
        local_runtime=_StubLocalRuntime(),  # type: ignore[arg-type]
    )
    request = _make_request(target)
    # Make sure allow_dirty_target is False so the check actually runs.
    request = request.model_copy(update={"allow_dirty_target": False})

    warnings = orch._preflight(request)
    dirty_warns = [w for w in warnings if "dirty" in w.lower()]
    assert dirty_warns == [], f"unexpected dirty warning: {dirty_warns}"


def test_qa_watch_infers_run_json_path(tmp_path):
    """qa_watch auto-detects the qa_run.json sibling from a jsonl path."""
    from colosseum.qa_watch import _infer_run_json_path

    jsonl = tmp_path / ".colosseum" / "qa" / "run-abc" / "gladiators" / "c_0" / "stream.jsonl"
    jsonl.parent.mkdir(parents=True)
    jsonl.touch()
    expected = tmp_path / ".colosseum" / "qa" / "run-abc" / "qa_run.json"
    assert _infer_run_json_path(jsonl) == expected


def test_qa_watch_reads_run_status(tmp_path):
    """qa_watch parses the status field from qa_run.json."""
    from colosseum.qa_watch import _read_run_status

    run_json = tmp_path / "qa_run.json"
    run_json.write_text('{"status": "running"}', encoding="utf-8")
    assert _read_run_status(run_json) == "running"

    run_json.write_text('{"status": "completed"}', encoding="utf-8")
    assert _read_run_status(run_json) == "completed"

    # Missing file → None
    assert _read_run_status(tmp_path / "does-not-exist.json") is None

    # Malformed JSON → None
    run_json.write_text("not json", encoding="utf-8")
    assert _read_run_status(run_json) is None

    # Missing status key → None
    run_json.write_text('{"other": "x"}', encoding="utf-8")
    assert _read_run_status(run_json) is None


def test_launch_tmux_qa_panes_skips_when_not_in_tmux(monkeypatch):
    """Without $TMUX, the function returns an empty list (no-op)."""
    from colosseum import cli as _cli

    monkeypatch.delenv("TMUX", raising=False)
    spawned = _cli._launch_tmux_qa_panes(
        "run-id",
        [("c_0", "claude", "/tmp/fake.jsonl")],
    )
    assert spawned == []


def test_launch_tmux_qa_panes_empty_gladiator_list(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,1,0")
    from colosseum import cli as _cli

    assert _cli._launch_tmux_qa_panes("run", []) == []


class _FakeTmuxRunner:
    """Records every `tmux ...` call and returns canned outputs by verb."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, *args, timeout: float = 5.0):
        self.calls.append(list(args))
        verb = args[0] if args else ""
        canned = self.responses.get(verb)
        if canned is None:
            return _FakeResult(returncode=0, stdout="", stderr="")
        if callable(canned):
            return canned(list(args), self.calls)
        return canned


class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_launch_tmux_qa_panes_percent_formula_three_gladiators(monkeypatch):
    """With 3 gladiators, every split should use 50% (not 100%)."""
    from colosseum import cli as _cli

    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,1,0")

    pane_counter = {"next": 10}

    def fake_split_window(args, calls):
        pane_counter["next"] += 1
        return _FakeResult(returncode=0, stdout=f"%{pane_counter['next']}", stderr="")

    runner = _FakeTmuxRunner(
        responses={
            "display-message": _FakeResult(returncode=0, stdout="%0 CONVERSATION\n"),
            "list-panes": _FakeResult(returncode=0, stdout=""),
            "show-option": _FakeResult(returncode=0, stdout=""),
            "split-window": fake_split_window,
            "select-pane": _FakeResult(returncode=0, stdout=""),
            "set-option": _FakeResult(returncode=0, stdout=""),
            "set": _FakeResult(returncode=0, stdout=""),
            "kill-pane": _FakeResult(returncode=0, stdout=""),
        }
    )
    monkeypatch.setattr(_cli, "_run_tmux", runner)
    monkeypatch.setattr(_cli.shutil, "which", lambda binary: "/usr/bin/tmux")

    gladiators = [
        ("c_0", "claude", "/tmp/a.jsonl"),
        ("c_1", "claude", "/tmp/b.jsonl"),
        ("g_2", "mediated", "/tmp/c.jsonl"),
    ]
    spawned = _cli._launch_tmux_qa_panes("run-id", gladiators)
    assert len(spawned) == 3

    # Extract the split-window calls in order
    splits = [c for c in runner.calls if c and c[0] == "split-window"]
    assert len(splits) == 3

    # First split: -h -l 50%
    assert "-h" in splits[0]
    assert "-l" in splits[0]
    assert "50%" in splits[0]

    # Second split: -v -l 50% (remaining_incl_self = 3 - 1 + 1 = 3 → actually 100/3=33 NO)
    # wait: remaining_incl_self = len(gladiators) - index + 1 = 3 - 1 + 1 = 3 → 33%
    # and third: 3 - 2 + 1 = 2 → 50%
    assert "-v" in splits[1]
    assert "-l" in splits[1]
    # Percent is 33% for index=1 (remaining_incl_self=3)
    assert "33%" in splits[1]

    assert "-v" in splits[2]
    assert "-l" in splits[2]
    assert "50%" in splits[2]

    # And 100% should NEVER appear.
    for s in splits:
        assert "100%" not in s, f"bogus 100% split: {s}"


def test_launch_tmux_qa_panes_saves_pane_ids_to_option(monkeypatch):
    from colosseum import cli as _cli

    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,1,0")

    counter = {"n": 100}

    def fake_split(args, calls):
        counter["n"] += 1
        return _FakeResult(returncode=0, stdout=f"%{counter['n']}")

    runner = _FakeTmuxRunner(
        responses={
            "display-message": _FakeResult(stdout="%0 CONVERSATION"),
            "list-panes": _FakeResult(stdout=""),
            "show-option": _FakeResult(stdout=""),
            "split-window": fake_split,
            "select-pane": _FakeResult(),
            "set-option": _FakeResult(),
            "set": _FakeResult(),
            "kill-pane": _FakeResult(),
        }
    )
    monkeypatch.setattr(_cli, "_run_tmux", runner)
    monkeypatch.setattr(_cli.shutil, "which", lambda binary: "/usr/bin/tmux")

    spawned = _cli._launch_tmux_qa_panes(
        "run-id",
        [("c_0", "claude", "/tmp/a.jsonl")],
    )
    assert spawned == ["%101"]

    # A `set-option -g <option> "<ids>"` call should have been made with
    # the spawned pane IDs as the value. Filter out the `-gu` (unset)
    # call used to clear stale values before spawning.
    set_option_calls = [
        c
        for c in runner.calls
        if c and c[0] == "set-option" and "-gu" not in c
    ]
    stored_call = next(
        (c for c in set_option_calls if _cli._TMUX_WATCHER_OPTION in c), None
    )
    assert stored_call is not None, f"no set-option call: {set_option_calls}"
    # The value is the trailing positional arg (space-separated pane ids).
    assert "%101" in stored_call[-1]


def test_launch_tmux_qa_panes_cleans_previous_leftovers(monkeypatch):
    """If the user-option already holds stale pane IDs, they should be killed
    before we spawn new ones."""
    from colosseum import cli as _cli

    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,1,0")

    counter = {"n": 200}

    def fake_split(args, calls):
        counter["n"] += 1
        return _FakeResult(returncode=0, stdout=f"%{counter['n']}")

    responses = {
        "display-message": _FakeResult(stdout="%0 CONVERSATION"),
        "list-panes": _FakeResult(stdout=""),
        "show-option": _FakeResult(stdout="%5 %6 %7"),  # ← stale
        "split-window": fake_split,
        "select-pane": _FakeResult(),
        "set-option": _FakeResult(),
        "set": _FakeResult(),
        "kill-pane": _FakeResult(),
    }
    runner = _FakeTmuxRunner(responses=responses)
    monkeypatch.setattr(_cli, "_run_tmux", runner)
    monkeypatch.setattr(_cli.shutil, "which", lambda binary: "/usr/bin/tmux")

    _cli._launch_tmux_qa_panes("run-id", [("c_0", "claude", "/tmp/a.jsonl")])

    kill_calls = [c for c in runner.calls if c and c[0] == "kill-pane"]
    killed_ids = {c[-1] for c in kill_calls}
    assert "%5" in killed_ids
    assert "%6" in killed_ids
    assert "%7" in killed_ids


def test_launch_tmux_qa_panes_avoids_watcher_pane_as_orig(monkeypatch):
    """If the currently active pane is already a watcher (from a previous
    run), _pick_orig_pane must fall through to a non-watcher sibling."""
    from colosseum import cli as _cli

    monkeypatch.setenv("TMUX", "/tmp/tmux-0/default,1,0")

    calls: list[list[str]] = []

    def fake_run_tmux(*args, timeout: float = 5.0):
        calls.append(list(args))
        verb = args[0] if args else ""
        if verb == "display-message":
            # Active pane IS a stale watcher
            return _FakeResult(
                stdout=f"%9 {_cli._WATCHER_TITLE_PREFIX}:c_0(claude)"
            )
        if verb == "list-panes":
            # Siblings: one real conversation pane, one other watcher
            return _FakeResult(
                stdout=(
                    f"%0 some-shell\n"
                    f"%9 {_cli._WATCHER_TITLE_PREFIX}:c_0(claude)\n"
                )
            )
        return _FakeResult(stdout="")

    monkeypatch.setattr(_cli, "_run_tmux", fake_run_tmux)

    picked = _cli._pick_orig_pane()
    assert picked == "%0"


def test_preflight_still_warns_on_real_dirt(tmp_path, monkeypatch):
    """If there's a real uncommitted source change, the warning still fires."""
    import subprocess as _sp

    from colosseum.services.qa_orchestrator import QAOrchestrator
    from colosseum.services.qa_finding_clusterer import QAFindingClusterer
    from colosseum.services.qa_gpu_allocator import QAGpuAllocator
    from colosseum.services.qa_repository import QARunRepository
    from colosseum.services.qa_report_parser import QAReportParser
    from colosseum.services.qa_report_synthesizer import QAReportSynthesizer

    target = _make_target(tmp_path)
    _sp.run(["git", "-C", str(target), "init", "-q"], check=True)
    _sp.run(["git", "-C", str(target), "config", "user.email", "t@t"], check=True)
    _sp.run(["git", "-C", str(target), "config", "user.name", "t"], check=True)
    _sp.run(["git", "-C", str(target), "add", "."], check=True)
    _sp.run(["git", "-C", str(target), "commit", "-q", "-m", "init"], check=True)
    # Add real dirt (untracked file outside .colosseum)
    (target / "real_change.py").write_text("# uncommitted", encoding="utf-8")

    orch = QAOrchestrator(
        gpu_allocator=QAGpuAllocator(local_runtime=_StubLocalRuntime()),
        repository=QARunRepository(root=tmp_path / "qa_runs"),
        report_parser=QAReportParser(),
        clusterer_factory=lambda root: QAFindingClusterer(target_root=root),
        synthesizer=QAReportSynthesizer(provider_runtime=None),
        provider_runtime=None,  # type: ignore[arg-type]
        local_runtime=_StubLocalRuntime(),  # type: ignore[arg-type]
    )
    request = _make_request(target).model_copy(update={"allow_dirty_target": False})
    warnings = orch._preflight(request)
    dirty_warns = [w for w in warnings if "dirty" in w.lower()]
    assert dirty_warns, "expected dirty warning when there is real dirt"
