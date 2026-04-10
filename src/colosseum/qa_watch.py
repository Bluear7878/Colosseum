#!/usr/bin/env python3
"""Live pretty-print a Colosseum QA gladiator's stream.jsonl or mediated_trace.jsonl.

Usage:
    qa_watch.py <jsonl_path> claude [--exit-when-done]
    qa_watch.py <jsonl_path> mediated [--exit-when-done]

`--exit-when-done` makes the watcher self-terminate once the QA run's
`qa_run.json` reports a terminal status (`completed` or `failed`). The
run.json path is inferred from the jsonl path:

    .colosseum/qa/<run_id>/gladiators/<gid>/{stream,mediated_trace}.jsonl
                                           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                           jsonl is parents[0]
    .colosseum/qa/<run_id>/qa_run.json       <-- parents[2] / qa_run.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

CYAN = "\033[36m"
YEL = "\033[33m"
GRN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
RST = "\033[0m"

# When --exit-when-done is active, how long (seconds) to keep tailing
# the jsonl after we observe a terminal run status, so the final events
# land in the pane before it closes.
TERMINAL_GRACE_SECONDS = 3.0


def pretty_claude(ev: dict) -> None:
    t = ev.get("type", "")
    if t == "assistant":
        msg = ev.get("message") or {}
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                txt = (block.get("text") or "").strip()
                if txt:
                    print(f"{CYAN}[text]{RST} {txt[:240]}")
            elif block.get("type") == "tool_use":
                name = block.get("name", "?")
                inp_obj = block.get("input") or {}
                summary = ""
                if isinstance(inp_obj, dict):
                    if "command" in inp_obj:
                        summary = str(inp_obj["command"])[:140]
                    elif "file_path" in inp_obj:
                        summary = str(inp_obj["file_path"])[:140]
                    elif "path" in inp_obj:
                        summary = str(inp_obj["path"])[:140]
                    elif "pattern" in inp_obj:
                        summary = str(inp_obj["pattern"])[:140]
                    elif "description" in inp_obj:
                        summary = str(inp_obj["description"])[:140]
                    elif "subagent_type" in inp_obj:
                        summary = f"subagent={inp_obj.get('subagent_type','?')} {str(inp_obj.get('description',''))[:80]}"
                    else:
                        summary = json.dumps(inp_obj)[:140]
                print(f"{YEL}[tool {name}]{RST} {summary}")
    elif t == "user":
        msg = ev.get("message") or {}
        for block in msg.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, str):
                    print(f"{DIM}[result] {content[:180]}{RST}")
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            txt = c.get("text", "")
                            if txt:
                                print(f"{DIM}[result] {txt[:180]}{RST}")
    elif t == "result":
        cost = ev.get("total_cost_usd") or ev.get("cost_usd") or 0
        usage = ev.get("usage") or {}
        print(
            f"{GRN}[done] cost=${cost:.4f} "
            f"in={usage.get('input_tokens', 0)} "
            f"out={usage.get('output_tokens', 0)} "
            f"cache_in={usage.get('cache_creation_input_tokens', 0)} "
            f"cache_read={usage.get('cache_read_input_tokens', 0)}{RST}"
        )
    elif t == "system":
        sub = ev.get("subtype", "")
        if sub == "init":
            print(f"{DIM}[system init session={ev.get('session_id', '?')[:8]}]{RST}")


def pretty_mediated(ev: dict) -> None:
    idx = ev.get("index", "?")
    action = ev.get("action") or {}
    kind = action.get("action", "?")
    detail = (
        action.get("command")
        or action.get("path")
        or action.get("purpose")
        or ""
    )
    obs = ev.get("observation_preview") or ""
    print(f"{YEL}[#{idx} {kind}]{RST} {str(detail)[:140]}")
    if obs:
        print(f"  {DIM}{obs[:240]}{RST}")


def _infer_run_json_path(jsonl_path: Path) -> Path | None:
    """Return the qa_run.json sibling for a gladiator jsonl path.

    .colosseum/qa/<run>/gladiators/<gid>/stream.jsonl
                        -> parents[0] = <gid> dir
                        -> parents[1] = gladiators/
                        -> parents[2] = <run>/
                        -> parents[2] / qa_run.json
    """
    try:
        return jsonl_path.parents[2] / "qa_run.json"
    except IndexError:
        return None


def _read_run_status(run_json_path: Path) -> str | None:
    """Return the current status string from qa_run.json, or None on error."""
    try:
        data = json.loads(run_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    return status if isinstance(status, str) else None


def _render_lines(lines: list[str], mode: str) -> None:
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            if mode == "claude":
                pretty_claude(ev)
            else:
                pretty_mediated(ev)
        except Exception as exc:
            print(f"{RED}[render error] {exc}{RST}")


def watch(path: Path, mode: str, exit_when_done: bool) -> int:
    """Tail `path` and pretty-print new events forever (or until the run's
    qa_run.json reports a terminal status when `exit_when_done` is True).
    """
    print(f"{BOLD}== watching {path.name} ({mode}) =={RST}", flush=True)

    run_json_path = _infer_run_json_path(path) if exit_when_done else None
    if exit_when_done and run_json_path:
        print(f"{DIM}   auto-exit when {run_json_path} reports completed/failed{RST}", flush=True)

    seen = 0
    terminal_first_seen_at: float | None = None

    while True:
        if path.exists():
            try:
                with path.open(encoding="utf-8") as fh:
                    lines = fh.readlines()
            except OSError:
                time.sleep(1.0)
                continue
            _render_lines(lines[seen:], mode)
            seen = len(lines)
            sys.stdout.flush()

        # Check run status for auto-exit.
        if exit_when_done and run_json_path is not None:
            status = _read_run_status(run_json_path)
            if status in ("completed", "failed"):
                if terminal_first_seen_at is None:
                    terminal_first_seen_at = time.monotonic()
                    print(
                        f"{GRN}[QA run {status}] — watcher will exit in "
                        f"{TERMINAL_GRACE_SECONDS:.0f}s{RST}",
                        flush=True,
                    )
                elif time.monotonic() - terminal_first_seen_at >= TERMINAL_GRACE_SECONDS:
                    # One last drain in case the jsonl grew in the grace window.
                    if path.exists():
                        try:
                            with path.open(encoding="utf-8") as fh:
                                lines = fh.readlines()
                            _render_lines(lines[seen:], mode)
                            seen = len(lines)
                            sys.stdout.flush()
                        except OSError:
                            pass
                    print(f"{DIM}[watcher exited]{RST}", flush=True)
                    return 0

        time.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser(prog="qa_watch")
    parser.add_argument("jsonl_path", help="Path to gladiator stream.jsonl or mediated_trace.jsonl")
    parser.add_argument(
        "mode",
        nargs="?",
        default="claude",
        choices=("claude", "mediated"),
        help="Which schema to pretty-print (default: claude)",
    )
    parser.add_argument(
        "--exit-when-done",
        action="store_true",
        default=False,
        help="Self-exit once the QA run's qa_run.json reports completed/failed",
    )
    args = parser.parse_args()
    return watch(Path(args.jsonl_path), args.mode, args.exit_when_done)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
