#!/usr/bin/env python3
"""Live pretty-print a Colosseum QA gladiator's stream.jsonl or mediated_trace.jsonl.

Usage:
    qa_watch.py <jsonl_path> claude     # for ClaudeQAExecutor stream.jsonl
    qa_watch.py <jsonl_path> mediated   # for MediatedQAExecutor mediated_trace.jsonl
"""
from __future__ import annotations

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


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: qa_watch.py <jsonl_path> [claude|mediated]")
        sys.exit(1)
    path = Path(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else "claude"

    print(f"{BOLD}== watching {path.name} ({mode}) =={RST}", flush=True)

    seen = 0
    while True:
        if path.exists():
            try:
                with path.open(encoding="utf-8") as fh:
                    lines = fh.readlines()
            except Exception:
                time.sleep(1)
                continue
            new_lines = lines[seen:]
            for line in new_lines:
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
            seen = len(lines)
            sys.stdout.flush()
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
