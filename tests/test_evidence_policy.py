from colosseum.core.models import (
    ExperimentRun,
    JudgeConfig,
    JudgeMode,
    PlanDocument,
    RiskItem,
    TaskSpec,
    UsageMetrics,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderRuntimeService


def build_judge(tmp_path):
    budget_manager = BudgetManager()
    provider_runtime = ProviderRuntimeService(
        budget_manager=budget_manager,
        quota_path=tmp_path / "provider_quotas.json",
    )
    return JudgeService(
        budget_manager=budget_manager,
        provider_runtime=provider_runtime,
    )


def test_plan_normalizer_preserves_evidence_basis():
    normalizer = ResponseNormalizer()
    plan = normalizer.normalize_plan(
        agent=type("Agent", (), {"agent_id": "agent-a", "display_name": "Agent A"})(),
        payload={
            "summary": "Evidence-backed plan",
            "evidence_basis": ["Frozen repo snapshot", "Shared architecture note"],
            "assumptions": ["The repo state is current."],
        },
        raw_content="unused",
        usage=UsageMetrics(),
    )
    assert plan.evidence_basis == ["Frozen repo snapshot", "Shared architecture note"]


def test_automated_judge_does_not_early_finalize_when_evidence_is_thin(tmp_path):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Evidence test", problem_statement="Pick the strongest plan."),
        agents=[],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        plans=[
            PlanDocument(
                agent_id="a",
                display_name="Plan A",
                summary="Strong structure but weak evidence.",
                assumptions=["A1", "A2", "A3", "A4"],
                architecture=["X1", "X2", "X3", "X4"],
                implementation_strategy=["S1", "S2", "S3", "S4", "S5"],
                risks=[
                    RiskItem(title="R1", severity="medium", mitigation="M1"),
                    RiskItem(title="R2", severity="medium", mitigation="M2"),
                    RiskItem(title="R3", severity="medium", mitigation="M3"),
                ],
                strengths=["T1", "T2", "T3"],
                weaknesses=["W1", "W2"],
            ),
            PlanDocument(
                agent_id="b",
                display_name="Plan B",
                summary="Weaker plan.",
                assumptions=["A1"],
                architecture=["X1"],
                implementation_strategy=["S1"],
                risks=[],
                strengths=["T1"],
                weaknesses=["W1"],
            ),
        ],
    )

    decision = judge._automated_decide(run)

    assert decision.action.value == "continue_debate"
    assert "Evidence grounding" in decision.reasoning
