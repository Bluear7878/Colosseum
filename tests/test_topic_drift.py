"""Regression tests for topic-adherence enforcement.

Background: prior to the fix, agendas for round N+1 were derived purely from
round N's leftover critiques, with no check that those critiques were still
about the original task. A meta-complaint such as "Agent X failed to provide
a plan summary" could become the entire agenda for the next round, dragging
the whole debate off-topic. See ``docs/gotchas.md`` for the incident details.
"""

from __future__ import annotations

from colosseum.core.models import (
    AgentConfig,
    AgentMessage,
    BudgetPolicy,
    DebateClaim,
    DebateRound,
    ExperimentRun,
    JudgeConfig,
    PlanDocument,
    ProviderConfig,
    ProviderType,
    RoundSummary,
    RoundType,
    TaskSpec,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.judge import JudgeService
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.topic_guard import (
    anchor_question,
    has_meta_drift_marker,
    is_drifting,
    topic_overlap,
    topic_token_set,
)


def _build_judge(tmp_path) -> JudgeService:
    budget_manager = BudgetManager()
    provider_runtime = ProviderRuntimeService(
        budget_manager=budget_manager,
        quota_path=tmp_path / "provider_quotas.json",
    )
    return JudgeService(
        budget_manager=budget_manager,
        provider_runtime=provider_runtime,
    )


def _build_run(
    *,
    title: str = "Design a vendor-neutral LLM provider abstraction",
    problem: str = (
        "Plan a migration from a single-vendor LLM integration to a "
        "multi-vendor provider layer without breaking existing observability."
    ),
    summaries: list[str] | None = None,
) -> ExperimentRun:
    summaries = summaries or [
        "Introduce a provider interface and a registry; migrate one vendor at a time.",
        "Wrap the existing vendor with an adapter and add capability flags per provider.",
    ]
    run = ExperimentRun(
        project_name="Test",
        task=TaskSpec(title=title, problem_statement=problem),
        agents=[
            AgentConfig(
                agent_id=f"agent-{i}",
                display_name=f"Agent {i}",
                provider=ProviderConfig(type=ProviderType.MOCK, model=f"mock-{i}"),
            )
            for i in range(len(summaries))
        ],
        judge=JudgeConfig(),
        budget_policy=BudgetPolicy(max_rounds=3, min_rounds=1),
    )
    for index, summary in enumerate(summaries):
        run.plans.append(
            PlanDocument(
                agent_id=f"agent-{index}",
                display_name=f"Agent {index}",
                summary=summary,
            )
        )
    return run


# ── Pure helpers ──────────────────────────────────────────────────────────────


def test_topic_overlap_scores_off_topic_low():
    run = _build_run()
    tokens = topic_token_set(run)
    drifting = "Agent X failed to provide any plan summary."
    on_topic = "The provider abstraction needs a registry that tracks vendor capabilities."
    assert topic_overlap(drifting, tokens) < 0.15
    assert topic_overlap(on_topic, tokens) >= 0.30


def test_is_drifting_detects_meta_complaint():
    run = _build_run()
    tokens = topic_token_set(run)
    assert is_drifting("Agent X failed to provide any plan summary.", run, tokens=tokens)
    assert is_drifting(
        "Claude (Opus 4.6) provided no summary so there is zero evidence of a strategy.",
        run,
        tokens=tokens,
    )


def test_is_drifting_korean_meta_marker():
    run = _build_run(
        title="현존 가장 똑똑한 AI 모델은 뭐지?",
        problem="현존하는 LLM 중 가장 똑똑한 모델을 선정하라.",
        summaries=["Claude가 추론 벤치마크에서 우위를 보인다."],
    )
    text = "Andrew Ng이 언급한 '독립 리더보드 1위' 주장은 출처를 제공하지 않았다."
    assert has_meta_drift_marker(text)
    assert is_drifting(text, run)


def test_is_drifting_accepts_on_topic_text():
    run = _build_run()
    on_topic = (
        "The provider registry must expose capability flags per vendor so the "
        "abstraction can be migrated incrementally."
    )
    assert not is_drifting(on_topic, run)


def test_anchor_question_is_idempotent():
    topic = "Vendor-neutral LLM provider abstraction"
    raw = "Take a position on registry shape vs adapter wrapper."
    once = anchor_question(raw, topic)
    twice = anchor_question(once, topic)
    assert topic in once
    assert once == twice  # idempotent — no double stamping


def test_anchor_question_handles_empty_inputs():
    assert anchor_question("", "topic").endswith("'topic'?")
    assert anchor_question("question", "") == "question"


# ── JudgeService integration ──────────────────────────────────────────────────


def test_select_agenda_filters_drifting_unresolved_questions(tmp_path):
    judge = _build_judge(tmp_path)
    run = _build_run()
    # Simulate a finished round whose summary was contaminated by an
    # off-topic critique. The judge must NOT pick this as the next agenda.
    drifting_question = (
        "Take a position on this issue and respond to peer arguments directly: "
        "Agent 0 failed to provide any plan summary."
    )
    on_topic_question = (
        "How should the registry handle per-vendor capability flags during "
        "the staged migration?"
    )
    run.debate_rounds.append(
        DebateRound(
            index=1,
            round_type=RoundType.CRITIQUE,
            purpose="initial",
            summary=RoundSummary(
                key_disagreements=[
                    "Agent 0 failed to provide any plan summary",
                    on_topic_question,
                ],
                unresolved_questions=[
                    drifting_question,
                    on_topic_question,
                ],
            ),
        )
    )

    agenda = judge._select_agenda(run, RoundType.REBUTTAL)

    assert "failed to provide" not in agenda.question.lower()
    assert run.task.title in agenda.question
    assert any(
        word in agenda.question.lower() for word in ("registry", "capability", "migration", "vendor")
    )


def test_select_agenda_falls_back_to_topic_when_all_candidates_drift(tmp_path):
    judge = _build_judge(tmp_path)
    run = _build_run()
    run.debate_rounds.append(
        DebateRound(
            index=1,
            round_type=RoundType.CRITIQUE,
            purpose="initial",
            summary=RoundSummary(
                key_disagreements=["Agent 0 failed to provide any plan summary"],
                unresolved_questions=["Agent 1 provided no plan."],
            ),
        )
    )

    agenda = judge._select_agenda(run, RoundType.REBUTTAL)

    # Both candidates were drift, so the fallback fires. Either way the
    # agenda must explicitly carry the topic title.
    assert run.task.title in agenda.question
    assert "failed to provide" not in agenda.question.lower()
    assert "provided no plan" not in agenda.question.lower()


def test_adjudicate_round_emits_drift_flags(tmp_path):
    judge = _build_judge(tmp_path)
    run = _build_run()

    drift_message = AgentMessage(
        round_index=1,
        round_type=RoundType.CRITIQUE,
        agent_id="agent-0",
        plan_id=run.plans[0].plan_id,
        content="meta-debate",
        critique_points=[
            DebateClaim(
                category="meta",
                text="Agent 1 failed to provide any plan summary.",
                target_plan_ids=[run.plans[1].plan_id],
                evidence=["frozen bundle states no summary provided"],
            ),
            DebateClaim(
                category="meta",
                text="Agent 1 provided no concrete steps.",
                target_plan_ids=[run.plans[1].plan_id],
                evidence=["frozen bundle"],
            ),
        ],
    )
    on_topic_message = AgentMessage(
        round_index=1,
        round_type=RoundType.CRITIQUE,
        agent_id="agent-1",
        plan_id=run.plans[1].plan_id,
        content="on-topic",
        critique_points=[
            DebateClaim(
                category="architecture",
                text=(
                    "The provider registry must expose capability flags so the "
                    "abstraction migrates incrementally."
                ),
                target_plan_ids=[run.plans[0].plan_id],
                evidence=["bundle: registry section"],
            ),
        ],
    )

    debate_round = DebateRound(
        index=1,
        round_type=RoundType.CRITIQUE,
        purpose="initial",
        messages=[drift_message, on_topic_message],
        summary=RoundSummary(
            key_disagreements=["Agent 1 failed to provide any plan summary"],
            unresolved_questions=["Agent 1 failed to provide any plan summary"],
        ),
    )

    adjudication = judge.adjudicate_round(run, debate_round)

    assert any("drift" in flag.lower() or "topic" in flag.lower() for flag in adjudication.drift_flags)
    assert any("Agent 0" in flag for flag in adjudication.drift_flags)
    # The contaminated unresolved point must not survive into the next round.
    assert not any("failed to provide" in point.lower() for point in adjudication.unresolved_points)


def test_adjudicate_round_no_drift_flag_for_clean_debate(tmp_path):
    judge = _build_judge(tmp_path)
    run = _build_run()
    clean_message = AgentMessage(
        round_index=1,
        round_type=RoundType.CRITIQUE,
        agent_id="agent-0",
        plan_id=run.plans[0].plan_id,
        content="on-topic",
        critique_points=[
            DebateClaim(
                category="architecture",
                text=(
                    "The vendor adapter wrapper hides the provider registry, "
                    "making capability flags impossible to migrate incrementally."
                ),
                target_plan_ids=[run.plans[1].plan_id],
                evidence=["bundle: provider section"],
            ),
        ],
    )
    debate_round = DebateRound(
        index=1,
        round_type=RoundType.CRITIQUE,
        purpose="initial",
        messages=[clean_message],
        summary=RoundSummary(),
    )

    adjudication = judge.adjudicate_round(run, debate_round)
    assert adjudication.drift_flags == []
