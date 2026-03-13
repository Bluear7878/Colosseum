"""Provider presets for popular CLI-based AI tools."""
from __future__ import annotations

import sys
from pathlib import Path

# The wrapper script path (bundled with Colosseum)
WRAPPER_SCRIPT = str(Path(__file__).resolve().parent / "cli_wrapper.py")


PRESETS: dict[str, dict] = {
    "claude_cli": {
        "command": [sys.executable, WRAPPER_SCRIPT, "--provider", "claude"],
        "env": {},
        "timeout_seconds": 300,
        "description": "Anthropic Claude CLI (uses 'claude' command with -p flag)",
    },
    "codex_cli": {
        "command": [sys.executable, WRAPPER_SCRIPT, "--provider", "codex"],
        "env": {},
        "timeout_seconds": 300,
        "description": "OpenAI Codex CLI (uses 'codex' command)",
    },
    "gemini_cli": {
        "command": [sys.executable, WRAPPER_SCRIPT, "--provider", "gemini"],
        "env": {},
        "timeout_seconds": 300,
        "description": "Google Gemini CLI (uses 'gemini' command)",
    },
    "ollama": {
        "command": [sys.executable, WRAPPER_SCRIPT, "--provider", "ollama"],
        "env": {},
        "timeout_seconds": 600,
        "description": "Ollama local runner (uses 'ollama run' for open-source models)",
    },
}


def get_preset(name: str) -> dict:
    """Return preset configuration by name."""
    if name not in PRESETS:
        raise ValueError(f"Unknown preset: {name}. Available: {list(PRESETS.keys())}")
    return PRESETS[name].copy()
