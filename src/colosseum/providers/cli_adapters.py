"""Provider-specific CLI adapter hierarchy for wrapper-based runtimes.

The wrapper script is the narrow waist between Colosseum's JSON protocol and
multiple external CLIs. Keeping provider quirks in subclasses prevents
provider-specific fallback logic from leaking into unrelated call sites.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


class CliProviderAdapter(ABC):
    """Template-method base class for subprocess-backed CLI adapters."""

    provider_name = "unknown"

    def __init__(self, model: str = "") -> None:
        self.model = str(model or "").strip()

    def call_with_usage(self, prompt: str) -> tuple[str, dict]:
        """Return (content, usage_info). Base implementation has no usage info."""
        return self.call(prompt), {}

    def call(self, prompt: str) -> str:
        """Return the raw model text for *prompt*.

        Subclasses can override this when a provider needs a custom execution
        flow, but the default loop is enough for most CLI tools.
        """

        assert isinstance(prompt, str), "Prompt must be a string."
        failures: list[str] = []
        for command in self.command_attempts(prompt):
            result = self._run(command)
            raw = self.normalize_stdout(result.stdout)
            if raw:
                return raw
            self.record_failure(failures, result)
        return self.empty_response(failures)

    def command_attempts(self, prompt: str) -> list[list[str]]:
        """Return subprocess attempts in priority order."""

        return [self.build_command(prompt)]

    @abstractmethod
    def build_command(self, prompt: str) -> list[str]:
        """Build the primary subprocess command for this provider."""

    def normalize_stdout(self, stdout: str) -> str:
        return stdout.strip()

    def environment(self) -> dict[str, str] | None:
        return None

    def record_failure(
        self,
        failures: list[str],
        result: subprocess.CompletedProcess[str],
    ) -> None:
        stderr = result.stderr.strip()
        if stderr:
            failures.append(stderr)
            return
        if result.returncode == 0:
            failures.append(f"{self.provider_name} CLI returned no stdout content.")
            return
        failures.append(f"{self.provider_name} CLI failed with code {result.returncode}.")

    def empty_response(self, failures: list[str]) -> str:
        return ""

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": self.subprocess_timeout(),
        }
        env = self.environment()
        if env is not None:
            kwargs["env"] = env
        return subprocess.run(command, **kwargs)

    @staticmethod
    def subprocess_timeout() -> float | None:
        """Read COLOSSEUM_TIMEOUT from the environment.

        Missing or 0 means "no timeout".
        """

        raw = os.environ.get("COLOSSEUM_TIMEOUT", "")
        if not raw:
            return None
        val = int(raw)
        return None if val == 0 else float(val)


class ClaudeCliAdapter(CliProviderAdapter):
    """Claude Code adapter with JSON-envelope unwrapping and plain fallback."""

    provider_name = "claude"

    def call_with_usage(self, prompt: str) -> tuple[str, dict]:
        assert isinstance(prompt, str), "Prompt must be a string."
        primary = self._run(self.build_command(prompt))
        usage: dict = {}
        content = ""
        stripped = primary.stdout.strip()
        if stripped:
            try:
                envelope = json.loads(stripped)
                if isinstance(envelope, dict):
                    if envelope.get("total_input_tokens"):
                        usage["prompt_tokens"] = envelope["total_input_tokens"]
                    if envelope.get("total_output_tokens"):
                        usage["completion_tokens"] = envelope["total_output_tokens"]
                    if envelope.get("cost_usd"):
                        usage["cost_usd"] = envelope["cost_usd"]
            except json.JSONDecodeError:
                pass
            content = self._unwrap_result(primary.stdout)
        if primary.returncode == 0 and content:
            return content, usage
        fallback = self._run(self._fallback_command(prompt))
        fallback_raw = fallback.stdout.strip()
        return fallback_raw or content, usage

    def call(self, prompt: str) -> str:
        content, _ = self.call_with_usage(prompt)
        return content

    def build_command(self, prompt: str) -> list[str]:
        command = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--dangerously-skip-permissions",
        ]
        if self.model:
            command.extend(["--model", self.model])
        return command

    def _fallback_command(self, prompt: str) -> list[str]:
        command = ["claude", "-p", prompt]
        if self.model:
            command.extend(["--model", self.model])
        return command

    def _unwrap_result(self, raw: str) -> str:
        stripped = raw.strip()
        if not stripped:
            return ""
        try:
            envelope = json.loads(stripped)
        except json.JSONDecodeError:
            return stripped
        if not isinstance(envelope, dict) or "result" not in envelope:
            return stripped
        inner = envelope["result"]
        if isinstance(inner, str):
            return inner.strip()
        return json.dumps(inner)

    def environment(self) -> dict[str, str] | None:
        env = os.environ.copy()
        env["CLAUDECODE"] = ""
        return env


_codex_exec_flags_cache: list[str] | None = None


def detect_codex_exec_flags() -> list[str]:
    """Return the non-interactive safety flags supported by the installed codex exec.

    Runs ``codex exec --help`` once and caches the result.  Falls back to the
    empty list when codex is not installed or the help output cannot be parsed.
    """
    global _codex_exec_flags_cache
    if _codex_exec_flags_cache is not None:
        return _codex_exec_flags_cache

    import shutil

    if not shutil.which("codex"):
        _codex_exec_flags_cache = []
        return _codex_exec_flags_cache

    try:
        result = subprocess.run(
            ["codex", "exec", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        help_text = result.stdout + result.stderr
    except Exception:
        _codex_exec_flags_cache = []
        return _codex_exec_flags_cache

    flags: list[str] = []
    if "--dangerously-bypass-approvals-and-sandbox" in help_text:
        flags.append("--dangerously-bypass-approvals-and-sandbox")

    _codex_exec_flags_cache = flags
    return flags


class CodexCliAdapter(CliProviderAdapter):
    """Codex adapter that reads the clean response from an output file."""

    provider_name = "codex"

    def call(self, prompt: str) -> str:
        assert isinstance(prompt, str), "Prompt must be a string."
        fd, out_file = tempfile.mkstemp(suffix=".txt", prefix="codex_")
        os.close(fd)
        output_path = Path(out_file)
        try:
            result = subprocess.run(
                self.build_command(prompt) + ["-o", str(output_path), prompt],
                capture_output=True,
                text=True,
                timeout=self.subprocess_timeout(),
            )
            raw = self._read_output_file(output_path)
            if raw:
                return raw
            if result.stdout.strip():
                lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
                if lines:
                    return lines[-1].strip()
            return ""
        finally:
            output_path.unlink(missing_ok=True)

    def build_command(self, prompt: str) -> list[str]:
        del prompt
        command = ["codex", "exec"] + detect_codex_exec_flags()
        if self.model:
            command.extend(["--model", self.model])
        return command

    def _read_output_file(self, output_path: Path) -> str:
        if not output_path.exists():
            return ""
        with output_path.open(encoding="utf-8") as handle:
            return handle.read().strip()


class GeminiCliAdapter(CliProviderAdapter):
    """Gemini adapter with explicit approval escalation and banner stripping."""

    provider_name = "gemini"

    def command_attempts(self, prompt: str) -> list[list[str]]:
        base = ["gemini"]
        if self.model:
            base.extend(["--model", self.model])
        return [
            [*base, "-p", prompt],
            [*base, "--approval-mode", "yolo", "-p", prompt],
            [*base, "--yolo", "-p", prompt],
        ]

    def build_command(self, prompt: str) -> list[str]:
        return self.command_attempts(prompt)[0]

    def normalize_stdout(self, stdout: str) -> str:
        if not stdout.strip():
            return ""
        cleaned_lines: list[str] = []
        for line in stdout.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if not stripped:
                continue
            if lowered.startswith("yolo mode is enabled."):
                continue
            if lowered.startswith("loaded cached credentials."):
                continue
            if lowered.startswith("loaded credentials."):
                continue
            if lowered.startswith("using cached credentials."):
                continue
            if lowered.startswith('skill "') and "overriding the built-in skill" in lowered:
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    def empty_response(self, failures: list[str]) -> str:
        if failures:
            combined_err = next(
                (
                    failure
                    for failure in reversed(failures)
                    if "yolo" not in failure.lower() or "approval-mode" in failure.lower()
                ),
                failures[-1],
            )
        else:
            combined_err = "Gemini CLI returned empty output."
        return json.dumps(
            {
                "content": f"Gemini CLI returned empty output. stderr: {combined_err[:300]}",
                "error": "empty_response",
            }
        )


class OllamaCliAdapter(CliProviderAdapter):
    """Ollama-backed local runtime adapter."""

    provider_name = "ollama"

    def build_command(self, prompt: str) -> list[str]:
        self._ensure_runtime_started()
        model = self.model or "llama3.3"
        return ["ollama", "run", model, prompt]

    def _ensure_runtime_started(self) -> None:
        if os.environ.get("COLOSSEUM_LOCAL_RUNTIME_MANAGED") != "1":
            return
        from colosseum.services.local_runtime import LocalRuntimeService

        LocalRuntimeService().ensure_runtime_started()


class HuggingFaceLocalCliAdapter(OllamaCliAdapter):
    """Alias adapter for local HuggingFace/Ollama-backed runtimes."""

    provider_name = "huggingface"


def build_cli_adapter(provider: str, model: str = "") -> CliProviderAdapter:
    """Return the concrete adapter for a wrapper provider name."""

    normalized = str(provider or "").strip().lower()
    if normalized == "claude":
        return ClaudeCliAdapter(model=model)
    if normalized == "codex":
        return CodexCliAdapter(model=model)
    if normalized == "gemini":
        return GeminiCliAdapter(model=model)
    if normalized == "ollama":
        return OllamaCliAdapter(model=model)
    if normalized == "huggingface":
        return HuggingFaceLocalCliAdapter(model=model)
    raise ValueError(f"Unsupported provider: {provider}")
