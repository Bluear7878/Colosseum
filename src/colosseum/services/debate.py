from __future__ import annotations

import asyncio
import logging
from difflib import SequenceMatcher
from statistics import mean

from colosseum.core.config import (
    build_evidence_policy,
    MAX_DEBATE_MEMORY_CHARS,
    MAX_DEBATE_PEER_SUMMARIES,
    MAX_DEBATE_SUMMARY_CHARS,
)
from colosseum.core.models import (
    AgentConfig,
    DebateAgenda,
    DebateRound,
    ExperimentRun,
    RoundSummary,
    RoundType,
    UsageMetrics,
    utc_now,
)
from colosseum.services.budget import BudgetManager
from colosseum.services.context_media import extract_image_inputs, summarize_image_inputs
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderRuntimeService
from colosseum.services.prompt_contracts import (
    DEBATE_BEHAVIOR_GUARDRAIL,
    DEBATE_HONESTY_GUARDRAIL,
)
from colosseum.services.topic_guard import is_drifting, topic_token_set
from colosseum.personas.prompting import (
    build_persona_expression_requirement,
    build_persona_prefix,
)

logger = logging.getLogger(__name__)


class DebateEngine:
    def __init__(
        self,
        budget_manager: BudgetManager,
        normalizer: ResponseNormalizer,
        provider_runtime: ProviderRuntimeService,
    ) -> None:
        self.budget_manager = budget_manager
        self.normalizer = normalizer
        self.provider_runtime = provider_runtime

    async def run_round(
        self,
        run: ExperimentRun,
        round_type: RoundType,
        agenda: DebateAgenda | None = None,
        instructions: str | None = None,
    ) -> DebateRound:
        round_index = len(run.debate_rounds) + 1
        if not run.plans:
            raise ValueError("Cannot start a debate round without generated plans.")
        plan_map = {plan.agent_id: plan for plan in run.plans}
        if not plan_map:
            raise ValueError("Cannot start a debate round without a plan map.")
        image_inputs = self._image_inputs(run)
        image_summary = self._image_summary(run)
        round_timeout = run.budget_policy.timeout_for_round(round_index)
        tasks = []
        for agent in run.agents:
            plan = plan_map[agent.agent_id]
            prompt = self._build_prompt(
                run,
                agent,
                round_type,
                agenda,
                instructions,
                image_summary=image_summary,
                has_image_inputs=bool(image_inputs),
            )
            tasks.append(
                self.provider_runtime.execute(
                    run=run,
                    actor_id=agent.agent_id,
                    actor_label=agent.display_label,
                    provider_config=agent.provider,
                    operation="debate",
                    instructions=prompt,
                    timeout_override=round_timeout,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": agent.agent_id,
                        "round_type": round_type.value,
                        "own_plan_id": plan.plan_id,
                        "own_display_name": plan.display_name,
                        "other_plan_ids": [
                            candidate.plan_id
                            for candidate in run.plans
                            if candidate.plan_id != plan.plan_id
                        ],
                        "other_plan_labels": [
                            candidate.display_name
                            for candidate in run.plans
                            if candidate.plan_id != plan.plan_id
                        ],
                        "task_title": run.task.title,
                        "response_language": run.response_language or "",
                        "focus_hint": self._focus_hint(run),
                        "agenda_title": agenda.title if agenda else "",
                        "agenda_question": agenda.question if agenda else "",
                        "round_index": round_index,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
                        "encourage_internet_search": run.encourage_internet_search,
                        "search_policy": build_evidence_policy(run.encourage_internet_search),
                        "persona": agent.persona_content or "",
                    },
                )
            )

        results = await asyncio.gather(*tasks)
        messages = []
        for agent, execution in zip(run.agents, results, strict=True):
            result = execution.result
            plan = plan_map[agent.agent_id]
            message = self.normalizer.normalize_message(
                agent_id=agent.agent_id,
                plan_id=plan.plan_id,
                round_index=round_index,
                round_type=round_type,
                payload=result.json_payload,
                raw_content=result.content,
                usage=result.usage,
            )
            message.novelty_score = self._novelty_score(
                message.content,
                [prior.content for prior in messages]
                + [
                    prior.content
                    for debate_round in run.debate_rounds
                    for prior in debate_round.messages
                    if prior.agent_id == agent.agent_id
                ],
            )
            message.repetitive = message.novelty_score < run.budget_policy.min_novelty_threshold
            run.budget_ledger.record(agent.agent_id, result.usage, round_index=round_index)
            messages.append(message)

        summary = self._summarize_round(messages, round_type)
        usage = self._aggregate_usage(messages)
        return DebateRound(
            index=round_index,
            round_type=round_type,
            purpose=self._purpose_for(round_type),
            agenda=agenda,
            messages=messages,
            summary=summary,
            usage=usage,
            completed_at=utc_now(),
        )

    async def run_round_streaming(
        self,
        run: ExperimentRun,
        round_type: RoundType,
        agenda: DebateAgenda | None = None,
        instructions: str | None = None,
        skip_event: asyncio.Event | None = None,
        cancel_event: asyncio.Event | None = None,
    ):
        """Yields (event_type, data) tuples as agents complete.

        If *skip_event* is set while agents are still running, remaining
        tasks are cancelled and the round completes with whatever messages
        have been collected so far.

        If *cancel_event* is set, the round is aborted and a
        ``round_cancelled`` event is emitted instead of ``round_complete``.
        """
        round_index = len(run.debate_rounds) + 1
        round_timeout = run.budget_policy.timeout_for_round(round_index)
        plan_map = {plan.agent_id: plan for plan in run.plans}
        if not plan_map:
            raise ValueError("Cannot stream a debate round without generated plans.")
        image_inputs = self._image_inputs(run)
        image_summary = self._image_summary(run)

        # Create tasks with agent mapping
        task_to_agent: dict[asyncio.Task, tuple[AgentConfig, object]] = {}
        for agent in run.agents:
            plan = plan_map.get(agent.agent_id)
            if plan is None:
                continue
            prompt = self._build_prompt(
                run,
                agent,
                round_type,
                agenda,
                instructions,
                image_summary=image_summary,
                has_image_inputs=bool(image_inputs),
            )

            async def agent_generate(a=agent, p=prompt, pl=plan):
                execution = await self.provider_runtime.execute(
                    run=run,
                    actor_id=a.agent_id,
                    actor_label=a.display_label,
                    provider_config=a.provider,
                    operation="debate",
                    instructions=p,
                    timeout_override=round_timeout,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": a.agent_id,
                        "round_type": round_type.value,
                        "own_plan_id": pl.plan_id,
                        "own_display_name": pl.display_name,
                        "other_plan_ids": [c.plan_id for c in run.plans if c.plan_id != pl.plan_id],
                        "other_plan_labels": [
                            c.display_name for c in run.plans if c.plan_id != pl.plan_id
                        ],
                        "task_title": run.task.title,
                        "response_language": run.response_language or "",
                        "focus_hint": self._focus_hint(run),
                        "agenda_title": agenda.title if agenda else "",
                        "agenda_question": agenda.question if agenda else "",
                        "round_index": round_index,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
                        "encourage_internet_search": run.encourage_internet_search,
                        "search_policy": build_evidence_policy(run.encourage_internet_search),
                        "persona": a.persona_content or "",
                    },
                )
                return a, pl, execution.result

            task = asyncio.create_task(agent_generate())
            task_to_agent[task] = (agent, plan)
            yield (
                "agent_thinking",
                {
                    "agent_id": agent.agent_id,
                    "display_name": agent.display_label,
                    "round_index": round_index,
                },
            )

        messages = []
        skipped = False
        cancelled = False
        pending: set[asyncio.Task] = set(task_to_agent.keys())

        while pending:
            # Check cancel signal before waiting
            if cancel_event and cancel_event.is_set():
                for task in pending:
                    task.cancel()
                cancelled = True
                break

            # Check skip signal before waiting
            if skip_event and skip_event.is_set():
                for task in pending:
                    task.cancel()
                skipped = True
                break

            # Wait for next completion or skip/cancel signal
            wait_tasks: set[asyncio.Task | asyncio.Future] = set(pending)
            skip_waiter: asyncio.Task | None = None
            cancel_waiter: asyncio.Task | None = None
            if skip_event and not skip_event.is_set():
                skip_waiter = asyncio.create_task(skip_event.wait())
                wait_tasks.add(skip_waiter)
            if cancel_event and not cancel_event.is_set():
                cancel_waiter = asyncio.create_task(cancel_event.wait())
                wait_tasks.add(cancel_waiter)

            done, _ = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            # Clean up waiters that didn't fire
            for waiter in (skip_waiter, cancel_waiter):
                if waiter and waiter not in done:
                    waiter.cancel()
                    try:
                        await waiter
                    except (asyncio.CancelledError, Exception):
                        pass

            # Check if cancel was triggered
            if cancel_waiter and cancel_waiter in done:
                done.discard(cancel_waiter)
                if skip_waiter and skip_waiter in done:
                    done.discard(skip_waiter)
                for task in pending:
                    if not task.done():
                        task.cancel()
                cancelled = True
                # Fall through to process `done`

            # Check if skip was triggered
            elif skip_waiter and skip_waiter in done:
                done.discard(skip_waiter)
                for task in pending:
                    if not task.done():
                        task.cancel()
                skipped = True
                # Still process any tasks that completed simultaneously
                # Fall through to process `done`

            for task in done:
                if task not in task_to_agent:
                    continue
                pending.discard(task)
                agent_result_cfg, plan_obj = task_to_agent[task]
                try:
                    agent_result, plan, result = task.result()
                    message = self.normalizer.normalize_message(
                        agent_id=agent_result.agent_id,
                        plan_id=plan.plan_id,
                        round_index=round_index,
                        round_type=round_type,
                        payload=result.json_payload,
                        raw_content=result.content,
                        usage=result.usage,
                    )
                    message.novelty_score = self._novelty_score(
                        message.content,
                        [prior.content for prior in messages]
                        + [
                            prior.content
                            for dr in run.debate_rounds
                            for prior in dr.messages
                            if prior.agent_id == agent_result.agent_id
                        ],
                    )
                    message.repetitive = (
                        message.novelty_score < run.budget_policy.min_novelty_threshold
                    )
                    run.budget_ledger.record(
                        agent_result.agent_id, result.usage, round_index=round_index
                    )
                    messages.append(message)

                    yield (
                        "agent_message",
                        {
                            "agent_id": agent_result.agent_id,
                            "display_name": agent_result.display_label,
                            "content": message.content,
                            "critique_count": len(message.critique_points),
                            "defense_count": len(message.defense_points),
                            "concession_count": len(message.concessions),
                            "novelty_score": message.novelty_score,
                            "usage": {
                                "prompt_tokens": message.usage.prompt_tokens,
                                "completion_tokens": message.usage.completion_tokens,
                                "total_tokens": message.usage.total_tokens,
                            },
                            "round_index": round_index,
                        },
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception(
                        "Agent %s failed in round %d: %s", agent_result_cfg.agent_id, round_index, e
                    )

            if skipped:
                break

        # Suppress cancelled-task warnings
        for task in task_to_agent:
            if task.done() and not task.cancelled():
                try:
                    task.result()
                except Exception:
                    pass

        if cancelled:
            yield (
                "round_cancelled",
                {"round_index": round_index, "messages_collected": len(messages)},
            )
            return

        if skipped:
            yield (
                "round_skipped",
                {"round_index": round_index, "messages_collected": len(messages)},
            )

        summary = self._summarize_round(messages, round_type)
        usage = self._aggregate_usage(messages)
        debate_round = DebateRound(
            index=round_index,
            round_type=round_type,
            purpose=self._purpose_for(round_type),
            agenda=agenda,
            messages=messages,
            summary=summary,
            usage=usage,
            completed_at=utc_now(),
        )
        yield ("round_complete", debate_round)

    def _build_prompt(
        self,
        run: ExperimentRun,
        agent: AgentConfig,
        round_type: RoundType,
        agenda: DebateAgenda | None,
        instructions: str | None,
        image_summary: str,
        has_image_inputs: bool,
    ) -> str:
        own_plan = next(plan for plan in run.plans if plan.agent_id == agent.agent_id)
        peer_summaries = [
            f"{plan.display_name}: {self._compact_text(plan.summary, MAX_DEBATE_SUMMARY_CHARS)}"
            for plan in run.plans
            if plan.agent_id != agent.agent_id
        ][:MAX_DEBATE_PEER_SUMMARIES]
        memory = self._compact_text(self._memory_summary(run), MAX_DEBATE_MEMORY_CHARS)

        # Build actual debate transcript from previous rounds so agents can
        # directly rebut, accept, or build on each other's specific points.
        debate_transcript = self._build_debate_transcript(run, agent)

        round_goals = {
            RoundType.CRITIQUE: (
                "Surface the most consequential weaknesses in each peer plan. "
                "Focus on evidence gaps, architectural flaws, and risks that are specific to this task. "
                "Every critique must be grounded in the frozen context or explicitly labeled as inference."
            ),
            RoundType.REBUTTAL: (
                "Defend your core choices with evidence, concede valid criticisms honestly, and sharpen trade-offs. "
                "Propose hybrids if peer arguments revealed genuine weaknesses in your plan. "
                "Do not simply reassert your plan — respond directly to the critiques raised."
            ),
            RoundType.SYNTHESIS: (
                "Propose merged solutions that retain the strongest evidence-backed ideas from all plans "
                "and reduce the highest-severity risks. Focus only on what is actually feasible for this specific task. "
                "Ground every proposal in the frozen context."
            ),
            RoundType.FINAL_COMPARISON: (
                "State concisely which plan or hybrid should win and exactly why, grounded in evidence and the task requirements. "
                "No new arguments — only your clearest comparative case."
            ),
            RoundType.TARGETED_REVISION: (
                "Address the specific unresolved issue identified by the judge. "
                "Do not reopen the full debate. Stay narrowly focused on this one issue."
            ),
        }
        round_goal = round_goals.get(
            round_type, "Contribute your strongest evidence-backed argument for this debate round."
        )

        prompt_parts = [
            f"DEBATE TOPIC: {run.task.title}",
            f"Problem: {run.task.problem_statement}",
            f"Round type: {round_type.value}",
            f"Round goal: {round_goal}",
            f"Your specialty: {agent.specialty or 'generalist'}",
            f"Your plan summary: {self._compact_text(own_plan.summary, MAX_DEBATE_SUMMARY_CHARS)}",
            f"Your evidence basis: {self._compact_text('; '.join(own_plan.evidence_basis[:3]) or 'No explicit evidence listed.', MAX_DEBATE_SUMMARY_CHARS)}",
            "Peer plan summaries:",
            "\n".join(peer_summaries),
        ]
        if agenda:
            prompt_parts.extend(
                [
                    f"Judge agenda title: {agenda.title}",
                    f"Judge question: {agenda.question}",
                    f"Why this issue matters now: {agenda.why_it_matters or 'The judge selected this as the next issue to resolve.'}",
                    f"TOPIC ANCHOR: This agenda only matters insofar as it advances the original debate "
                    f"topic — '{run.task.title}'. If the agenda question wanders into meta-debate "
                    "(e.g. complaining that a peer 'failed to provide a plan' or arguing about prior "
                    "rounds rather than the task), reframe your answer back to the original topic and "
                    "say so explicitly in your response.",
                    "Structure your answer around the judge question first. Then explicitly state which peer points "
                    "you reject, which peer points you accept, and which specific claim from your side you believe survives scrutiny best.",
                ]
            )

        if debate_transcript:
            prompt_parts.append(debate_transcript)

        priority_focus = (
            agenda.question if agenda else self._focus_hint(run)
        ) or run.task.title
        prompt_parts.extend(
            [
                f"Memory summary: {memory}",
                f"Priority focus: {priority_focus}",
                build_evidence_policy(run.encourage_internet_search),
                (
                    f"SCOPE ENFORCEMENT: Every argument must be strictly relevant to '{run.task.title}'. "
                    "Do not introduce unrelated topics, generic best practices disconnected from this task, "
                    "or examples from outside this debate's scope. "
                    "Do NOT spend the round arguing about peer behavior (e.g. 'agent X failed to "
                    "provide a plan'); always re-anchor on the original task. "
                    "If a point does not directly address the judge's question or a peer's argument about this task, omit it."
                ),
                "Constraints: You MUST directly respond to other participants' arguments. "
                "Quote or reference specific points they made. Rebut claims you disagree with, "
                "concede points that are well-supported, and propose alternatives where appropriate. "
                "Do NOT simply restate your own position — engage with what others have said. "
                "Evidence quality matters more than rhetorical force: cite the frozen bundle or state uncertainty explicitly. "
                "Unsupported claims reduce judge confidence. "
                f"{DEBATE_BEHAVIOR_GUARDRAIL} {DEBATE_HONESTY_GUARDRAIL}",
                build_persona_expression_requirement(
                    "debate response, including content, critique points, defense points, and concessions",
                    agent.persona_content,
                ),
            ]
        )
        if has_image_inputs:
            prompt_parts.extend(
                [
                    f"Shared visual context: {image_summary}",
                    "Use the shared image package when you critique or defend factual visual claims. "
                    "If you cannot inspect images, say so and limit yourself to textual evidence.",
                ]
            )
        if instructions:
            prompt_parts.append(f"Additional judge instructions: {instructions}")

        # Build prefix: language rule first, then persona
        prefix: list[str] = []
        lang = (
            run.response_language
            if run.response_language and run.response_language != "auto"
            else ""
        )
        if lang:
            prefix.append(
                f"MANDATORY LANGUAGE: You MUST write your ENTIRE response in {lang}. "
                f"Every field, every argument, every sentence must be in {lang}. "
                "This rule overrides all other instructions and cannot be skipped."
            )
        prefix.extend(build_persona_prefix(agent.persona_content, agent.system_prompt))
        if lang:
            prompt_parts.append(
                f"REMINDER: Your response MUST be entirely in {lang}. No other language permitted."
            )

        return "\n\n".join(prefix + prompt_parts)

    def _build_debate_transcript(self, run: ExperimentRun, agent: AgentConfig) -> str:
        """Build a transcript of previous debate rounds showing what each
        participant actually said, so agents can directly rebut or accept
        specific points rather than talking past each other."""
        if not run.debate_rounds:
            return ""

        max_chars = MAX_DEBATE_MEMORY_CHARS * 3  # Allow more space for real transcript
        lines: list[str] = ["=== DEBATE TRANSCRIPT (previous rounds) ==="]

        agent_names = {a.agent_id: a.display_name for a in run.agents}

        for debate_round in run.debate_rounds[-2:]:  # Last 2 rounds for recency
            lines.append(f"\n--- Round {debate_round.index}: {debate_round.round_type.value} ---")
            for msg in debate_round.messages:
                speaker = agent_names.get(msg.agent_id, msg.agent_id)
                is_self = msg.agent_id == agent.agent_id

                # Show content (truncated)
                content_preview = self._compact_text(msg.content, 400)
                tag = "[YOU]" if is_self else f"[{speaker}]"
                lines.append(f"{tag}: {content_preview}")

                # Show key critique/defense points for non-self agents
                if not is_self:
                    if msg.critique_points:
                        critiques = [f"  - CRITIQUE: {c.text}" for c in msg.critique_points[:3]]
                        lines.extend(critiques)
                    if msg.defense_points:
                        defenses = [f"  - DEFENSE: {d.text}" for d in msg.defense_points[:3]]
                        lines.extend(defenses)
                    if msg.concessions:
                        concessions_text = [f"  - CONCESSION: {c}" for c in msg.concessions[:2]]
                        lines.extend(concessions_text)

        lines.append("=== END TRANSCRIPT ===")
        lines.append(
            "You must respond to the specific points above. "
            "Reference other participants by name when agreeing or disagreeing."
        )

        transcript = "\n".join(lines)
        if len(transcript) > max_chars:
            transcript = transcript[: max_chars - 3].rstrip() + "..."
        return transcript

    def _image_inputs(self, run: ExperimentRun) -> list[dict]:
        return extract_image_inputs(run.context_bundle)

    def _image_summary(self, run: ExperimentRun) -> str:
        return summarize_image_inputs(self._image_inputs(run), limit=3)

    def _memory_summary(self, run: ExperimentRun) -> str:
        if not run.debate_rounds:
            return "No prior debate rounds."
        latest = run.debate_rounds[-1].summary
        return (
            f"Agreements: {latest.agreements[:3]}; "
            f"Disagreements: {latest.key_disagreements[:3]}; "
            f"Unresolved: {latest.unresolved_questions[:3]}"
        )

    def _focus_hint(self, run: ExperimentRun) -> str:
        topic = run.task.title or ""
        tokens = topic_token_set(run)

        def _on_topic(items: list[str]) -> list[str]:
            if not items:
                return []
            if not tokens:
                return items
            return [item for item in items if item and not is_drifting(item, run, tokens=tokens)]

        if run.judge_trace and run.judge_trace[-1].focus_areas:
            on_topic = _on_topic(list(run.judge_trace[-1].focus_areas[:3]))
            if on_topic:
                return self._compact_text(", ".join(on_topic), 120)
        if run.debate_rounds and run.debate_rounds[-1].summary.key_disagreements:
            on_topic = _on_topic(list(run.debate_rounds[-1].summary.key_disagreements[:3]))
            if on_topic:
                return self._compact_text(", ".join(on_topic[:2]), 120)
        if topic:
            return self._compact_text(topic, 120)
        return "correctness, feasibility, maintainability"

    def _compact_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _novelty_score(self, text: str, previous_texts: list[str]) -> float:
        if not previous_texts:
            return 1.0
        similarities = [
            SequenceMatcher(None, text, previous).ratio() for previous in previous_texts
        ]
        return round(max(0.0, 1.0 - max(similarities)), 2)

    def _summarize_round(self, messages: list, round_type: RoundType) -> RoundSummary:
        critique_topics: list[str] = []
        defenses: list[str] = []
        hybrid_suggestions: list[str] = []
        concessions: list[str] = []
        for message in messages:
            critique_topics.extend(claim.text for claim in message.critique_points)
            defenses.extend(claim.text for claim in message.defense_points)
            hybrid_suggestions.extend(message.hybrid_suggestions)
            concessions.extend(message.concessions)

        disagreements = critique_topics[:5]
        strongest = defenses[:5]
        agreements = concessions[:3]
        unresolved = list(
            dict.fromkeys(disagreements[:2] + [suggestion for suggestion in hybrid_suggestions[:2]])
        )
        moderator_note = (
            f"{round_type.value.title()} round completed with average novelty "
            f"{round(mean(message.novelty_score for message in messages), 2) if messages else 0.0}."
        )
        return RoundSummary(
            agreements=agreements,
            key_disagreements=disagreements,
            strongest_arguments=strongest,
            hybrid_opportunities=list(dict.fromkeys(hybrid_suggestions))[:4],
            unresolved_questions=unresolved,
            moderator_note=moderator_note,
        )

    def _aggregate_usage(self, messages: list) -> UsageMetrics:
        prompt_tokens = sum(message.usage.prompt_tokens for message in messages)
        completion_tokens = sum(message.usage.completion_tokens for message in messages)
        estimated_cost = sum(message.usage.estimated_cost_usd for message in messages)
        return UsageMetrics(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=estimated_cost,
        )

    def _purpose_for(self, round_type: RoundType) -> str:
        purposes = {
            RoundType.CRITIQUE: "Surface the most consequential weaknesses in each plan.",
            RoundType.REBUTTAL: "Defend choices, concede valid points, and sharpen trade-offs.",
            RoundType.SYNTHESIS: "Propose hybrid solutions that combine the best elements of competing plans.",
            RoundType.FINAL_COMPARISON: "State which plan or hybrid should win and why.",
            RoundType.TARGETED_REVISION: "Address one unresolved issue with a narrowly scoped revision.",
        }
        return purposes[round_type]
