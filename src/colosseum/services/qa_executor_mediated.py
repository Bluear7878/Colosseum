"""Mediated QA executor for non-Claude gladiators (Gemini, Codex, etc.).

Non-Claude gladiators cannot natively spawn Claude Code subagents or invoke
Claude skills. To still get a meaningful QA pass from them, Colosseum drives
the model in a manual action loop:

  1. Load the target's `.claude/skills/qa/SKILL.md` and reference files
     into one fat system prompt (Claude-Code-only directives stripped).
  2. Send the prompt to the model.
  3. Model responds with a structured JSON action — `run_bash`, `read_file`,
     `write_file`, `list_dir`, or `finalize_report`.
  4. Colosseum executes the action with the gladiator's GPU env locked
     (CUDA_VISIBLE_DEVICES = its slice) and sandbox boundaries enforced.
  5. The result is fed back to the model and the loop continues until
     `finalize_report` or until the action budget runs out.

v1 mediated path is best for Layer 1-3 (baseline / parameter variations /
known-risky combos). Exploratory work (Layer 5) is harder to drive this way
and the prompt explicitly tells the model to skip it.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from colosseum.core.config import (
    QA_DEFAULT_MAX_BUDGET_USD_PER_GLADIATOR,
    QA_DEFAULT_MAX_GLADIATOR_MINUTES,
    QA_DEFAULT_STALL_TIMEOUT_MINUTES,
    QA_MEDIATED_MAX_ACTIONS,
    QA_MEDIATED_MAX_BASH_TIMEOUT_SECONDS,
    QA_MEDIATED_PER_ACTION_TIMEOUT_SECONDS,
)
from colosseum.core.models import (
    AgentConfig,
    BudgetPolicy,
    ContextSourceInput,
    ExperimentRun,
    JudgeConfig,
    JudgeMode,
    QAGladiatorOutcome,
    QAGladiatorStatus,
    RunStatus,
    TaskSpec,
    TaskType,
    utc_now,
)
from colosseum.services.provider_runtime import ProviderRuntimeService


SKILL_REFERENCE_FILES = (
    "SKILL.md",
    "test_matrix.md",
    "exploratory_domains.md",
    "agent_prompts.md",
    "verification.md",
    "report_template.md",
    "api_pitfalls.md",
    "calibration_data.md",
    "multimodal_testing.md",
    "customer_spec.md",
)


@dataclass
class MediatedTrace:
    actions: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    finalized: bool = False
    final_report_path: str | None = None
    error: str | None = None


def load_skill_prompt(target_path: Path) -> str:
    """Concatenate SKILL.md and reference files into one prompt block.

    Returns an empty string if no QA skill is found.
    """
    skill_dir = target_path / ".claude" / "skills" / "qa"
    if not skill_dir.exists():
        return ""

    sections: list[str] = []
    for name in SKILL_REFERENCE_FILES:
        path = skill_dir / name
        if not path.exists() or not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        sections.append(f"════════════════════ {name} ════════════════════\n\n{content}\n")
    return "\n".join(sections)


def build_mediated_system_prompt(
    skill_text: str,
    target_path: Path,
    gladiator_id: str,
    run_id: str,
    qa_args: str,
    assigned_gpus: list[int],
    report_path: Path,
    output_root: Path,
    brief: bool,
    spec: str | None,
    response_language: str,
) -> str:
    gpus_csv = ",".join(str(i) for i in assigned_gpus) if assigned_gpus else "(none)"
    lang_line = (
        f"Respond in language: {response_language}.\n\n"
        if response_language and response_language != "auto"
        else ""
    )
    mode_line = "BRIEF MODE: code analysis only, do not run any GPU code." if brief else (
        "FULL EXECUTION MODE: actually run quantization and lm-eval on the assigned GPUs."
    )
    spec_line = f"Customer spec: {spec}" if spec else "Customer spec: none"

    return (
        "You are running inside a Colosseum mediated executor as a non-Claude QA gladiator.\n"
        "You DO NOT have native access to file tools, bash, or sub-agents — Colosseum is\n"
        "driving you in an action loop. To do anything, you must respond with a single JSON\n"
        "object describing the next action. Colosseum will execute it and feed you the\n"
        "result, then ask you for the next action.\n"
        "\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "ACTION PROTOCOL\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "\n"
        "Every response from you MUST be a single JSON object inside a fenced ```json block,\n"
        "with no other text outside the block. Schemas:\n"
        "\n"
        '  {"action": "run_bash", "command": "...", "timeout_seconds": 600, "purpose": "..."}\n'
        '  {"action": "read_file", "path": "<absolute or relative path>"}\n'
        '  {"action": "list_dir", "path": "<dir>"}\n'
        '  {"action": "write_file", "path": "<inside gladiator dir>", "content": "..."}\n'
        '  {"action": "finalize_report", "path": "<COLOSSEUM_QA_REPORT_PATH>"}\n'
        "\n"
        "Rules:\n"
        f"- Bash commands run with cwd={target_path} and env CUDA_VISIBLE_DEVICES={gpus_csv}.\n"
        f"- write_file is only allowed under {output_root} or to COLOSSEUM_QA_REPORT_PATH.\n"
        "- read_file may read from anywhere under the target project.\n"
        "- timeout_seconds maxes out at"
        f" {QA_MEDIATED_MAX_BASH_TIMEOUT_SECONDS}s. Long jobs should be split.\n"
        f"- You have at most {QA_MEDIATED_MAX_ACTIONS} actions. Plan accordingly.\n"
        "- DO NOT modify any file inside the target repo other than COLOSSEUM_QA_REPORT_PATH.\n"
        "- DO NOT spawn subagents — you don't have that capability here.\n"
        "- Restrict yourself to QA Layer 1-3 (baseline / parameter variations / known-risky).\n"
        "  Do not attempt Layer 5 exploratory work — it requires native subagent dispatch.\n"
        "- Every bug in your final report MUST be REPRODUCED via actual execution.\n"
        "\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "RUN CONTEXT\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "\n"
        f"COLOSSEUM_QA_RUN_ID: {run_id}\n"
        f"COLOSSEUM_QA_GLADIATOR_ID: {gladiator_id}\n"
        f"COLOSSEUM_QA_REPORT_PATH: {report_path}\n"
        f"COLOSSEUM_QA_OUTPUT_ROOT: {output_root}\n"
        f"TARGET PROJECT: {target_path}\n"
        f"QA SCOPE ARGS: {qa_args}\n"
        f"GPU ASSIGNMENT: [{gpus_csv}]\n"
        f"{spec_line}\n"
        f"{mode_line}\n"
        "\n"
        f"{lang_line}"
        "═══════════════════════════════════════════════════════════════════════\n"
        "QA SKILL — REFERENCE MATERIAL (read in full, then act)\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "\n"
        "The following is the QA skill that Claude Code gladiators invoke natively. Adapt its\n"
        "intent to the action protocol above. Skip any instruction that requires Task/subagent\n"
        "spawning, or that writes outside COLOSSEUM_QA_REPORT_PATH / COLOSSEUM_QA_OUTPUT_ROOT.\n"
        "\n"
        f"{skill_text}\n"
        "\n"
        "═══════════════════════════════════════════════════════════════════════\n"
        "BEGIN — your first response should be the first action you want to take.\n"
        "═══════════════════════════════════════════════════════════════════════\n"
    )


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_action(model_text: str) -> dict[str, Any] | None:
    """Extract the first JSON action from a model response."""
    if not model_text:
        return None
    match = _JSON_FENCE.search(model_text)
    candidate = match.group(1) if match else model_text.strip()
    # Locate the first { that opens a balanced JSON object.
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None
    try:
        return json.loads(candidate[start:end])
    except json.JSONDecodeError:
        return None


class MediatedQAExecutor:
    """Drive a non-Claude model through the QA skill via an action loop."""

    def __init__(
        self,
        gladiator_id: str,
        agent_config: AgentConfig,
        target_path: Path,
        gladiator_dir: Path,
        run_id: str,
        qa_args: str,
        assigned_gpus: list[int],
        provider_runtime: ProviderRuntimeService,
        brief: bool = False,
        spec: str | None = None,
        keep_bug_outputs: bool = False,
        response_language: str = "auto",
        max_budget_usd: float = QA_DEFAULT_MAX_BUDGET_USD_PER_GLADIATOR,
        max_gladiator_minutes: int = QA_DEFAULT_MAX_GLADIATOR_MINUTES,
        stall_timeout_minutes: int = QA_DEFAULT_STALL_TIMEOUT_MINUTES,
        max_actions: int = QA_MEDIATED_MAX_ACTIONS,
        per_action_timeout_seconds: int = QA_MEDIATED_PER_ACTION_TIMEOUT_SECONDS,
        on_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.gladiator_id = gladiator_id
        self.agent_config = agent_config
        self.target_path = target_path
        self.gladiator_dir = gladiator_dir
        self.run_id = run_id
        self.qa_args = qa_args
        self.assigned_gpus = assigned_gpus
        self.provider_runtime = provider_runtime
        self.brief = brief
        self.spec = spec
        self.keep_bug_outputs = keep_bug_outputs
        self.response_language = response_language
        self.max_budget_usd = max_budget_usd
        self.max_gladiator_minutes = max_gladiator_minutes
        self.stall_timeout_minutes = stall_timeout_minutes
        self.max_actions = max_actions
        self.per_action_timeout_seconds = max(30, int(per_action_timeout_seconds))
        self.on_event = on_event

    async def run(self) -> QAGladiatorOutcome:
        self.gladiator_dir.mkdir(parents=True, exist_ok=True)
        report_path = self.gladiator_dir / "report.md"
        output_root = self.gladiator_dir / "scratch"
        output_root.mkdir(parents=True, exist_ok=True)
        trace_path = self.gladiator_dir / "mediated_trace.jsonl"

        outcome = QAGladiatorOutcome(
            gladiator_id=self.gladiator_id,
            display_name=self.agent_config.display_name,
            provider_type=self.agent_config.provider.type,
            model=self.agent_config.provider.model,
            assigned_gpus=list(self.assigned_gpus),
            status=QAGladiatorStatus.RUNNING,
            report_path=str(report_path),
            stream_jsonl_path=str(trace_path),
            started_at=datetime.now(timezone.utc),
        )
        await self._emit("gladiator_started", {"gladiator_id": self.gladiator_id})

        skill_text = load_skill_prompt(self.target_path)
        if not skill_text:
            outcome.status = QAGladiatorStatus.FAILED
            outcome.error = (
                f"target {self.target_path} has no .claude/skills/qa/ — "
                "mediated executor requires the QA skill files to load"
            )
            outcome.completed_at = datetime.now(timezone.utc)
            outcome.duration_seconds = (
                outcome.completed_at - outcome.started_at
            ).total_seconds()
            return outcome

        system_prompt = build_mediated_system_prompt(
            skill_text=skill_text,
            target_path=self.target_path,
            gladiator_id=self.gladiator_id,
            run_id=self.run_id,
            qa_args=self.qa_args,
            assigned_gpus=self.assigned_gpus,
            report_path=report_path,
            output_root=output_root,
            brief=self.brief,
            spec=self.spec,
            response_language=self.response_language,
        )

        history: list[str] = []
        trace = MediatedTrace()
        soft_deadline = time.monotonic() + self.max_gladiator_minutes * 60
        last_event_at = time.monotonic()

        # We need a synthetic ExperimentRun to satisfy provider_runtime.execute().
        synthetic_run = self._build_synthetic_run()

        action_index = 0
        while action_index < self.max_actions:
            if time.monotonic() >= soft_deadline:
                outcome.status = QAGladiatorStatus.TIMED_OUT
                outcome.error = "soft timeout reached during mediated loop"
                break
            if time.monotonic() - last_event_at >= self.stall_timeout_minutes * 60:
                outcome.status = QAGladiatorStatus.TIMED_OUT
                outcome.error = "stall timeout in mediated loop"
                break

            instructions = self._build_user_message(history, action_index)
            # Pin timeout per call: prevents one slow gemini call from
            # devouring the entire stall budget. Override is non-destructive
            # because provider_runtime.execute() does its own model_copy.
            scoped_provider = self.agent_config.provider.model_copy(deep=True)
            scoped_provider.timeout_seconds = self.per_action_timeout_seconds
            try:
                execution = await asyncio.wait_for(
                    self.provider_runtime.execute(
                        run=synthetic_run,
                        actor_id=self.gladiator_id,
                        actor_label=self.agent_config.display_name,
                        provider_config=scoped_provider,
                        operation="qa_action",
                        instructions=system_prompt + "\n\n" + instructions,
                        metadata={
                            "qa_run_id": self.run_id,
                            "qa_gladiator_id": self.gladiator_id,
                            "action_index": action_index,
                            "response_language": self.response_language,
                        },
                        timeout_override=self.per_action_timeout_seconds,
                    ),
                    timeout=self.per_action_timeout_seconds + 30,
                )
            except asyncio.TimeoutError:
                history.append(
                    f"[colosseum] Action {action_index} timed out after "
                    f"{self.per_action_timeout_seconds}s. The model did not "
                    f"return in time."
                )
                self._append_trace(
                    trace_path,
                    {
                        "index": action_index,
                        "action": {"action": "(timeout)"},
                        "observation_preview": (
                            f"per-action timeout {self.per_action_timeout_seconds}s"
                        ),
                    },
                )
                action_index += 1
                last_event_at = time.monotonic()
                continue
            except Exception as exc:
                outcome.status = QAGladiatorStatus.FAILED
                outcome.error = f"provider call failed at action {action_index}: {exc}"
                break

            usage = execution.result.usage
            trace.input_tokens += usage.prompt_tokens
            trace.output_tokens += usage.completion_tokens
            trace.cost_usd += usage.estimated_cost_usd
            last_event_at = time.monotonic()

            response_text = execution.result.content or ""
            action = parse_action(response_text)
            history.append(f"ASSISTANT (action {action_index}):\n{response_text}\n")

            if action is None:
                history.append(
                    "[colosseum] Your last response was not a valid JSON action. "
                    "Respond with a single fenced ```json block.\n"
                )
                action_index += 1
                continue

            action_record: dict[str, Any] = {"index": action_index, "action": action}
            try:
                obs, finalize, finalize_path = await self._execute_action(
                    action, output_root, report_path
                )
            except Exception as exc:
                obs = f"[error] {exc}"
                finalize = False
                finalize_path = None

            action_record["observation_preview"] = obs[:300]
            trace.actions.append(action_record)
            self._append_trace(trace_path, action_record)

            history.append(f"OBSERVATION (action {action_index}):\n{obs[:4000]}\n")

            if finalize:
                trace.finalized = True
                trace.final_report_path = finalize_path
                outcome.status = QAGladiatorStatus.REPORT_WRITTEN
                break

            action_index += 1

        if not trace.finalized and outcome.status == QAGladiatorStatus.RUNNING:
            outcome.status = QAGladiatorStatus.NO_OUTPUT
            outcome.error = (outcome.error or "") + " (action budget exhausted before finalize_report)"

        outcome.completed_at = datetime.now(timezone.utc)
        outcome.duration_seconds = (outcome.completed_at - outcome.started_at).total_seconds()
        outcome.token_usage = {
            "input_tokens": trace.input_tokens,
            "output_tokens": trace.output_tokens,
            "total_tokens": trace.input_tokens + trace.output_tokens,
        }
        outcome.cost_usd = trace.cost_usd

        # Resolve report path.
        resolved = self._resolve_report(report_path)
        if resolved is not None:
            outcome.report_path = str(resolved)
            try:
                outcome.raw_report_text = resolved.read_text(encoding="utf-8")
            except Exception:
                outcome.raw_report_text = None
        elif history:
            outcome.raw_report_text = "\n\n".join(history[-3:])

        await self._emit(
            "gladiator_finished",
            {
                "gladiator_id": self.gladiator_id,
                "status": outcome.status.value,
                "cost_usd": outcome.cost_usd,
                "actions": len(trace.actions),
            },
        )
        return outcome

    # ── action execution ────────────────────────────────────────────

    async def _execute_action(
        self, action: dict[str, Any], output_root: Path, report_path: Path
    ) -> tuple[str, bool, str | None]:
        kind = str(action.get("action") or "").strip().lower()
        if kind == "run_bash":
            return await self._action_run_bash(action), False, None
        if kind == "read_file":
            return self._action_read_file(action), False, None
        if kind == "list_dir":
            return self._action_list_dir(action), False, None
        if kind == "write_file":
            return self._action_write_file(action, output_root, report_path), False, None
        if kind == "finalize_report":
            obs, ok, path = self._action_finalize(action, report_path)
            return obs, ok, path
        return f"[error] unknown action kind: {kind!r}", False, None

    async def _action_run_bash(self, action: dict[str, Any]) -> str:
        cmd = str(action.get("command") or "").strip()
        if not cmd:
            return "[error] run_bash requires a non-empty command"
        timeout = int(action.get("timeout_seconds") or 300)
        timeout = max(1, min(timeout, QA_MEDIATED_MAX_BASH_TIMEOUT_SECONDS))
        env = os.environ.copy()
        if self.assigned_gpus:
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in self.assigned_gpus)
        env["QA_OUTPUT_ROOT"] = str(self.gladiator_dir / "scratch")
        env["COLOSSEUM_QA_RUN_ID"] = self.run_id
        env["COLOSSEUM_QA_GLADIATOR_ID"] = self.gladiator_id

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(self.target_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            return f"[error] failed to spawn shell: {exc}"

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return f"[error] command timed out after {timeout}s"

        out = (stdout or b"").decode("utf-8", errors="replace")
        err = (stderr or b"").decode("utf-8", errors="replace")
        snippet_out = out[-4000:]
        snippet_err = err[-2000:]
        return (
            f"[bash exit={proc.returncode}]\n"
            f"-- stdout (last 4000 chars) --\n{snippet_out}\n"
            f"-- stderr (last 2000 chars) --\n{snippet_err}\n"
        )

    def _action_read_file(self, action: dict[str, Any]) -> str:
        raw_path = str(action.get("path") or "").strip()
        if not raw_path:
            return "[error] read_file requires a path"
        path = self._resolve_path(raw_path)
        if path is None:
            return f"[error] path not allowed: {raw_path}"
        try:
            data = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"[error] file not found: {path}"
        except IsADirectoryError:
            return f"[error] is a directory: {path}"
        except Exception as exc:
            return f"[error] read failed: {exc}"
        return data[:8000]

    def _action_list_dir(self, action: dict[str, Any]) -> str:
        raw_path = str(action.get("path") or "").strip()
        path = self._resolve_path(raw_path or ".")
        if path is None:
            return f"[error] path not allowed: {raw_path}"
        if not path.exists():
            return f"[error] not found: {path}"
        if not path.is_dir():
            return f"[error] not a directory: {path}"
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
        return "\n".join(entries[:200])

    def _action_write_file(
        self, action: dict[str, Any], output_root: Path, report_path: Path
    ) -> str:
        raw_path = str(action.get("path") or "").strip()
        content = str(action.get("content") or "")
        if not raw_path:
            return "[error] write_file requires a path"
        target = self._resolve_writable(raw_path, output_root, report_path)
        if target is None:
            return (
                f"[error] write_file path not in sandbox. Allowed roots: "
                f"{output_root}, {report_path}"
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"[error] write failed: {exc}"
        return f"[wrote {len(content)} chars to {target}]"

    def _action_finalize(
        self, action: dict[str, Any], report_path: Path
    ) -> tuple[str, bool, str | None]:
        raw_path = str(action.get("path") or "").strip()
        target = report_path
        if raw_path:
            resolved = self._resolve_writable(raw_path, report_path.parent, report_path)
            if resolved is not None:
                target = resolved
        if not target.exists() or target.stat().st_size == 0:
            return (
                f"[error] finalize_report: nothing at {target}. "
                "Use write_file first, then call finalize_report.",
                False,
                None,
            )
        return f"[finalized report at {target}]", True, str(target)

    # ── path/sandbox helpers ─────────────────────────────────────────

    def _resolve_path(self, raw: str) -> Path | None:
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (self.target_path / candidate).resolve()
            else:
                candidate = candidate.resolve()
        except Exception:
            return None
        # Allow reads from target tree, gladiator dir, or absolute paths in
        # /tmp (skill scratch space).
        try:
            for root in (self.target_path.resolve(), self.gladiator_dir.resolve(), Path("/tmp")):
                if candidate == root or root in candidate.parents:
                    return candidate
        except Exception:
            return None
        return None

    def _resolve_writable(self, raw: str, output_root: Path, report_path: Path) -> Path | None:
        try:
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = (self.gladiator_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
        except Exception:
            return None
        report_resolved = report_path.resolve()
        if candidate == report_resolved:
            return candidate
        try:
            output_resolved = output_root.resolve()
            if output_resolved in candidate.parents or candidate == output_resolved:
                return candidate
            gd_resolved = self.gladiator_dir.resolve()
            if gd_resolved in candidate.parents or candidate == gd_resolved:
                return candidate
        except Exception:
            return None
        return None

    def _resolve_report(self, expected: Path) -> Path | None:
        if expected.exists() and expected.is_file() and expected.stat().st_size > 0:
            return expected
        for md in self.gladiator_dir.rglob("*.md"):
            try:
                if md.stat().st_size > 0:
                    return md
            except OSError:
                continue
        return None

    # ── prompt scaffolding ──────────────────────────────────────────

    def _build_user_message(self, history: list[str], action_index: int) -> str:
        recent = "\n".join(history[-12:])
        return (
            f"Action index: {action_index} of max {self.max_actions}.\n\n"
            f"Recent trace:\n{recent}\n\n"
            "Now respond with your next JSON action."
        )

    def _build_synthetic_run(self) -> ExperimentRun:
        return ExperimentRun(
            project_name="Colosseum QA (mediated)",
            task=TaskSpec(
                title=f"QA: {self.qa_args or 'mediated run'}",
                problem_statement=(
                    f"Mediated QA pass for gladiator {self.gladiator_id} "
                    f"on target {self.target_path}"
                ),
                task_type=TaskType.TECHNICAL_REVIEW,
            ),
            agents=[self.agent_config],
            judge=JudgeConfig(mode=JudgeMode.AUTOMATED),
            status=RunStatus.PENDING,
            budget_policy=BudgetPolicy(),
        )

    def _append_trace(self, trace_path: Path, record: dict[str, Any]) -> None:
        try:
            with trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    async def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            await self.on_event(name, payload)
        except Exception:
            pass
