"""Helpers for serializing streaming API events."""

from __future__ import annotations

import json
from typing import Any

from colosseum.core.models import DebateRound, ExperimentRun, JudgeVerdict


def encode_sse(payload: dict[str, Any]) -> str:
    """Serialize one SSE event payload."""
    return f"data: {json.dumps(payload)}\n\n"


def plan_ready_payload(event_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "plan_ready",
        "agent_id": event_data["agent_id"],
        "display_name": event_data["display_name"],
        "plan_id": event_data["plan_id"],
        "summary": event_data["summary"],
        "strengths": event_data["strengths"],
        "weaknesses": event_data["weaknesses"],
    }


def round_complete_payload(debate_round: DebateRound) -> dict[str, Any]:
    return {
        "phase": "round_complete",
        "round": {
            "index": debate_round.index,
            "round_type": debate_round.round_type.value,
            "purpose": debate_round.purpose,
            "agenda": debate_round.agenda.model_dump(mode="json") if debate_round.agenda else None,
            "adjudication": debate_round.adjudication.model_dump(mode="json")
            if debate_round.adjudication
            else None,
            "usage": {
                "total_tokens": debate_round.usage.total_tokens,
                "prompt_tokens": debate_round.usage.prompt_tokens,
                "completion_tokens": debate_round.usage.completion_tokens,
            },
            "summary": {
                "key_disagreements": debate_round.summary.key_disagreements,
                "strongest_arguments": debate_round.summary.strongest_arguments,
                "hybrid_opportunities": debate_round.summary.hybrid_opportunities,
                "moderator_note": debate_round.summary.moderator_note,
            },
            "messages": [
                {
                    "agent_id": message.agent_id,
                    "content": message.content,
                    "novelty_score": message.novelty_score,
                    "usage": {"total_tokens": message.usage.total_tokens},
                }
                for message in debate_round.messages
            ],
        },
    }


def complete_payload(run: ExperimentRun) -> dict[str, Any]:
    verdict_data = verdict_payload(run.verdict)
    budget_by_actor = {
        actor_id: {
            "total_tokens": usage.total_tokens,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "estimated_cost_usd": usage.estimated_cost_usd,
        }
        for actor_id, usage in run.budget_ledger.by_actor.items()
    }
    final_report_data = run.final_report.model_dump(mode="json") if run.final_report else None
    return {
        "phase": "complete",
        "verdict": verdict_data,
        "budget_total": run.budget_ledger.total.total_tokens,
        "budget_total_cost_usd": run.budget_ledger.total.estimated_cost_usd,
        "budget_by_actor": budget_by_actor,
        "final_report": final_report_data,
    }


def verdict_payload(verdict: JudgeVerdict | None) -> dict[str, Any]:
    if verdict is None:
        return {}
    payload: dict[str, Any] = {
        "verdict_type": verdict.verdict_type.value,
        "winning_plan_ids": verdict.winning_plan_ids,
        "rationale": verdict.rationale,
        "selected_strengths": verdict.selected_strengths,
        "rejected_risks": verdict.rejected_risks,
        "stop_reason": verdict.stop_reason,
        "confidence": verdict.confidence,
    }
    if verdict.synthesized_plan:
        payload["synthesized_plan"] = {"summary": verdict.synthesized_plan.summary}
    return payload
