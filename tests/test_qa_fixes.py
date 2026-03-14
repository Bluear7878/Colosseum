"""Tests for QA fixes: bug fixes, feature improvements, and CLI changes."""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import zlib

import pytest
from fastapi import HTTPException

from colosseum.api.routes import (
    create_run_stream,
    download_run_markdown,
    download_run_pdf,
    get_run,
)
from colosseum.core.models import (
    AgentConfig,
    BillingTier,
    BudgetLedger,
    ContextSourceInput,
    ContextSourceKind,
    ExperimentRun,
    FinalReport,
    HumanJudgeActionRequest,
    JudgeConfig,
    JudgeVerdict,
    JudgeMode,
    PlanDocument,
    ProviderConfig,
    ProviderQuotaState,
    ProviderType,
    RunCreateRequest,
    TaskSpec,
    UsageMetrics,
    VerdictType,
)
from colosseum.providers.mock import MockProvider
from colosseum.services.budget import BudgetManager
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.judge import JudgeService
from colosseum.services.markdown_report import generate_markdown
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.orchestrator import ColosseumOrchestrator
from colosseum.services import pdf_report as pdf_report_module
from colosseum.services.pdf_report import generate_pdf
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.repository import FileRunRepository
from colosseum.services.report_synthesizer import ReportSynthesizer


def build_orchestrator(tmp_path):
    budget_manager = BudgetManager()
    normalizer = ResponseNormalizer()
    repository = FileRunRepository(root=tmp_path)
    context_service = ContextBundleService()
    provider_runtime = ProviderRuntimeService(
        budget_manager=budget_manager,
        quota_path=tmp_path / "provider_quotas.json",
    )
    judge_service = JudgeService(
        budget_manager=budget_manager,
        provider_runtime=provider_runtime,
    )
    debate_engine = DebateEngine(
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
    )
    return ColosseumOrchestrator(
        repository=repository,
        context_service=context_service,
        debate_engine=debate_engine,
        judge_service=judge_service,
        budget_manager=budget_manager,
        normalizer=normalizer,
        provider_runtime=provider_runtime,
    )


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract flate-compressed page text from a generated PDF."""
    raw_pdf = pdf_bytes.decode("latin1", errors="ignore")
    text_chunks: list[str] = []
    pattern = re.compile(r"(\d+ \d+ obj.*?stream\r?\n)(.*?)(\r?\nendstream)", re.S)
    for match in pattern.finditer(raw_pdf):
        header, stream_data, _ = match.groups()
        if "/FlateDecode" not in header:
            continue
        try:
            decoded = zlib.decompress(stream_data.encode("latin1"))
        except zlib.error:
            continue
        text_chunks.append(decoded.decode("latin1", errors="ignore"))
    return "\n".join(text_chunks)


# ── Bug fix: MockProvider produces varied plans ─────────────────


def test_mock_provider_produces_different_plans_for_different_agents():
    """Same model with different agent_ids (mock vs mock_1) should produce different plans."""
    provider_same = MockProvider(model_name="x")
    result_1 = asyncio.run(
        provider_same.generate("plan", "test", {"agent_id": "mock", "task_title": "Test"})
    )
    result_2 = asyncio.run(
        provider_same.generate("plan", "test", {"agent_id": "mock_1", "task_title": "Test"})
    )
    summary_1 = result_1.json_payload.get("summary", "")
    summary_2 = result_2.json_payload.get("summary", "")
    assert summary_1 != summary_2, (
        "Same model with different agent_ids should produce different plans"
    )


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
    assert len(merged.strengths) == len(set(merged.strengths)), (
        f"Merged strengths have duplicates: {merged.strengths}"
    )


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
        agent_id="a",
        display_name="A",
        summary="Plan A",
        strengths=["Reusable", "Scalable"],
        evidence_basis=["e1", "e2", "e3"],
        assumptions=["a1"],
        architecture=["arch1", "arch2"],
        implementation_strategy=["s1"],
        weaknesses=["w1"],
    )
    plan_b = PlanDocument(
        agent_id="b",
        display_name="B",
        summary="Plan B",
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
    assert len(verdict.selected_strengths) == len(set(verdict.selected_strengths)), (
        f"Verdict strengths have duplicates: {verdict.selected_strengths}"
    )


# ── Bug fix: CLI exit codes ────────────────────────────────────


def test_cli_show_nonexistent_returns_nonzero():
    """'colosseum show nonexistent' should exit with code 1."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "show", "nonexistent_run_xyz"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, "show for nonexistent run should exit non-zero"


# ── Feature: --version flag ──────────────────────────────────


def test_cli_version():
    """'colosseum --version' should print version."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "0.1.0" in result.stdout


# ── Feature: --mock flag ─────────────────────────────────────


def test_cli_mock_flag_runs_debate():
    """'colosseum debate --topic X --mock --depth 1' should complete."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "--topic",
            "Mock flag test",
            "--mock",
            "--depth",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "VERDICT" in result.stdout


# ── Feature: --json flag ─────────────────────────────────────


def test_cli_json_output_is_valid_json():
    """'colosseum debate --topic X --mock --depth 1 --json' should output valid JSON."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "--topic",
            "JSON test",
            "--mock",
            "--depth",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "completed"
    assert "verdict" in data
    assert data["final_report"]["final_answer"].strip()
    assert len(data["plans"]) >= 2


# ── Feature: delete command ──────────────────────────────────


def test_cli_delete_nonexistent():
    """'colosseum delete nonexistent' should fail gracefully."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", "delete", "nonexistent_run_xyz"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0


# ── API: Comprehensive endpoint tests ────────────────────────


def test_api_create_run_with_mock_agents(tmp_path):
    """Create a full run with mock agents via API."""
    orchestrator = build_orchestrator(tmp_path)
    run = asyncio.run(
        orchestrator.create_run(
            RunCreateRequest(
                project_name="QA",
                task=TaskSpec(title="API QA", problem_statement="test"),
                context_sources=[
                    ContextSourceInput(
                        source_id="t",
                        kind=ContextSourceKind.INLINE_TEXT,
                        label="t",
                        content="x",
                    )
                ],
                agents=[
                    AgentConfig(
                        agent_id="a",
                        display_name="A",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
                    ),
                    AgentConfig(
                        agent_id="b",
                        display_name="B",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
                    ),
                ],
                judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
            )
        )
    )
    assert run.status.value == "completed"
    assert len(run.plans) == 2
    assert run.verdict is not None


def test_api_sse_stream_delivers_all_phases(tmp_path):
    """SSE stream should include init, planning, plans_ready, and complete."""
    orchestrator = build_orchestrator(tmp_path)
    response = asyncio.run(
        create_run_stream(
            RunCreateRequest(
                project_name="SSE",
                task=TaskSpec(title="SSE", problem_statement="test"),
                context_sources=[
                    ContextSourceInput(
                        source_id="t",
                        kind=ContextSourceKind.INLINE_TEXT,
                        label="t",
                        content="x",
                    )
                ],
                agents=[
                    AgentConfig(
                        agent_id="a",
                        display_name="A",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
                    ),
                    AgentConfig(
                        agent_id="b",
                        display_name="B",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
                    ),
                ],
                judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
            ),
            orchestrator=orchestrator,
        )
    )

    async def collect_text():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
        return "".join(chunks)

    text = asyncio.run(collect_text())
    events = [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data:")]
    phases = [e.get("phase") for e in events]
    assert "init" in phases
    assert "plans_ready" in phases
    assert "complete" in phases


def test_api_sse_complete_event_has_verdict_aware_final_report(tmp_path):
    """SSE completion payload should synthesize the final report from the real verdict."""
    orchestrator = build_orchestrator(tmp_path)
    response = asyncio.run(
        create_run_stream(
            RunCreateRequest(
                project_name="SSE Verdict Report",
                task=TaskSpec(title="SSE Verdict Report", problem_statement="test"),
                context_sources=[
                    ContextSourceInput(
                        source_id="t",
                        kind=ContextSourceKind.INLINE_TEXT,
                        label="t",
                        content="x",
                    )
                ],
                agents=[
                    AgentConfig(
                        agent_id="a",
                        display_name="A",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
                    ),
                    AgentConfig(
                        agent_id="b",
                        display_name="B",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
                    ),
                ],
                judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
            ),
            orchestrator=orchestrator,
        )
    )

    async def collect_text():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk))
        return "".join(chunks)

    text = asyncio.run(collect_text())
    events = [json.loads(line[6:]) for line in text.split("\n") if line.startswith("data:")]
    complete_event = next(event for event in events if event.get("phase") == "complete")
    final_report = complete_event["final_report"]

    assert complete_event["verdict"], "complete payload should include a verdict"
    assert final_report is not None, "complete payload should include a synthesized final report"
    assert final_report["one_line_verdict"].strip()
    assert final_report["final_answer"].strip()
    assert "ended without a final verdict" not in final_report["one_line_verdict"]
    if complete_event["verdict"].get("verdict_type") == "merged":
        assert "Merged recommendation" in final_report["one_line_verdict"]


def test_api_human_judge_select_winner(tmp_path):
    """Human judge can select a winner."""
    orchestrator = build_orchestrator(tmp_path)
    run = asyncio.run(
        orchestrator.create_run(
            RunCreateRequest(
                project_name="HJ",
                task=TaskSpec(title="HJ", problem_statement="test"),
                context_sources=[
                    ContextSourceInput(
                        source_id="t",
                        kind=ContextSourceKind.INLINE_TEXT,
                        label="t",
                        content="x",
                    )
                ],
                agents=[
                    AgentConfig(
                        agent_id="a",
                        display_name="A",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
                    ),
                    AgentConfig(
                        agent_id="b",
                        display_name="B",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
                    ),
                ],
                judge=JudgeConfig(mode=JudgeMode.HUMAN),
            )
        )
    )
    assert run.status.value == "awaiting_human_judge"

    updated = asyncio.run(
        orchestrator.continue_human_run(
            run.run_id,
            HumanJudgeActionRequest(
                action="select_winner",
                winning_plan_ids=[run.plans[0].plan_id],
            ),
        )
    )
    assert updated.status.value == "completed"
    assert updated.verdict is not None
    assert updated.verdict.verdict_type.value == "winner"


# ── Bug fix: Repeated -g flags accumulate gladiators ─────────


def test_cli_repeated_g_flags_accumulate():
    """'debate -g mock:a -g mock:b' should accumulate into 2 gladiators."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "-g",
            "mock:alpha",
            "-g",
            "mock:beta",
            "--topic",
            "Repeated -g test",
            "--depth",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Repeated -g should work but got exit {result.returncode}: {result.stderr}"
    )
    assert "VERDICT" in result.stdout


def test_cli_mixed_g_flag_styles():
    """'-g a b -g c' should accumulate all 3 gladiators."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "-g",
            "mock:a",
            "mock:b",
            "-g",
            "mock:c",
            "--topic",
            "Mixed -g test",
            "--depth",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Mixed -g styles should work but got exit {result.returncode}: {result.stderr}"
    )


# ── Bug fix: JSON output has no ANSI escape codes ────────────


def test_cli_json_output_no_ansi():
    """--json output must not contain ANSI escape sequences."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "--topic",
            "ANSI test",
            "--mock",
            "--depth",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "\x1b" not in result.stdout, "ANSI escape codes leaked into JSON output"
    json.loads(result.stdout)  # must parse cleanly


def test_cli_json_output_includes_verdict_details(tmp_path):
    """--json output should preserve strengths, risks, and merged-plan details."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "--topic",
            "JSON verdict details",
            "--mock",
            "--depth",
            "1",
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    verdict = data["verdict"]
    assert "selected_strengths" in verdict
    assert "rejected_risks" in verdict
    assert isinstance(verdict["selected_strengths"], list)
    assert isinstance(verdict["rejected_risks"], list)
    assert data["final_report"]["final_answer"].strip()
    if verdict["type"] == "merged":
        assert verdict["synthesized_plan"]["summary"]


def test_report_synthesizer_generates_direct_final_answer():
    """Heuristic report synthesis should directly answer the user's question."""
    budget_manager = BudgetManager()
    provider_runtime = ProviderRuntimeService(budget_manager=budget_manager)
    synthesizer = ReportSynthesizer(provider_runtime=provider_runtime)

    run = ExperimentRun(
        project_name="final-answer",
        task=TaskSpec(
            title="Rollout Choice",
            problem_statement="Should we choose the safer rollout path for this launch?",
        ),
        agents=[AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig())],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
    )
    plan = PlanDocument(
        agent_id="a",
        display_name="A",
        summary="Choose the safer rollout path with phased deployment and rollback guards.",
        strengths=["Lower operational risk", "Clear rollback path"],
        open_questions=["Confirm telemetry thresholds before launch."],
    )
    run.plans = [plan]
    verdict = JudgeVerdict(
        judge_mode=JudgeMode.AUTOMATED,
        verdict_type=VerdictType.WINNER,
        winning_plan_ids=[plan.plan_id],
        rationale="The safer rollout has the better risk profile.",
        selected_strengths=["Lower operational risk", "Clear rollback path"],
        rejected_risks=["Telemetry thresholds still need confirmation"],
        stop_reason="judge_finalize",
        confidence=0.87,
    )

    report = asyncio.run(synthesizer.synthesize(run, verdict=verdict))

    assert "best answer is to follow A's approach" in report.final_answer
    assert "safer rollout path" in report.final_answer
    assert "Telemetry thresholds still need confirmation" in report.final_answer


def test_pdf_report_includes_final_answer_section(monkeypatch):
    """Generated PDFs should foreground the direct answer to the user's question."""
    monkeypatch.setattr(pdf_report_module, "_resolve_unicode_font_paths", lambda: None)
    run = ExperimentRun(
        project_name="pdf-answer",
        task=TaskSpec(title="PDF Answer", problem_statement="What should we do?"),
        agents=[AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig())],
        judge=JudgeConfig(),
        final_report=FinalReport(
            final_answer="You should choose the safer rollout with staged checks.",
            executive_summary="The debate favored staged rollout over the aggressive option.",
        ),
    )

    pdf_text = _extract_pdf_text(generate_pdf(run))

    assert "Answer to the User Question" in pdf_text
    assert "You should choose the safer rollout with staged checks." in pdf_text


def test_pdf_report_supports_unicode_content():
    """Unicode-heavy reports should export without font encoding failures."""
    run = ExperimentRun(
        project_name="unicode-pdf",
        task=TaskSpec(title="한국어 리포트", problem_statement="무엇을 해야 하나요?"),
        agents=[AgentConfig(agent_id="a", display_name="메시", provider=ProviderConfig())],
        judge=JudgeConfig(),
        final_report=FinalReport(
            final_answer="질문에 대한 최종 답변은 단계적으로 배포하는 것입니다.",
            executive_summary="판사는 위험을 낮추는 점진적 배포를 권고했습니다.",
        ),
    )

    pdf_bytes = generate_pdf(run)

    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 1000


def test_markdown_report_includes_direct_answer():
    """Markdown export should foreground the direct answer section."""
    run = ExperimentRun(
        project_name="markdown-answer",
        task=TaskSpec(title="Markdown Answer", problem_statement="What should we do next?"),
        agents=[AgentConfig(agent_id="a", display_name="A", provider=ProviderConfig())],
        judge=JudgeConfig(),
        final_report=FinalReport(
            final_answer="You should proceed with a phased rollout and explicit rollback checks.",
            executive_summary="The debate favored the safer staged rollout.",
            recommendations=["Confirm monitoring thresholds before launch."],
        ),
    )

    markdown = generate_markdown(run)

    assert "## Final Answer" in markdown
    assert "phased rollout" in markdown
    assert "## Executive Summary" in markdown


def test_api_report_download_endpoints_return_pdf_and_markdown(tmp_path):
    """Completed runs should be downloadable as PDF and Markdown artifacts."""
    orchestrator = build_orchestrator(tmp_path)
    run = ExperimentRun(
        project_name="download-artifacts",
        task=TaskSpec(title="다운로드 테스트", problem_statement="어떻게 해야 하나요?"),
        agents=[AgentConfig(agent_id="a", display_name="호날두", provider=ProviderConfig())],
        judge=JudgeConfig(),
        final_report=FinalReport(
            final_answer="질문에 대한 최종 답변은 안전한 단계적 배포입니다.",
            executive_summary="토론은 안전한 배포 전략을 선택했습니다.",
        ),
    )
    orchestrator.repository.save_run(run)

    pdf_response = asyncio.run(download_run_pdf(run.run_id, orchestrator=orchestrator))
    markdown_response = asyncio.run(download_run_markdown(run.run_id, orchestrator=orchestrator))

    assert pdf_response.media_type == "application/pdf"
    assert len(pdf_response.body) > 1000
    assert markdown_response.media_type == "text/markdown; charset=utf-8"
    markdown_text = markdown_response.body.decode("utf-8")
    assert "## Final Answer" in markdown_text
    assert "안전한 단계적 배포" in markdown_text


# ── Internal: MockProvider all operations ─────────────────────


def test_mock_provider_debate_operation():
    """MockProvider debate should return structured critique/defense points."""
    provider = MockProvider(model_name="test")
    result = asyncio.run(
        provider.generate(
            "debate",
            "inst",
            {
                "round_type": "critique",
                "own_plan_id": "p1",
                "own_display_name": "Agent A",
                "other_plan_ids": ["p2"],
                "other_plan_labels": ["Agent B"],
            },
        )
    )
    payload = result.json_payload
    assert "critique_points" in payload
    assert "defense_points" in payload
    assert len(payload["critique_points"]) > 0


def test_mock_provider_judge_operation():
    """MockProvider judge should return action and confidence."""
    provider = MockProvider(model_name="test")
    result = asyncio.run(
        provider.generate(
            "judge",
            "inst",
            {
                "suggested_action": "continue_debate",
            },
        )
    )
    payload = result.json_payload
    assert payload["action"] == "continue_debate"
    assert 0 < payload["confidence"] <= 1.0
    assert "reasoning" in payload


def test_mock_provider_synthesis_operation():
    """MockProvider synthesis should reference basis plan IDs."""
    provider = MockProvider(model_name="test")
    result = asyncio.run(
        provider.generate(
            "synthesis",
            "inst",
            {
                "basis_plan_ids": ["plan_a", "plan_b"],
            },
        )
    )
    payload = result.json_payload
    assert "plan_a" in payload["strengths"][1]
    assert "plan_b" in payload["strengths"][1]


def test_mock_provider_unknown_operation():
    """MockProvider should handle unknown operations gracefully."""
    provider = MockProvider(model_name="test")
    result = asyncio.run(provider.generate("unknown_op", "inst", {}))
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


@pytest.mark.parametrize(
    "subcmd",
    [
        "serve",
        "models",
        "personas",
        "history",
        "show",
        "delete",
        "check",
        "debate",
    ],
)
def test_cli_subcommand_help(subcmd):
    """Every subcommand --help should exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "colosseum.cli", subcmd, "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"{subcmd} --help failed: {result.stderr}"


# ── CLI: Invalid depth values ─────────────────────────────────


@pytest.mark.parametrize("depth", ["0", "6", "999", "-1"])
def test_cli_invalid_depth_rejected(depth):
    """Invalid depth values should be rejected by argparse."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "colosseum.cli",
            "debate",
            "--mock",
            "--topic",
            "T",
            "--depth",
            depth,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0


# ── API: Error handling ───────────────────────────────────────


def test_api_get_nonexistent_run(tmp_path):
    """GET /runs/nonexistent should raise HTTP 404."""
    orchestrator = build_orchestrator(tmp_path)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(get_run("nonexistent-id-xyz", orchestrator=orchestrator))
    assert exc_info.value.status_code == 404


def test_api_human_judge_merge_plans(tmp_path):
    """Human judge can merge plans."""
    orchestrator = build_orchestrator(tmp_path)
    run = asyncio.run(
        orchestrator.create_run(
            RunCreateRequest(
                project_name="merge",
                task=TaskSpec(title="Merge", problem_statement="test"),
                context_sources=[
                    ContextSourceInput(
                        source_id="t",
                        kind=ContextSourceKind.INLINE_TEXT,
                        label="t",
                        content="x",
                    )
                ],
                agents=[
                    AgentConfig(
                        agent_id="a",
                        display_name="A",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
                    ),
                    AgentConfig(
                        agent_id="b",
                        display_name="B",
                        provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
                    ),
                ],
                judge=JudgeConfig(mode=JudgeMode.HUMAN),
            )
        )
    )
    assert run.status.value == "awaiting_human_judge"

    updated = asyncio.run(
        orchestrator.continue_human_run(
            run.run_id,
            HumanJudgeActionRequest(
                action="merge_plans",
                winning_plan_ids=[plan.plan_id for plan in run.plans],
            ),
        )
    )
    assert updated.status.value == "completed"
    assert updated.verdict is not None
    assert updated.verdict.verdict_type.value == "merged"


def test_cli_show_displays_merged_plan_summary(monkeypatch, capsys):
    """show should render the merged plan summary for merged verdicts."""
    from argparse import Namespace

    import colosseum.bootstrap as bootstrap
    from colosseum.cli import cmd_show
    from colosseum.core.models import JudgeVerdict, RunStatus, VerdictType

    plan_a = PlanDocument(agent_id="a", display_name="A", summary="Plan A")
    plan_b = PlanDocument(agent_id="b", display_name="B", summary="Plan B")
    merged_plan = PlanDocument(
        agent_id="merged",
        display_name="Merged",
        summary="Merged plan summary",
    )
    run = ExperimentRun(
        project_name="Show merged",
        task=TaskSpec(title="Merged display", problem_statement="test"),
        agents=[
            AgentConfig(
                agent_id="a",
                display_name="A",
                provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
            ),
            AgentConfig(
                agent_id="b",
                display_name="B",
                provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
            ),
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
    )
    run.status = RunStatus.COMPLETED
    run.plans = [plan_a, plan_b]
    run.verdict = JudgeVerdict(
        judge_mode=JudgeMode.AUTOMATED,
        verdict_type=VerdictType.MERGED,
        winning_plan_ids=[plan_a.plan_id, plan_b.plan_id],
        synthesized_plan=merged_plan,
        rationale="Combined the strongest parts of both plans.",
        selected_strengths=["Strong testing", "Concrete architecture"],
        rejected_risks=["Unclear rollout"],
        stop_reason="judge_finalize",
        confidence=0.82,
    )

    class FakeOrchestrator:
        def load_run(self, run_id: str) -> ExperimentRun:
            assert run_id == run.run_id
            return run

    monkeypatch.setattr(bootstrap, "get_orchestrator", lambda: FakeOrchestrator())
    cmd_show(Namespace(run_id=run.run_id))

    output = capsys.readouterr().out
    assert "Merged Plan:" in output
    assert "Merged plan summary" in output


def test_api_sse_rejects_exhausted_ai_judge(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    orchestrator.provider_runtime.upsert_quota_states(
        [
            ProviderQuotaState(
                quota_key="paid:openai",
                label="OpenAI",
                billing_tier=BillingTier.PAID,
                cycle_token_limit=500,
                remaining_tokens=0,
            )
        ]
    )

    request = RunCreateRequest(
        project_name="SSE Judge",
        task=TaskSpec(title="SSE Judge", problem_statement="test"),
        context_sources=[
            ContextSourceInput(
                source_id="t",
                kind=ContextSourceKind.INLINE_TEXT,
                label="t",
                content="x",
            )
        ],
        agents=[
            AgentConfig(
                agent_id="a",
                display_name="A",
                provider=ProviderConfig(type=ProviderType.MOCK, model="a"),
            ),
            AgentConfig(
                agent_id="b",
                display_name="B",
                provider=ProviderConfig(type=ProviderType.MOCK, model="b"),
            ),
        ],
        judge=JudgeConfig(
            mode=JudgeMode.AI,
            provider=ProviderConfig(
                type=ProviderType.CODEX_CLI,
                model="gpt-5.4",
                billing_tier=BillingTier.PAID,
                quota_key="paid:openai",
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_run_stream(request, orchestrator=orchestrator))

    assert exc.value.status_code == 400
    assert "AI judge" in str(exc.value.detail)
