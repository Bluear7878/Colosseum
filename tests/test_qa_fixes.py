"""Tests for QA fixes: bug fixes, feature improvements, and CLI changes."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from colosseum.core.models import (
    AgentConfig,
    BudgetLedger,
    ExperimentRun,
    JudgeConfig,
    JudgeMode,
    PlanDocument,
    ProviderConfig,
    TaskSpec,
    UsageMetrics,
)
from colosseum.main import app
from colosseum.providers.mock import MockProvider
from colosseum.services.judge import JudgeService
from colosseum.services.budget import BudgetManager
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderRuntimeService


# ── Bug fix: MockProvider produces varied plans ─────────────────

@pytest.mark.asyncio
async def test_mock_provider_produces_different_plans_for_different_agents():
    """Same model with different agent_ids (mock vs mock_1) should produce different plans."""
    provider_same = MockProvider(model_name="x")
    result_1 = await provider_same.generate("plan", "test", {"agent_id": "mock", "task_title": "Test"})
    result_2 = await provider_same.generate("plan", "test", {"agent_id": "mock_1", "task_title": "Test"})
    summary_1 = result_1.json_payload.get("summary", "")
    summary_2 = result_2.json_payload.get("summary", "")
    assert summary_1 != summary_2, "Same model with different agent_ids should produce different plans"


# ── Bug fix: No duplicate strengths in merged verdict ───────────

def test_merged_verdict_has_no_duplicate_strengths():
    """Merged verdict should deduplicate strengths from both plans."""
    budget_manager = BudgetManager()
    provider_runtime = ProviderRuntimeService(budget_manager=budget_manager)
    judge = JudgeService(budget_manager=budget_manager, provider_runtime=provider_runtime)

    # Create two plans with overlapping strengths
    plan_a = PlanDocument(
        agent_id="a",
        display_name="A",
        summary="Plan A",
        strengths=["Strong design", "Good testing", "Fast"],
    )
    plan_b = PlanDocument(
        agent_id="b",
        display_name="B",
        summary="Plan B",
        strengths=["Strong design", "Low cost", "Good testing"],
    )

    merged = judge._build_merged_plan(plan_a, plan_b)
    # Check no duplicates in merged strengths
    assert len(merged.strengths) == len(set(merged.strengths)), \
        f"Merged strengths have duplicates: {merged.strengths}"


def test_automated_finalize_deduplicates_strengths():
    """_automated_finalize should produce unique strengths list."""
    budget_manager = BudgetManager()
    provider_runtime = ProviderRuntimeService(budget_manager=budget_manager)
    judge = JudgeService(budget_manager=budget_manager, provider_runtime=provider_runtime)

    run = ExperimentRun(
        project_name="test",
        task=TaskSpec(title="T", problem_statement="P"),
        agents=[
            AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig()),
            AgentConfig(agent_id="b", display_name="B", provider=ProviderConfig()),
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED, prefer_merged_plan_on_close_scores=True),
    )

    # Create plans with identical scores and same strengths
    plan_a = PlanDocument(
        agent_id="a", display_name="A", summary="Plan A",
        strengths=["Reusable", "Scalable"],
        evidence_basis=["e1", "e2", "e3"],
        assumptions=["a1"],
        architecture=["arch1", "arch2"],
        implementation_strategy=["s1"],
        weaknesses=["w1"],
    )
    plan_b = PlanDocument(
        agent_id="b", display_name="B", summary="Plan B",
        strengths=["Reusable", "Fast"],
        evidence_basis=["e1", "e2", "e3"],
        assumptions=["a1"],
        architecture=["arch1", "arch2"],
        implementation_strategy=["s1"],
        weaknesses=["w1"],
    )
    run.plans = [plan_a, plan_b]
    run.plan_evaluations = judge.evaluate_plans(run.plans)

    verdict = judge._automated_finalize(run, None)
    assert verdict.verdict_type.value == "merged"
    assert len(verdict.selected_strengths) == len(set(verdict.selected_strengths)), \
        f"Verdict strengths have duplicates: {verdict.selected_strengths}"


# ── Bug fix: CLI exit codes ────────────────────────────────────

def test_cli_show_nonexistent_returns_nonzero():
    """'colosseum show nonexistent' should exit with code 1."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "show", "nonexistent_run_xyz"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0, "show for nonexistent run should exit non-zero"


# ── Feature: --version flag ──────────────────────────────────

def test_cli_version():
    """'colosseum --version' should print version."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


# ── Feature: --mock flag ─────────────────────────────────────

def test_cli_mock_flag_runs_debate():
    """'colosseum debate --topic X --mock --depth 1' should complete."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate", "--topic", "Mock flag test", "--mock", "--depth", "1"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "VERDICT" in result.stdout


# ── Feature: --json flag ─────────────────────────────────────

def test_cli_json_output_is_valid_json():
    """'colosseum debate --topic X --mock --depth 1 --json' should output valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate", "--topic", "JSON test", "--mock", "--depth", "1", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "completed"
    assert "verdict" in data
    assert len(data["plans"]) >= 2


# ── Feature: delete command ──────────────────────────────────

def test_cli_delete_nonexistent():
    """'colosseum delete nonexistent' should fail gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "delete", "nonexistent_run_xyz"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


# ── API: Comprehensive endpoint tests ────────────────────────

@pytest.fixture
def client():
    return TestClient(app)


def test_api_create_run_with_mock_agents(client):
    """Create a full run with mock agents via API."""
    r = client.post("/runs", json={
        "project_name": "QA",
        "task": {"title": "API QA", "problem_statement": "test"},
        "context_sources": [{"source_id": "t", "kind": "inline_text", "label": "t", "content": "x"}],
        "agents": [
            {"agent_id": "a", "display_name": "A", "provider": {"type": "mock", "model": "a"}},
            {"agent_id": "b", "display_name": "B", "provider": {"type": "mock", "model": "b"}},
        ],
        "judge": {"mode": "automated"},
        "budget_policy": {"max_rounds": 1},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert len(data["plans"]) == 2
    assert data["verdict"] is not None


def test_api_sse_stream_delivers_all_phases(client):
    """SSE stream should include init, planning, plans_ready, and complete."""
    r = client.post("/runs/stream", json={
        "project_name": "SSE",
        "task": {"title": "SSE", "problem_statement": "test"},
        "context_sources": [{"source_id": "t", "kind": "inline_text", "label": "t", "content": "x"}],
        "agents": [
            {"agent_id": "a", "display_name": "A", "provider": {"type": "mock", "model": "a"}},
            {"agent_id": "b", "display_name": "B", "provider": {"type": "mock", "model": "b"}},
        ],
        "judge": {"mode": "automated"},
        "budget_policy": {"max_rounds": 1},
    })
    events = [json.loads(line[6:]) for line in r.text.split("\n") if line.startswith("data:")]
    phases = [e.get("phase") for e in events]
    assert "init" in phases
    assert "plans_ready" in phases
    assert "complete" in phases


def test_api_human_judge_select_winner(client):
    """Human judge can select a winner."""
    r = client.post("/runs", json={
        "project_name": "HJ",
        "task": {"title": "HJ", "problem_statement": "test"},
        "context_sources": [{"source_id": "t", "kind": "inline_text", "label": "t", "content": "x"}],
        "agents": [
            {"agent_id": "a", "display_name": "A", "provider": {"type": "mock", "model": "a"}},
            {"agent_id": "b", "display_name": "B", "provider": {"type": "mock", "model": "b"}},
        ],
        "judge": {"mode": "human"},
    })
    run = r.json()
    assert run["status"] == "awaiting_human_judge"

    plan_id = run["plans"][0]["plan_id"]
    r2 = client.post(f'/runs/{run["run_id"]}/judge-actions', json={
        "action": "select_winner",
        "winning_plan_ids": [plan_id],
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"
    assert r2.json()["verdict"]["verdict_type"] == "winner"


# ── Bug fix: Repeated -g flags accumulate gladiators ─────────

def test_cli_repeated_g_flags_accumulate():
    """'debate -g mock:a -g mock:b' should accumulate into 2 gladiators."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate",
         "-g", "mock:alpha", "-g", "mock:beta",
         "--topic", "Repeated -g test", "--depth", "1"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Repeated -g should work but got exit {result.returncode}: {result.stderr}"
    )
    assert "VERDICT" in result.stdout


def test_cli_mixed_g_flag_styles():
    """'-g a b -g c' should accumulate all 3 gladiators."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate",
         "-g", "mock:a", "mock:b", "-g", "mock:c",
         "--topic", "Mixed -g test", "--depth", "1"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"Mixed -g styles should work but got exit {result.returncode}: {result.stderr}"
    )


# ── Bug fix: JSON output has no ANSI escape codes ────────────

def test_cli_json_output_no_ansi():
    """--json output must not contain ANSI escape sequences."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate",
         "--topic", "ANSI test", "--mock", "--depth", "1", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    assert "\x1b" not in result.stdout, "ANSI escape codes leaked into JSON output"
    json.loads(result.stdout)  # must parse cleanly


# ── Internal: MockProvider all operations ─────────────────────

@pytest.mark.asyncio
async def test_mock_provider_debate_operation():
    """MockProvider debate should return structured critique/defense points."""
    provider = MockProvider(model_name="test")
    result = await provider.generate("debate", "inst", {
        "round_type": "critique",
        "own_plan_id": "p1",
        "own_display_name": "Agent A",
        "other_plan_ids": ["p2"],
        "other_plan_labels": ["Agent B"],
    })
    payload = result.json_payload
    assert "critique_points" in payload
    assert "defense_points" in payload
    assert len(payload["critique_points"]) > 0


@pytest.mark.asyncio
async def test_mock_provider_judge_operation():
    """MockProvider judge should return action and confidence."""
    provider = MockProvider(model_name="test")
    result = await provider.generate("judge", "inst", {
        "suggested_action": "continue_debate",
    })
    payload = result.json_payload
    assert payload["action"] == "continue_debate"
    assert 0 < payload["confidence"] <= 1.0
    assert "reasoning" in payload


@pytest.mark.asyncio
async def test_mock_provider_synthesis_operation():
    """MockProvider synthesis should reference basis plan IDs."""
    provider = MockProvider(model_name="test")
    result = await provider.generate("synthesis", "inst", {
        "basis_plan_ids": ["plan_a", "plan_b"],
    })
    payload = result.json_payload
    assert "plan_a" in payload["strengths"][1]
    assert "plan_b" in payload["strengths"][1]


@pytest.mark.asyncio
async def test_mock_provider_unknown_operation():
    """MockProvider should handle unknown operations gracefully."""
    provider = MockProvider(model_name="test")
    result = await provider.generate("unknown_op", "inst", {})
    assert "Unsupported" in result.json_payload.get("content", "")


# ── Internal: UsageMetrics & BudgetLedger ─────────────────────

def test_usage_metrics_add_and_computed_field():
    """UsageMetrics.add() accumulates and total_tokens is computed."""
    a = UsageMetrics(prompt_tokens=100, completion_tokens=200)
    assert a.total_tokens == 300
    b = UsageMetrics(prompt_tokens=50, completion_tokens=75)
    a.add(b)
    assert a.prompt_tokens == 150
    assert a.completion_tokens == 275
    assert a.total_tokens == 425


def test_budget_ledger_record():
    """BudgetLedger.record() tracks by actor and by round."""
    ledger = BudgetLedger()
    usage = UsageMetrics(prompt_tokens=100, completion_tokens=200)
    ledger.record("agent-a", usage, round_index=0)
    assert ledger.total.total_tokens == 300
    assert ledger.by_actor["agent-a"].total_tokens == 300
    assert ledger.by_round["0"].total_tokens == 300

    usage2 = UsageMetrics(prompt_tokens=50, completion_tokens=50)
    ledger.record("agent-b", usage2, round_index=0)
    assert ledger.total.total_tokens == 400
    assert ledger.by_round["0"].total_tokens == 400


# ── Internal: Normalizer fallback handling ────────────────────

def test_normalizer_plan_from_valid_json():
    """Normalizer should produce PlanDocument from valid JSON payload."""
    normalizer = ResponseNormalizer()
    agent = AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig())
    usage = UsageMetrics(prompt_tokens=10, completion_tokens=20)
    plan = normalizer.normalize_plan(
        agent=agent,
        payload={"summary": "Test plan", "architecture": ["Arch1"]},
        raw_content='{"summary":"Test plan","architecture":["Arch1"]}',
        usage=usage,
    )
    assert plan.summary == "Test plan"
    assert plan.architecture == ["Arch1"]


def test_normalizer_plan_from_empty_payload():
    """Normalizer should fallback to raw_content when payload is empty."""
    normalizer = ResponseNormalizer()
    agent = AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig())
    usage = UsageMetrics(prompt_tokens=10, completion_tokens=20)
    plan = normalizer.normalize_plan(
        agent=agent,
        payload={},
        raw_content="This is a raw plan about architecture and risks.",
        usage=usage,
    )
    assert plan.agent_id == "a"
    assert len(plan.summary) > 0


# ── CLI: Help text for every subcommand ───────────────────────

@pytest.mark.parametrize("subcmd", [
    "serve", "models", "personas", "history", "show", "delete", "check", "debate",
])
def test_cli_subcommand_help(subcmd):
    """Every subcommand --help should exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", subcmd, "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"{subcmd} --help failed: {result.stderr}"


# ── CLI: Invalid depth values ─────────────────────────────────

@pytest.mark.parametrize("depth", ["0", "6", "999", "-1"])
def test_cli_invalid_depth_rejected(depth):
    """Invalid depth values should be rejected by argparse."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "debate",
         "--mock", "--topic", "T", "--depth", depth],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0


# ── API: Error handling ───────────────────────────────────────

def test_api_get_nonexistent_run(client):
    """GET /runs/nonexistent should return 404."""
    r = client.get("/runs/nonexistent-id-xyz")
    assert r.status_code == 404


def test_api_human_judge_merge_plans(client):
    """Human judge can merge plans."""
    r = client.post("/runs", json={
        "project_name": "merge",
        "task": {"title": "Merge", "problem_statement": "test"},
        "context_sources": [{"source_id": "t", "kind": "inline_text", "label": "t", "content": "x"}],
        "agents": [
            {"agent_id": "a", "display_name": "A", "provider": {"type": "mock", "model": "a"}},
            {"agent_id": "b", "display_name": "B", "provider": {"type": "mock", "model": "b"}},
        ],
        "judge": {"mode": "human"},
    })
    run = r.json()
    assert run["status"] == "awaiting_human_judge"

    plan_ids = [p["plan_id"] for p in run["plans"]]
    r2 = client.post(f'/runs/{run["run_id"]}/judge-actions', json={
        "action": "merge_plans",
        "winning_plan_ids": plan_ids,
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "completed"
    assert r2.json()["verdict"]["verdict_type"] == "merged"
