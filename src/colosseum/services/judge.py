from __future__ import annotations

from statistics import mean
from typing import Any

from colosseum.core.config import (
    LOW_EVIDENCE_SUPPORT_THRESHOLD,
    MIN_EVIDENCE_SUPPORT_TO_FINALIZE,
    ROUND_SEQUENCE,
)
from colosseum.core.models import (
    AdoptedArgument,
    DebateRound,
    DebateAgenda,
    ExperimentRun,
    HumanJudgePacket,
    JudgeActionType,
    JudgeDecision,
    JudgeMode,
    JudgeVerdict,
    PlanDocument,
    PlanEvaluation,
    PlanSummaryCard,
    RiskItem,
    RoundAdjudication,
    RoundType,
    VerdictType,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.prompt_contracts import JUDGE_RECORD_ONLY_GUARDRAIL
from colosseum.services.topic_guard import (
    anchor_question,
    is_drifting,
    topic_token_set,
)


class JudgeService:
    def __init__(
        self,
        budget_manager: BudgetManager,
        provider_runtime: ProviderRuntimeService,
    ) -> None:
        self.budget_manager = budget_manager
        self.provider_runtime = provider_runtime

    def evaluate_plans(
        self,
        plans: list[PlanDocument],
        use_evidence_based_judging: bool = True,
    ) -> list[PlanEvaluation]:
        if not plans:
            return []
        evaluations: list[PlanEvaluation] = []
        for plan in plans:
            scores = {
                "assumption_clarity": min(1.0, len(plan.assumptions) / 4),
                "evidence_grounding": (
                    min(1.0, len(plan.evidence_basis) / 4) if use_evidence_based_judging else 0.5
                ),
                "architecture_specificity": min(1.0, len(plan.architecture) / 4),
                "implementation_feasibility": min(1.0, len(plan.implementation_strategy) / 5),
                "risk_coverage": min(1.0, len(plan.risks) / 3),
                "strength_signal": min(1.0, len(plan.strengths) / 3),
                "weakness_honesty": min(1.0, len(plan.weaknesses) / 2),
            }
            overall = round(sum(scores.values()) / len(scores), 3)
            evaluations.append(
                PlanEvaluation(
                    plan_id=plan.plan_id,
                    scores=scores,
                    notes=[
                        (
                            f"{plan.display_name} plan cites {len(plan.evidence_basis)} explicit evidence item(s)."
                            if use_evidence_based_judging
                            else f"{plan.display_name} plan was scored without evidence-grounding as a gating condition."
                        ),
                        f"{plan.display_name} plan covers {len(plan.risks)} explicit risk items.",
                        f"{plan.display_name} plan lists {len(plan.implementation_strategy)} implementation steps.",
                    ],
                    overall_score=overall,
                )
            )
        return sorted(evaluations, key=lambda item: item.overall_score, reverse=True)

    async def decide(self, run: ExperimentRun) -> JudgeDecision:
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            decision = await self._ai_decide(run)
        else:
            decision = self._automated_decide(run)
        return self._enforce_full_debate(run, decision)

    async def finalize(
        self, run: ExperimentRun, decision: JudgeDecision | None = None
    ) -> JudgeVerdict:
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            verdict = await self._ai_finalize(run, decision)
            if verdict:
                return verdict
        return self._automated_finalize(run, decision)

    def build_human_packet(self, run: ExperimentRun) -> HumanJudgePacket:
        evaluations = run.plan_evaluations or self.evaluate_plans(
            run.plans,
            use_evidence_based_judging=run.judge.use_evidence_based_judging,
        )
        score_by_plan = {item.plan_id: item.overall_score for item in evaluations}
        suggested_agenda = self._select_agenda(run, self._next_round_type(run))
        cards = [
            PlanSummaryCard(
                plan_id=plan.plan_id,
                display_name=plan.display_name,
                summary=plan.summary,
                evidence_basis=plan.evidence_basis[:3],
                strengths=plan.strengths[:3],
                weaknesses=plan.weaknesses[:3],
                overall_score=score_by_plan.get(plan.plan_id, 0.0),
            )
            for plan in run.plans
        ]
        last_round = run.debate_rounds[-1].summary if run.debate_rounds else None
        return HumanJudgePacket(
            plan_cards=cards,
            last_round_summary=last_round,
            key_disagreements=last_round.key_disagreements
            if last_round
            else self._initial_disagreements(run),
            strongest_arguments=last_round.strongest_arguments
            if last_round
            else self._initial_strengths(run),
            recommended_action=self._recommended_human_action(run),
            available_actions=[
                "request_round",
                "select_winner",
                "merge_plans",
                "request_revision",
            ],
            suggested_agenda=suggested_agenda,
        )

    def build_human_round_decision(
        self,
        run: ExperimentRun,
        round_type: RoundType,
        instructions: str | None = None,
    ) -> JudgeDecision:
        agenda = self._select_agenda(run, round_type, instructions=instructions)
        return JudgeDecision(
            mode=JudgeMode.HUMAN,
            action=JudgeActionType.REQUEST_REVISION
            if round_type == RoundType.TARGETED_REVISION
            else JudgeActionType.CONTINUE_DEBATE,
            reasoning="Human judge requested another bounded round on a specific issue.",
            confidence=1.0,
            disagreement_level=self._disagreement_level(run),
            expected_value_of_next_round=0.25,
            next_round_type=round_type,
            focus_areas=agenda.focus_areas,
            budget_pressure=self.budget_manager.budget_pressure(
                run.budget_policy, run.budget_ledger
            ),
            agenda=agenda,
        )

    def adjudicate_round(
        self,
        run: ExperimentRun,
        debate_round: DebateRound,
    ) -> RoundAdjudication:
        agenda = debate_round.agenda or self._select_agenda(run, debate_round.round_type)
        candidates = self._rank_argument_candidates(run, debate_round)
        adopted: list[AdoptedArgument] = []
        adopted_agents: set[str] = set()
        for candidate in candidates:
            if len(adopted) >= 3:
                break
            if candidate.agent_id in adopted_agents and len(candidates) > 3:
                continue
            adopted.append(candidate)
            adopted_agents.add(candidate.agent_id)

        # Hallucination detection: flag agents whose claims lack evidence backing
        hallucination_flags: list[str] = []
        agent_names = {a.agent_id: a.display_name for a in run.agents}
        for msg in debate_round.messages:
            agent_name = agent_names.get(msg.agent_id, msg.agent_id)
            all_claims = list(msg.critique_points) + list(msg.defense_points)
            if not all_claims:
                continue
            unsupported = [c for c in all_claims if not c.evidence]
            total = len(all_claims)
            unsupported_ratio = len(unsupported) / total if total > 0 else 0
            if unsupported_ratio >= 0.6 and total >= 2:
                hallucination_flags.append(
                    f"{agent_name}: {len(unsupported)} of {total} claim(s) carry no cited evidence — "
                    "assertions may be inference or fabrication rather than grounded in the frozen context."
                )
            elif unsupported_ratio == 1.0 and total >= 1:
                hallucination_flags.append(
                    f"{agent_name}: no evidence cited for any claim in this round — "
                    "all arguments should be treated as unverified until grounded in the frozen context."
                )

        # Drift detection: flag messages whose arguments wander away from the
        # original task topic, and filter out drifting items so they cannot
        # become the agenda for the next round.
        drift_flags = self._collect_drift_flags(run, debate_round)
        unresolved = self._filter_drifting_items(
            run, debate_round.summary.unresolved_questions
        )[:3]
        if adopted:
            adopted_labels = ", ".join(
                f"{item.display_name} ({item.claim_kind})" for item in adopted[:2]
            )
            resolution = (
                f"The judge resolved the round by adopting {adopted_labels} on the issue "
                f"'{agenda.title.lower()}'."
            )
            judge_note = (
                "Move to the next issue because the adopted arguments were more evidence-backed "
                "or more concrete than the alternatives."
                if run.judge.use_evidence_based_judging
                else "Move to the next issue because the adopted arguments were more concrete or decision-useful than the alternatives."
            )
            moved_to_next_issue = True
        else:
            resolution = (
                "No argument clearly cleared the evidence bar for this issue, so the judge should "
                "keep the scope narrow if another round is requested."
                if run.judge.use_evidence_based_judging
                else "No argument clearly separated itself on this issue, so the judge should keep the scope narrow if another round is requested."
            )
            judge_note = (
                "The round surfaced disagreement, but not enough objective support to endorse a single stance."
                if run.judge.use_evidence_based_judging
                else "The round surfaced disagreement, but not enough separation to endorse a single stance."
            )
            moved_to_next_issue = False

        return RoundAdjudication(
            agenda_title=agenda.title,
            agenda_question=agenda.question,
            adopted_arguments=adopted,
            resolution=resolution,
            unresolved_points=unresolved,
            judge_note=judge_note,
            moved_to_next_issue=moved_to_next_issue,
            hallucination_flags=hallucination_flags,
            drift_flags=drift_flags,
        )

    def _collect_drift_flags(
        self,
        run: ExperimentRun,
        debate_round: DebateRound,
    ) -> list[str]:
        """Detect arguments that wander away from the original task topic."""
        tokens = topic_token_set(run)
        if not tokens:
            return []
        agent_names = {a.agent_id: a.display_name for a in run.agents}
        flags: list[str] = []
        for msg in debate_round.messages:
            claims = [claim.text for claim in msg.critique_points] + [
                claim.text for claim in msg.defense_points
            ]
            if not claims:
                continue
            drifting = [
                text
                for text in claims
                if text and is_drifting(text, run, tokens=tokens)
            ]
            if not drifting:
                continue
            ratio = len(drifting) / len(claims)
            if ratio >= 0.5:
                agent_name = agent_names.get(msg.agent_id, msg.agent_id)
                example = drifting[0].strip()
                if len(example) > 140:
                    example = example[:137].rstrip() + "..."
                flags.append(
                    f"{agent_name}: {len(drifting)} of {len(claims)} claim(s) drifted "
                    f"from the topic '{run.task.title}'. Example: \"{example}\""
                )
        return flags

    def _filter_drifting_items(
        self,
        run: ExperimentRun,
        items: list[str],
    ) -> list[str]:
        """Drop list entries that look off-topic for the current run."""
        tokens = topic_token_set(run)
        if not tokens:
            return list(items)
        return [item for item in items if item and not is_drifting(item, run, tokens=tokens)]

    def _automated_decide(self, run: ExperimentRun) -> JudgeDecision:
        evaluations = run.plan_evaluations or self.evaluate_plans(
            run.plans,
            use_evidence_based_judging=run.judge.use_evidence_based_judging,
        )
        if not run.plan_evaluations:
            run.plan_evaluations = evaluations

        disagreement_level = self._disagreement_level(run)
        budget_pressure = self.budget_manager.budget_pressure(run.budget_policy, run.budget_ledger)
        next_round_type = self._next_round_type(run)
        agenda = self._select_agenda(run, next_round_type)
        confidence = self._decision_confidence(run, evaluations, disagreement_level)
        evidence_support = self._evidence_support(run)
        remaining_rounds = run.budget_policy.max_rounds - len(run.debate_rounds)

        if (
            len(run.debate_rounds) == 0
            and run.budget_policy.min_rounds <= 0
            and confidence >= run.judge.minimum_confidence_to_stop
            and (
                not run.judge.use_evidence_based_judging
                or evidence_support >= MIN_EVIDENCE_SUPPORT_TO_FINALIZE
            )
        ):
            return JudgeDecision(
                mode=JudgeMode.AUTOMATED,
                action=JudgeActionType.FINALIZE,
                reasoning="Plans are already sufficiently differentiated and another debate round is unlikely to materially improve the result.",
                confidence=confidence,
                disagreement_level=disagreement_level,
                expected_value_of_next_round=0.12,
                budget_pressure=budget_pressure,
            )

        if (
            run.judge.use_evidence_based_judging
            and remaining_rounds > 0
            and evidence_support < LOW_EVIDENCE_SUPPORT_THRESHOLD
            and budget_pressure < 0.9
        ):
            return JudgeDecision(
                mode=JudgeMode.AUTOMATED,
                action=JudgeActionType.CONTINUE_DEBATE,
                reasoning="Evidence grounding is still too weak. Another bounded round should force more source-backed claims and clearer uncertainty handling.",
                confidence=min(confidence, 0.72),
                disagreement_level=max(disagreement_level, 0.45),
                expected_value_of_next_round=0.38,
                next_round_type=next_round_type,
                focus_areas=agenda.focus_areas
                or ["objective evidence", "explicit uncertainty", "source-backed trade-offs"],
                budget_pressure=budget_pressure,
                agenda=agenda,
            )

        if remaining_rounds <= 0:
            return JudgeDecision(
                mode=JudgeMode.AUTOMATED,
                action=JudgeActionType.FINALIZE,
                reasoning="Maximum debate rounds reached.",
                confidence=max(confidence, 0.65),
                disagreement_level=disagreement_level,
                expected_value_of_next_round=0.0,
                budget_pressure=budget_pressure,
            )

        if budget_pressure >= 0.9:
            return JudgeDecision(
                mode=JudgeMode.AUTOMATED,
                action=JudgeActionType.FINALIZE,
                reasoning="Budget pressure is too high to justify another round.",
                confidence=max(confidence, 0.7),
                disagreement_level=disagreement_level,
                expected_value_of_next_round=0.0,
                budget_pressure=budget_pressure,
            )

        if run.debate_rounds:
            latest_round = run.debate_rounds[-1]
            average_novelty = (
                mean(message.novelty_score for message in latest_round.messages)
                if latest_round.messages
                else 0.0
            )
            convergence = self._convergence_score(latest_round)
            if len(run.debate_rounds) >= run.budget_policy.min_rounds and (
                average_novelty < run.budget_policy.min_novelty_threshold
                or convergence >= run.budget_policy.convergence_threshold
            ):
                return JudgeDecision(
                    mode=JudgeMode.AUTOMATED,
                    action=JudgeActionType.FINALIZE,
                    reasoning="Arguments have converged or become repetitive enough that another round is unlikely to add value.",
                    confidence=max(confidence, 0.72),
                    disagreement_level=disagreement_level,
                    expected_value_of_next_round=0.08,
                    budget_pressure=budget_pressure,
                )

        action = JudgeActionType.CONTINUE_DEBATE
        if next_round_type == RoundType.TARGETED_REVISION:
            action = JudgeActionType.REQUEST_REVISION

        return JudgeDecision(
            mode=JudgeMode.AUTOMATED,
            action=action,
            reasoning="One more bounded debate round should help resolve the remaining disagreements.",
            confidence=min(confidence, 0.76),
            disagreement_level=disagreement_level,
            expected_value_of_next_round=0.32,
            next_round_type=next_round_type,
            focus_areas=agenda.focus_areas or self._focus_areas(run),
            budget_pressure=budget_pressure,
            agenda=agenda,
        )

    async def _ai_decide(self, run: ExperimentRun) -> JudgeDecision:
        assert run.judge.provider is not None  # caller guarantees this
        suggested_round = self._next_round_type(run)
        suggested_agenda = self._select_agenda(run, suggested_round)
        allowed_round_types = ", ".join(RoundType.supported_values())
        judge_record = self._build_ai_judge_record(run)
        judge_instructions = (
            f"You are judging a structured evidence-first debate on: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}. "
            f"The debate has run {len(run.debate_rounds)} round(s) so far. "
            f"{JUDGE_RECORD_ONLY_GUARDRAIL} "
            f"\n\nSubmitted record:\n{judge_record}\n\n"
            "Evaluate: (1) disagreement level between plans on this specific task, "
            "(2) novelty of recent arguments — are agents adding new task-relevant support or repeating themselves, "
            "(3) evidence quality inside the submitted record — are claims supported by cited material or labeled as inference, "
            "(4) budget pressure. "
            "Decide: continue_debate if agents are still producing relevant new support on this task; "
            "finalize if arguments are drifting off-topic, repeating without meaningful new support, or budget is high. "
            "TOPIC ANCHOR: Your agenda question MUST explicitly reference the original task above and ask "
            "agents to advance that task. Do NOT pick an agenda that re-litigates a previous round's "
            "meta-complaints (e.g. 'agent X failed to provide a plan', 'evidence is missing'). "
            "If the previous round's unresolved questions are themselves off-topic, override them and "
            "set an agenda that drags the debate back to the original task. "
            "Your focus_areas must also be directly relevant to the debate topic above. "
            "Submission-quality check: for each agent, assess whether specific facts, numbers, named tools, "
            "or technical details in their arguments are actually supported somewhere in the submitted record. "
            "Flag any agent that states precise claims (e.g., specific percentages, library names, "
            "architectural specifics) without support in the submitted record. "
            "Lower that agent's credibility and note the concern in your reasoning. "
            f"If you return next_round_type, it must be exactly one of: {allowed_round_types}."
        )
        if not run.judge.use_evidence_based_judging:
            judge_instructions += (
                " Evidence quality is still useful context, but it is NOT a gating condition for this run. "
                "Do not continue or finalize solely because explicit evidence is sparse. "
                "Weigh coherence, feasibility, responsiveness, and the overall substance of the debate as first-class factors."
            )
        if (
            not run.judge.allow_early_finalization
            and len(run.debate_rounds) < run.budget_policy.max_rounds
        ):
            judge_instructions += (
                " Early finalization is disabled for this run. Unless the configured maximum "
                "number of debate rounds has already been reached, you must continue_debate "
                "or request_revision rather than finalize."
            )
        if run.response_language and run.response_language != "auto":
            judge_instructions += (
                f" MANDATORY: Write ALL content — reasoning, focus_areas, agenda fields — in {run.response_language}. "
                "No other language is permitted under any circumstances."
            )
        execution = await self.provider_runtime.execute(
            run=run,
            actor_id="judge:decision",
            actor_label="AI Judge",
            provider_config=run.judge.provider,
            operation="judge",
            instructions=judge_instructions,
            metadata={
                "suggested_action": "continue_debate",
                "next_round_type": suggested_round.value if suggested_round else "rebuttal",
                "run_id": run.run_id,
                "task_title": run.task.title,
                "plan_count": len(run.plans),
                "round_count": len(run.debate_rounds),
                "evidence_support": self._evidence_support(run),
                "use_evidence_based_judging": run.judge.use_evidence_based_judging,
                "suggested_agenda": suggested_agenda.model_dump(mode="json"),
                "judge_custom_instructions": run.judge.custom_instructions or "",
            },
        )
        result = execution.result
        payload = result.json_payload
        payload_agenda = payload.get("agenda") if isinstance(payload.get("agenda"), dict) else None
        agenda = DebateAgenda.model_validate(payload_agenda) if payload_agenda else suggested_agenda
        # Topic guard: if the AI judge proposed an agenda that itself drifts
        # off the original task, fall back to the deterministic on-topic
        # suggestion. Either way, anchor the question text to the topic so
        # agents always see the task title in the agenda block.
        topic = run.task.title or ""
        tokens = topic_token_set(run)
        if tokens and is_drifting(agenda.question, run, tokens=tokens):
            agenda = suggested_agenda
        agenda.question = anchor_question(agenda.question, topic)
        return JudgeDecision(
            mode=JudgeMode.AI,
            action=JudgeActionType.coerce(
                payload.get("action"),
                fallback=JudgeActionType.CONTINUE_DEBATE,
            ),
            reasoning=str(payload.get("reasoning", result.content)),
            confidence=float(payload.get("confidence", 0.7)),
            disagreement_level=float(
                payload.get("disagreement_level", self._disagreement_level(run))
            ),
            expected_value_of_next_round=float(payload.get("expected_value_of_next_round", 0.2)),
            next_round_type=RoundType.coerce(
                payload.get("next_round_type"),
                fallback=suggested_round,
            )
            if payload.get("next_round_type")
            else None,
            focus_areas=[str(item) for item in payload.get("focus_areas", [])]
            or agenda.focus_areas,
            budget_pressure=self.budget_manager.budget_pressure(
                run.budget_policy, run.budget_ledger
            ),
            agenda=agenda,
        )

    def _enforce_full_debate(self, run: ExperimentRun, decision: JudgeDecision) -> JudgeDecision:
        """Prevent non-user runs from finalizing before the configured round budget is used."""
        if (
            run.judge.allow_early_finalization
            or run.judge.mode == JudgeMode.HUMAN
            or decision.action != JudgeActionType.FINALIZE
        ):
            return decision

        remaining_rounds = run.budget_policy.max_rounds - len(run.debate_rounds)
        if remaining_rounds <= 0:
            return decision

        next_round_type = decision.next_round_type or self._next_round_type(run)
        agenda = decision.agenda or self._select_agenda(run, next_round_type)
        action = (
            JudgeActionType.REQUEST_REVISION
            if next_round_type == RoundType.TARGETED_REVISION
            else JudgeActionType.CONTINUE_DEBATE
        )
        return JudgeDecision(
            mode=decision.mode,
            action=action,
            reasoning=(
                "Early finalization is disabled for this run. Continue debating until the "
                f"configured round budget is exhausted. Original finalize rationale: {decision.reasoning}"
            ),
            confidence=min(decision.confidence, 0.76),
            disagreement_level=max(decision.disagreement_level, self._disagreement_level(run)),
            expected_value_of_next_round=max(decision.expected_value_of_next_round, 0.2),
            next_round_type=next_round_type,
            focus_areas=decision.focus_areas or agenda.focus_areas or self._focus_areas(run),
            budget_pressure=decision.budget_pressure,
            agenda=agenda,
        )

    def _automated_finalize(
        self,
        run: ExperimentRun,
        decision: JudgeDecision | None,
    ) -> JudgeVerdict:
        if not run.plans:
            raise ValueError("Cannot finalize a run without any plans.")
        evaluations = run.plan_evaluations or self.evaluate_plans(
            run.plans,
            use_evidence_based_judging=run.judge.use_evidence_based_judging,
        )
        sorted_plans = sorted(
            run.plans,
            key=lambda plan: next(
                (item.overall_score for item in evaluations if item.plan_id == plan.plan_id),
                0.0,
            ),
            reverse=True,
        )
        top_plan = sorted_plans[0]
        second_plan = sorted_plans[1] if len(sorted_plans) > 1 else None
        top_score = next(
            item.overall_score for item in evaluations if item.plan_id == top_plan.plan_id
        )
        second_score = (
            next(item.overall_score for item in evaluations if item.plan_id == second_plan.plan_id)
            if second_plan
            else 0.0
        )
        margin = round(top_score - (second_score if second_plan else 0.0), 3)
        if margin < 0.05 and second_plan and run.judge.prefer_merged_plan_on_close_scores:
            # Close scores with merge preference → merged verdict
            rationale = (
                f"Scores are too close to declare a clear winner (gap: {margin:.3f}). "
                f"The best elements of both plans have been merged."
            )
            merged_plan = self.merge_plans(top_plan, second_plan)
            return JudgeVerdict(
                judge_mode=run.judge.mode,
                verdict_type=VerdictType.MERGED,
                winning_plan_ids=[top_plan.plan_id, second_plan.plan_id],
                synthesized_plan=merged_plan,
                rationale=rationale,
                selected_strengths=merged_plan.strengths[:6],
                rejected_risks=[risk.title for risk in merged_plan.risks[:3]],
                stop_reason=decision.reasoning if decision else "judge_finalize",
                confidence=max(0.70, top_score),
            )
        rationale = (
            f"{top_plan.display_name} produced the strongest evidence-backed plan for this task."
            if run.judge.use_evidence_based_judging
            else f"{top_plan.display_name} produced the strongest overall plan for this task."
        )
        return JudgeVerdict(
            judge_mode=run.judge.mode,
            verdict_type=VerdictType.WINNER,
            winning_plan_ids=[top_plan.plan_id],
            rationale=rationale,
            selected_strengths=top_plan.strengths[:4],
            rejected_risks=[risk.title for risk in top_plan.risks[:3]],
            stop_reason=decision.reasoning if decision else "judge_finalize",
            confidence=max(0.74, top_score),
        )

    async def _ai_finalize(
        self,
        run: ExperimentRun,
        decision: JudgeDecision | None,
    ) -> JudgeVerdict | None:
        plan_summaries = "\n".join(
            f"- [{p.plan_id[:8]}] {p.display_name}: {p.summary[:200]}" for p in run.plans
        )
        lang = (
            run.response_language
            if run.response_language and run.response_language != "auto"
            else ""
        )
        lang_prefix = (
            f"MANDATORY LANGUAGE: Write ALL content in {lang}. Every field must be in {lang}.\n\n"
            if lang
            else ""
        )
        judge_record = self._build_ai_judge_record(run)
        instructions = (
            f"{lang_prefix}"
            f"You are the judge for a debate on: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}. "
            f"Success criteria: {run.task.success_criteria}. "
            f"{JUDGE_RECORD_ONLY_GUARDRAIL} "
            f"\n\nParticipating plans:\n{plan_summaries}\n\nSubmitted record:\n{judge_record}\n\n"
            + (
                "Select EXACTLY ONE winning plan — the one with the strongest evidence-backed arguments "
                "for this specific task. "
                if run.judge.use_evidence_based_judging
                else "Select EXACTLY ONE winning plan — the one with the strongest overall case "
                "for this specific task. "
            )
            + "There must always be a single winner. "
            "Return JSON with: winning_plan_id (str, the plan_id of the winner), "
            "rationale (str, 2-3 sentences on why this plan wins), "
            "selected_strengths (list[str], top 3-4 strengths of the winner), "
            "rejected_risks (list[str], risks that were mitigated or rejected)."
            + (f"\n\nREMINDER: Write in {lang}." if lang else "")
        )
        if run.judge.provider is None:
            return None
        execution = await self.provider_runtime.execute(
            run=run,
            actor_id="judge:finalize",
            actor_label="AI Judge",
            provider_config=run.judge.provider,
            operation="judge",
            instructions=instructions,
            metadata={
                "run_id": run.run_id,
                "task_title": run.task.title,
                "response_language": run.response_language,
                "judge_custom_instructions": run.judge.custom_instructions or "",
            },
        )
        result = execution.result
        payload = result.json_payload
        if not payload:
            return None
        winning_id = str(payload.get("winning_plan_id", ""))
        if not winning_id:
            # Fall back to first plan if AI didn't return a valid id
            winning_id = run.plans[0].plan_id if run.plans else ""
        # Validate the id exists in plans
        valid_ids = {p.plan_id for p in run.plans}
        # Try prefix match if exact match fails
        if winning_id not in valid_ids:
            matched = next((p.plan_id for p in run.plans if p.plan_id.startswith(winning_id)), None)
            winning_id = matched or (run.plans[0].plan_id if run.plans else winning_id)
        winner = next(
            (p for p in run.plans if p.plan_id == winning_id), run.plans[0] if run.plans else None
        )
        return JudgeVerdict(
            judge_mode=JudgeMode.AI,
            verdict_type=VerdictType.WINNER,
            winning_plan_ids=[winning_id],
            rationale=str(
                payload.get(
                    "rationale", decision.reasoning if decision else "AI judge selected the winner."
                )
            ),
            selected_strengths=[
                str(s)
                for s in payload.get("selected_strengths", winner.strengths[:3] if winner else [])
            ],
            rejected_risks=[str(r) for r in payload.get("rejected_risks", [])],
            stop_reason=decision.reasoning if decision else "ai_judge_finalize",
            confidence=decision.confidence if decision else 0.75,
        )

    def _payload_to_plan(self, payload: dict[str, Any], run: ExperimentRun) -> PlanDocument:
        def _strlist(key: str) -> list[str]:
            val = payload.get(key, [])
            return [str(item) for item in val] if isinstance(val, list) else []

        risks_raw = payload.get("risks", [])
        risks: list[RiskItem] = [
            RiskItem(
                title=str(risk.get("title", "Unspecified risk")),
                severity=risk.get("severity", "medium"),
                mitigation=str(risk.get("mitigation", "Clarify mitigation.")),
            )
            for risk in risks_raw
            if isinstance(risk, dict)
        ]
        return PlanDocument(
            agent_id="judge:synthesis",
            display_name="Judge synthesis",
            summary=str(payload.get("summary", "Synthesized final plan")),
            evidence_basis=_strlist("evidence_basis"),
            assumptions=_strlist("assumptions"),
            architecture=_strlist("architecture"),
            implementation_strategy=_strlist("implementation_strategy"),
            risks=risks,
            strengths=_strlist("strengths"),
            weaknesses=_strlist("weaknesses"),
            trade_offs=_strlist("trade_offs"),
            open_questions=_strlist("open_questions"),
            raw_response=str(payload),
        )

    def _build_merged_plan(self, top_plan: PlanDocument, second_plan: PlanDocument) -> PlanDocument:
        return PlanDocument(
            agent_id="judge:merged",
            display_name="Merged finalist plan",
            summary=f"{top_plan.summary} Combined with selected strengths from {second_plan.display_name}.",
            evidence_basis=list(
                dict.fromkeys(top_plan.evidence_basis[:3] + second_plan.evidence_basis[:3])
            ),
            assumptions=list(dict.fromkeys(top_plan.assumptions[:3] + second_plan.assumptions[:3])),
            architecture=list(
                dict.fromkeys(top_plan.architecture[:3] + second_plan.architecture[:3])
            ),
            implementation_strategy=list(
                dict.fromkeys(
                    top_plan.implementation_strategy[:3] + second_plan.implementation_strategy[:3]
                )
            ),
            risks=list(
                {risk.title: risk for risk in (top_plan.risks + second_plan.risks)}.values()
            ),
            strengths=list(dict.fromkeys(top_plan.strengths[:3] + second_plan.strengths[:3])),
            weaknesses=list(dict.fromkeys(top_plan.weaknesses[:2] + second_plan.weaknesses[:2])),
            trade_offs=list(dict.fromkeys(top_plan.trade_offs[:2] + second_plan.trade_offs[:2])),
            open_questions=list(
                dict.fromkeys(top_plan.open_questions[:2] + second_plan.open_questions[:2])
            ),
        )

    def merge_plans(self, top_plan: PlanDocument, second_plan: PlanDocument) -> PlanDocument:
        """Public merger used by both automated and human-judge verdict paths."""
        return self._build_merged_plan(top_plan, second_plan)

    def _disagreement_level(self, run: ExperimentRun) -> float:
        if not run.debate_rounds:
            if len(run.plan_evaluations) < 2:
                return 0.4
            score_gap = abs(
                run.plan_evaluations[0].overall_score - run.plan_evaluations[1].overall_score
            )
            return round(max(0.2, 1.0 - score_gap), 2)
        summary = run.debate_rounds[-1].summary
        return round(min(1.0, len(summary.key_disagreements) / max(1, len(run.plans) + 1)), 2)

    def _convergence_score(self, debate_round: DebateRound) -> float:
        agreements = len(debate_round.summary.agreements)
        disagreements = len(debate_round.summary.key_disagreements)
        if agreements + disagreements == 0:
            return 0.5
        return agreements / (agreements + disagreements)

    def _decision_confidence(
        self,
        run: ExperimentRun,
        evaluations: list[PlanEvaluation],
        disagreement_level: float,
    ) -> float:
        top_score = evaluations[0].overall_score if evaluations else 0.5
        novelty_penalty = 0.0
        if run.debate_rounds:
            latest_novelty = mean(
                message.novelty_score for message in run.debate_rounds[-1].messages
            )
            novelty_penalty = max(0.0, 0.15 - latest_novelty)
        return round(
            min(0.95, max(0.5, top_score - (disagreement_level * 0.15) - novelty_penalty)), 2
        )

    def _next_round_type(self, run: ExperimentRun) -> RoundType:
        current_rounds = len(run.debate_rounds)
        if current_rounds >= len(ROUND_SEQUENCE):
            return RoundType.TARGETED_REVISION
        return RoundType.coerce(
            ROUND_SEQUENCE[current_rounds], fallback=RoundType.TARGETED_REVISION
        )

    def _focus_areas(self, run: ExperimentRun) -> list[str]:
        if (
            run.judge.use_evidence_based_judging
            and self._evidence_support(run) < MIN_EVIDENCE_SUPPORT_TO_FINALIZE
        ):
            return ["objective evidence", "source-backed assumptions", "explicit uncertainty"]
        if not run.debate_rounds:
            return ["feasibility", "maintainability", "cost", "risk"]
        latest = run.debate_rounds[-1].summary
        # Filter drift here so JudgeDecision.focus_areas — which propagates
        # into the next prompt and the report — never contains a leftover
        # off-topic critique. See docs/gotchas.md §1.
        on_topic = self._filter_drifting_items(run, list(latest.key_disagreements[:4]))
        return on_topic or ["implementation complexity", "traceability"]

    def _build_ai_judge_record(self, run: ExperimentRun) -> str:
        """Render the debate artifacts that the AI judge is allowed to use."""
        plan_lines = ["Opening plans:"]
        for plan in run.plans:
            plan_lines.append(
                f"- [{plan.plan_id[:8]}] {plan.display_name}: {self._truncate_text(plan.summary, 220)}"
            )
            if plan.strengths:
                plan_lines.append(
                    f"  strengths: {self._truncate_text('; '.join(plan.strengths[:3]), 180)}"
                )
            if plan.weaknesses:
                plan_lines.append(
                    f"  weaknesses: {self._truncate_text('; '.join(plan.weaknesses[:2]), 160)}"
                )
            if plan.evidence_basis:
                plan_lines.append(
                    "  cited support from the debater: "
                    f"{self._truncate_text('; '.join(plan.evidence_basis[:2]), 180)}"
                )

        round_lines = ["Debate record:"]
        if not run.debate_rounds:
            round_lines.append("- No debate rounds yet. Judge from the opening plans only.")
        else:
            agent_names = {agent.agent_id: agent.display_name for agent in run.agents}
            for debate_round in run.debate_rounds[-2:]:
                round_lines.append(
                    f"- Round {debate_round.index} ({debate_round.round_type.value})"
                )
                if debate_round.agenda:
                    round_lines.append(
                        f"  agenda: {self._truncate_text(debate_round.agenda.question, 180)}"
                    )
                if debate_round.summary.moderator_note:
                    round_lines.append(
                        "  moderator summary: "
                        f"{self._truncate_text(debate_round.summary.moderator_note, 220)}"
                    )
                if debate_round.summary.key_disagreements:
                    round_lines.append(
                        "  key disagreements: "
                        f"{self._truncate_text('; '.join(debate_round.summary.key_disagreements[:3]), 220)}"
                    )
                if debate_round.summary.strongest_arguments:
                    round_lines.append(
                        "  strongest arguments noted: "
                        f"{self._truncate_text('; '.join(debate_round.summary.strongest_arguments[:3]), 220)}"
                    )
                for message in debate_round.messages:
                    display_name = agent_names.get(message.agent_id, message.agent_id)
                    round_lines.append(
                        f"  {display_name}: {self._truncate_text(message.content, 180)}"
                    )
                    if message.critique_points:
                        round_lines.append(
                            "    critiques: "
                            f"{self._truncate_text('; '.join(point.text for point in message.critique_points[:2]), 180)}"
                        )
                    if message.defense_points:
                        round_lines.append(
                            "    defenses: "
                            f"{self._truncate_text('; '.join(point.text for point in message.defense_points[:2]), 180)}"
                        )
                    if message.concessions:
                        round_lines.append(
                            "    concessions: "
                            f"{self._truncate_text('; '.join(message.concessions[:2]), 160)}"
                        )

        return "\n".join(plan_lines + [""] + round_lines)

    def _truncate_text(self, text: str, limit: int) -> str:
        cleaned = " ".join(str(text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: max(0, limit - 3)].rstrip() + "..."

    def _initial_disagreements(self, run: ExperimentRun) -> list[str]:
        return [
            "How much abstraction is justified in the MVP.",
            "Whether merged plans are better than winner-take-all selection.",
            "How aggressive budget controls should be before debate quality suffers.",
        ]

    def _initial_strengths(self, run: ExperimentRun) -> list[str]:
        return [strength for plan in run.plans for strength in plan.strengths[:1]]

    def _recommended_human_action(self, run: ExperimentRun) -> str:
        if (
            run.judge.use_evidence_based_judging
            and self._evidence_support(run) < LOW_EVIDENCE_SUPPORT_THRESHOLD
        ):
            return "Evidence is still thin. Request another bounded round focused on source-backed claims before picking a winner."
        if not run.debate_rounds:
            return "Review plan cards and either pick a winner or request a critique round."
        latest = run.debate_rounds[-1]
        if self._convergence_score(latest) >= run.budget_policy.convergence_threshold:
            return "Arguments are converging. Select a winner or request a merged plan."
        return "Debate still contains unresolved issues. Request another bounded round or finalize with a merged plan."

    def _evidence_support(self, run: ExperimentRun) -> float:
        plan_supports = [min(1.0, len(plan.evidence_basis) / 3) for plan in run.plans]
        plan_support = mean(plan_supports) if plan_supports else 0.0
        if not run.debate_rounds:
            return round(plan_support, 2)

        latest = run.debate_rounds[-1]
        claims = [
            claim
            for message in latest.messages
            for claim in (message.critique_points + message.defense_points)
        ]
        if not claims:
            return round(plan_support, 2)
        supported_claims = sum(1 for claim in claims if claim.evidence)
        round_support = supported_claims / len(claims)
        return round((plan_support + round_support) / 2, 2)

    def _select_agenda(
        self,
        run: ExperimentRun,
        round_type: RoundType,
        instructions: str | None = None,
    ) -> DebateAgenda:
        focus_areas = self._focus_areas(run)
        topic = run.task.title or ""
        tokens = topic_token_set(run)
        if instructions:
            return DebateAgenda(
                title=self._agenda_title(instructions),
                question=anchor_question(instructions.strip(), topic),
                why_it_matters="The judge explicitly requested this issue for the next bounded round.",
                focus_areas=focus_areas[:3] or [round_type.value],
                source_plan_ids=[plan.plan_id for plan in run.plans[:2]],
            )

        used_questions = {
            debate_round.agenda.question.strip().lower()
            for debate_round in run.debate_rounds
            if debate_round.agenda and debate_round.agenda.question
        }
        for candidate in self._agenda_candidates(run, round_type):
            if candidate.question.strip().lower() in used_questions:
                continue
            # Skip candidates that are themselves off-topic. These come from
            # round-N-1 critiques and would otherwise drag round N+1 further
            # away from the original task.
            if tokens and is_drifting(candidate.question, run, tokens=tokens):
                continue
            candidate.question = anchor_question(candidate.question, topic)
            return candidate

        # Topic-anchored fallback so we never hand the agents an agenda that
        # has no link to the original task.
        if focus_areas:
            on_topic_focus = [
                area for area in focus_areas if not is_drifting(area, run, tokens=tokens)
            ]
        else:
            on_topic_focus = []
        focus_phrase = ", ".join(on_topic_focus[:2]) if on_topic_focus else (topic or "the original task")
        fallback_question = anchor_question(
            f"Which side has the strongest evidence for the next decision on {focus_phrase}?",
            topic,
        )
        return DebateAgenda(
            title=self._agenda_title(fallback_question),
            question=fallback_question,
            why_it_matters="The judge needs one crisp on-topic issue to compare the plans side by side.",
            focus_areas=(on_topic_focus or focus_areas)[:3] or [round_type.value],
            source_plan_ids=[plan.plan_id for plan in run.plans[:2]],
        )

    def _agenda_candidates(
        self,
        run: ExperimentRun,
        round_type: RoundType,
    ) -> list[DebateAgenda]:
        candidates: list[DebateAgenda] = []
        focus_areas = self._focus_areas(run)

        if (
            run.judge.use_evidence_based_judging
            and self._evidence_support(run) < LOW_EVIDENCE_SUPPORT_THRESHOLD
        ):
            candidates.append(
                DebateAgenda(
                    title="Evidence Grounding",
                    question="Which claims in the competing plans are directly supported by the frozen evidence, and which remain inference?",
                    why_it_matters="The debate should not progress while unsupported claims still drive the comparison.",
                    focus_areas=[
                        "objective evidence",
                        "explicit uncertainty",
                        "source-backed trade-offs",
                    ],
                    source_plan_ids=[plan.plan_id for plan in run.plans],
                )
            )

        if run.debate_rounds:
            latest = run.debate_rounds[-1].summary
            tokens = topic_token_set(run)
            for item in latest.key_disagreements[:3] + latest.unresolved_questions[:2]:
                text = item.strip()
                if not text:
                    continue
                # Skip leftover items that are themselves drift — otherwise
                # round N+1 inherits the same off-topic agenda as round N.
                if tokens and is_drifting(text, run, tokens=tokens):
                    continue
                candidates.append(
                    DebateAgenda(
                        title=self._agenda_title(text),
                        question=f"Take a position on this issue and respond to peer arguments directly: {text}",
                        why_it_matters="This disagreement remained open after the previous round.",
                        focus_areas=[text][:1] + focus_areas[:2],
                        source_plan_ids=self._related_plan_ids(run, text),
                    )
                )
        else:
            for plan in run.plans:
                for risk in plan.risks[:1]:
                    text = risk.title.strip()
                    if not text:
                        continue
                    candidates.append(
                        DebateAgenda(
                            title=self._agenda_title(text),
                            question=f"How should the team address the risk '{text}' without breaking feasibility or maintainability?",
                            why_it_matters="The opening plans disagree on what the riskiest implementation boundary is.",
                            focus_areas=[text][:1] + focus_areas[:2],
                            source_plan_ids=self._related_plan_ids(run, text),
                        )
                    )
                for weak in plan.weaknesses[:1] + plan.open_questions[:1]:
                    text = weak.strip()
                    if not text:
                        continue
                    candidates.append(
                        DebateAgenda(
                            title=self._agenda_title(text),
                            question=f"Which side has the stronger answer to this issue: {text}",
                            why_it_matters="This is a plan-level weakness or open question that could change the final ranking.",
                            focus_areas=[text][:1] + focus_areas[:2],
                            source_plan_ids=self._related_plan_ids(run, text),
                        )
                    )

        if not candidates:
            candidates.append(
                DebateAgenda(
                    title="Final Comparison"
                    if round_type == RoundType.FINAL_COMPARISON
                    else "Implementation Fit",
                    question="Which plan fits the existing codebase or task context best, and what objective evidence supports that answer?",
                    why_it_matters="The judge still needs one concrete comparison axis before finalizing.",
                    focus_areas=focus_areas[:3],
                    source_plan_ids=[plan.plan_id for plan in run.plans],
                )
            )
        return candidates

    def _agenda_title(self, text: str) -> str:
        words = [word.strip(" ,.:;!?") for word in text.split() if word.strip(" ,.:;!?")]
        compact = " ".join(words[:6]).strip()
        return compact.title() or "Focused Issue"

    def _related_plan_ids(self, run: ExperimentRun, text: str) -> list[str]:
        lowered = text.lower()
        related: list[str] = []
        for plan in run.plans:
            haystack = " ".join(
                plan.weaknesses[:2]
                + [risk.title for risk in plan.risks[:2]]
                + plan.open_questions[:2]
                + plan.trade_offs[:2]
            ).lower()
            if lowered and lowered in haystack:
                related.append(plan.plan_id)
        return related or [plan.plan_id for plan in run.plans[:2]]

    def _rank_argument_candidates(
        self,
        run: ExperimentRun,
        debate_round: DebateRound,
    ) -> list[AdoptedArgument]:
        candidates: list[tuple[float, AdoptedArgument]] = []
        agent_names = {agent.agent_id: agent.display_name for agent in run.agents}
        for message in debate_round.messages:
            display_name = agent_names.get(message.agent_id, message.agent_id)
            for claim in message.critique_points:
                evidence_bonus = (
                    0.15 if run.judge.use_evidence_based_judging and claim.evidence else 0.0
                )
                score = 0.55 + evidence_bonus + (message.novelty_score * 0.2)
                candidates.append(
                    (
                        score,
                        AdoptedArgument(
                            agent_id=message.agent_id,
                            display_name=display_name,
                            claim_kind="critique",
                            summary=claim.text,
                            target_plan_ids=claim.target_plan_ids,
                            evidence=claim.evidence,
                            adoption_reason="This critique identified a consequential weakness and anchored it to evidence or round novelty.",
                            source_message_id=message.message_id,
                        ),
                    )
                )
            for claim in message.defense_points:
                evidence_bonus = (
                    0.18 if run.judge.use_evidence_based_judging and claim.evidence else 0.0
                )
                score = 0.58 + evidence_bonus + (message.novelty_score * 0.18)
                candidates.append(
                    (
                        score,
                        AdoptedArgument(
                            agent_id=message.agent_id,
                            display_name=display_name,
                            claim_kind="defense",
                            summary=claim.text,
                            target_plan_ids=claim.target_plan_ids,
                            evidence=claim.evidence,
                            adoption_reason="This defense gave the judge a concrete reason to keep or merge part of the proposal.",
                            source_message_id=message.message_id,
                        ),
                    )
                )
            for concession in message.concessions[:2]:
                score = 0.42 + (message.novelty_score * 0.14)
                candidates.append(
                    (
                        score,
                        AdoptedArgument(
                            agent_id=message.agent_id,
                            display_name=display_name,
                            claim_kind="concession",
                            summary=concession,
                            adoption_reason="A direct concession reduced noise and helped the judge narrow the dispute.",
                            source_message_id=message.message_id,
                        ),
                    )
                )
            for hybrid in message.hybrid_suggestions[:2]:
                score = 0.5 + (message.novelty_score * 0.16)
                candidates.append(
                    (
                        score,
                        AdoptedArgument(
                            agent_id=message.agent_id,
                            display_name=display_name,
                            claim_kind="hybrid",
                            summary=hybrid,
                            adoption_reason="This hybrid suggestion combined useful elements without reopening settled arguments.",
                            source_message_id=message.message_id,
                        ),
                    )
                )

        ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
        return [item for _, item in ranked]
