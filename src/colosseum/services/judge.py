from __future__ import annotations

from statistics import mean

from colosseum.core.config import (
    build_evidence_policy,
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
    RoundAdjudication,
    RoundType,
    VerdictType,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.provider_runtime import ProviderRuntimeService


class JudgeService:
    def __init__(
        self,
        budget_manager: BudgetManager,
        provider_runtime: ProviderRuntimeService,
    ) -> None:
        self.budget_manager = budget_manager
        self.provider_runtime = provider_runtime

    def evaluate_plans(self, plans: list[PlanDocument]) -> list[PlanEvaluation]:
        evaluations: list[PlanEvaluation] = []
        for plan in plans:
            scores = {
                "assumption_clarity": min(1.0, len(plan.assumptions) / 4),
                "evidence_grounding": min(1.0, len(plan.evidence_basis) / 4),
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
                        f"{plan.display_name} plan cites {len(plan.evidence_basis)} explicit evidence item(s).",
                        f"{plan.display_name} plan covers {len(plan.risks)} explicit risk items.",
                        f"{plan.display_name} plan lists {len(plan.implementation_strategy)} implementation steps.",
                    ],
                    overall_score=overall,
                )
            )
        return sorted(evaluations, key=lambda item: item.overall_score, reverse=True)

    async def decide(self, run: ExperimentRun) -> JudgeDecision:
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            return await self._ai_decide(run)
        return self._automated_decide(run)

    async def finalize(self, run: ExperimentRun, decision: JudgeDecision | None = None) -> JudgeVerdict:
        if run.judge.mode == JudgeMode.AI and run.judge.provider:
            verdict = await self._ai_finalize(run, decision)
            if verdict:
                return verdict
        return self._automated_finalize(run, decision)

    def build_human_packet(self, run: ExperimentRun) -> HumanJudgePacket:
        evaluations = run.plan_evaluations or self.evaluate_plans(run.plans)
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
            key_disagreements=last_round.key_disagreements if last_round else self._initial_disagreements(run),
            strongest_arguments=last_round.strongest_arguments if last_round else self._initial_strengths(run),
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
            action=JudgeActionType.REQUEST_REVISION if round_type == RoundType.TARGETED_REVISION else JudgeActionType.CONTINUE_DEBATE,
            reasoning="Human judge requested another bounded round on a specific issue.",
            confidence=1.0,
            disagreement_level=self._disagreement_level(run),
            expected_value_of_next_round=0.25,
            next_round_type=round_type,
            focus_areas=agenda.focus_areas,
            budget_pressure=self.budget_manager.budget_pressure(run.budget_policy, run.budget_ledger),
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

        unresolved = debate_round.summary.unresolved_questions[:3]
        if adopted:
            adopted_labels = ", ".join(
                f"{item.display_name} ({item.claim_kind})"
                for item in adopted[:2]
            )
            resolution = (
                f"The judge resolved the round by adopting {adopted_labels} on the issue "
                f"'{agenda.title.lower()}'."
            )
            judge_note = (
                "Move to the next issue because the adopted arguments were more evidence-backed "
                "or more concrete than the alternatives."
            )
            moved_to_next_issue = True
        else:
            resolution = (
                "No argument clearly cleared the evidence bar for this issue, so the judge should "
                "keep the scope narrow if another round is requested."
            )
            judge_note = (
                "The round surfaced disagreement, but not enough objective support to endorse a single stance."
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
        )

    def _automated_decide(self, run: ExperimentRun) -> JudgeDecision:
        evaluations = run.plan_evaluations or self.evaluate_plans(run.plans)
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
            and evidence_support >= MIN_EVIDENCE_SUPPORT_TO_FINALIZE
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
            remaining_rounds > 0
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
                focus_areas=agenda.focus_areas or ["objective evidence", "explicit uncertainty", "source-backed trade-offs"],
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
            average_novelty = mean(message.novelty_score for message in latest_round.messages) if latest_round.messages else 0.0
            convergence = self._convergence_score(latest_round)
            if (
                len(run.debate_rounds) >= run.budget_policy.min_rounds
                and (average_novelty < run.budget_policy.min_novelty_threshold or convergence >= run.budget_policy.convergence_threshold)
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
        suggested_round = self._next_round_type(run)
        suggested_agenda = self._select_agenda(run, suggested_round)
        image_inputs = self._image_inputs(run)
        judge_instructions = (
            f"You are judging a structured evidence-first debate on: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}. "
            f"The debate has run {len(run.debate_rounds)} round(s) so far. "
            "Evaluate: (1) disagreement level between plans on this specific task, "
            "(2) novelty of recent arguments — are agents adding new task-relevant evidence or repeating themselves, "
            "(3) evidence quality — are claims grounded in the frozen context or labeled as inference, "
            "(4) budget pressure. "
            "Decide: continue_debate if agents are still producing relevant new evidence grounded in this task; "
            "finalize if arguments are drifting off-topic, repeating without new evidence, or budget is high. "
            "Your agenda and focus areas must be directly relevant to the debate topic above."
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
                "plan_count": len(run.plans),
                "round_count": len(run.debate_rounds),
                "image_inputs": image_inputs,
                "image_summary": self._image_summary(image_inputs),
                "evidence_policy": build_evidence_policy(run.encourage_internet_search),
                "encourage_internet_search": run.encourage_internet_search,
                "search_policy": build_evidence_policy(run.encourage_internet_search),
                "evidence_support": self._evidence_support(run),
                "suggested_agenda": suggested_agenda.model_dump(mode="json"),
            },
        )
        result = execution.result
        payload = result.json_payload
        payload_agenda = payload.get("agenda") if isinstance(payload.get("agenda"), dict) else None
        agenda = (
            DebateAgenda.model_validate(payload_agenda)
            if payload_agenda
            else suggested_agenda
        )
        return JudgeDecision(
            mode=JudgeMode.AI,
            action=JudgeActionType(payload.get("action", "continue_debate")),
            reasoning=str(payload.get("reasoning", result.content)),
            confidence=float(payload.get("confidence", 0.7)),
            disagreement_level=float(payload.get("disagreement_level", self._disagreement_level(run))),
            expected_value_of_next_round=float(payload.get("expected_value_of_next_round", 0.2)),
            next_round_type=RoundType(payload["next_round_type"]) if payload.get("next_round_type") else None,
            focus_areas=[str(item) for item in payload.get("focus_areas", [])] or agenda.focus_areas,
            budget_pressure=self.budget_manager.budget_pressure(run.budget_policy, run.budget_ledger),
            agenda=agenda,
        )

    def _automated_finalize(
        self,
        run: ExperimentRun,
        decision: JudgeDecision | None,
    ) -> JudgeVerdict:
        evaluations = run.plan_evaluations or self.evaluate_plans(run.plans)
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
        top_score = next(item.overall_score for item in evaluations if item.plan_id == top_plan.plan_id)
        second_score = (
            next(item.overall_score for item in evaluations if item.plan_id == second_plan.plan_id)
            if second_plan
            else 0.0
        )
        close_scores = second_plan is not None and abs(top_score - second_score) < 0.1

        if close_scores and run.judge.prefer_merged_plan_on_close_scores:
            synthesized_plan = self._build_merged_plan(top_plan, second_plan)
            return JudgeVerdict(
                judge_mode=run.judge.mode,
                verdict_type=VerdictType.MERGED,
                winning_plan_ids=[top_plan.plan_id, second_plan.plan_id],
                synthesized_plan=synthesized_plan,
                rationale="Top plans are close in quality, so a merged plan captures complementary strengths.",
                selected_strengths=list(dict.fromkeys(top_plan.strengths[:2] + second_plan.strengths[:2])),
                rejected_risks=[risk.title for risk in synthesized_plan.risks],
                stop_reason=decision.reasoning if decision else "judge_finalize",
                confidence=max(0.74, top_score),
            )

        return JudgeVerdict(
            judge_mode=run.judge.mode,
            verdict_type=VerdictType.WINNER,
            winning_plan_ids=[top_plan.plan_id],
            rationale=f"{top_plan.display_name} produced the strongest plan under the current evaluation rubric.",
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
        image_inputs = self._image_inputs(run)
        synthesis_instructions = (
            f"You are producing the final verdict for a debate on: '{run.task.title}'. "
            f"Problem: {run.task.problem_statement}. "
            f"Success criteria: {run.task.success_criteria}. "
            "Synthesize the strongest evidence-backed ideas from all agents into a final plan "
            "strictly focused on this task. "
            "Select only what directly addresses the problem statement and success criteria above. "
            "Do not include generic content unrelated to this specific task."
        )
        if run.response_language and run.response_language != "auto":
            synthesis_instructions += (
                f" MANDATORY: Write ALL content — every field, every sentence — in {run.response_language}. "
                "No other language is permitted under any circumstances."
            )
        execution = await self.provider_runtime.execute(
            run=run,
            actor_id="judge:synthesis",
            actor_label="AI Judge",
            provider_config=run.judge.provider,
            operation="synthesis",
            instructions=synthesis_instructions,
            metadata={
                "run_id": run.run_id,
                "basis_plan_ids": [plan.plan_id for plan in run.plans[:2]],
                "image_inputs": image_inputs,
                "image_summary": self._image_summary(image_inputs),
                "evidence_policy": build_evidence_policy(run.encourage_internet_search),
                "encourage_internet_search": run.encourage_internet_search,
                "search_policy": build_evidence_policy(run.encourage_internet_search),
            },
        )
        result = execution.result
        payload = result.json_payload
        if not payload:
            return None
        synthesized = self._payload_to_plan(payload, run)
        return JudgeVerdict(
            judge_mode=JudgeMode.AI,
            verdict_type=VerdictType.MERGED if synthesized else VerdictType.WINNER,
            winning_plan_ids=[plan.plan_id for plan in run.plans[:2]],
            synthesized_plan=synthesized,
            rationale=decision.reasoning if decision else "AI judge synthesized the final plan.",
            selected_strengths=synthesized.strengths if synthesized else [],
            rejected_risks=[risk.title for risk in synthesized.risks] if synthesized else [],
            stop_reason=decision.reasoning if decision else "ai_judge_finalize",
            confidence=decision.confidence if decision else 0.75,
        )

    def _payload_to_plan(self, payload: dict[str, object], run: ExperimentRun) -> PlanDocument:
        return PlanDocument(
            agent_id="judge:synthesis",
            display_name="Judge synthesis",
            summary=str(payload.get("summary", "Synthesized final plan")),
            evidence_basis=[str(item) for item in payload.get("evidence_basis", [])],
            assumptions=[str(item) for item in payload.get("assumptions", [])],
            architecture=[str(item) for item in payload.get("architecture", [])],
            implementation_strategy=[str(item) for item in payload.get("implementation_strategy", [])],
            risks=[
                {
                    "title": risk.get("title", "Unspecified risk"),
                    "severity": risk.get("severity", "medium"),
                    "mitigation": risk.get("mitigation", "Clarify mitigation."),
                }
                for risk in payload.get("risks", [])
                if isinstance(risk, dict)
            ],
            strengths=[str(item) for item in payload.get("strengths", [])],
            weaknesses=[str(item) for item in payload.get("weaknesses", [])],
            trade_offs=[str(item) for item in payload.get("trade_offs", [])],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            raw_response=str(payload),
        )

    def _build_merged_plan(self, top_plan: PlanDocument, second_plan: PlanDocument) -> PlanDocument:
        return PlanDocument(
            agent_id="judge:merged",
            display_name="Merged finalist plan",
            summary=f"{top_plan.summary} Combined with selected strengths from {second_plan.display_name}.",
            evidence_basis=list(dict.fromkeys(top_plan.evidence_basis[:3] + second_plan.evidence_basis[:3])),
            assumptions=list(dict.fromkeys(top_plan.assumptions[:3] + second_plan.assumptions[:3])),
            architecture=list(dict.fromkeys(top_plan.architecture[:3] + second_plan.architecture[:3])),
            implementation_strategy=list(
                dict.fromkeys(
                    top_plan.implementation_strategy[:3] + second_plan.implementation_strategy[:3]
                )
            ),
            risks=list({risk.title: risk for risk in (top_plan.risks + second_plan.risks)}.values()),
            strengths=list(dict.fromkeys(top_plan.strengths[:3] + second_plan.strengths[:3])),
            weaknesses=list(dict.fromkeys(top_plan.weaknesses[:2] + second_plan.weaknesses[:2])),
            trade_offs=list(dict.fromkeys(top_plan.trade_offs[:2] + second_plan.trade_offs[:2])),
            open_questions=list(dict.fromkeys(top_plan.open_questions[:2] + second_plan.open_questions[:2])),
        )

    def _disagreement_level(self, run: ExperimentRun) -> float:
        if not run.debate_rounds:
            if len(run.plan_evaluations) < 2:
                return 0.4
            score_gap = abs(run.plan_evaluations[0].overall_score - run.plan_evaluations[1].overall_score)
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
            latest_novelty = mean(message.novelty_score for message in run.debate_rounds[-1].messages)
            novelty_penalty = max(0.0, 0.15 - latest_novelty)
        return round(min(0.95, max(0.5, top_score - (disagreement_level * 0.15) - novelty_penalty)), 2)

    def _next_round_type(self, run: ExperimentRun) -> RoundType:
        current_rounds = len(run.debate_rounds)
        if current_rounds >= len(ROUND_SEQUENCE):
            return RoundType.TARGETED_REVISION
        return RoundType(ROUND_SEQUENCE[current_rounds])

    def _focus_areas(self, run: ExperimentRun) -> list[str]:
        if self._evidence_support(run) < MIN_EVIDENCE_SUPPORT_TO_FINALIZE:
            return ["objective evidence", "source-backed assumptions", "explicit uncertainty"]
        if not run.debate_rounds:
            return ["feasibility", "maintainability", "cost", "risk"]
        latest = run.debate_rounds[-1].summary
        return latest.key_disagreements[:4] or ["implementation complexity", "traceability"]

    def _image_inputs(self, run: ExperimentRun) -> list[dict]:
        if not run.context_bundle:
            return []
        image_inputs: list[dict] = []
        for source in run.context_bundle.sources:
            for fragment in source.fragments:
                media_type = fragment.media_type or str(source.metadata.get("media_type", ""))
                if not fragment.is_binary or not media_type.startswith("image/"):
                    continue
                image_inputs.append(
                    {
                        "source_id": source.source_id,
                        "label": fragment.label,
                        "path": fragment.path or source.resolved_path,
                        "media_type": media_type,
                        "checksum": fragment.checksum,
                        "size_bytes": fragment.size_bytes,
                        "inline_data": fragment.inline_data,
                    }
                )
        return image_inputs

    def _image_summary(self, image_inputs: list[dict]) -> str:
        if not image_inputs:
            return "No shared image inputs."
        snippets = []
        for item in image_inputs[:3]:
            size_bytes = item.get("size_bytes") or 0
            size_text = f"{round(size_bytes / 1024, 1)} KB" if size_bytes else "size unknown"
            snippets.append(
                f"{item['label']} ({item['media_type']}, {size_text}, checksum {str(item['checksum'])[:8]})"
            )
        if len(image_inputs) > len(snippets):
            snippets.append(f"+{len(image_inputs) - len(snippets)} more image(s)")
        return f"{len(image_inputs)} shared image(s): " + "; ".join(snippets)

    def _initial_disagreements(self, run: ExperimentRun) -> list[str]:
        return [
            "How much abstraction is justified in the MVP.",
            "Whether merged plans are better than winner-take-all selection.",
            "How aggressive budget controls should be before debate quality suffers.",
        ]

    def _initial_strengths(self, run: ExperimentRun) -> list[str]:
        return [strength for plan in run.plans for strength in plan.strengths[:1]]

    def _recommended_human_action(self, run: ExperimentRun) -> str:
        if self._evidence_support(run) < LOW_EVIDENCE_SUPPORT_THRESHOLD:
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
        if instructions:
            return DebateAgenda(
                title=self._agenda_title(instructions),
                question=instructions.strip(),
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
            return candidate

        fallback_question = f"Resolve the key disagreement around {', '.join(focus_areas[:2]) or 'implementation risk'}."
        return DebateAgenda(
            title=self._agenda_title(fallback_question),
            question=fallback_question,
            why_it_matters="The judge still needs one crisp issue to compare the plans side by side.",
            focus_areas=focus_areas[:3] or [round_type.value],
            source_plan_ids=[plan.plan_id for plan in run.plans[:2]],
        )

    def _agenda_candidates(
        self,
        run: ExperimentRun,
        round_type: RoundType,
    ) -> list[DebateAgenda]:
        candidates: list[DebateAgenda] = []
        focus_areas = self._focus_areas(run)

        if self._evidence_support(run) < LOW_EVIDENCE_SUPPORT_THRESHOLD:
            candidates.append(
                DebateAgenda(
                    title="Evidence Grounding",
                    question="Which claims in the competing plans are directly supported by the frozen evidence, and which remain inference?",
                    why_it_matters="The debate should not progress while unsupported claims still drive the comparison.",
                    focus_areas=["objective evidence", "explicit uncertainty", "source-backed trade-offs"],
                    source_plan_ids=[plan.plan_id for plan in run.plans],
                )
            )

        if run.debate_rounds:
            latest = run.debate_rounds[-1].summary
            for item in latest.key_disagreements[:3] + latest.unresolved_questions[:2]:
                text = item.strip()
                if not text:
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
                    title="Final Comparison" if round_type == RoundType.FINAL_COMPARISON else "Implementation Fit",
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
                score = 0.55 + (0.15 if claim.evidence else 0.0) + (message.novelty_score * 0.2)
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
                score = 0.58 + (0.18 if claim.evidence else 0.0) + (message.novelty_score * 0.18)
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
