"""Colosseum Monitor — Real-time tmux dashboard for debate progress.

Reads events from the JSONL event log and renders a live-updating
terminal dashboard showing phase, agents, budget, judge decisions, etc.
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from collections import deque
from datetime import datetime, timezone

from colosseum.services.event_bus import EventReader  # noqa: E402

# ── ANSI codes ─────────────────────────────────────────────

BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"
GOLD = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
WHITE = "\033[37m"
BG_BLACK = "\033[40m"
CLEAR = "\033[2J\033[H"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"

# Phase ordering for the progress bar
PHASE_ORDER = ["init", "context", "planning", "debate", "verdict", "complete"]
PHASE_LABELS = {
    "init": "INIT",
    "context": "CONTEXT",
    "planning": "PLANNING",
    "debate": "DEBATE",
    "verdict": "VERDICT",
    "complete": "COMPLETE",
}

# ── Monitor state ──────────────────────────────────────────


class MonitorState:
    """Tracks the current state of a debate from events."""

    def __init__(self) -> None:
        self.run_id: str = ""
        self.topic: str = ""
        self.status: str = "pending"
        self.phase: str = "init"
        self.completed_phases: set[str] = set()
        self.started_at: datetime | None = None

        # Agents
        self.agents: dict[str, dict] = {}  # agent_id -> {name, status, tokens}

        # Budget
        self.total_tokens: int = 0
        self.token_budget: int = 80000
        self.rounds_done: int = 0
        self.max_rounds: int = 3

        # Judge
        self.last_judge_action: str = ""
        self.last_judge_confidence: float = 0.0
        self.last_judge_disagreement: float = 0.0
        self.last_judge_focus: str = ""
        self.last_judge_next_round: str = ""

        # Round
        self.current_round: int = 0
        self.current_round_type: str = ""

        # Verdict
        self.verdict_type: str = ""
        self.verdict_winners: list[str] = []
        self.verdict_confidence: float = 0.0
        self.final_answer: str = ""

        # Event log (last N)
        self.event_log: deque[dict] = deque(maxlen=20)

        # Error
        self.error: str = ""

    def process_event(self, event: dict) -> None:
        etype = event.get("type", "")
        data = event.get("data", {})
        ts = event.get("ts", "")

        if not self.run_id and event.get("run_id"):
            self.run_id = event["run_id"]

        if not self.started_at and ts:
            try:
                self.started_at = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                pass

        self.event_log.append(event)

        if etype == "debate_start":
            self.topic = data.get("topic", self.topic)
            self.token_budget = data.get("token_budget", self.token_budget)
            self.max_rounds = data.get("max_rounds", self.max_rounds)
            agents = data.get("agents", [])
            for a in agents:
                aid = a.get("agent_id", "")
                self.agents[aid] = {
                    "name": a.get("display_name", aid),
                    "status": "ready",
                    "tokens": 0,
                }
            self.phase = "init"
            self.completed_phases.add("init")

        elif etype == "phase":
            phase_name = data.get("phase", "")
            self.status = data.get("status", self.status)
            if phase_name in ("context", "freezing_context"):
                self.phase = "context"
                self.completed_phases.add("init")
            elif phase_name in ("planning", "generating_plans"):
                self.phase = "planning"
                self.completed_phases.update({"init", "context"})
            elif phase_name in ("debate", "debate_round"):
                self.phase = "debate"
                self.completed_phases.update({"init", "context", "planning"})
            elif phase_name in ("verdict", "judging", "rendering_verdict"):
                self.phase = "verdict"
                self.completed_phases.update({"init", "context", "planning", "debate"})
            elif phase_name in ("complete", "completed"):
                self.phase = "complete"
                self.completed_phases.update(PHASE_ORDER)

        elif etype == "agent_planning":
            aid = data.get("agent_id", "")
            name = data.get("display_name", aid)
            if aid not in self.agents:
                self.agents[aid] = {"name": name, "status": "planning...", "tokens": 0}
            else:
                self.agents[aid]["status"] = "planning..."

        elif etype == "plan_ready":
            aid = data.get("agent_id", "")
            name = data.get("display_name", aid)
            if aid not in self.agents:
                self.agents[aid] = {"name": name, "status": "plan ready", "tokens": 0}
            else:
                self.agents[aid]["name"] = name
                self.agents[aid]["status"] = "plan ready"

        elif etype == "plan_scores":
            scores = data.get("scores", {})
            for plan_id, score_info in scores.items():
                aid = score_info.get("agent_id", "")
                if aid in self.agents:
                    self.agents[aid]["score"] = score_info.get("score", 0.0)

        elif etype == "agent_thinking":
            aid = data.get("agent_id", "")
            name = data.get("display_name", aid)
            ri = data.get("round_index", 0)
            if aid in self.agents:
                self.agents[aid]["status"] = f"thinking... (R{ri})"
            else:
                self.agents[aid] = {"name": name, "status": f"thinking... (R{ri})", "tokens": 0}

        elif etype == "agent_message":
            aid = data.get("agent_id", "")
            name = data.get("display_name", aid)
            tokens = data.get("usage", {}).get("total_tokens", 0)
            novelty = data.get("novelty_score", 0)
            if aid in self.agents:
                self.agents[aid]["status"] = f"responded (novelty={novelty:.2f})"
                self.agents[aid]["tokens"] += tokens
            else:
                self.agents[aid] = {"name": name, "status": "responded", "tokens": tokens}
            self.total_tokens += tokens

        elif etype == "round_complete":
            ri = data.get("round_index", data.get("index", 0))
            rt = data.get("round_type", "")
            self.rounds_done = ri
            self.current_round = ri
            self.current_round_type = rt

        elif etype == "judge_decision":
            self.last_judge_action = data.get("action", "")
            self.last_judge_confidence = data.get("confidence", 0.0)
            self.last_judge_disagreement = data.get("disagreement_level", 0.0)
            self.last_judge_focus = data.get("focus", "")
            self.last_judge_next_round = data.get("next_round_type", "")

        elif etype == "debate_round_start":
            ri = data.get("round_index", 0)
            rt = data.get("round_type", "")
            self.current_round = ri
            self.current_round_type = rt
            self.phase = "debate"

        elif etype == "verdict":
            self.verdict_type = data.get("verdict_type", "")
            self.verdict_winners = data.get("winners", [])
            self.verdict_confidence = data.get("confidence", 0.0)
            self.final_answer = data.get("final_answer", "")
            self.phase = "complete"
            self.completed_phases.update(PHASE_ORDER)
            self.status = "completed"

        elif etype == "error":
            self.error = data.get("message", str(data))
            self.status = "failed"

        elif etype == "budget_update":
            self.total_tokens = data.get("total_tokens", self.total_tokens)


# ── Renderer ───────────────────────────────────────────────


def _bar(
    value: float, width: int = 30, filled_char: str = "\u2593", empty_char: str = "\u2591"
) -> str:
    filled = int(value * width)
    filled = min(filled, width)
    return f"{GOLD}{filled_char * filled}{DIM}{empty_char * (width - filled)}{RST}"


def _wrapped_lines(text: str, *, width: int = 58, prefix: str = "  ") -> list[str]:
    """Wrap user-facing copy for the monitor layout."""
    content = str(text or "").strip()
    if not content:
        return []
    return [f"{prefix}{line}" for line in textwrap.wrap(content, width=width)]


def _elapsed(started_at: datetime | None) -> str:
    if not started_at:
        return "--:--"
    delta = datetime.now(timezone.utc) - started_at
    total_s = int(delta.total_seconds())
    if total_s < 0:
        return "0s"
    m, s = divmod(total_s, 60)
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _phase_bar(state: MonitorState) -> str:
    parts = []
    for phase in PHASE_ORDER:
        label = PHASE_LABELS[phase]
        if phase in state.completed_phases and phase != state.phase:
            parts.append(f"{GREEN}{label}{RST}")
        elif phase == state.phase:
            parts.append(f"{GOLD}{BOLD}{label}{RST}")
        else:
            parts.append(f"{DIM}{label}{RST}")
    return f"  {DIM}---{RST}  ".join(parts)


def _format_ts(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str)
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return "??:??:??"


def _event_line(event: dict) -> str:
    ts = _format_ts(event.get("ts", ""))
    etype = event.get("type", "?")
    data = event.get("data", {})

    # Color by type
    type_colors = {
        "phase": GOLD,
        "agent_planning": CYAN,
        "plan_ready": GREEN,
        "agent_thinking": CYAN,
        "agent_message": GREEN,
        "round_complete": BLUE,
        "judge_decision": MAGENTA,
        "debate_round_start": GOLD,
        "verdict": GOLD,
        "error": RED,
        "debate_start": WHITE,
        "plan_scores": DIM,
        "budget_update": DIM,
    }
    color = type_colors.get(etype, DIM)

    # Short description
    desc = ""
    if etype == "phase":
        desc = data.get("message", data.get("phase", ""))
    elif etype == "agent_planning":
        desc = f"{data.get('display_name', '?')} crafting strategy..."
    elif etype == "plan_ready":
        name = data.get("display_name", "?")
        summary = data.get("summary", "")[:60]
        desc = f"{name}: plan ready"
        if summary:
            desc += f" - {summary}"
    elif etype == "agent_thinking":
        desc = f"{data.get('display_name', '?')} thinking... (R{data.get('round_index', '?')})"
    elif etype == "agent_message":
        name = data.get("display_name", "?")
        tok = data.get("usage", {}).get("total_tokens", 0)
        nov = data.get("novelty_score", 0)
        desc = f"{name} responded ({tok:,} tok, novelty={nov:.2f})"
    elif etype == "round_complete":
        ri = data.get("round_index", data.get("index", "?"))
        rt = data.get("round_type", "")
        desc = f"Round {ri} complete ({rt})"
    elif etype == "judge_decision":
        action = data.get("action", "?")
        conf = data.get("confidence", 0)
        desc = f"{action.upper()} (conf={conf:.2f})"
        nrt = data.get("next_round_type", "")
        if nrt:
            desc += f" -> {nrt}"
    elif etype == "verdict":
        vtype = data.get("verdict_type", "?")
        winners = data.get("winners", [])
        desc = f"{vtype.upper()}: {', '.join(winners)}"
    elif etype == "debate_start":
        desc = data.get("topic", "")[:60]
    elif etype == "debate_round_start":
        ri = data.get("round_index", "?")
        rt = data.get("round_type", "")
        desc = f"Round {ri}: {rt}"
    elif etype == "error":
        desc = data.get("message", "")[:60]
    elif etype == "plan_scores":
        desc = "Plan evaluations ready"
    elif etype == "budget_update":
        desc = f"{data.get('total_tokens', 0):,} tokens used"
    else:
        desc = str(data)[:60] if data else ""

    etype_short = etype[:14].ljust(14)
    return f"  {DIM}{ts}{RST}  {color}{etype_short}{RST}  {desc[:60]}"


def render(state: MonitorState, term_height: int = 0) -> str:
    """Render the monitor dashboard to a string."""
    if term_height <= 0:
        try:
            term_height = os.get_terminal_size().lines
        except OSError:
            term_height = 40

    lines: list[str] = []

    # Header
    lines.append("")
    lines.append(f"  {GOLD}{BOLD}  COLOSSEUM MONITOR{RST}")
    lines.append(f"  {DIM}{'=' * 58}{RST}")

    # Run info
    run_short = state.run_id[:12] + "..." if len(state.run_id) > 12 else state.run_id
    topic_short = state.topic[:50] + "..." if len(state.topic) > 50 else state.topic
    status_colors = {
        "pending": DIM,
        "planning": CYAN,
        "debating": GOLD,
        "completed": GREEN,
        "failed": RED,
    }
    sc = status_colors.get(state.status, DIM)
    lines.append(
        f"  Run:    {DIM}{run_short}{RST}    Elapsed: {BOLD}{_elapsed(state.started_at)}{RST}"
    )
    if topic_short:
        lines.append(f"  Topic:  {BOLD}{topic_short}{RST}")
    lines.append(f"  Status: {sc}{BOLD}{state.status.upper()}{RST}")

    # Phase progress
    lines.append("")
    lines.append(f"  {DIM}-- Progress {'─' * 46}{RST}")
    lines.append(f"  {_phase_bar(state)}")

    # Budget
    lines.append("")
    lines.append(f"  {DIM}-- Budget {'─' * 48}{RST}")
    token_pct = state.total_tokens / state.token_budget if state.token_budget > 0 else 0
    lines.append(
        f"  Tokens: {_bar(token_pct)}  {state.total_tokens:,} / {state.token_budget:,} ({token_pct:.0%})"
    )
    round_pct = state.rounds_done / state.max_rounds if state.max_rounds > 0 else 0
    round_blocks = int(round_pct * 5)
    round_bar = f"{GOLD}{'█' * round_blocks}{DIM}{'░' * (5 - round_blocks)}{RST}"
    lines.append(f"  Rounds: {round_bar}  {state.rounds_done} / {state.max_rounds}")
    if state.current_round_type:
        lines.append(f"  Current: {BOLD}{state.current_round_type.upper()}{RST}")

    # Agents
    lines.append("")
    lines.append(f"  {DIM}-- Agents {'─' * 48}{RST}")
    if state.agents:
        for aid, info in state.agents.items():
            name = info.get("name", aid)
            status = info.get("status", "idle")
            tokens = info.get("tokens", 0)

            if "thinking" in status:
                dot = f"{GOLD}*{RST}"
                status_color = GOLD
            elif "ready" in status or "responded" in status:
                dot = f"{GREEN}*{RST}"
                status_color = GREEN
            elif "planning" in status:
                dot = f"{CYAN}*{RST}"
                status_color = CYAN
            else:
                dot = f"{DIM}*{RST}"
                status_color = DIM

            tok_str = f"{tokens:,} tok" if tokens > 0 else ""
            score = info.get("score")
            score_str = f"  score={score:.2f}" if score is not None else ""
            lines.append(
                f"  {dot} {BOLD}{name:<22}{RST}  {status_color}{status:<24}{RST}  {DIM}{tok_str}{score_str}{RST}"
            )
    else:
        lines.append(f"  {DIM}No agents registered yet{RST}")

    # Judge
    lines.append("")
    lines.append(f"  {DIM}-- Judge {'─' * 49}{RST}")
    if state.last_judge_action:
        action_colors = {
            "finalize": RED,
            "continue_debate": GREEN,
            "request_revision": BLUE,
        }
        jc = action_colors.get(state.last_judge_action, DIM)
        lines.append(
            f"  Decision: {jc}{BOLD}{state.last_judge_action.upper()}{RST}  "
            f"{DIM}conf={state.last_judge_confidence:.2f}  "
            f"disagree={state.last_judge_disagreement:.2f}{RST}"
        )
        if state.last_judge_focus:
            lines.append(f"  Focus:    {state.last_judge_focus[:55]}")
        if state.last_judge_next_round:
            lines.append(f"  Next:     {BOLD}{state.last_judge_next_round.upper()}{RST}")
    else:
        lines.append(f"  {DIM}Waiting for first judge decision...{RST}")

    # Verdict (if done)
    if state.verdict_type:
        lines.append("")
        lines.append(f"  {DIM}-- Verdict {'─' * 47}{RST}")
        vc = MAGENTA if state.verdict_type == "merged" else GOLD
        lines.append(
            f"  {vc}{BOLD}{state.verdict_type.upper()}{RST}: {', '.join(state.verdict_winners)}"
        )
        if state.final_answer:
            lines.append(f"  {CYAN}Final Answer:{RST}")
            lines.extend(_wrapped_lines(state.final_answer, prefix="    "))
        lines.append(f"  {DIM}Confidence: {state.verdict_confidence:.2f}{RST}")

    # Error
    if state.error:
        lines.append("")
        lines.append(f"  {RED}{BOLD}ERROR: {state.error[:60]}{RST}")

    # Event log
    lines.append("")
    lines.append(f"  {DIM}-- Events {'─' * 48}{RST}")

    # Calculate available space for events
    header_lines = len(lines) + 3  # +3 for footer
    available = max(4, term_height - header_lines - 1)
    recent_events = list(state.event_log)[-available:]

    if recent_events:
        for ev in recent_events:
            lines.append(_event_line(ev))
    else:
        lines.append(f"  {DIM}Waiting for events...{RST}")

    # Footer
    lines.append("")
    lines.append(f"  {DIM}Press Ctrl+C to detach (debate continues in background){RST}")

    return "\n".join(lines)


def find_latest_run() -> str | None:
    """Find the most recently updated run ID."""
    from colosseum.core.config import ARTIFACT_ROOT

    if not ARTIFACT_ROOT.exists():
        return None
    candidates = []
    for run_json in ARTIFACT_ROOT.glob("*/events.jsonl"):
        candidates.append((run_json.stat().st_mtime, run_json.parent.name))
    if not candidates:
        # Fallback: check run.json
        for run_json in ARTIFACT_ROOT.glob("*/run.json"):
            candidates.append((run_json.stat().st_mtime, run_json.parent.name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def run_monitor(run_id: str | None = None, poll_interval: float = 0.3) -> None:
    """Main monitor loop. Reads events and refreshes the display."""
    from colosseum.core.config import ARTIFACT_ROOT

    # Resolve run_id
    if not run_id:
        # Wait for a run to appear
        print(f"{GOLD}Waiting for a debate to start...{RST}")
        for _ in range(300):  # Wait up to ~90 seconds
            run_id = find_latest_run()
            if run_id:
                break
            time.sleep(poll_interval)
        if not run_id:
            print(f"{RED}No active debate found.{RST}")
            return

    event_path = ARTIFACT_ROOT / run_id / "events.jsonl"

    # Wait for event file to appear
    if not event_path.exists():
        print(f"{GOLD}Waiting for events from run {run_id[:12]}...{RST}")
        for _ in range(120):
            if event_path.exists():
                break
            time.sleep(poll_interval)
        if not event_path.exists():
            print(f"{RED}No events file found for run {run_id[:12]}.{RST}")
            return

    reader = EventReader(event_path)
    state = MonitorState()
    state.run_id = run_id

    # Hide cursor for cleaner display
    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.flush()

    try:
        while True:
            new_events = reader.read_new()
            for ev in new_events:
                state.process_event(ev)

            # Render
            sys.stdout.write(CLEAR)
            sys.stdout.write(render(state))
            sys.stdout.flush()

            # Stop if debate is done
            if state.status in ("completed", "failed"):
                time.sleep(1)  # One final refresh
                sys.stdout.write(CLEAR)
                sys.stdout.write(render(state))
                sys.stdout.flush()
                # Wait a bit so user can see the final state
                time.sleep(3)
                break

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.write("\n")
        sys.stdout.flush()


if __name__ == "__main__":
    _run_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_monitor(run_id=_run_id)
