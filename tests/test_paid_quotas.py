import asyncio
from datetime import timedelta

import pytest

from colosseum.core.models import (
    AgentConfig,
    BillingTier,
    ContextSourceInput,
    ContextSourceKind,
    ExperimentRun,
    JudgeConfig,
    JudgeMode,
    PaidExhaustionAction,
    PaidProviderPolicy,
    ProviderConfig,
    ProviderQuotaState,
    ProviderType,
    RunCreateRequest,
    TaskSpec,
    utc_now,
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
    repository = FileRunRepository(root=tmp_path / "runs")
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


def test_exhausted_paid_agent_is_rejected_before_run(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    orchestrator.provider_runtime.upsert_quota_states(
        [
            ProviderQuotaState(
                quota_key="paid:claude",
                label="Claude",
                cycle_token_limit=2000,
                remaining_tokens=0,
            )
        ]
    )
    request = RunCreateRequest(
        task=TaskSpec(title="Quota gate", problem_statement="Should fail before execution."),
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
                agent_id="claude-agent",
                display_name="Claude Agent",
                provider=ProviderConfig(
                    type=ProviderType.CLAUDE_CLI,
                    model="claude-sonnet-4-6",
                ),
            )
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
    )

    with pytest.raises(ValueError):
        asyncio.run(orchestrator.create_run(request))


def test_paid_quota_switches_to_free_fallback(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    orchestrator.provider_runtime.upsert_quota_states(
        [
            ProviderQuotaState(
                quota_key="paid:mock",
                label="Mock Paid",
                cycle_token_limit=200,
                remaining_tokens=0,
            )
        ]
    )
    paid_provider = ProviderConfig(
        type=ProviderType.MOCK,
        model="mock-paid",
        billing_tier=BillingTier.PAID,
        quota_key="paid:mock",
    )
    fallback_provider = ProviderConfig(
        type=ProviderType.MOCK,
        model="mock-free",
        billing_tier=BillingTier.FREE,
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Fallback", problem_statement="Switch after paid quota exhaustion."),
        agents=[
            AgentConfig(
                agent_id="agent-a",
                display_name="Agent A",
                provider=paid_provider,
            )
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        paid_provider_policy=PaidProviderPolicy(
            on_exhaustion=PaidExhaustionAction.SWITCH_TO_FREE,
            fallback_provider=fallback_provider,
        ),
    )

    execution = asyncio.run(
        orchestrator.provider_runtime.execute(
            run=run,
            actor_id="agent-a",
            actor_label="Agent A",
            provider_config=paid_provider,
            operation="debate",
            instructions="Compare the plans and make one concrete point.",
            metadata={},
        )
    )

    assert execution.effective_provider.model == "mock-free"
    assert any(event.event_type.value == "quota_switched" for event in run.runtime_events)


def test_wait_for_reset_resumes_original_provider(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    orchestrator.provider_runtime.upsert_quota_states(
        [
            ProviderQuotaState(
                quota_key="paid:mock-wait",
                label="Mock Wait",
                cycle_token_limit=300,
                remaining_tokens=0,
                reset_at=utc_now() + timedelta(milliseconds=20),
            )
        ]
    )
    paid_provider = ProviderConfig(
        type=ProviderType.MOCK,
        model="mock-wait",
        billing_tier=BillingTier.PAID,
        quota_key="paid:mock-wait",
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Wait", problem_statement="Pause until reset."),
        agents=[
            AgentConfig(
                agent_id="agent-a",
                display_name="Agent A",
                provider=paid_provider,
            )
        ],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        paid_provider_policy=PaidProviderPolicy(
            on_exhaustion=PaidExhaustionAction.WAIT_FOR_RESET,
            wait_for_reset_max_seconds=1,
        ),
    )

    execution = asyncio.run(
        orchestrator.provider_runtime.execute(
            run=run,
            actor_id="agent-a",
            actor_label="Agent A",
            provider_config=paid_provider,
            operation="plan",
            instructions="Produce a short independent plan.",
            metadata={},
        )
    )

    assert execution.effective_provider.model == "mock-wait"
    event_types = [event.event_type.value for event in run.runtime_events]
    assert "waiting_for_reset" in event_types
    assert "quota_reset" in event_types
