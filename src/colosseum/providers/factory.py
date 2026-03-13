from __future__ import annotations

import sys
from pathlib import Path

from colosseum.core.models import ProviderConfig, ProviderType
from colosseum.providers.base import BaseProvider
from colosseum.providers.command import CommandProvider
from colosseum.providers.mock import MockProvider
from colosseum.services.local_runtime import LocalRuntimeService

WRAPPER_SCRIPT = str(Path(__file__).resolve().parent / "cli_wrapper.py")


def _strip_provider_prefix(model_name: str | None) -> str | None:
    if not model_name:
        return None
    if ":" not in model_name:
        return model_name
    prefix, remainder = model_name.split(":", 1)
    if prefix in {"ollama", "hf", "huggingface"} and remainder:
        return remainder
    return model_name


def _timeout(config: ProviderConfig, default: int) -> int | None:
    """Return the effective timeout.  ``None`` means no limit."""
    if config.timeout_seconds is None:
        return None  # explicitly no limit
    return config.timeout_seconds or default


def build_provider(config: ProviderConfig) -> BaseProvider:
    runtime_env = LocalRuntimeService().provider_env()
    if config.type == ProviderType.MOCK:
        return MockProvider(model_name=config.model)
    if config.type == ProviderType.COMMAND:
        return CommandProvider(
            model_name=config.model,
            command=config.command,
            env=config.env,
            timeout_seconds=_timeout(config, 300),
        )
    if config.type == ProviderType.CLAUDE_CLI:
        model = config.model or "claude-sonnet-4-6"
        return CommandProvider(
            model_name=model,
            command=config.command
            or [sys.executable, WRAPPER_SCRIPT, "--provider", "claude", "--model", model],
            env=config.env,
            timeout_seconds=_timeout(config, 300),
        )
    if config.type == ProviderType.CODEX_CLI:
        model = config.model or "o3"
        return CommandProvider(
            model_name=model,
            command=config.command
            or [sys.executable, WRAPPER_SCRIPT, "--provider", "codex", "--model", model],
            env=config.env,
            timeout_seconds=_timeout(config, 300),
        )
    if config.type == ProviderType.GEMINI_CLI:
        model = config.model or "gemini-2.5-pro"
        return CommandProvider(
            model_name=model,
            command=config.command
            or [sys.executable, WRAPPER_SCRIPT, "--provider", "gemini", "--model", model],
            env=config.env,
            timeout_seconds=_timeout(config, 300),
        )
    if config.type == ProviderType.OLLAMA:
        ollama_model = config.ollama_model or _strip_provider_prefix(config.model) or "llama3.3"
        return CommandProvider(
            model_name=config.model or f"ollama:{ollama_model}",
            command=config.command
            or [sys.executable, WRAPPER_SCRIPT, "--provider", "ollama", "--model", ollama_model],
            env={**runtime_env, **config.env},
            timeout_seconds=_timeout(config, 600),
        )
    if config.type == ProviderType.HUGGINGFACE_LOCAL:
        hf_model = (
            config.hf_model
            or config.ollama_model
            or _strip_provider_prefix(config.model)
            or "llama3.3"
        )
        return CommandProvider(
            model_name=config.model or f"hf:{hf_model}",
            command=config.command
            or [sys.executable, WRAPPER_SCRIPT, "--provider", "huggingface", "--model", hf_model],
            env={**runtime_env, **config.env},
            timeout_seconds=_timeout(config, 600),
        )
    raise ValueError(f"Unsupported provider type: {config.type}")
