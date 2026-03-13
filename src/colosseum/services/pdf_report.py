"""Generate a downloadable PDF report from a completed ExperimentRun."""

from __future__ import annotations

import textwrap
from datetime import timezone

from fpdf import FPDF

from colosseum.core.models import ExperimentRun


# ── Colour palette (Colosseum arena theme, mapped to RGB) ──
_GOLD = (212, 164, 76)
_DARK = (15, 15, 26)
_SAND = (232, 220, 200)
_STONE = (42, 42, 62)
_BLOOD = (192, 57, 43)
_WHITE = (255, 255, 255)
_GREY = (154, 142, 122)
_LIGHT_BG = (245, 241, 235)


def _ts(dt) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _wrap(text: str, width: int = 95) -> str:
    return "\n".join(textwrap.wrap(str(text or ""), width=width))


class _PDF(FPDF):
    """Customised FPDF with Colosseum header/footer."""

    run_title: str = ""

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*_GREY)
        self.cell(0, 6, f"COLOSSEUM  |  {self.run_title}", align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_GREY)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    # ── helpers ──

    def section_title(self, title: str) -> None:
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*_GOLD)
        self.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        # underline
        y = self.get_y()
        self.set_draw_color(*_GOLD)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(4)

    def sub_title(self, title: str) -> None:
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*_DARK)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def body_text(self, text: str) -> None:
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*_DARK)
        self.multi_cell(0, 5, _wrap(text, 105))
        self.ln(2)

    def label_value(self, label: str, value: str) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_GREY)
        self.cell(45, 6, label)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*_DARK)
        self.multi_cell(0, 6, str(value))
        self.ln(1)

    def bullet_list(self, items: list[str]) -> None:
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_DARK)
        for item in items:
            x = self.get_x()
            self.cell(6, 5, "\u2022")
            self.multi_cell(0, 5, _wrap(str(item), 100))
            self.set_x(x)
            self.ln(1)
        self.ln(1)

    def safe_page_break(self, h: float = 30) -> None:
        if self.get_y() + h > self.h - self.b_margin:
            self.add_page()


def generate_pdf(run: ExperimentRun) -> bytes:
    """Return PDF bytes for the given run."""
    pdf = _PDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.run_title = run.task.title
    pdf.set_auto_page_break(auto=True, margin=20)

    # ════════════════════════════════════════
    # Title page
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.ln(40)
    pdf.set_font("Helvetica", "B", 32)
    pdf.set_text_color(*_GOLD)
    pdf.cell(0, 14, "COLOSSEUM", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 8, "Battle Report", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(12)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_DARK)
    pdf.multi_cell(0, 9, run.task.title, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_GREY)
    pdf.cell(0, 6, f"Run ID: {run.run_id[:8]}   |   {_ts(run.created_at)}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Status: {run.status.value.upper()}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(20)

    # Quick stats
    agents_count = len(run.agents)
    rounds_count = len(run.debate_rounds)
    total_tokens = run.budget_ledger.total.total_tokens

    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_DARK)
    stats_text = f"Agents: {agents_count}    |    Rounds: {rounds_count}    |    Tokens: {total_tokens:,}"
    pdf.cell(0, 8, stats_text, align="C", new_x="LMARGIN", new_y="NEXT")

    # ════════════════════════════════════════
    # Verdict
    # ════════════════════════════════════════
    if run.verdict:
        pdf.add_page()
        pdf.section_title("Verdict")

        v = run.verdict
        winner_names = []
        for wid in v.winning_plan_ids:
            match = next((p for p in run.plans if p.plan_id == wid), None)
            winner_names.append(match.display_name if match else wid[:8])

        pdf.label_value("Result", v.verdict_type.value.upper())
        pdf.label_value("Winner(s)", ", ".join(winner_names) if winner_names else "N/A")
        pdf.label_value("Confidence", f"{v.confidence:.2f}")
        pdf.label_value("Stop Reason", v.stop_reason)
        pdf.ln(3)

        pdf.sub_title("Rationale")
        pdf.body_text(v.rationale)

        if v.selected_strengths:
            pdf.sub_title("Selected Strengths")
            pdf.bullet_list(v.selected_strengths)

        if v.rejected_risks:
            pdf.sub_title("Rejected Risks")
            pdf.bullet_list(v.rejected_risks)

        if v.synthesized_plan:
            pdf.sub_title("Synthesized Plan")
            pdf.body_text(v.synthesized_plan.summary)

    # ════════════════════════════════════════
    # Executive Report
    # ════════════════════════════════════════
    if run.final_report:
        pdf.add_page()
        pdf.section_title("Executive Report")

        fr = run.final_report
        pdf.sub_title("Summary")
        pdf.body_text(fr.executive_summary)

        if fr.key_conclusions:
            pdf.sub_title("Key Conclusions")
            pdf.bullet_list(fr.key_conclusions)

        if fr.verdict_explanation:
            pdf.sub_title("Verdict Explanation")
            pdf.body_text(fr.verdict_explanation)

        if fr.debate_highlights:
            pdf.sub_title("Debate Highlights")
            pdf.bullet_list(fr.debate_highlights)

        if fr.recommendations:
            pdf.sub_title("Recommendations")
            pdf.bullet_list(fr.recommendations)

    # ════════════════════════════════════════
    # Task Description
    # ════════════════════════════════════════
    pdf.add_page()
    pdf.section_title("Task Description")
    pdf.label_value("Title", run.task.title)
    pdf.label_value("Type", run.task.task_type.value)
    pdf.ln(2)
    pdf.sub_title("Problem Statement")
    pdf.body_text(run.task.problem_statement)

    if run.task.success_criteria:
        pdf.sub_title("Success Criteria")
        pdf.bullet_list(run.task.success_criteria)

    if run.task.constraints:
        pdf.sub_title("Constraints")
        pdf.bullet_list(run.task.constraints)

    # ════════════════════════════════════════
    # Plans
    # ════════════════════════════════════════
    if run.plans:
        pdf.add_page()
        pdf.section_title("Agent Plans")

        score_map: dict[str, float] = {}
        for ev in run.plan_evaluations:
            score_map[ev.plan_id] = ev.overall_score

        for plan in run.plans:
            pdf.safe_page_break(50)
            score = score_map.get(plan.plan_id)
            score_str = f" (Score: {score:.2f})" if score is not None else ""
            pdf.sub_title(f"{plan.display_name}{score_str}")
            pdf.body_text(plan.summary)

            if plan.architecture:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, "Architecture", new_x="LMARGIN", new_y="NEXT")
                pdf.bullet_list(plan.architecture)

            if plan.strengths:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, "Strengths", new_x="LMARGIN", new_y="NEXT")
                pdf.bullet_list(plan.strengths)

            if plan.weaknesses:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, "Weaknesses", new_x="LMARGIN", new_y="NEXT")
                pdf.bullet_list(plan.weaknesses)

            pdf.ln(4)

    # ════════════════════════════════════════
    # Debate Timeline
    # ════════════════════════════════════════
    if run.debate_rounds:
        pdf.add_page()
        pdf.section_title("Debate Timeline")

        agent_names: dict[str, str] = {}
        for a in run.agents:
            agent_names[a.agent_id] = a.display_name

        for rnd in run.debate_rounds:
            pdf.safe_page_break(40)
            agenda = rnd.agenda
            title = agenda.title if agenda else (rnd.round_type.value if rnd.round_type else "Round")
            pdf.sub_title(f"Round {rnd.index}: {title}")

            if agenda and agenda.question:
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(*_GREY)
                pdf.multi_cell(0, 5, _wrap(agenda.question, 100))
                pdf.ln(2)

            # Messages
            for msg in rnd.messages:
                pdf.safe_page_break(25)
                name = agent_names.get(msg.agent_id, msg.agent_id)
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(*_STONE)
                pdf.cell(0, 6, f"{name}  (novelty {msg.novelty_score:.2f})", new_x="LMARGIN", new_y="NEXT")
                pdf.body_text(msg.content)

            # Round summary
            summary = rnd.summary
            if summary and summary.key_disagreements:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, "Key Disagreements", new_x="LMARGIN", new_y="NEXT")
                pdf.bullet_list(summary.key_disagreements)

            # Adjudication
            adj = rnd.adjudication
            if adj and adj.resolution:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, "Judge Resolution", new_x="LMARGIN", new_y="NEXT")
                pdf.body_text(adj.resolution)

            if adj and adj.adopted_arguments:
                pdf.set_font("Helvetica", "BI", 9)
                pdf.set_text_color(*_GREY)
                pdf.cell(0, 5, f"Adopted Arguments ({len(adj.adopted_arguments)})", new_x="LMARGIN", new_y="NEXT")
                for adopted in adj.adopted_arguments:
                    pdf.safe_page_break(15)
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*_DARK)
                    pdf.multi_cell(0, 5, _wrap(f"[{adopted.claim_kind}] {adopted.display_name}: {adopted.summary}", 100))
                    pdf.ln(1)

            pdf.ln(4)

    # ════════════════════════════════════════
    # Usage Report
    # ════════════════════════════════════════
    by_actor = run.budget_ledger.by_actor
    if by_actor:
        pdf.safe_page_break(40)
        pdf.section_title("Token Usage")

        agent_names_map: dict[str, str] = {a.agent_id: a.display_name for a in run.agents}

        # Table header
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_WHITE)
        pdf.set_fill_color(*_STONE)
        pdf.cell(60, 7, "Actor", border=1, fill=True)
        pdf.cell(35, 7, "Prompt", border=1, fill=True, align="R")
        pdf.cell(35, 7, "Completion", border=1, fill=True, align="R")
        pdf.cell(35, 7, "Total", border=1, fill=True, align="R")
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK)
        for actor_id, usage in by_actor.items():
            label = agent_names_map.get(actor_id, actor_id)
            pdf.cell(60, 7, label[:30], border=1)
            pdf.cell(35, 7, f"{usage.prompt_tokens:,}", border=1, align="R")
            pdf.cell(35, 7, f"{usage.completion_tokens:,}", border=1, align="R")
            pdf.cell(35, 7, f"{usage.total_tokens:,}", border=1, align="R")
            pdf.ln()

        # Totals row
        t = run.budget_ledger.total
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(60, 7, "TOTAL", border=1)
        pdf.cell(35, 7, f"{t.prompt_tokens:,}", border=1, align="R")
        pdf.cell(35, 7, f"{t.completion_tokens:,}", border=1, align="R")
        pdf.cell(35, 7, f"{t.total_tokens:,}", border=1, align="R")
        pdf.ln(10)

    # ── Output ──
    return bytes(pdf.output())
