import asyncio

from colosseum.core.models import (
    AgentConfig,
    ContextSourceInput,
    ContextSourceKind,
    JudgeConfig,
    JudgeMode,
    ProviderConfig,
    ProviderType,
    RunCreateRequest,
    TaskSpec,
)
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


def build_request(mode: JudgeMode) -> RunCreateRequest:
    return RunCreateRequest(
        project_name="Colosseum",
        task=TaskSpec(
            title="Test task",
            problem_statement="Compare implementation plans.",
        ),
        context_sources=[
            ContextSourceInput(
                source_id="brief",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Brief",
                content="A small planning problem.",
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
        judge=JudgeConfig(mode=mode),
    )


def test_automated_run_completes(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    run = asyncio.run(orchestrator.create_run(build_request(JudgeMode.AUTOMATED)))
    assert run.status.value == "completed"
    assert len(run.plans) == 2
    assert run.verdict is not None


def test_human_run_pauses(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    run = asyncio.run(orchestrator.create_run(build_request(JudgeMode.HUMAN)))
    assert run.status.value == "awaiting_human_judge"
    assert run.human_judge_packet is not None
