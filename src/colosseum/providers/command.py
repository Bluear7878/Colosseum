from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from colosseum.core.models import UsageMetrics
from colosseum.providers.base import (
    BaseProvider,
    ProviderExecutionError,
    ProviderQuotaExceededError,
    ProviderResult,
)


class CommandProvider(BaseProvider):
    """Subprocess-backed provider for local CLIs or wrapper scripts."""

    QUOTA_PATTERNS = (
        "quota",
        "usage limit",
        "plan limit",
        "rate limit exceeded",
        "credit balance is too low",
        "token limit reached",
        "tokens are exhausted",
        "try again later",
    )

    def __init__(
        self,
        model_name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        timeout_seconds: int | None = 180,
    ) -> None:
        self.model_name = model_name
        self.command = command
        self.env = env or {}
        self.timeout_seconds = timeout_seconds

    async def generate(
        self,
        operation: str,
        instructions: str,
        metadata: dict[str, Any],
    ) -> ProviderResult:
        if not self.command:
            raise ValueError("Command provider requires a non-empty command.")

        payload = {
            "operation": operation,
            "instructions": instructions,
            "metadata": metadata,
            "model": self.model_name,
        }

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="colosseum-provider-",
            delete=False,
        ) as handle:
            json.dump(payload, handle)
            handle.flush()
            input_path = Path(handle.name)

        process_env = os.environ.copy()
        process_env.update(self.env)
        process_env["COLOSSEUM_INPUT_PATH"] = str(input_path)

        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            except (TimeoutError, asyncio.TimeoutError):
                # Kill the timed-out process
                try:
                    process.kill()
                    await process.wait()
                except ProcessLookupError:
                    pass
                cmd_label = " ".join(self.command[:3])
                raise ProviderExecutionError(
                    f"Provider '{self.model_name}' timed out after {self.timeout_seconds}s "
                    f"(command: {cmd_label}...). Consider increasing timeout_seconds."
                )
        finally:
            input_path.unlink(missing_ok=True)

        if process.returncode != 0:
            error_text = stderr.decode("utf-8")
            if self._looks_like_quota_error(error_text):
                raise ProviderQuotaExceededError(error_text.strip() or "Provider quota exhausted.")
            raise ProviderExecutionError(
                f"Provider command failed with code {process.returncode}: {stderr.decode('utf-8')}"
            )

        raw = stdout.decode("utf-8").strip()
        parsed = self._parse_stdout(raw)
        error_text = str(parsed["json_payload"].get("error", "")) if parsed["json_payload"] else ""
        if self._looks_like_quota_error(f"{raw}\n{error_text}\n{stderr.decode('utf-8')}"):
            raise ProviderQuotaExceededError(error_text or raw or "Provider quota exhausted.")
        usage = UsageMetrics(
            prompt_tokens=max(32, len(instructions) // 4),
            completion_tokens=max(32, len(raw) // 4),
        )
        return ProviderResult(
            content=parsed["content"],
            json_payload=parsed["json_payload"],
            usage=usage,
            raw_response={"stdout": raw, "stderr": stderr.decode("utf-8")},
        )

    def _parse_stdout(self, raw: str) -> dict[str, Any]:
        if not raw:
            return {"content": "", "json_payload": {}}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"content": raw, "json_payload": {}}
        if isinstance(payload, dict):
            content = payload.get("content") if "content" in payload else json.dumps(payload, indent=2)
            return {"content": content, "json_payload": payload}
        return {"content": raw, "json_payload": {}}

    def _looks_like_quota_error(self, text: str) -> bool:
        lowered = text.lower()
        return any(pattern in lowered for pattern in self.QUOTA_PATTERNS)
