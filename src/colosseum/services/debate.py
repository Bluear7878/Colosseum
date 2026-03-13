from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
from statistics import mean

from colosseum.core.config import (
    EVIDENCE_POLICY,
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
)
from colosseum.services.budget import BudgetManager
from colosseum.services.normalizers import ResponseNormalizer
from colosseum.services.provider_runtime import ProviderRuntimeService


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
        plan_map = {plan.agent_id: plan for plan in run.plans}
        image_inputs = self._image_inputs(run)
        image_summary = self._image_summary(run)
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
                    actor_label=agent.display_name,
                    provider_config=agent.provider,
                    operation="debate",
                    instructions=prompt,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": agent.agent_id,
                        "round_type": round_type.value,
                        "own_plan_id": plan.plan_id,
                        "own_display_name": plan.display_name,
                        "other_plan_ids": [
                            candidate.plan_id for candidate in run.plans if candidate.plan_id != plan.plan_id
                        ],
                        "other_plan_labels": [
                            candidate.display_name for candidate in run.plans if candidate.plan_id != plan.plan_id
                        ],
                        "focus_hint": self._focus_hint(run),
                        "agenda_title": agenda.title if agenda else "",
                        "agenda_question": agenda.question if agenda else "",
                        "round_index": round_index,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
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
                + [prior.content for debate_round in run.debate_rounds for prior in debate_round.messages if prior.agent_id == agent.agent_id],
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
        )

    async def run_round_streaming(
        self,
        run: ExperimentRun,
        round_type: RoundType,
        agenda: DebateAgenda | None = None,
        instructions: str | None = None,
    ):
        """Yields (event_type, data) tuples as agents complete."""
        round_index = len(run.debate_rounds) + 1
        plan_map = {plan.agent_id: plan for plan in run.plans}
        image_inputs = self._image_inputs(run)
        image_summary = self._image_summary(run)

        # Create tasks with agent mapping
        agent_tasks: dict[int, asyncio.Task] = {}
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

            async def agent_generate(a=agent, p=prompt, pl=plan):
                execution = await self.provider_runtime.execute(
                    run=run,
                    actor_id=a.agent_id,
                    actor_label=a.display_name,
                    provider_config=a.provider,
                    operation="debate",
                    instructions=p,
                    metadata={
                        "run_id": run.run_id,
                        "agent_id": a.agent_id,
                        "round_type": round_type.value,
                        "own_plan_id": pl.plan_id,
                        "own_display_name": pl.display_name,
                        "other_plan_ids": [c.plan_id for c in run.plans if c.plan_id != pl.plan_id],
                        "other_plan_labels": [c.display_name for c in run.plans if c.plan_id != pl.plan_id],
                        "focus_hint": self._focus_hint(run),
                        "agenda_title": agenda.title if agenda else "",
                        "agenda_question": agenda.question if agenda else "",
                        "round_index": round_index,
                        "image_inputs": image_inputs,
                        "image_summary": image_summary,
                        "persona": a.persona_content or "",
                    },
                )
                return a, pl, execution.result

            task = asyncio.create_task(agent_generate())
            agent_tasks[id(task)] = task
            yield ("agent_thinking", {"agent_id": agent.agent_id, "display_name": agent.display_name, "round_index": round_index})

        messages = []
        pending = list(agent_tasks.values())
        try:
            for coro in asyncio.as_completed(pending):
                agent_result, plan, result = await coro
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
                    + [prior.content for dr in run.debate_rounds for prior in dr.messages if prior.agent_id == agent_result.agent_id],
                )
                message.repetitive = message.novelty_score < run.budget_policy.min_novelty_threshold
                run.budget_ledger.record(agent_result.agent_id, result.usage, round_index=round_index)
                messages.append(message)

                yield ("agent_message", {
                    "agent_id": agent_result.agent_id,
                    "display_name": agent_result.display_name,
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
                })
        except Exception:
            for task in pending:
                if not task.done():
                    task.cancel()
            for task in pending:
                if task.done() and not task.cancelled():
                    try:
                        task.result()
                    except Exception:
                        pass
            raise

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

        prompt_parts = [
            f"Round type: {round_type.value}",
            f"Task: {run.task.title}",
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
                    "Structure your answer around the judge question first. Then explicitly state which peer points "
                    "you reject, which peer points you accept, and what the judge should adopt from your argument.",
                ]
            )

        if debate_transcript:
            prompt_parts.append(debate_transcript)

        prompt_parts.extend([
            f"Memory summary: {memory}",
            f"Priority focus: {agenda.question if agenda else self._focus_hint(run)}",
            EVIDENCE_POLICY,
            "Constraints: You MUST directly respond to other participants' arguments. "
            "Quote or reference specific points they made. Rebut claims you disagree with, "
            "concede points that are well-supported, and propose alternatives where appropriate. "
            "Do NOT simply restate your own position — engage with what others have said. "
            "Support critique/defense claims with evidence arrays.",
        ])
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
        if agent.persona_content:
            prompt_parts.insert(0, "=== YOUR PERSONA ===\n" + agent.persona_content + "\n=== END PERSONA ===")
        elif agent.system_prompt:
            prompt_parts.insert(0, "System: " + agent.system_prompt)
        return "\n\n".join(prompt_parts)

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
            transcript = transcript[:max_chars - 3].rstrip() + "..."
        return transcript

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

    def _image_summary(self, run: ExperimentRun) -> str:
        image_inputs = self._image_inputs(run)
        if not image_inputs:
            return "No shared image inputs."
        entries = []
        for item in image_inputs[:3]:
            size_bytes = item.get("size_bytes") or 0
            size_text = f"{round(size_bytes / 1024, 1)} KB" if size_bytes else "size unknown"
            entries.append(
                f"{item['label']} ({item['media_type']}, {size_text}, checksum {str(item['checksum'])[:8]})"
            )
        if len(image_inputs) > len(entries):
            entries.append(f"+{len(image_inputs) - len(entries)} more image(s)")
        return f"{len(image_inputs)} shared image(s): " + "; ".join(entries)

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
        if run.judge_trace and run.judge_trace[-1].focus_areas:
            return self._compact_text(", ".join(run.judge_trace[-1].focus_areas[:3]), 120)
        if run.debate_rounds and run.debate_rounds[-1].summary.key_disagreements:
            return self._compact_text(", ".join(run.debate_rounds[-1].summary.key_disagreements[:2]), 120)
        return "correctness, feasibility, maintainability"

    def _compact_text(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _novelty_score(self, text: str, previous_texts: list[str]) -> float:
        if not previous_texts:
            return 1.0
        similarities = [SequenceMatcher(None, text, previous).ratio() for previous in previous_texts]
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
        unresolved = list(dict.fromkeys(disagreements[:2] + [suggestion for suggestion in hybrid_suggestions[:2]]))
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
