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


def get_subprocess_timeout() -> float | None:
    """Read COLOSSEUM_TIMEOUT env var. '0' or absent → None (no limit)."""
    raw = os.environ.get("COLOSSEUM_TIMEOUT", "")
    if not raw:
        return None
    val = int(raw)
    return None if val == 0 else float(val)


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

    # Surface task title prominently so the model cannot ignore the topic
    task_title = metadata.get("task_title", "")
    task_preamble = (
        f"=== DEBATE TOPIC ===\n{task_title}\n=== END TOPIC ===\n\n" if task_title else ""
    )

    # Enforce response language as the very first instruction
    response_language = metadata.get("response_language", "")
    if response_language and response_language != "auto":
        lang_rule = (
            f"MANDATORY LANGUAGE: Write your ENTIRE response in {response_language}. "
            f"Every field, every sentence must be in {response_language}. No other language permitted.\n\n"
        )
    else:
        lang_rule = ""

    prompt = f"{lang_rule}{persona_preamble}{task_preamble}{image_preamble}{search_preamble}Operation: {operation}\n\n{instructions}\n\n"
    prompt += "Respond with valid JSON containing these fields:\n"

    if operation == "plan":
        prompt += "summary, evidence_basis (list), assumptions (list), architecture (list), implementation_strategy (list), "
        prompt += (
            "risks (list of {title, severity, mitigation}), strengths (list), weaknesses (list), "
        )
        prompt += "trade_offs (list), open_questions (list)"
        prompt += "\n\nIMPORTANT: Every field must be strictly relevant to the debate topic above. "
        prompt += "Do not include generic content or examples unrelated to this specific task."
    elif operation == "debate":
        prompt += "content, critique_points (list of {category, text, target_plan_ids, evidence}), "
        prompt += "defense_points (list of {category, text, target_plan_ids, evidence}), "
        prompt += "concessions (list), hybrid_suggestions (list), referenced_plan_ids (list)"
        prompt += "\n\nIMPORTANT: You are in a structured evidence-first debate. "
        prompt += "Every argument must be directly relevant to the debate topic. "
        prompt += (
            "Directly respond to other participants' specific arguments — reference them by name. "
        )
        prompt += "Rebut what you disagree with, concede well-supported points. "
        prompt += "Evidence quality matters more than rhetoric: cite the frozen context or state uncertainty. "
        prompt += "Do not introduce off-topic content or generic advice unrelated to this task."
    elif operation == "judge":
        prompt += "action (continue_debate|finalize|request_revision), confidence (float), "
        prompt += "reasoning, disagreement_level (float), expected_value_of_next_round (float), "
        prompt += "next_round_type, focus_areas (list)"
        prompt += "\n\nIMPORTANT: Your focus_areas and reasoning must be directly tied to the debate topic. "
        prompt += "Only continue the debate if agents are producing new, topic-relevant evidence."
    elif operation in ("synthesis", "report_synthesis"):
        prompt += "summary, evidence_basis (list), assumptions (list), architecture (list), implementation_strategy (list), "
        prompt += (
            "risks (list of {title, severity, mitigation}), strengths (list), weaknesses (list), "
        )
        prompt += "trade_offs (list), open_questions (list)"
        prompt += "\n\nIMPORTANT: The synthesis must be strictly focused on the debate topic. "
        prompt += "Select only the strongest evidence-backed ideas from the debate. "
        prompt += "Do not include generic filler or content unrelated to this specific task."

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
    sp_timeout = get_subprocess_timeout()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=sp_timeout, env=env)
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
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=sp_timeout, env=env)
        raw = result.stdout.strip()

    return raw


def call_codex(prompt: str, model: str = "") -> str:
    """Call OpenAI Codex CLI non-interactively via `codex exec`.

    Uses -o to write clean output to a temp file, since stdout mixes
    agent logs with the actual response.
    """
    import tempfile

    fd, out_file = tempfile.mkstemp(suffix=".txt", prefix="codex_")
    os.close(fd)
    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "-o",
        out_file,
    ]
    if model:
        cmd.extend(["--model", model])
    cmd.append(prompt)

    sp_timeout = get_subprocess_timeout()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=sp_timeout)

    # Read clean output from file
    raw = ""
    try:
        with open(out_file, encoding="utf-8") as f:
            raw = f.read().strip()
    except FileNotFoundError:
        pass
    finally:
        try:
            os.unlink(out_file)
        except OSError:
            pass

    if raw:
        return raw

    # Fallback: parse stdout (last non-empty line is usually the response)
    if result.stdout.strip():
        lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
        if lines:
            return lines[-1].strip()

    return ""


def call_gemini(prompt: str, model: str = "") -> str:
    """Call Gemini CLI: gemini [--model <model>] -p <prompt> --yolo"""
    sp_timeout = get_subprocess_timeout()
    cmd = ["gemini", "--yolo"]
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", prompt])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=sp_timeout)
    raw = result.stdout.strip()

    # If stdout is empty, check stderr for clues and retry without --yolo
    if not raw:
        stderr = result.stderr.strip()
        # Retry without --yolo flag in case it's unsupported
        cmd_retry = ["gemini"]
        if model:
            cmd_retry.extend(["--model", model])
        cmd_retry.extend(["-p", prompt])
        result2 = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=sp_timeout)
        raw = result2.stdout.strip()

        # If still empty, return a structured error so it propagates clearly
        if not raw:
            combined_err = stderr or result2.stderr.strip()
            return json.dumps(
                {
                    "content": f"Gemini CLI returned empty output. stderr: {combined_err[:300]}",
                    "error": "empty_response",
                }
            )

    return raw


def call_ollama(prompt: str, model: str = "llama3.3") -> str:
    """Call Ollama: ollama run <model> <prompt>"""
    if os.environ.get("COLOSSEUM_LOCAL_RUNTIME_MANAGED") == "1":
        from colosseum.services.local_runtime import LocalRuntimeService

        LocalRuntimeService().ensure_runtime_started()
    sp_timeout = get_subprocess_timeout()
    result = subprocess.run(
        ["ollama", "run", model, prompt], capture_output=True, text=True, timeout=sp_timeout
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
        try:
            end = raw.index("```", start)
            extracted = raw[start:end].strip()
        except ValueError:
            # No closing fence found, use everything after the opening fence
            extracted = raw[start:].strip()
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass
    if "```" in raw:
        start = raw.index("```") + 3
        try:
            end = raw.index("```", start)
            extracted = raw[start:end].strip()
        except ValueError:
            # No closing fence found, use everything after the opening fence
            extracted = raw[start:].strip()
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass
    # Return as content string
    return {"content": raw}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider", required=True, choices=["claude", "codex", "gemini", "ollama", "huggingface"]
    )
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
        print(
            json.dumps(
                {
                    "content": f"CLI tool '{args.provider}' not found. Please install it first.",
                    "error": f"{args.provider} command not found in PATH",
                }
            )
        )
        sys.exit(0)
    except subprocess.TimeoutExpired:
        print(json.dumps({"content": f"CLI tool '{args.provider}' timed out.", "error": "timeout"}))
        sys.exit(0)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "content": f"CLI tool '{args.provider}' failed before producing output.",
                    "error": str(exc),
                }
            )
        )
        sys.exit(0)

    parsed = parse_response(raw)
    if "content" not in parsed:
        parsed["content"] = json.dumps(parsed, indent=2)

    print(json.dumps(parsed))


if __name__ == "__main__":
    main()
