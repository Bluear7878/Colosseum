import asyncio
from pathlib import Path

from colosseum.core.models import (
    AgentConfig,
    ContextSourceInput,
    ContextSourceKind,
    HumanJudgeActionRequest,
    JudgeConfig,
    JudgeMode,
    ProviderConfig,
    ProviderType,
    RunCreateRequest,
    TaskSpec,
)
from colosseum.main import index, report_page
from colosseum.services.budget import BudgetManager
from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.orchestrator import ColosseumOrchestrator
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.repository import FileRunRepository


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


def test_index_serves_ui_file():
    response = asyncio.run(index())
    assert response.status_code == 200
    assert str(response.path).endswith("index.html")


def test_report_serves_ui_file():
    response = asyncio.run(report_page("demo-run"))
    assert response.status_code == 200
    assert str(response.path).endswith("report.html")


def test_run_list_contains_created_run(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    request = RunCreateRequest(
        project_name="Colosseum",
        task=TaskSpec(
            title="UI smoke",
            problem_statement="Generate plans for UI verification.",
        ),
        context_sources=[
            ContextSourceInput(
                source_id="brief",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Brief",
                content="A tiny test context.",
            )
        ],
        agents=[
            AgentConfig(
                agent_id="agent-a",
                display_name="Agent A",
                provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
            )
        ],
        judge=JudgeConfig(mode=JudgeMode.HUMAN),
    )

    run = asyncio.run(orchestrator.create_run(request))
    runs = orchestrator.list_runs()

    assert len(runs) == 1
    assert runs[0].run_id == run.run_id
    assert runs[0].task_title == "UI smoke"


def test_human_round_records_agenda_and_adjudication(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    request = RunCreateRequest(
        project_name="Colosseum",
        task=TaskSpec(
            title="Judge flow",
            problem_statement="Force one human-judge round for report testing.",
        ),
        context_sources=[
            ContextSourceInput(
                source_id="brief",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Brief",
                content="A tiny test context.",
            )
        ],
        agents=[
            AgentConfig(
                agent_id="agent-a",
                display_name="Agent A",
                provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
            ),
            AgentConfig(
                agent_id="agent-b",
                display_name="Agent B",
                provider=ProviderConfig(type=ProviderType.MOCK, model="mock-b"),
            ),
        ],
        judge=JudgeConfig(mode=JudgeMode.HUMAN),
    )

    run = asyncio.run(orchestrator.create_run(request))
    updated = asyncio.run(
        orchestrator.continue_human_run(
            run.run_id,
            HumanJudgeActionRequest(action="request_round"),
        )
    )

    assert updated.debate_rounds
    round_one = updated.debate_rounds[0]
    assert round_one.agenda is not None
    assert round_one.agenda.question
    assert round_one.adjudication is not None
    assert round_one.adjudication.adopted_arguments


def test_index_contains_search_toggle_and_star_cta():
    response = asyncio.run(index())
    html = Path(response.path).read_text(encoding="utf-8")
    assert 'encourage-search-toggle' in html
    assert 'star-link' in html
