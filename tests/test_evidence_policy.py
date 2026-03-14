import asyncio

from colosseum.core.config import build_evidence_policy
from colosseum.core.models import (
    AgentConfig,
    AgentMessage,
    DebateRound,
    ExperimentRun,
    JudgeActionType,
    JudgeDecision,
    JudgeConfig,
    JudgeMode,
    PlanDocument,
    ProviderConfig,
    ProviderType,
    RiskItem,
    RoundSummary,
    RoundType,
    TaskSpec,
    UsageMetrics,
)
from colosseum.providers.base import ProviderResult
from colosseum.services.budget import BudgetManager
from colosseum.services.judge import JudgeService
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderExecution
from colosseum.services.provider_runtime import ProviderRuntimeService


from colosseum.services.context_bundle import ContextBundleService
from colosseum.services.debate import DebateEngine
from colosseum.services.orchestrator import ColosseumOrchestrator
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


def test_agent_display_label_includes_persona_name_or_humanized_id():
    named = AgentConfig(
        agent_id="agent-a",
        display_name="Gemini (2.5 Pro)",
        provider=ProviderConfig(type=ProviderType.GEMINI_CLI, model="gemini-2.5-pro"),
        persona_id="andrej_karpathy",
        persona_name="Andrej Karpathy",
    )
    inferred = AgentConfig(
        agent_id="agent-b",
        display_name="Claude (Sonnet 4.6)",
        provider=ProviderConfig(type=ProviderType.CLAUDE_CLI, model="claude-sonnet-4-6"),
        persona_id="startup_cto",
    )

    assert named.persona_label == "Andrej Karpathy"
    assert named.display_label == "Gemini (2.5 Pro) [Andrej Karpathy]"
    assert inferred.persona_label == "Startup Cto"
    assert inferred.display_label == "Claude (Sonnet 4.6) [Startup Cto]"


def test_plan_normalizer_uses_agent_display_label():
    normalizer = ResponseNormalizer()
    agent = AgentConfig(
        agent_id="agent-a",
        display_name="OpenAI (GPT-5.4)",
        provider=ProviderConfig(type=ProviderType.CODEX_CLI, model="gpt-5.4"),
        persona_id="serena_williams",
        persona_name="Serena Williams",
    )

    plan = normalizer.normalize_plan(
        agent=agent,
        payload={"summary": "Use staged rollout."},
        raw_content="unused",
        usage=UsageMetrics(),
    )

    assert plan.display_name == "OpenAI (GPT-5.4) [Serena Williams]"


def test_round_type_coerce_handles_provider_aliases():
    assert (
        RoundType.coerce("initial_evidence_gathering", fallback=RoundType.REBUTTAL)
        == RoundType.CRITIQUE
    )
    assert (
        RoundType.coerce("round final comparison", fallback=RoundType.CRITIQUE)
        == RoundType.FINAL_COMPARISON
    )


def test_judge_action_type_coerce_handles_provider_aliases():
    assert (
        JudgeActionType.coerce("select_winner", fallback=JudgeActionType.CONTINUE_DEBATE)
        == JudgeActionType.FINALIZE
    )
    assert (
        JudgeActionType.coerce("needs_human", fallback=JudgeActionType.CONTINUE_DEBATE)
        == JudgeActionType.HUMAN_REQUIRED
    )


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


def test_automated_judge_can_finalize_when_evidence_gating_is_disabled(tmp_path):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Evidence toggle", problem_statement="Pick the strongest plan."),
        agents=[],
        judge=JudgeConfig(
            mode=JudgeMode.AUTOMATED,
            minimum_confidence_to_stop=0.6,
            allow_early_finalization=True,
            use_evidence_based_judging=False,
        ),
        plans=[
            PlanDocument(
                agent_id="a",
                display_name="Plan A",
                summary="Strong structure with sparse citations.",
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
    run.budget_policy.min_rounds = 0

    decision = asyncio.run(judge.decide(run))

    assert decision.action == JudgeActionType.FINALIZE
    assert "sufficiently differentiated" in decision.reasoning


def test_plan_evaluation_neutralizes_evidence_score_when_disabled(tmp_path):
    judge = build_judge(tmp_path)
    plans = [
        PlanDocument(
            agent_id="a",
            display_name="Plan A",
            summary="Sparse evidence plan",
            assumptions=["A1", "A2"],
            architecture=["X1", "X2"],
            implementation_strategy=["S1", "S2"],
            risks=[RiskItem(title="R1", severity="medium", mitigation="M1")],
            strengths=["T1"],
            weaknesses=["W1"],
        )
    ]

    evaluations = judge.evaluate_plans(plans, use_evidence_based_judging=False)

    assert evaluations[0].scores["evidence_grounding"] == 0.5
    assert "without evidence-grounding as a gating condition" in evaluations[0].notes[0]


def test_default_judge_policy_blocks_early_finalize_before_max_rounds(tmp_path):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Full debate", problem_statement="Pick a plan."),
        agents=[],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED, minimum_confidence_to_stop=0.6),
        plans=[
            PlanDocument(
                agent_id="a",
                display_name="Plan A",
                summary="Well-evidenced plan.",
                evidence_basis=["E1", "E2", "E3", "E4"],
                assumptions=["A1", "A2", "A3", "A4"],
                architecture=["X1", "X2", "X3", "X4"],
                implementation_strategy=["S1", "S2", "S3", "S4", "S5"],
                risks=[RiskItem(title="R1", severity="medium", mitigation="M1")],
                strengths=["T1", "T2", "T3"],
                weaknesses=["W1"],
            ),
            PlanDocument(
                agent_id="b",
                display_name="Plan B",
                summary="Clearly weaker plan.",
                evidence_basis=["E1"],
                assumptions=["A1"],
                architecture=["X1"],
                implementation_strategy=["S1"],
                risks=[],
                strengths=["T1"],
                weaknesses=["W1"],
            ),
        ],
    )
    run.budget_policy.min_rounds = 0
    run.budget_policy.max_rounds = 3

    decision = asyncio.run(judge.decide(run))

    assert decision.action.value == "continue_debate"
    assert "Early finalization is disabled" in decision.reasoning


def test_repetitive_rounds_still_continue_until_max_rounds(tmp_path):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Repetition test", problem_statement="Do not stop early."),
        agents=[],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        plans=[
            PlanDocument(
                agent_id="a",
                display_name="Plan A",
                summary="Plan A",
                evidence_basis=["E1", "E2", "E3"],
                strengths=["T1", "T2"],
            ),
            PlanDocument(
                agent_id="b",
                display_name="Plan B",
                summary="Plan B",
                evidence_basis=["E1", "E2", "E3"],
                strengths=["T1", "T2"],
            ),
        ],
        debate_rounds=[
            DebateRound(
                index=1,
                round_type=RoundType.CRITIQUE,
                purpose="Stress test",
                summary=RoundSummary(agreements=["Same conclusion", "Same risk"]),
                messages=[
                    AgentMessage(
                        round_index=1,
                        round_type=RoundType.CRITIQUE,
                        agent_id="a",
                        plan_id="plan-a",
                        content="Repeating prior points.",
                        novelty_score=0.0,
                    ),
                    AgentMessage(
                        round_index=1,
                        round_type=RoundType.CRITIQUE,
                        agent_id="b",
                        plan_id="plan-b",
                        content="Repeating prior points.",
                        novelty_score=0.0,
                    ),
                ],
            )
        ],
    )
    run.budget_policy.min_rounds = 1
    run.budget_policy.max_rounds = 3

    decision = asyncio.run(judge.decide(run))

    assert decision.action in {
        JudgeActionType.CONTINUE_DEBATE,
        JudgeActionType.REQUEST_REVISION,
    }
    assert "Early finalization is disabled" in decision.reasoning


def test_ai_judge_finalize_is_deferred_until_last_round(tmp_path, monkeypatch):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="AI judge defer", problem_statement="Do not end early."),
        agents=[],
        judge=JudgeConfig(
            mode=JudgeMode.AI,
            provider=ProviderConfig(type=ProviderType.MOCK, model="mock-judge"),
        ),
        plans=[
            PlanDocument(agent_id="a", display_name="Plan A", summary="Plan A"),
            PlanDocument(agent_id="b", display_name="Plan B", summary="Plan B"),
        ],
    )
    run.budget_policy.max_rounds = 2

    async def fake_ai_decide(_run):
        return JudgeDecision(
            mode=JudgeMode.AI,
            action=JudgeActionType.FINALIZE,
            reasoning="The judge would normally stop here.",
            confidence=0.9,
            disagreement_level=0.2,
            expected_value_of_next_round=0.0,
        )

    monkeypatch.setattr(judge, "_ai_decide", fake_ai_decide)

    decision = asyncio.run(judge.decide(run))

    assert decision.action.value == "continue_debate"
    assert "Early finalization is disabled" in decision.reasoning


def test_ai_judge_invalid_next_round_type_falls_back_to_supported_round(tmp_path, monkeypatch):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="AI judge fallback", problem_statement="Use a safe round type."),
        agents=[],
        judge=JudgeConfig(
            mode=JudgeMode.AI,
            provider=ProviderConfig(type=ProviderType.MOCK, model="mock-judge"),
        ),
        plans=[
            PlanDocument(agent_id="a", display_name="Plan A", summary="Plan A"),
            PlanDocument(agent_id="b", display_name="Plan B", summary="Plan B"),
        ],
    )

    async def fake_execute(**kwargs):
        return ProviderExecution(
            result=ProviderResult(
                content="Judge response",
                json_payload={
                    "action": "continue_debate",
                    "reasoning": "A bounded next round is still useful.",
                    "confidence": 0.73,
                    "disagreement_level": 0.51,
                    "expected_value_of_next_round": 0.24,
                    "next_round_type": "initial_evidence_gathering",
                    "focus_areas": ["grounded disagreement"],
                },
            ),
            effective_provider=kwargs["provider_config"],
        )

    monkeypatch.setattr(judge.provider_runtime, "execute", fake_execute)

    decision = asyncio.run(judge._ai_decide(run))

    assert decision.action == JudgeActionType.CONTINUE_DEBATE
    assert decision.next_round_type == RoundType.CRITIQUE


def test_ai_judge_alias_action_is_normalized_to_supported_enum(tmp_path, monkeypatch):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="AI judge action alias", problem_statement="Use a safe action."),
        agents=[],
        judge=JudgeConfig(
            mode=JudgeMode.AI,
            provider=ProviderConfig(type=ProviderType.MOCK, model="mock-judge"),
        ),
        plans=[
            PlanDocument(
                agent_id="a",
                display_name="Plan A",
                summary="Plan A",
                evidence_basis=["Shared repo snapshot"],
            ),
            PlanDocument(
                agent_id="b",
                display_name="Plan B",
                summary="Plan B",
                evidence_basis=["Shared repo snapshot"],
            ),
        ],
    )

    async def fake_execute(**kwargs):
        return ProviderExecution(
            result=ProviderResult(
                content="alias action",
                json_payload={
                    "action": "select_winner",
                    "confidence": 0.82,
                    "reasoning": "One plan clearly wins.",
                    "disagreement_level": 0.2,
                    "expected_value_of_next_round": 0.0,
                    "next_round_type": "initial_evidence_gathering",
                    "focus_areas": ["winner selection"],
                },
            ),
            effective_provider=run.judge.provider,
        )

    monkeypatch.setattr(judge.provider_runtime, "execute", fake_execute)

    decision = asyncio.run(judge._ai_decide(run))

    assert decision.action == JudgeActionType.FINALIZE
    assert decision.next_round_type == RoundType.CRITIQUE


def test_ai_judge_prompt_uses_debate_record_without_search_metadata(tmp_path, monkeypatch):
    judge = build_judge(tmp_path)
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Judge from debate", problem_statement="Use only the debate record."),
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
        judge=JudgeConfig(
            mode=JudgeMode.AI,
            provider=ProviderConfig(type=ProviderType.MOCK, model="mock-judge"),
        ),
        plans=[
            PlanDocument(
                plan_id="plan-a",
                agent_id="agent-a",
                display_name="Plan A",
                summary="Plan A summary",
                strengths=["Fast rollout"],
                evidence_basis=["Repo scan"],
            ),
            PlanDocument(
                plan_id="plan-b",
                agent_id="agent-b",
                display_name="Plan B",
                summary="Plan B summary",
                weaknesses=["Higher cost"],
            ),
        ],
        debate_rounds=[
            DebateRound(
                index=1,
                round_type=RoundType.CRITIQUE,
                purpose="Compare plans",
                messages=[
                    AgentMessage(
                        round_index=1,
                        round_type=RoundType.CRITIQUE,
                        agent_id="agent-a",
                        plan_id="plan-a",
                        content="Agent A argues the rollout is lower risk.",
                    ),
                    AgentMessage(
                        round_index=1,
                        round_type=RoundType.CRITIQUE,
                        agent_id="agent-b",
                        plan_id="plan-b",
                        content="Agent B argues the rollout is more flexible later.",
                    ),
                ],
                summary=RoundSummary(
                    moderator_note="The agents disagree on immediate risk versus future flexibility.",
                    key_disagreements=["Immediate risk versus future flexibility"],
                ),
            )
        ],
    )

    captured: dict[str, object] = {}

    async def fake_execute(**kwargs):
        captured["instructions"] = kwargs["instructions"]
        captured["metadata"] = kwargs["metadata"]
        return ProviderExecution(
            result=ProviderResult(
                content="Judge response",
                json_payload={
                    "action": "continue_debate",
                    "reasoning": "One more round is useful.",
                    "confidence": 0.7,
                    "disagreement_level": 0.5,
                    "expected_value_of_next_round": 0.2,
                    "next_round_type": "rebuttal",
                    "focus_areas": ["risk trade-offs"],
                },
            ),
            effective_provider=kwargs["provider_config"],
        )

    monkeypatch.setattr(judge.provider_runtime, "execute", fake_execute)

    decision = asyncio.run(judge._ai_decide(run))

    instructions = str(captured["instructions"])
    metadata = dict(captured["metadata"])
    assert decision.next_round_type == RoundType.REBUTTAL
    assert "Do not browse" in instructions
    assert "Plan A summary" in instructions
    assert "Agent A argues the rollout is lower risk." in instructions
    assert "search_policy" not in metadata
    assert "evidence_policy" not in metadata


def test_build_evidence_policy_changes_with_search_toggle():
    on_policy = build_evidence_policy(True)
    off_policy = build_evidence_policy(False)

    assert "Internet search is encouraged" in on_policy
    assert "Do not fill evidence gaps from memory" in off_policy


def test_plan_prompt_reflects_search_preference(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    agent = AgentConfig(
        agent_id="agent-a",
        display_name="Agent A",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Prompt policy", problem_statement="Test search guidance."),
        agents=[agent],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        encourage_internet_search=True,
    )

    enabled_prompt = orchestrator._build_plan_prompt(
        run, agent, "Frozen context", image_summary="", has_image_inputs=False
    )
    assert "Internet search is encouraged" in enabled_prompt

    run.encourage_internet_search = False
    disabled_prompt = orchestrator._build_plan_prompt(
        run, agent, "Frozen context", image_summary="", has_image_inputs=False
    )
    assert "Do not fill evidence gaps from memory" in disabled_prompt


def test_plan_prompt_reinforces_persona_voice(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    agent = AgentConfig(
        agent_id="agent-a",
        display_name="Agent A",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
        persona_content="Use short, severe sentences. Attack weak reasoning immediately.",
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Persona prompt", problem_statement="Test persona voice guidance."),
        agents=[agent],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
    )

    prompt = orchestrator._build_plan_prompt(
        run, agent, "Frozen context", image_summary="", has_image_inputs=False
    )

    assert "VOICE CONTRACT" in prompt
    assert "PERSONA EXPRESSION" in prompt
    assert "sound like the assigned persona" in prompt


def test_debate_prompt_reinforces_persona_voice(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    agent_a = AgentConfig(
        agent_id="agent-a",
        display_name="Agent A",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
        persona_content="Speak like a relentless reviewer with sharp, clipped rebuttals.",
    )
    agent_b = AgentConfig(
        agent_id="agent-b",
        display_name="Agent B",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-b"),
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Persona debate", problem_statement="Debate the better plan."),
        agents=[agent_a, agent_b],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        plans=[
            PlanDocument(agent_id="agent-a", display_name="Plan A", summary="Plan A"),
            PlanDocument(agent_id="agent-b", display_name="Plan B", summary="Plan B"),
        ],
    )

    prompt = orchestrator.debate_engine._build_prompt(
        run,
        agent_a,
        RoundType.CRITIQUE,
        agenda=None,
        instructions=None,
        image_summary="",
        has_image_inputs=False,
    )

    assert "VOICE CONTRACT" in prompt
    assert "PERSONA EXPRESSION" in prompt
    assert "critique points, defense points, and concessions" in prompt


def test_debate_prompt_includes_structured_persona_voice_profile(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    persona = """
    # Relentless Closer

    > High-pressure operator who speaks in scoreboards and accountability.

    ## Your Role
    Drive the room toward measurable execution. Keep standards obvious.

    ## Debating Style
    - Push for concrete scoreboards, milestones, and visible progress.
    - Challenge half-measures before they harden into the default.

    ## Voice Signals
    - Overall tone: clipped, intense, and forward-leaning.
    - Signature move: turn vague optimism into a measurable demand.

    ## Core Principles
    - High standards are a feature, not a tax.
    - Confidence should be earned through preparation.
    """.strip()
    agent_a = AgentConfig(
        agent_id="agent-a",
        display_name="Agent A",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
        persona_content=persona,
    )
    agent_b = AgentConfig(
        agent_id="agent-b",
        display_name="Agent B",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-b"),
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Persona debate", problem_statement="Debate the better plan."),
        agents=[agent_a, agent_b],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        plans=[
            PlanDocument(agent_id="agent-a", display_name="Plan A", summary="Plan A"),
            PlanDocument(agent_id="agent-b", display_name="Plan B", summary="Plan B"),
        ],
    )

    prompt = orchestrator.debate_engine._build_prompt(
        run,
        agent_a,
        RoundType.CRITIQUE,
        agenda=None,
        instructions=None,
        image_summary="",
        has_image_inputs=False,
    )

    assert "PERSONA VOICE PROFILE:" in prompt
    assert "Push for concrete scoreboards, milestones, and visible progress." in prompt
    assert "High standards are a feature, not a tax." in prompt
    assert "generic assistant prose" in prompt


def test_debate_prompt_bans_judge_flattery_and_lies(tmp_path):
    orchestrator = build_orchestrator(tmp_path)
    agent_a = AgentConfig(
        agent_id="agent-a",
        display_name="Agent A",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-a"),
    )
    agent_b = AgentConfig(
        agent_id="agent-b",
        display_name="Agent B",
        provider=ProviderConfig(type=ProviderType.MOCK, model="mock-b"),
    )
    run = ExperimentRun(
        project_name="Colosseum",
        task=TaskSpec(title="Prompt guardrail", problem_statement="Debate honestly."),
        agents=[agent_a, agent_b],
        judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
        plans=[
            PlanDocument(agent_id="agent-a", display_name="Plan A", summary="Plan A"),
            PlanDocument(agent_id="agent-b", display_name="Plan B", summary="Plan B"),
        ],
    )

    prompt = orchestrator.debate_engine._build_prompt(
        run,
        agent_a,
        RoundType.CRITIQUE,
        agenda=None,
        instructions=None,
        image_summary="",
        has_image_inputs=False,
    )

    assert "Do not flatter the judge" in prompt
    assert "Do not lie, invent evidence, fake consensus" in prompt
