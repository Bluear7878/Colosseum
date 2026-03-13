from __future__ import annotations

import hashlib
import json
from typing import Any

from colosseum.core.models import UsageMetrics
from colosseum.providers.base import BaseProvider, ProviderResult


class MockProvider(BaseProvider):
    """Deterministic provider for local development and tests."""

    PLAN_STYLES = (
        {
            "summary": "A modular service-first rollout that isolates provider concerns behind a strict orchestration contract.",
            "assumptions": [
                "The existing system can tolerate an adapter layer without changing external APIs.",
                "Artifact persistence is more important than immediate low-latency optimization.",
            ],
            "architecture": [
                "Introduce a provider abstraction with typed request and response envelopes.",
                "Persist every run artifact under a run-specific directory for traceability.",
                "Use a bounded orchestration loop with judge-driven stopping rules.",
            ],
            "implementation": [
                "Start with a mock provider and one real integration surface.",
                "Keep debate state summaries between rounds instead of replaying full transcripts.",
                "Expose human-judge actions through an explicit API contract.",
            ],
            "strengths": [
                "Strong separation of concerns.",
                "Low migration risk for adding providers later.",
            ],
            "weaknesses": [
                "Extra abstraction may feel heavy for very small deployments.",
            ],
            "tradeoffs": [
                "Optimizes maintainability over minimum initial lines of code.",
            ],
        },
        {
            "summary": "A workflow-first design that prioritizes frozen context, comparable outputs, and operator control over model behavior.",
            "assumptions": [
                "Users need consistent plan sections more than open-ended brainstorming.",
                "The first version should support codebase and research tasks through the same pipeline.",
            ],
            "architecture": [
                "Model each stage explicitly: intake, freeze, plan, debate, judge, synthesize.",
                "Use file-backed JSON artifacts as the source of truth for runs.",
                "Represent provider integrations as pluggable executors.",
            ],
            "implementation": [
                "Define strict schemas for plans, debate turns, and verdicts.",
                "Use judge heuristics to skip low-value debate rounds early.",
                "Defer network fetchers for external references to a later release.",
            ],
            "strengths": [
                "Clear operator mental model.",
                "Good auditability for experiment comparisons.",
            ],
            "weaknesses": [
                "Directory context ingestion can become expensive without additional pruning.",
            ],
            "tradeoffs": [
                "Prefers explicit state machines over implicit agent autonomy.",
            ],
        },
        {
            "summary": "A cost-aware architecture that uses selective escalation and hybrid synthesis instead of long debates.",
            "assumptions": [
                "Token budget pressure should be first-class in the judge loop.",
                "Merged plans often outperform strict winner-take-all selection on complex tasks.",
            ],
            "architecture": [
                "Score plans heuristically before starting debate.",
                "Route only the highest-value disagreements into debate prompts.",
                "Use one synthesis artifact rather than replaying all raw messages in later rounds.",
            ],
            "implementation": [
                "Estimate token usage from prompt length when provider telemetry is unavailable.",
                "Run targeted revision rounds only when a gap is isolated and fixable.",
                "Expose human judge packets as concise summaries rather than transcripts by default.",
            ],
            "strengths": [
                "Strong cost control.",
                "Avoids infinite or repetitive debate loops.",
            ],
            "weaknesses": [
                "Heuristic scoring can bias early elimination if not monitored.",
            ],
            "tradeoffs": [
                "Optimizes for practical throughput over exhaustive deliberation.",
            ],
        },
    )

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    async def generate(
        self,
        operation: str,
        instructions: str,
        metadata: dict[str, Any],
    ) -> ProviderResult:
        if operation == "plan":
            payload = self._build_plan_payload(metadata)
        elif operation == "debate":
            payload = self._build_debate_payload(metadata)
        elif operation == "judge":
            payload = self._build_judge_payload(metadata)
        elif operation == "synthesis":
            payload = self._build_synthesis_payload(metadata)
        else:
            payload = {"content": "Unsupported mock operation."}

        content = json.dumps(payload, indent=2)
        usage = UsageMetrics(
            prompt_tokens=max(32, len(instructions) // 4),
            completion_tokens=max(64, len(content) // 4),
        )
        return ProviderResult(
            content=content,
            json_payload=payload,
            usage=usage,
            raw_response={"model": self.model_name, "operation": operation},
        )

    def _pick_style(self, key: str) -> dict[str, Any]:
        # Use a combined key that guarantees different agents get different styles
        combined = f"{self.model_name}:{key}"
        digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % len(self.PLAN_STYLES)
        return self.PLAN_STYLES[index]

    def _pick_style_for_agent(self, agent_id: str, agent_index: int = 0) -> dict[str, Any]:
        """Pick a style ensuring different agents get different styles."""
        digest = hashlib.sha256(f"{self.model_name}:{agent_id}".encode("utf-8")).hexdigest()
        base_index = int(digest[:8], 16) % len(self.PLAN_STYLES)
        # Offset by agent_index to guarantee variety when hash collides
        index = (base_index + agent_index) % len(self.PLAN_STYLES)
        return self.PLAN_STYLES[index]

    def _build_plan_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        agent_id = metadata.get("agent_id", self.model_name)
        # Extract numeric suffix from agent_id (e.g., "mock_1" -> 1) for variety
        parts = agent_id.rsplit("_", 1)
        agent_index = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        style = self._pick_style_for_agent(agent_id, agent_index)
        task_title = metadata.get("task_title", "Untitled task")
        context_summary = metadata.get("context_summary", "No external context summary was provided.")
        image_inputs = metadata.get("image_inputs", [])
        visual_assumption = []
        if image_inputs:
            visual_assumption.append(
                f"The plan should account for shared visual evidence from {len(image_inputs)} image(s)."
            )
        return {
            "summary": f"{task_title}: {style['summary']}",
            "evidence_basis": [
                f"Frozen context summary: {context_summary}",
                "Provider outputs are compared under one shared Colosseum schema.",
            ] + ([f"Shared image packet count: {len(image_inputs)}"] if image_inputs else []),
            "assumptions": style["assumptions"] + [f"Context summary: {context_summary}"] + visual_assumption,
            "architecture": style["architecture"],
            "implementation_strategy": style["implementation"],
            "risks": [
                {
                    "title": "Provider mismatch during rollout",
                    "severity": "medium",
                    "mitigation": "Keep provider behavior behind versioned contracts and add snapshot fixtures.",
                },
                {
                    "title": "Debate quality collapse from repeated arguments",
                    "severity": "medium",
                    "mitigation": "Use novelty thresholds and summary-based memory between rounds.",
                },
            ],
            "strengths": style["strengths"],
            "weaknesses": style["weaknesses"],
            "trade_offs": style["tradeoffs"],
            "open_questions": [
                "Should external URL fetching happen inside Colosseum or via prebuilt context bundles?",
                "How strict should schema validation be for command-based providers?",
            ],
        }

    def _build_debate_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        round_type = metadata.get("round_type", "critique")
        own_plan_id = metadata.get("own_plan_id", "self")
        own_display_name = metadata.get("own_display_name", own_plan_id)
        other_plan_ids = metadata.get("other_plan_ids", [])
        other_plan_labels = metadata.get("other_plan_labels", [])
        target_plan = other_plan_ids[0] if other_plan_ids else own_plan_id
        target_label = other_plan_labels[0] if other_plan_labels else target_plan
        focus_hint = metadata.get("focus_hint", "operator control")
        agenda_title = metadata.get("agenda_title", "Focused Issue")
        agenda_question = metadata.get("agenda_question", "")
        focus_theme = focus_hint if len(str(focus_hint)) <= 60 else "the open implementation risk"
        image_inputs = metadata.get("image_inputs", [])
        visual_clause = ""
        if image_inputs:
            visual_clause = " The shared image set creates a factual interpretation surface that should be checked explicitly."
        round_prefix = {
            "critique": f"Critique round on {agenda_title}. {target_label} needs a clearer stance on {focus_theme}.{visual_clause}",
            "rebuttal": f"Rebuttal round on {agenda_title}. {own_display_name} keeps the stronger extension path while accepting one concrete concern.{visual_clause}",
            "synthesis": f"Synthesis round on {agenda_title}. A hybrid between {own_display_name} and {target_label} looks stronger than either alone.{visual_clause}",
            "final_comparison": f"Final comparison on {agenda_title}. {own_display_name} has the cleaner balance of control, cost, and maintainability.{visual_clause}",
            "targeted_revision": f"Targeted revision on {agenda_title}. Narrow the remaining gap around {focus_theme} without reopening the whole plan.{visual_clause}",
        }.get(round_type, f"{round_type.title()} round response.")
        critique_text = f"{target_label} should answer the judge's issue more directly: {agenda_question or focus_theme}."
        if image_inputs:
            critique_text += " It also needs a clearer plan for validating image-grounded claims."
        return {
            "content": round_prefix + (f" Judge question: {agenda_question}" if agenda_question else ""),
            "critique_points": [
                {
                    "category": "feasibility",
                    "text": critique_text,
                    "target_plan_ids": [target_plan],
                    "evidence": [f"The visible proposal does not fully resolve {focus_theme}."],
                }
            ],
            "defense_points": [
                {
                    "category": "maintainability",
                    "text": f"{own_display_name} keeps orchestration logic vendor-neutral and easier to extend.",
                    "target_plan_ids": [own_plan_id],
                    "evidence": ["Typed provider contract limits vendor-specific branching."],
                }
            ],
            "concessions": [
                "Directory-heavy context bundles still need aggressive prompt pruning in production."
            ],
            "hybrid_suggestions": [
                f"Combine {target_label}'s strongest migration idea with {own_display_name}'s budget controls."
            ],
            "referenced_plan_ids": [own_plan_id, *other_plan_ids],
        }

    def _build_judge_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        suggested_agenda = metadata.get("suggested_agenda", {}) or {}
        return {
            "action": metadata.get("suggested_action", "continue_debate"),
            "confidence": 0.81,
            "reasoning": "The disagreement is still material, but one additional bounded round should resolve the open migration-risk issue.",
            "disagreement_level": 0.46,
            "expected_value_of_next_round": 0.33,
            "next_round_type": metadata.get("next_round_type", "rebuttal"),
            "focus_areas": ["migration risk", "cost control", "traceability"],
            "agenda": suggested_agenda,
        }

    def _build_synthesis_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        basis_plan_ids = metadata.get("basis_plan_ids", [])
        return {
            "summary": "A synthesized plan that combines modular provider abstractions with explicit budget-aware judge controls.",
            "evidence_basis": [
                "Judge synthesis is based on the top submitted plan artifacts and debate summaries."
            ],
            "assumptions": [
                "The final design should preserve run traceability while remaining simple to operate."
            ],
            "architecture": [
                "File-backed run artifacts, provider registry, orchestration loop, judge service, and API layer."
            ],
            "implementation_strategy": [
                "Start with mock and command providers, then add API-backed providers behind the same contract."
            ],
            "risks": [
                {
                    "title": "Artifact growth over long-running experiments",
                    "severity": "medium",
                    "mitigation": "Introduce retention policies and external storage adapters later.",
                }
            ],
            "strengths": [
                "Balanced maintainability and budget control.",
                f"Based on plans: {', '.join(basis_plan_ids) if basis_plan_ids else 'n/a'}.",
            ],
            "weaknesses": [
                "Some heuristics remain simplistic in the MVP."
            ],
            "trade_offs": [
                "The MVP emphasizes traceability and control over advanced automation.",
            ],
            "open_questions": [
                "When should a targeted revision round replace a full debate round?"
            ],
        }
