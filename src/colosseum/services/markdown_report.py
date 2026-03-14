"""Generate a downloadable Markdown report from a completed ExperimentRun."""

from __future__ import annotations

from datetime import timezone

from colosseum.core.models import ExperimentRun


def _ts(dt) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _winner_names(run: ExperimentRun) -> list[str]:
    """Return winner display names for the final verdict."""
    if not run.verdict:
        return []
    names: list[str] = []
    for winning_id in run.verdict.winning_plan_ids:
        match = next((plan for plan in run.plans if plan.plan_id == winning_id), None)
        names.append(match.display_name if match else winning_id[:8])
    return names


def _append_list(lines: list[str], title: str, items: list[str], *, level: str = "##") -> None:
    """Append a Markdown bullet section when items are present."""
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return
    lines.extend([f"{level} {title}", ""])
    lines.extend(f"- {item}" for item in cleaned)
    lines.append("")


def generate_markdown(run: ExperimentRun) -> str:
    """Return Markdown text for the given run."""
    lines: list[str] = [
        "# COLOSSEUM Battle Report",
        "",
        f"**Title:** {run.task.title}",
        f"**Run ID:** {run.run_id}",
        f"**Created:** {_ts(run.created_at)}",
        f"**Status:** {run.status.value}",
        f"**Agents:** {len(run.agents)}",
        f"**Rounds:** {len(run.debate_rounds)}",
        f"**Tokens:** {run.budget_ledger.total.total_tokens:,}",
        "",
        "## User Question",
        "",
        run.task.problem_statement,
        "",
    ]

    if run.final_report and run.final_report.final_answer:
        lines.extend(["## Final Answer", "", run.final_report.final_answer, ""])

    if run.verdict:
        winner_names = _winner_names(run)
        lines.extend(
            [
                "## Verdict",
                "",
                f"**Type:** {run.verdict.verdict_type.value}",
                f"**Winner(s):** {', '.join(winner_names) if winner_names else 'N/A'}",
                f"**Confidence:** {run.verdict.confidence:.2f}",
                f"**Stop Reason:** {run.verdict.stop_reason}",
                "",
                run.verdict.rationale,
                "",
            ]
        )
        if run.verdict.synthesized_plan:
            lines.extend(
                [
                    "### Synthesized Plan",
                    "",
                    run.verdict.synthesized_plan.summary,
                    "",
                ]
            )
        _append_list(lines, "Selected Strengths", run.verdict.selected_strengths)
        _append_list(lines, "Rejected Risks", run.verdict.rejected_risks)

    if run.final_report:
        lines.extend(["## Executive Summary", "", run.final_report.executive_summary, ""])
        _append_list(lines, "Key Conclusions", run.final_report.key_conclusions)
        if run.final_report.verdict_explanation:
            lines.extend(
                [
                    "## Verdict Explanation",
                    "",
                    run.final_report.verdict_explanation,
                    "",
                ]
            )
        _append_list(lines, "Debate Highlights", run.final_report.debate_highlights)
        _append_list(lines, "Recommendations", run.final_report.recommendations)

    if run.plans:
        lines.extend(["## Agent Plans", ""])
        score_map = {ev.plan_id: ev.overall_score for ev in run.plan_evaluations}
        for plan in run.plans:
            score = score_map.get(plan.plan_id)
            score_text = f" (score {score:.2f})" if score is not None else ""
            lines.extend([f"### {plan.display_name}{score_text}", "", plan.summary, ""])
            _append_list(lines, "Architecture", plan.architecture, level="####")
            _append_list(lines, "Strengths", plan.strengths, level="####")
            _append_list(lines, "Weaknesses", plan.weaknesses, level="####")

    if run.debate_rounds:
        lines.extend(["## Debate Timeline", ""])
        for debate_round in run.debate_rounds:
            lines.extend(
                [
                    f"### Round {debate_round.index}: {debate_round.round_type.value}",
                    "",
                ]
            )
            if debate_round.agenda and debate_round.agenda.question:
                lines.extend([f"**Agenda:** {debate_round.agenda.question}", ""])
            if debate_round.summary.moderator_note:
                lines.extend([debate_round.summary.moderator_note, ""])
            _append_list(
                lines,
                "Key Disagreements",
                debate_round.summary.key_disagreements,
                level="####",
            )
            if debate_round.adjudication and debate_round.adjudication.resolution:
                lines.extend(
                    [
                        "#### Judge Resolution",
                        "",
                        debate_round.adjudication.resolution,
                        "",
                    ]
                )

    if run.budget_ledger.by_actor:
        lines.extend(["## Token Usage", ""])
        agent_names = {agent.agent_id: agent.display_name for agent in run.agents}
        for actor_id, usage in run.budget_ledger.by_actor.items():
            label = agent_names.get(actor_id, actor_id)
            lines.append(
                f"- {label}: prompt {usage.prompt_tokens:,}, completion {usage.completion_tokens:,}, total {usage.total_tokens:,}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
