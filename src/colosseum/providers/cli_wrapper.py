#!/usr/bin/env python3
"""Universal CLI wrapper for Colosseum provider integration.

This script bridges Colosseum's JSON protocol with CLI-based AI tools.
It reads the input from COLOSSEUM_INPUT_PATH, calls the appropriate CLI,
and outputs structured JSON to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


def read_input() -> dict:
    input_path = os.environ.get("COLOSSEUM_INPUT_PATH")
    if not input_path:
        return {"operation": "unknown", "instructions": "", "metadata": {}}
    with open(input_path, encoding="utf-8") as f:
        return json.load(f)


def build_prompt(data: dict) -> str:
    operation = data.get("operation", "plan")
    instructions = data.get("instructions", "")
    metadata = data.get("metadata", {})

    persona = metadata.get("persona")
    persona_preamble = ""
    if persona:
        persona_preamble = f"=== YOUR PERSONA ===\n{persona}\n=== END PERSONA ===\n\n"

    image_note = build_image_note(metadata)
    image_preamble = f"{image_note}\n\n" if image_note else ""

    search_policy = metadata.get("search_policy")
    search_preamble = f"Search policy: {search_policy}\n\n" if search_policy else ""

    prompt = f"{persona_preamble}{image_preamble}{search_preamble}Operation: {operation}\n\n{instructions}\n\n"
    prompt += "Respond with valid JSON containing these fields:\n"

    if operation == "plan":
        prompt += "summary, evidence_basis (list), assumptions (list), architecture (list), implementation_strategy (list), "
        prompt += "risks (list of {title, severity, mitigation}), strengths (list), weaknesses (list), "
        prompt += "trade_offs (list), open_questions (list)"
    elif operation == "debate":
        prompt += "content, critique_points (list of {category, text, target_plan_ids, evidence}), "
        prompt += "defense_points (list of {category, text, target_plan_ids, evidence}), "
        prompt += "concessions (list), hybrid_suggestions (list), referenced_plan_ids (list)"
        prompt += "\n\nIMPORTANT: You are in a debate. Directly respond to other participants' arguments. "
        prompt += "Reference specific points they made. Rebut what you disagree with, concede well-supported points."
    elif operation == "judge":
        prompt += "action (continue_debate|finalize|request_revision), confidence (float), "
        prompt += "reasoning, disagreement_level (float), expected_value_of_next_round (float), "
        prompt += "next_round_type, focus_areas (list)"
    elif operation == "synthesis":
        prompt += "summary, evidence_basis (list), assumptions (list), architecture (list), implementation_strategy (list), "
        prompt += "risks (list of {title, severity, mitigation}), strengths (list), weaknesses (list), "
        prompt += "trade_offs (list), open_questions (list)"

    prompt += "\n\nRule: prefer objective evidence from the provided context bundle. If a claim is inferential or uncertain, say so."
    prompt += "\n\nReturn ONLY valid JSON, no markdown fences or extra text."
    return prompt


def build_image_note(metadata: dict) -> str:
    image_inputs = metadata.get("image_inputs") or []
    if not image_inputs:
        return ""
    entries = []
    for item in image_inputs[:4]:
        label = item.get("label") or "unnamed image"
        media_type = item.get("media_type") or "image"
        checksum = str(item.get("checksum") or "")[:8]
        size_bytes = item.get("size_bytes") or 0
        size_text = f"{round(size_bytes / 1024, 1)} KB" if size_bytes else "size unknown"
        entries.append(f"- {label} ({media_type}, {size_text}, checksum {checksum})")
    if len(image_inputs) > len(entries):
        entries.append(f"- +{len(image_inputs) - len(entries)} more image(s)")
    return (
        "Shared visual context is available in the Colosseum input package.\n"
        "Use attached multimodal inputs if your CLI supports them. Do not invent visual facts if it does not.\n"
        + "\n".join(entries)
    )


def call_claude(prompt: str, model: str = "") -> str:
    """Call Claude Code CLI: claude -p <prompt> [--model <model>]

    Uses --output-format json which wraps the response in
    {"type":"result","result":"<actual text>"}.  We unwrap it here so
    parse_response receives the raw model text.
    """
    env = {**os.environ, "CLAUDECODE": ""}  # avoid nested-session guard
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--dangerously-skip-permissions"]
    if model:
        cmd.extend(["--model", model])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=280, env=env)
    raw = result.stdout.strip()

    # Unwrap Claude CLI JSON envelope: {"type":"result","result":"<text>"}
    if raw:
        try:
            envelope = json.loads(raw)
            if isinstance(envelope, dict) and "result" in envelope:
                inner = envelope["result"]
                if isinstance(inner, str):
                    return inner.strip()
                # result might already be a dict
                return json.dumps(inner)
        except json.JSONDecodeError:
            pass

    # Fallback: plain text mode
    if result.returncode != 0 or not raw:
        cmd2 = ["claude", "-p", prompt]
        if model:
            cmd2.extend(["--model", model])
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=280, env=env)
        raw = result.stdout.strip()

    return raw


def call_codex(prompt: str, model: str = "") -> str:
    """Call OpenAI Codex CLI non-interactively via `codex exec`.

    Uses -o to write clean output to a temp file, since stdout mixes
    agent logs with the actual response.
    """
    import tempfile
    out_file = tempfile.mktemp(suffix=".txt", prefix="codex_")
    cmd = [
        "codex", "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o", out_file,
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)

    # Read clean output from file
    raw = ""
    try:
        with open(out_file, encoding="utf-8") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        pass
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    if raw:
        return raw

    # Fallback: parse stdout (last non-empty line is usually the response)
    if result.stdout.strip():
        lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        if lines:
            return lines[-1].strip()

    return ""


def call_gemini(prompt: str, model: str = "") -> str:
    """Call Gemini CLI: gemini [--model <model>] -p <prompt> --yolo"""
    cmd = ["gemini", "--yolo"]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", prompt])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)
    raw = result.stdout.strip()

    # If stdout is empty, check stderr for clues and retry without --yolo
    if not raw:
        stderr = result.stderr.strip()
        # Retry without --yolo flag in case it's unsupported
        cmd_retry = ["gemini"]
        if model:
            cmd_retry.extend(["--model", model])
        cmd_retry.extend(["-p", prompt])
        result2 = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=280)
        raw = result2.stdout.strip()

        # If still empty, return a structured error so it propagates clearly
        if not raw:
            combined_err = stderr or result2.stderr.strip()
            return json.dumps({
                "content": f"Gemini CLI returned empty output. stderr: {combined_err[:300]}",
                "error": "empty_response",
            })

    return raw


def call_ollama(prompt: str, model: str = "llama3.3") -> str:
    """Call Ollama: ollama run <model> <prompt>"""
    result = subprocess.run(
        ["ollama", "run", model, prompt],
        capture_output=True, text=True, timeout=580
    )
    return result.stdout.strip()


def parse_response(raw: str) -> dict:
    """Try to extract JSON from the response."""
    raw = raw.strip()
    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown code block
    if "```json" in raw:
        start = raw.index("```json") + 7
        end = raw.index("```", start)
        try:
            return json.loads(raw[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass
    if "```" in raw:
        start = raw.index("```") + 3
        end = raw.index("```", start)
        try:
            return json.loads(raw[start:end].strip())
        except (json.JSONDecodeError, ValueError):
            pass
    # Return as content string
    return {"content": raw}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True, choices=["claude", "codex", "gemini", "ollama", "huggingface"])
    parser.add_argument("--model", default="", help="Model name to pass to the CLI tool")
    args = parser.parse_args()

    data = read_input()
    prompt = build_prompt(data)
    # Model priority: CLI arg > input metadata > data model field
    model = args.model or data.get("metadata", {}).get("model") or data.get("model", "")

    try:
        if args.provider == "claude":
            raw = call_claude(prompt, model=model)
        elif args.provider == "codex":
            raw = call_codex(prompt, model=model)
        elif args.provider == "gemini":
            raw = call_gemini(prompt, model=model)
        elif args.provider in ("ollama", "huggingface"):
            raw = call_ollama(prompt, model=model or "llama3.3")
        else:
            raw = '{"content": "Unsupported provider"}'
    except FileNotFoundError:
        print(json.dumps({
            "content": f"CLI tool '{args.provider}' not found. Please install it first.",
            "error": f"{args.provider} command not found in PATH"
        }))
        sys.exit(0)
    except subprocess.TimeoutExpired:
        print(json.dumps({
            "content": f"CLI tool '{args.provider}' timed out.",
            "error": "timeout"
        }))
        sys.exit(0)

    parsed = parse_response(raw)
    if "content" not in parsed:
        parsed["content"] = json.dumps(parsed, indent=2)

    print(json.dumps(parsed))


if __name__ == "__main__":
    main()
