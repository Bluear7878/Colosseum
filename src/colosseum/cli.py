"""Colosseum CLI — Run AI debates from the terminal.

Usage:
    colosseum quickstart                     Fastest path to your first debate
    colosseum setup                          Install & authenticate CLI providers
    colosseum setup claude codex             Set up specific tools only
    colosseum setup -y                       Auto-confirm all prompts
    colosseum serve                          Start the web UI server
    colosseum debate --topic "..."           Auto-picks authenticated providers
    colosseum debate --topic "..." -g ...    Explicit gladiator choice
    colosseum debate --topic "..." --mock    Quick test with mock providers (free)
    colosseum debate --topic "..." --monitor Run with tmux monitor panel
    colosseum review -t "..." -g ... --dir . Multi-phase code review
    colosseum review -t "..." --mock --phases A B C
    colosseum monitor [run_id]               Open live monitor for an active debate
    colosseum models                         List available models
    colosseum local-runtime status           Inspect managed local-model runtime state
    colosseum personas                       List available personas
    colosseum history                        List past battles
    colosseum show <run_id>                  Show a past battle result
    colosseum delete <run_id|all>            Delete a battle run
    colosseum check                          Verify CLI tool availability
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone

from colosseum.core.config import DEPTH_PROFILES
from colosseum.core.models import (
    BudgetPolicy,
    ContextSourceInput,
    ContextSourceKind,
    DebateRound,
    ExperimentRun,
    HumanJudgeActionRequest,
    JudgeConfig,
    JudgeMode,
    LocalRuntimeConfigUpdate,
    ProviderConfig,
    ProviderPricing,
    ReviewCreateRequest,
    ReviewPhase,
    ReviewSeverity,
    RoundType,
    RunCreateRequest,
    RunStatus,
    TaskSpec,
    TaskType,
    humanize_identifier,
)
from colosseum.core.pricing import MODEL_PRICING as _MODEL_PRICING
from colosseum.services.local_runtime import LocalRuntimeService

# ── ANSI colors (no external deps) ──────────────────────────────

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

DEPTH_LABELS = {1: "Quick", 2: "Brief", 3: "Standard", 4: "Thorough", 5: "Deep Dive"}

# ── Model registry ────────────────────────────────────────────────
#
# Candidate models per provider — a broad list of known model IDs.
# At startup the server probes each CLI to find which ones actually work,
# then serves only the verified models via /models.

_log = logging.getLogger("colosseum.cli")

_CANDIDATE_MODELS: dict[str, list[dict]] = {
    "claude": [
        {"model": "claude-opus-4-6", "label": "Opus 4.6"},
        {"model": "claude-sonnet-4-6", "label": "Sonnet 4.6"},
        {"model": "claude-haiku-4-5-20251001", "label": "Haiku 4.5"},
    ],
    "codex": [
        {"model": "gpt-5.4", "label": "GPT-5.4"},
        {"model": "gpt-5.3-codex", "label": "GPT-5.3 Codex"},
        {"model": "o3", "label": "o3"},
        {"model": "o4-mini", "label": "o4-mini"},
    ],
    "gemini": [
        {"model": "gemini-3.1-pro-preview", "label": "3.1 Pro"},
        {"model": "gemini-3-flash-preview", "label": "3 Flash"},
        {"model": "gemini-3.1-flash-lite-preview", "label": "3.1 Flash Lite"},
        {"model": "gemini-2.5-pro", "label": "2.5 Pro"},
        {"model": "gemini-2.5-flash", "label": "2.5 Flash"},
        {"model": "gemini-2.5-flash-lite", "label": "2.5 Flash Lite"},
    ],
}

_PROVIDER_TYPE_MAP = {
    "claude": "claude_cli",
    "codex": "codex_cli",
    "gemini": "gemini_cli",
}

_PROVIDER_ICON: dict[str, str] = {}
_PROVIDER_DISPLAY = {"claude": "Claude", "codex": "OpenAI", "gemini": "Gemini"}

# ── Fallback model catalog (used when probing hasn't run yet) ──

def _build_fallback_models() -> list[dict]:
    """Build fallback model list from _CANDIDATE_MODELS to stay in sync."""
    models: list[dict] = []
    for provider, candidates in _CANDIDATE_MODELS.items():
        provider_type = _PROVIDER_TYPE_MAP.get(provider, "command")
        display_prefix = _PROVIDER_DISPLAY.get(provider, provider)
        for c in candidates:
            models.append({
                "id": f"{provider}:{c['model']}",
                "name": f"{display_prefix} {c['label']}",
                "type": provider_type,
                "tier": "paid",
            })
    # Free (local via Ollama)
    models.extend([
        {"id": "ollama:llama3.3", "name": "Llama 3.3 70B", "type": "ollama", "tier": "free"},
        {"id": "ollama:llama3.2", "name": "Llama 3.2 3B", "type": "ollama", "tier": "free"},
        {"id": "ollama:mistral", "name": "Mistral 7B", "type": "ollama", "tier": "free"},
        {"id": "ollama:qwen2.5", "name": "Qwen 2.5 7B", "type": "ollama", "tier": "free"},
        {"id": "ollama:gemma3", "name": "Gemma 3 4B", "type": "ollama", "tier": "free"},
        {"id": "ollama:deepseek-r1", "name": "DeepSeek R1 7B", "type": "ollama", "tier": "free"},
    ])
    return models


_FALLBACK_MODELS = _build_fallback_models()


# ── Per-provider model probing ────────────────────────────────────


def _probe_model(cli_cmd: str, model: str, provider: str) -> bool:
    """Quick probe: run a minimal prompt and check if the model responds."""
    try:
        if provider == "claude":
            cmd = [cli_cmd, "-p", "--model", model, "--max-turns", "1", "say ok"]
        elif provider == "codex":
            from colosseum.providers.cli_adapters import detect_codex_exec_flags
            cmd = [cli_cmd, "exec"] + detect_codex_exec_flags() + ["--model", model, "say ok"]
        elif provider == "gemini":
            cmd = [cli_cmd, "--model", model, "-p", "say ok"]
        else:
            return False
        # Clean env: allow nested CLI calls (e.g. claude inside claude-code)
        env = {**os.environ}
        for key in ("CLAUDECODE", "CLAUDE_CODE"):
            env.pop(key, None)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        stderr = result.stderr.lower()
        # Only reject on model-specific errors, not general warnings
        if "not found" in stderr or "invalid model" in stderr or "does not exist" in stderr:
            return False
        if "modelnotfounderror" in stderr:
            return False
        return result.returncode == 0 and len(result.stdout.strip()) > 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def _get_cli_version(cmd: str) -> str | None:
    """Get CLI tool version string."""
    try:
        result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def probe_provider_models(provider: str) -> list[dict]:
    """Probe all candidate models for a provider, return verified ones."""
    cli_cmd = provider if provider != "codex" else "codex"
    if not shutil.which(cli_cmd):
        _log.warning("CLI '%s' not installed — skipping model probe", cli_cmd)
        return []

    version = _get_cli_version(cli_cmd)
    _log.info("Probing %s (version: %s)...", provider, version or "unknown")

    candidates = _CANDIDATE_MODELS.get(provider, [])
    verified = []
    for c in candidates:
        model_id = c["model"]
        ok = _probe_model(cli_cmd, model_id, provider)
        status = "OK" if ok else "UNAVAILABLE"
        _log.info("  %s %s → %s", provider, model_id, status)
        if ok:
            verified.append(
                {
                    "id": f"{provider}:{model_id}" if provider != "codex" else f"codex:{model_id}",
                    "model": model_id,
                    "name": f"{_PROVIDER_DISPLAY.get(provider, provider)} {c['label']}",
                    "label": c["label"],
                    "type": _PROVIDER_TYPE_MAP.get(provider, "command"),
                    "tier": "paid",
                    "provider": provider,
                    "icon": _PROVIDER_ICON.get(provider, ""),
                    "available": True,
                }
            )
    return verified


def _discover_ollama_models() -> list[dict]:
    """Discover locally installed Ollama models via `ollama list`."""
    if not shutil.which("ollama"):
        return []
    runtime = LocalRuntimeService()
    runtime_env = os.environ.copy()
    runtime_env.update(runtime.provider_env())
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            env=runtime_env,
        )
        if result.returncode != 0:
            return []
        models = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            parts = line.split()
            if not parts:
                continue
            name = parts[0]  # e.g. "llama3.3:latest" or "hf.co/org/model:latest"
            model_id = name.split(":")[0] if ":" in name else name
            size = parts[2] if len(parts) >= 3 else ""

            # Detect HuggingFace-sourced models
            is_hf = model_id.startswith("hf.co/")
            if is_hf:
                hf_path = model_id[len("hf.co/"):]
                display = hf_path.split("/")[-1].replace("-", " ").replace("_", " ").title()
                prefix = "hf"
            else:
                display = model_id.replace("-", " ").replace("_", " ").title()
                prefix = "ollama"

            if size:
                display = f"{display} ({size})"
            models.append(
                {
                    "id": f"{prefix}:{model_id}",
                    "model": model_id,
                    "name": display,
                    "label": display,
                    "type": "huggingface_local" if is_hf else "ollama",
                    "tier": "free",
                    "provider": prefix,
                    "icon": "",
                    "available": True,
                    "source": "huggingface_hub" if is_hf else "ollama_registry",
                }
            )
        return models
    except Exception:
        return []


def _discover_codex_default_model() -> str | None:
    """Read codex config to detect the user's configured default model."""
    config_path = os.path.expanduser("~/.codex/config.toml")
    try:
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("model") and "=" in line:
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return val
    except FileNotFoundError:
        pass
    return None


# ── Cached probed results ─────────────────────────────────────────

_probed_models: list[dict] | None = None
_cli_versions: dict[str, str] = {}


def probe_all_models() -> list[dict]:
    """Probe all providers and build the complete verified model list.

    Results are cached after the first run.
    """
    global _probed_models, _cli_versions

    _log.info("=== Colosseum model probe starting ===")

    # Check CLI versions
    for cli_name in ("claude", "codex", "gemini", "ollama"):
        v = _get_cli_version(cli_name)
        if v:
            _cli_versions[cli_name] = v
            _log.info("CLI %-8s version: %s", cli_name, v)
        else:
            _log.warning("CLI %-8s not found", cli_name)

    all_models: list[dict] = []
    seen: set[str] = set()

    # Probe paid providers
    for provider in ("claude", "codex", "gemini"):
        verified = probe_provider_models(provider)
        for m in verified:
            if m["id"] not in seen:
                all_models.append(m)
                seen.add(m["id"])

    # Codex default model
    codex_default = _discover_codex_default_model()
    if codex_default:
        codex_id = f"codex:{codex_default}"
        if codex_id not in seen:
            idx = next(
                (i for i, m in enumerate(all_models) if m.get("provider") == "codex"),
                len(all_models),
            )
            all_models.insert(
                idx,
                {
                    "id": codex_id,
                    "model": codex_default,
                    "name": codex_default,
                    "label": codex_default,
                    "type": "codex_cli",
                    "tier": "paid",
                    "provider": "codex",
                    "icon": "",
                    "available": True,
                },
            )
            seen.add(codex_id)

    # Ollama
    ollama_models = _discover_ollama_models()
    if ollama_models:
        for m in ollama_models:
            if m["id"] not in seen:
                all_models.append(m)
                seen.add(m["id"])
    else:
        for m in _FALLBACK_MODELS:
            if m["tier"] == "free" and m["id"] not in seen:
                installed = shutil.which("ollama") is not None
                all_models.append({**m, "available": installed, "provider": "ollama", "icon": ""})
                seen.add(m["id"])

    _probed_models = all_models
    _log.info("=== Model probe complete: %d models available ===", len(all_models))
    return all_models


def discover_models() -> list[dict]:
    """Return probed models if available, otherwise build from fallback.

    Ollama models are always re-checked live so newly started runtimes or
    newly pulled models are reflected without a full server restart.
    """
    if _probed_models is not None:
        # Start from probed paid models; re-check Ollama live every call.
        paid = [m for m in _probed_models if m.get("tier") != "free"]
        seen_ids = {m["id"] for m in paid}
        ollama_models = _discover_ollama_models()
        if ollama_models:
            for m in ollama_models:
                if m["id"] not in seen_ids:
                    paid.append(m)
                    seen_ids.add(m["id"])
        return paid

    # Fast fallback (probing hasn't completed yet)
    models: list[dict] = []
    seen_ids: set[str] = set()

    for m in _FALLBACK_MODELS:
        if m["tier"] != "paid":
            continue
        cli_name = m["id"].split(":")[0]
        installed = (
            shutil.which(cli_name) is not None
            if cli_name != "codex"
            else shutil.which("codex") is not None
        )
        entry = {**m, "available": installed}
        models.append(entry)
        seen_ids.add(m["id"])

    ollama_models = _discover_ollama_models()
    if ollama_models:
        for m in ollama_models:
            if m["id"] not in seen_ids:
                m["available"] = True
                models.append(m)
                seen_ids.add(m["id"])
    else:
        for m in _FALLBACK_MODELS:
            if m["tier"] == "free" and m["id"] not in seen_ids:
                installed = shutil.which("ollama") is not None
                models.append({**m, "available": installed})
                seen_ids.add(m["id"])

    return models


def get_cli_versions() -> dict[str, str]:
    """Return cached CLI version info."""
    return dict(_cli_versions)


# Eagerly build initial model list (fast — no network calls)
MODELS = _FALLBACK_MODELS[:]
_MODEL_MAP = {m["id"]: m for m in MODELS}

# ── CLI tool auth info ───────────────────────────────────────────

CLI_AUTH_INFO = {
    "claude": {
        "cmd": "claude",
        "login": "claude login",
        "auth": "OAuth (Anthropic account)",
        "billing": "Uses your Claude Pro / Team / Enterprise subscription. No separate API charges.",
        "install_cmd": "npm install -g @anthropic-ai/claude-code",
        "install_requires": "npm",
        "auth_check_cmd": ["claude", "--version"],
    },
    "codex": {
        "cmd": "codex",
        "login": "codex login",
        "auth": "OAuth (OpenAI account)",
        "billing": "Uses your ChatGPT Plus / Pro subscription. No separate API charges.",
        "install_cmd": "npm install -g @openai/codex",
        "install_requires": "npm",
        "auth_check_cmd": ["codex", "--version"],
    },
    "gemini": {
        "cmd": "gemini",
        "login": "gemini login",
        "auth": "OAuth (Google account)",
        "billing": "Free tier available. Or uses Google AI Studio / One AI Premium. No separate API charges.",
        "install_cmd": "npm install -g @google/gemini-cli",
        "install_requires": "npm",
        "auth_check_cmd": ["gemini", "--version"],
    },
    "ollama": {
        "cmd": "ollama",
        "login": None,
        "auth": "None (runs locally)",
        "billing": "Completely free. Models run on your local hardware.",
        "install_cmd": "curl -fsSL https://ollama.com/install.sh | sh",
        "install_requires": None,
        "auth_check_cmd": ["ollama", "--version"],
    },
    "llmfit": {
        "cmd": "llmfit",
        "login": None,
        "auth": "None (local hardware analysis)",
        "billing": "Completely free. Analyzes local GPU/CPU to determine which models can run.",
        "install_cmd": "curl -fsSL https://raw.githubusercontent.com/AlexsJones/llmfit/main/install.sh | sh",
        "install_requires": None,
        "auth_check_cmd": ["llmfit", "--version"],
        "auto_install": True,  # Install automatically during setup — no prompt needed
    },
}


def _print_header():
    print(f"\n{GOLD}{BOLD}  COLOSSEUM{RST} {DIM}— AI Debate Arena{RST}\n")


def _wrap(text: str, indent: int = 4, width: int = 76) -> str:
    return textwrap.fill(
        text, width=width, initial_indent=" " * indent, subsequent_indent=" " * indent
    )


# ── Subcommands ──────────────────────────────────────────────────


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the web UI server."""
    from colosseum.main import run

    _print_header()
    print(f"  Starting web server on {CYAN}http://127.0.0.1:8000{RST}")
    print(f"  Press {DIM}Ctrl+C{RST} to stop.\n")
    run()


def cmd_models(_args: argparse.Namespace) -> None:
    """List all available models."""
    _print_header()
    print(f"  {BOLD}Available Gladiators{RST}\n")

    models = discover_models()

    # Paid
    print(f"  {GOLD}Premium (CLI subscription){RST}")
    for m in models:
        if m["tier"] != "paid":
            continue
        cli_name = m["id"].split(":")[0]
        if cli_name == "codex":
            avail = shutil.which("codex") is not None
        else:
            avail = shutil.which(cli_name) is not None
        mark = f"{GREEN}+{RST}" if avail else f"{RED}x{RST}"
        print(f"    {mark} {BOLD}{m['id']}{RST}  {DIM}{m['name']}{RST}")

    # Free
    print(f"\n  {CYAN}Open-Source (Local){RST}")
    for m in models:
        if m["tier"] != "free":
            continue
        avail = shutil.which("ollama") is not None
        mark = f"{GREEN}+{RST}" if avail else f"{RED}x{RST}"
        print(f"    {mark} {BOLD}{m['id']}{RST}  {DIM}{m['name']}{RST}")

    print(f"\n  {DIM}+ = CLI found in PATH,  x = not found{RST}\n")


def _print_local_runtime_status(status) -> None:
    print(f"\n  {BOLD}Managed Local Runtime{RST}")
    print(f"  Host: {CYAN}{status.settings.host}{RST}")
    print(
        f"  Ollama installed: {GREEN if status.ollama_installed else RED}{status.ollama_installed}{RST}"
    )
    if status.ollama_version:
        print(f"  Version: {DIM}{status.ollama_version}{RST}")
    print(
        f"  Runtime running: {GREEN if status.runtime_running else GOLD}{status.runtime_running}{RST}"
    )
    print(
        f"  GPU setting: {DIM}{'auto' if status.settings.selected_gpu_indices is None else status.settings.selected_gpu_indices}{RST}"
    )
    if status.gpu_devices:
        print(f"  GPUs detected: {len(status.gpu_devices)}")
        for device in status.gpu_devices:
            memory = (
                f"{device.memory_total_mb} MB" if device.memory_total_mb is not None else "unknown"
            )
            print(f"    - [{device.index}] {device.name} ({memory})")
    else:
        print("  GPUs detected: 0")
    if status.installed_models_known:
        print(f"  Installed models: {', '.join(status.installed_models[:8]) or '(none)'}")
    else:
        print("  Installed models: unknown (runtime not started yet)")
    if status.runtime_note:
        print(f"  Note: {DIM}{status.runtime_note}{RST}")
    print()


def cmd_local_runtime(args: argparse.Namespace) -> None:
    """Inspect and manage the dedicated runtime Colosseum uses for local models."""
    service = LocalRuntimeService()
    action = args.local_command or "status"

    if action == "status":
        _print_local_runtime_status(service.get_status(ensure_ready=args.ensure_ready))
        return

    if action == "configure":
        update_kwargs: dict[str, object] = {"restart_runtime": not args.no_restart}
        if args.auto_gpu:
            update_kwargs["selected_gpu_indices"] = None
        elif args.cpu_only:
            update_kwargs["selected_gpu_indices"] = []
        elif args.gpu_count is not None:
            update_kwargs["selected_gpu_indices"] = list(range(args.gpu_count))
        _print_local_runtime_status(
            service.update_settings(LocalRuntimeConfigUpdate(**update_kwargs))
        )
        return

    if action == "pull":
        result = service.download_model(args.model)
        print(f"\n  {(GREEN if result.success else RED)}{result.message}{RST}\n")
        _print_local_runtime_status(result.status)
        return

    raise ValueError(f"Unsupported local runtime command: {action}")


def cmd_hf(args: argparse.Namespace) -> None:
    """HuggingFace Hub model operations."""
    from colosseum.core.models import HFRegisterRequest
    from colosseum.services.hf_hub import HuggingFaceHubService

    service = HuggingFaceHubService()
    action = args.hf_command or "list"

    if action == "search":
        _print_header()
        print(f"  {BOLD}Searching HuggingFace Hub for '{args.query}'...{RST}\n")
        result = service.search(args.query, limit=args.limit)
        if not result.results:
            print(f"  {DIM}No GGUF models found.{RST}\n")
            return
        for i, m in enumerate(result.results, 1):
            print(f"    {DIM}{i:>2}.{RST} {BOLD}{m.repo_id}{RST}  {DIM}{m.downloads:,} downloads{RST}")
        print(f"\n  {DIM}Pull with: colosseum hf pull <repo_id>{RST}\n")
        return

    if action == "pull":
        _print_header()
        print(f"  Pulling {CYAN}hf.co/{args.repo_id}{RST} ...")
        result = service.pull(args.repo_id)
        color = GREEN if result.success else RED
        print(f"\n  {color}{result.message}{RST}\n")
        return

    if action == "list":
        _print_header()
        hf_models = service.list_hf_models()
        if not hf_models:
            print(
                f"  {DIM}No HuggingFace models installed."
                f" Use 'colosseum hf pull <org/model>' to add one.{RST}\n"
            )
            return
        print(f"  {BOLD}Installed HuggingFace Models{RST}\n")
        for m in hf_models:
            print(f"    {GREEN}+{RST} {BOLD}{m}{RST}")
        print()
        return

    if action == "register":
        _print_header()
        print(f"  Registering {CYAN}{args.path}{RST} as {BOLD}{args.name}{RST}\n")
        result = service.register_model(
            HFRegisterRequest(name=args.name, model_path=args.path)
        )
        color = GREEN if result.success else RED
        print(f"  {color}{result.message}{RST}")
        if result.gguf_path:
            print(f"  {DIM}GGUF: {result.gguf_path}{RST}")
        print()
        return

    if action == "tools":
        _print_header()
        tools = service.conversion_tools_available()
        print(f"  {BOLD}Conversion Tools{RST}\n")
        for name, path in tools.items():
            status = f"{GREEN}found{RST} → {path}" if path else f"{RED}not found{RST}"
            print(f"    {name}: {status}")
        print(f"\n  {DIM}Set LLAMA_CPP_DIR or add tools to PATH.{RST}\n")
        return


def cmd_personas(_args: argparse.Namespace) -> None:
    """List available personas."""
    from colosseum.personas.loader import PersonaLoader

    _print_header()
    loader = PersonaLoader()
    personas = loader.list_personas()
    if not personas:
        print("  No personas found.\n")
        return

    print(f"  {BOLD}Available Personas{RST}\n")
    for p in personas:
        source_tag = f"{GOLD}builtin{RST}" if p["source"] == "builtin" else f"{CYAN}custom{RST}"
        print(
            f"    [{source_tag}] {BOLD}{p['persona_id']}{RST}  {DIM}{p.get('description', '')}{RST}"
        )


def _obj_value(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _persona_label(obj) -> str:
    persona_label = _obj_value(obj, "persona_label")
    if persona_label:
        return str(persona_label)
    persona_name = _obj_value(obj, "persona_name")
    if persona_name:
        return str(persona_name)
    persona_id = str(_obj_value(obj, "persona_id") or "").strip()
    if not persona_id:
        return ""
    if persona_id == "__custom__":
        return "Custom Persona"
    return humanize_identifier(persona_id)


def _display_label(obj) -> str:
    display_label = _obj_value(obj, "display_label")
    if display_label:
        return str(display_label)
    display_name = str(_obj_value(obj, "display_name") or _obj_value(obj, "agent_id") or "?")
    persona = _persona_label(obj)
    if not persona or persona.lower() in display_name.lower():
        return display_name
    return f"{display_name} [{persona}]"


def _plan_display_label(run: ExperimentRun, plan) -> str:
    agent = next((item for item in run.agents if item.agent_id == plan.agent_id), None)
    return _display_label(agent) if agent else plan.display_name


def cmd_history(_args: argparse.Namespace) -> None:
    """List past battles."""
    from colosseum.bootstrap import get_orchestrator

    _print_header()
    orch = get_orchestrator()
    runs = orch.list_runs()
    if not runs:
        print("  No battles fought yet.\n")
        return

    completed = sum(1 for r in runs if r.status == RunStatus.COMPLETED)
    failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
    total_tokens = sum(r.total_tokens for r in runs)

    print(
        f"  {BOLD}Past Battles{RST}  {DIM}({len(runs)} total: {completed} completed, {failed} failed, {total_tokens} tok){RST}\n"
    )
    for r in runs:
        status_color = GREEN if r.status == RunStatus.COMPLETED else RED if r.status == RunStatus.FAILED else GOLD
        verdict = r.verdict_type or "pending"
        print(
            f"    {DIM}{r.run_id[:8]}{RST}  "
            f"{status_color}{r.status:<10}{RST}  "
            f"{BOLD}{r.task_title[:50]}{RST}  "
            f"{DIM}{verdict} · {r.total_tokens} tok{RST}"
        )
    print()


def cmd_show(args: argparse.Namespace) -> None:
    """Show a past battle result."""
    from colosseum.bootstrap import get_orchestrator

    _print_header()
    orch = get_orchestrator()
    try:
        run = orch.load_run(args.run_id)
    except FileNotFoundError:
        print(f"  {RED}Run not found: {args.run_id}{RST}\n")
        sys.exit(1)

    print(f"  {BOLD}Battle: {run.task.title}{RST}")
    print(f"  {DIM}Run ID: {run.run_id}{RST}")
    total_tok = run.budget_ledger.total.total_tokens
    budget_tok = run.budget_policy.total_token_budget
    budget_pct = f"{total_tok / budget_tok * 100:.0f}%" if budget_tok > 0 else "n/a"
    print(
        f"  {DIM}Status: {run.status}  Agents: {len(run.agents)}  Rounds: {len(run.debate_rounds)}  Tokens: {total_tok}/{budget_tok} ({budget_pct}){RST}\n"
    )

    # Plans
    if run.plans:
        print(f"  {GOLD}{BOLD}Plans{RST}")
        scores = {e.plan_id: e.overall_score for e in (run.plan_evaluations or [])}
        for p in run.plans:
            score = scores.get(p.plan_id, 0.0)
            print(f"    {BOLD}{_plan_display_label(run, p)}{RST}  score={score:.2f}")
            print(_wrap(p.summary, indent=6))
        print()

    # Debate rounds
    for dr in run.debate_rounds:
        print(
            f"  {CYAN}{BOLD}Round {dr.index}: {dr.round_type}{RST}  {DIM}{dr.usage.total_tokens} tok{RST}"
        )
        if dr.summary.key_disagreements:
            print(f"    Disagreements: {', '.join(dr.summary.key_disagreements[:3])}")
        if dr.summary.moderator_note:
            print(_wrap(dr.summary.moderator_note, indent=4))
        print()

    # Verdict
    if run.verdict:
        v = run.verdict
        vtype_color = MAGENTA if v.verdict_type.value == "merged" else GOLD
        print(f"  {vtype_color}{BOLD}Verdict: {v.verdict_type.upper()}{RST}")
        if run.final_report and run.final_report.final_answer:
            print(f"    {CYAN}Answer:{RST}")
            print(_wrap(run.final_report.final_answer, indent=6))
        print(_wrap(v.rationale, indent=4))
        if v.selected_strengths:
            print(f"    {GREEN}Strengths:{RST} {', '.join(v.selected_strengths[:4])}")
        if v.rejected_risks:
            print(f"    {RED}Risks:{RST} {', '.join(v.rejected_risks[:3])}")
        if v.synthesized_plan:
            print(f"    {MAGENTA}Merged Plan:{RST}")
            print(_wrap(v.synthesized_plan.summary, indent=6))
        print(f"    {DIM}Confidence: {v.confidence:.2f}  Stop: {v.stop_reason}{RST}")

    # Token usage summary
    if run.budget_ledger.by_actor:
        print(f"\n  {DIM}Token usage:{RST}")
        for actor_id, usage in run.budget_ledger.by_actor.items():
            agent = next((a for a in run.agents if a.agent_id == actor_id), None)
            name = _display_label(agent) if agent else actor_id
            print(f"    {DIM}{name}: {usage.total_tokens} tok{RST}")
    print()


def cmd_delete(args: argparse.Namespace) -> None:
    """Delete a past battle run."""
    import shutil as _shutil
    from colosseum.core.config import ARTIFACT_ROOT

    _print_header()
    run_id = args.run_id

    if run_id == "all":
        if not ARTIFACT_ROOT.exists():
            print(f"  {DIM}No runs to delete.{RST}\n")
            return
        count = sum(1 for _ in ARTIFACT_ROOT.glob("*/run.json"))
        if count == 0:
            print(f"  {DIM}No runs to delete.{RST}\n")
            return
        if not getattr(args, "yes", False):
            confirm = input(f"  Delete all {count} run(s)? [y/N] ").strip().lower()
            if confirm != "y":
                print(f"  {DIM}Aborted.{RST}\n")
                return
        _shutil.rmtree(ARTIFACT_ROOT)
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        print(f"  {GREEN}Deleted all {count} run(s).{RST}\n")
        return

    # Find run directory
    run_dir = ARTIFACT_ROOT / run_id
    if not run_dir.exists():
        matches = sorted(ARTIFACT_ROOT.glob(f"{run_id}*/run.json"))
        if not matches:
            print(f"  {RED}Run not found: {run_id}{RST}\n")
            sys.exit(1)
        if len(matches) > 1:
            print(f"  {RED}Ambiguous prefix '{run_id}'. Matches: {len(matches)} runs.{RST}\n")
            sys.exit(1)
        run_dir = matches[0].parent

    _shutil.rmtree(run_dir)
    print(f"  {GREEN}Deleted run {run_dir.name[:8]}...{RST}\n")


# ── Auth status cache ───────────────────────────────────────────
#
# The auth probe (`claude -p "say ok"`, etc.) takes up to 30s per provider,
# so `colosseum setup` without a cache takes ~2 minutes on a fresh shell.
# We cache the probe result per tool in ~/.colosseum/auth_cache.json with a
# 24-hour TTL. Install (`shutil.which`) and version checks are cheap and
# always run fresh; only the probe is cached.

_AUTH_CACHE_TTL_SECONDS = 24 * 3600


def _auth_cache_path():
    from pathlib import Path

    return Path.home() / ".colosseum" / "auth_cache.json"


def _load_auth_cache() -> dict:
    path = _auth_cache_path()
    if not path.exists():
        return {}
    try:
        import json as _json

        with path.open(encoding="utf-8") as fh:
            data = _json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_auth_cache(cache: dict) -> None:
    path = _auth_cache_path()
    try:
        import json as _json

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            _json.dump(cache, fh, indent=2)
    except Exception:
        pass


def _get_cached_auth(tool_name: str) -> dict | None:
    cache = _load_auth_cache()
    entry = cache.get(tool_name)
    if not isinstance(entry, dict):
        return None
    ts = entry.get("timestamp", 0)
    if time.time() - ts > _AUTH_CACHE_TTL_SECONDS:
        return None
    return entry


def _set_cached_auth(tool_name: str, auth_ok: bool, auth_detail: str) -> None:
    cache = _load_auth_cache()
    cache[tool_name] = {
        "auth_ok": bool(auth_ok),
        "auth_detail": auth_detail,
        "timestamp": time.time(),
    }
    _save_auth_cache(cache)


def clear_auth_cache() -> None:
    """Public helper: delete the on-disk auth cache file."""
    path = _auth_cache_path()
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _check_tool_status(tool_name: str, info: dict, use_cache: bool = True) -> dict:
    """Check a single CLI tool's install and auth status.

    Returns dict with keys: installed, version, auth_ok, auth_detail.

    When ``use_cache`` is True (default) the expensive auth probe is skipped
    if a fresh entry exists in ``~/.colosseum/auth_cache.json``. Install
    (``shutil.which``) and version checks always run fresh.
    """
    status: dict = {
        "tool": tool_name,
        "installed": False,
        "version": None,
        "auth_ok": False,
        "auth_detail": "",
    }
    found = shutil.which(info["cmd"])
    if not found:
        return status
    status["installed"] = True

    # Version check
    try:
        result = subprocess.run(
            info["auth_check_cmd"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        version = result.stdout.strip() or result.stderr.strip()
        if version:
            status["version"] = version[:120]
    except Exception:
        pass

    # Auth check: for tools with login, try a trivial call to see if authenticated.
    if info.get("login"):
        # Fast path: reuse a recent probe result if still valid.
        if use_cache:
            cached = _get_cached_auth(tool_name)
            if cached is not None:
                status["auth_ok"] = bool(cached.get("auth_ok"))
                status["auth_detail"] = cached.get("auth_detail", "") or "cached"
                return status

        # Strip Claude Code nesting vars so the probe isn't blocked by nested-session guard
        probe_env = {**os.environ}
        for _k in ("CLAUDECODE", "CLAUDE_CODE"):
            probe_env.pop(_k, None)

        try:
            if tool_name == "claude":
                probe = subprocess.run(
                    ["claude", "-p", "say ok"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=probe_env,
                )
            elif tool_name == "codex":
                probe = subprocess.run(
                    ["codex", "exec", "say ok"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=probe_env,
                )
            elif tool_name == "gemini":
                probe = subprocess.run(
                    ["gemini", "-p", "say ok"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=probe_env,
                )
            else:
                probe = None

            if probe and probe.returncode == 0 and probe.stdout.strip():
                status["auth_ok"] = True
                status["auth_detail"] = "authenticated"
            elif probe:
                combined = (probe.stdout + probe.stderr).lower()
                if (
                    "login" in combined
                    or "auth" in combined
                    or "sign in" in combined
                    or "credentials" in combined
                ):
                    status["auth_detail"] = "not authenticated"
                elif "quota" in combined or "rate" in combined or "limit" in combined:
                    status["auth_ok"] = True
                    status["auth_detail"] = "authenticated (quota limited)"
                else:
                    status["auth_detail"] = "unknown auth status"
        except subprocess.TimeoutExpired:
            status["auth_detail"] = "timeout (may need login)"
        except Exception:
            status["auth_detail"] = "check failed"

        # Persist probe result so the next `setup` / `check` is instant.
        _set_cached_auth(tool_name, status["auth_ok"], status["auth_detail"])
    elif tool_name == "llmfit":
        # llmfit — local binary, no auth or runtime needed
        status["auth_ok"] = status["installed"]
        if not status["installed"]:
            status["auth_detail"] = "not installed"
        else:
            status["auth_detail"] = "installed (no auth required)"
    else:
        # ollama — no auth needed, Colosseum manages a dedicated runtime on demand
        runtime_status = LocalRuntimeService().get_status()
        status["auth_ok"] = status["installed"]
        if not status["installed"]:
            status["auth_detail"] = "not installed"
        elif runtime_status.runtime_running:
            status["auth_detail"] = f"managed runtime running on {runtime_status.settings.host}"
        else:
            status["auth_detail"] = (
                f"managed runtime will auto-start on demand ({runtime_status.settings.host})"
            )

    return status


def _install_tool(tool_name: str, info: dict) -> bool:
    """Attempt to install a CLI tool. Returns True if successful."""
    install_cmd = info["install_cmd"]
    requires = info.get("install_requires")

    # Check prerequisite
    if requires and not shutil.which(requires):
        print(f"    {RED}Prerequisite '{requires}' not found.{RST}")
        if requires == "npm":
            print(f"    {DIM}Install Node.js first: https://nodejs.org/{RST}")
        return False

    print(f"    {DIM}Running: {install_cmd}{RST}")
    try:
        result = subprocess.run(
            install_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            # Verify installation
            if shutil.which(info["cmd"]):
                print(f"    {GREEN}Installed successfully.{RST}")
                return True
            else:
                print(f"    {GOLD}Install completed but '{info['cmd']}' not found in PATH.{RST}")
                print(
                    f"    {DIM}You may need to restart your shell or add npm global bin to PATH.{RST}"
                )
                return False
        else:
            stderr = result.stderr.strip()[:200]
            print(f"    {RED}Install failed.{RST}")
            if stderr:
                print(f"    {DIM}{stderr}{RST}")
            return False
    except subprocess.TimeoutExpired:
        print(f"    {RED}Install timed out.{RST}")
        return False
    except Exception as e:
        print(f"    {RED}Install error: {e}{RST}")
        return False


def _run_login(tool_name: str, info: dict) -> bool:
    """Run the login command for a tool interactively. Returns True if successful."""
    login_cmd = info.get("login")
    if not login_cmd:
        return True

    print(f"    {CYAN}Running: {login_cmd}{RST}")
    print(f"    {DIM}(This will open an interactive login flow){RST}\n")
    try:
        result = subprocess.run(
            login_cmd.split(),
            timeout=120,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"    {RED}Login timed out.{RST}")
        return False
    except Exception as e:
        print(f"    {RED}Login error: {e}{RST}")
        return False


def cmd_setup(args: argparse.Namespace) -> None:
    """Interactive setup wizard — install CLI tools and authenticate."""
    _print_header()
    print(f"  {BOLD}Setup Wizard{RST}")
    print(f"  {DIM}Checks, installs, and authenticates CLI providers.{RST}\n")

    tools_to_setup = args.tools if args.tools else list(CLI_AUTH_INFO.keys())
    skip_auth = args.skip_auth
    yes_all = args.yes
    use_cache = not getattr(args, "refresh", False)
    if not use_cache:
        clear_auth_cache()
        print(f"  {DIM}Auth cache cleared — re-probing all tools.{RST}\n")

    summary: list[dict] = []

    for tool_name in tools_to_setup:
        if tool_name not in CLI_AUTH_INFO:
            print(f"  {RED}Unknown tool: {tool_name}{RST}\n")
            continue

        info = CLI_AUTH_INFO[tool_name]
        print(f"  {BOLD}{'─' * 50}{RST}")
        print(f"  {GOLD}{BOLD}{tool_name.upper()}{RST}")
        print(f"  {DIM}{info['billing']}{RST}\n")

        # Step 1: Check if installed
        status = _check_tool_status(tool_name, info, use_cache=use_cache)

        if status["installed"]:
            print(f"    {GREEN}✓ Installed{RST}  {DIM}{status['version'] or ''}{RST}")
        else:
            print(f"    {RED}✗ Not installed{RST}")

            # Offer to install (auto_install tools skip the prompt)
            if yes_all or info.get("auto_install"):
                if info.get("auto_install") and not yes_all:
                    print(f"    {DIM}Auto-installing {tool_name}...{RST}")
                do_install = True
            else:
                try:
                    answer = (
                        input(f"    Install {tool_name}? ({info['install_cmd']}) [Y/n] ")
                        .strip()
                        .lower()
                    )
                    do_install = answer in ("", "y", "yes")
                except (EOFError, KeyboardInterrupt):
                    print()
                    do_install = False

            if do_install:
                if _install_tool(tool_name, info):
                    status["installed"] = True
                    # Re-check
                    status = _check_tool_status(tool_name, info)
                else:
                    summary.append(status)
                    print()
                    continue
            else:
                print(f"    {DIM}Skipped.{RST}")
                summary.append(status)
                print()
                continue

        # Step 2: Check authentication
        if not skip_auth and info.get("login"):
            if status["auth_ok"]:
                print(f"    {GREEN}✓ Authenticated{RST}  {DIM}{status['auth_detail']}{RST}")
            else:
                print(f"    {GOLD}⚠ {status['auth_detail'] or 'Not authenticated'}{RST}")

                if yes_all:
                    do_login = True
                else:
                    try:
                        answer = (
                            input(f"    Run '{info['login']}' to authenticate? [Y/n] ")
                            .strip()
                            .lower()
                        )
                        do_login = answer in ("", "y", "yes")
                    except (EOFError, KeyboardInterrupt):
                        print()
                        do_login = False

                if do_login:
                    if _run_login(tool_name, info):
                        print(f"    {GREEN}✓ Login completed.{RST}")
                        status["auth_ok"] = True
                    else:
                        print(f"    {RED}✗ Login failed. Run '{info['login']}' manually.{RST}")
                else:
                    print(f"    {DIM}Skipped. Run '{info['login']}' later to authenticate.{RST}")
        elif tool_name == "ollama" and status["installed"]:
            runtime_status = LocalRuntimeService().get_status()
            if runtime_status.runtime_running:
                print(f"    {GREEN}✓ Running{RST}")
            else:
                print(f"    {GOLD}⚠ Not running.{RST} Start with: {DIM}ollama serve{RST}")

        summary.append(status)
        print()

    # Summary
    print(f"  {BOLD}{'─' * 50}{RST}")
    print(f"  {BOLD}Setup Summary{RST}\n")
    for s in summary:
        installed_mark = f"{GREEN}✓{RST}" if s["installed"] else f"{RED}✗{RST}"
        auth_mark = f"{GREEN}✓{RST}" if s["auth_ok"] else f"{GOLD}–{RST}"
        print(
            f"    {installed_mark} {BOLD}{s['tool']:<10}{RST}  auth: {auth_mark}  {DIM}{s.get('auth_detail', '')}{RST}"
        )

    ready = [s for s in summary if s["installed"] and s["auth_ok"]]
    if ready:
        examples = []
        for s in ready[:2]:
            tool = s["tool"]
            if tool == "ollama":
                examples.append("ollama:llama3.3")
            else:
                first_model = next(
                    (m["id"] for m in MODELS if m["id"].startswith(f"{tool}:")), None
                )
                if first_model:
                    examples.append(first_model)
        if len(examples) >= 2:
            print(f"\n  {GREEN}Ready!{RST} Try:")
            print(f'    colosseum debate -t "Your topic" -g {examples[0]} {examples[1]}')
    elif summary:
        print(
            f"\n  {GOLD}No providers fully ready.{RST} Install and authenticate at least one to get started."
        )
    print()


# ── Quickstart ──────────────────────────────────────────────────


def _default_model_for(tool_name: str) -> str | None:
    """Return the first known ``provider:model`` spec for a tool."""
    if tool_name == "ollama":
        return "ollama:llama3.2"
    for m in MODELS:
        if m["id"].startswith(f"{tool_name}:"):
            return m["id"]
    return None


def _pick_default_gladiators(statuses: list[dict], count: int = 2) -> list[str]:
    """Return up to ``count`` ``provider:model`` specs ready to debate.

    Ordering prefers paid CLIs (better quality) over ollama, but always
    includes ollama as a fallback when nothing else is ready. Tools that are
    installed but not authenticated are ignored.
    """
    preferred_order = ["claude", "codex", "gemini", "ollama"]
    by_tool = {s["tool"]: s for s in statuses}
    picks: list[str] = []
    for tool in preferred_order:
        s = by_tool.get(tool)
        if not s or not s.get("installed") or not s.get("auth_ok"):
            continue
        spec = _default_model_for(tool)
        if spec:
            picks.append(spec)
        if len(picks) >= count:
            break
    return picks


def _prompt_yes(message: str, default_yes: bool = True) -> bool:
    """Ask a yes/no question; treat EOF/ctrl-c as 'no'."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"    {message} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default_yes
    return answer in ("y", "yes")


def cmd_quickstart(args: argparse.Namespace) -> None:
    """One-command onboarding: pick the fastest path to a working debate.

    Unlike ``colosseum setup``, which walks through every provider, this
    command finds a single ready provider (or guides the user through one)
    and prints a copy-pasteable debate command.
    """
    _print_header()
    print(f"  {BOLD}Quickstart{RST}  {DIM}— fastest path to your first debate{RST}\n")

    if getattr(args, "refresh", False):
        clear_auth_cache()
        print(f"  {DIM}Auth cache cleared — re-probing.{RST}\n")

    # Fast scan (uses cache — typically ~1s on a warm run).
    statuses = get_all_tool_statuses(use_cache=not getattr(args, "refresh", False))
    ready = [s for s in statuses if s["installed"] and s["auth_ok"]]
    ready_tools = {s["tool"] for s in ready}

    print(f"  {BOLD}Current state{RST}")
    for s in statuses:
        if s["tool"] == "llmfit":
            continue
        mark = (
            f"{GREEN}ready{RST}"
            if s["installed"] and s["auth_ok"]
            else f"{GOLD}not ready{RST}"
        )
        detail = s.get("auth_detail", "") or ""
        print(f"    {BOLD}{s['tool']:<8}{RST}  {mark}  {DIM}{detail}{RST}")
    print()

    # Path A — already enough to debate.
    debate_ready_tools = ready_tools - {"llmfit"}
    if len(debate_ready_tools) >= 2:
        picks = _pick_default_gladiators(statuses, count=2)
        print(f"  {GREEN}✓ You already have {len(debate_ready_tools)} providers ready.{RST}\n")
        print("  Try your first debate:\n")
        print(f'    {CYAN}colosseum debate -t "Should we use microservices?" -g {" ".join(picks)}{RST}\n')
        print(
            f"  {DIM}Or omit -g and Colosseum will auto-pick defaults:{RST}\n"
            f'    {CYAN}colosseum debate -t "..."{RST}\n'
        )
        return

    # Path B — exactly one paid CLI authed. Offer to add a free local partner.
    paid_ready = debate_ready_tools - {"ollama"}
    if len(paid_ready) == 1 and "ollama" not in debate_ready_tools:
        only_tool = next(iter(paid_ready))
        print(f"  {GREEN}✓ {only_tool} is ready.{RST}")
        print(
            f"  {DIM}A debate needs 2 gladiators. Ollama is free and needs no login.{RST}\n"
        )
        if _prompt_yes("Install Ollama (free, runs locally) to pair with " + only_tool + "?"):
            info = CLI_AUTH_INFO["ollama"]
            if _install_tool("ollama", info):
                print(f"    {GREEN}Ollama installed.{RST}")
                print(
                    f"    {DIM}Pull a small model with: {RST}colosseum local-runtime pull llama3.2\n"
                )
            else:
                print(
                    f"    {GOLD}Ollama install failed — run manually: {info['install_cmd']}{RST}\n"
                )
        else:
            print(
                f"    {DIM}Skipped. You can still test with: {RST}"
                f"{CYAN}colosseum debate --mock -t \"...\"{RST}\n"
            )
        return

    # Path C — nothing ready. Recommend a single simplest path.
    print(f"  {GOLD}No provider ready yet.{RST} Pick {BOLD}one{RST} to get started:\n")
    print(f"    {BOLD}1){RST} {CYAN}Ollama{RST}   {DIM}(free, no login, runs locally){RST}")
    print(
        f"    {BOLD}2){RST} {CYAN}Claude{RST}   "
        f"{DIM}(needs Node.js + Claude Pro/Max account){RST}"
    )
    print(
        f"    {BOLD}3){RST} {CYAN}Codex{RST}    "
        f"{DIM}(needs Node.js + ChatGPT Plus/Pro account){RST}"
    )
    print(
        f"    {BOLD}4){RST} {CYAN}Gemini{RST}   "
        f"{DIM}(needs Node.js + Google account, free tier available){RST}\n"
    )
    try:
        choice = input("    Choose 1–4 (default 1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        print()
        return

    choice_map = {"1": "ollama", "2": "claude", "3": "codex", "4": "gemini"}
    picked_tool = choice_map.get(choice)
    if not picked_tool:
        print(f"    {RED}Invalid choice: {choice}{RST}\n")
        return

    info = CLI_AUTH_INFO[picked_tool]
    print(f"\n  {BOLD}Setting up {picked_tool}{RST}\n")

    # Install if missing.
    if not shutil.which(info["cmd"]):
        if not _install_tool(picked_tool, info):
            print(
                f"    {GOLD}Install did not complete. Try manually:{RST} "
                f"{info['install_cmd']}\n"
            )
            return

    # Login if the tool supports it.
    if info.get("login"):
        print(f"\n    {DIM}Launching interactive login...{RST}")
        if not _run_login(picked_tool, info):
            print(
                f"    {GOLD}Login incomplete. Run '{info['login']}' when ready, "
                f"then re-run {BOLD}colosseum quickstart{RST}{GOLD}.{RST}\n"
            )
            return

    # Re-probe (bypass cache — state just changed).
    clear_auth_cache()
    final = _check_tool_status(picked_tool, info, use_cache=False)
    if final.get("auth_ok"):
        print(f"    {GREEN}✓ {picked_tool} ready.{RST}\n")
        spec = _default_model_for(picked_tool) or f"{picked_tool}:default"
        print(f"  {BOLD}Try your first debate:{RST}")
        print(
            f'    {CYAN}colosseum debate -t "Your topic" -g {spec} mock:beta{RST}  '
            f"{DIM}(one real + one mock){RST}"
        )
        print(
            f"  {DIM}Or add ollama (no login) for a free second gladiator:{RST}\n"
            f"    {CYAN}colosseum quickstart{RST}  "
            f"{DIM}(re-run, choose 1 this time){RST}\n"
        )
    else:
        print(
            f"    {GOLD}{picked_tool} still not ready: "
            f"{final.get('auth_detail', 'unknown')}{RST}\n"
        )


def get_all_tool_statuses(use_cache: bool = True) -> list[dict]:
    """Return install/auth status for all CLI tools (used by API)."""
    statuses = []
    for tool_name, info in CLI_AUTH_INFO.items():
        status = _check_tool_status(tool_name, info, use_cache=use_cache)
        status["login_cmd"] = info.get("login")
        status["install_cmd"] = info.get("install_cmd", "")
        status["billing"] = info.get("billing", "")
        statuses.append(status)
    return statuses


def cmd_check(args: argparse.Namespace) -> None:
    """Verify CLI tool availability and auth status."""
    _print_header()
    print(f"  {BOLD}CLI Tool Check{RST}\n")

    if getattr(args, "refresh", False):
        clear_auth_cache()
        print(f"  {DIM}Auth cache cleared — re-probing all tools.{RST}\n")

    for tool_name, info in CLI_AUTH_INFO.items():
        found = shutil.which(info["cmd"]) is not None
        status = f"{GREEN}FOUND{RST}" if found else f"{RED}NOT FOUND{RST}"

        print(f"  {BOLD}{tool_name}{RST}  [{status}]")
        print(f"    Command:  {info['cmd']}")
        print(f"    Auth:     {info['auth']}")
        print(f"    Billing:  {info['billing']}")
        if info.get("login"):
            print(f"    Login:    {DIM}{info['login']}{RST}")

        if found:
            # Try a quick version check
            try:
                result = subprocess.run(
                    [info["cmd"], "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.strip() or result.stderr.strip()
                if version:
                    print(f"    Version:  {DIM}{version[:80]}{RST}")
            except Exception:
                pass
        print()

    print(f"  {BOLD}Summary:{RST}")
    print(f"    All CLI tools (claude, codex, gemini) use your {GOLD}existing subscription{RST}.")
    print(
        f"    They authenticate via OAuth to your account — {GREEN}no separate API key charges{RST}."
    )
    print(f"    Ollama runs models {CYAN}locally{RST} on your hardware for free.\n")


def _parse_gladiator(spec: str) -> dict:
    """Parse a gladiator spec like 'claude:claude-sonnet-4-6' or 'ollama:llama3.3'.

    Returns an AgentConfig-compatible dict.
    """
    if spec in _MODEL_MAP:
        m = _MODEL_MAP[spec]
        provider, model = spec.split(":", 1)
        ptype = m["type"]
        agent = {
            "agent_id": provider,
            "display_name": m["name"],
            "specialty": m["name"],
            "provider": {"type": ptype, "model": model},
        }
        if ptype in ("ollama", "huggingface_local"):
            agent["provider"]["ollama_model"] = model
        return agent

    # Custom spec: provider:model
    if ":" in spec:
        provider, model = spec.split(":", 1)
        type_map = {
            "claude": "claude_cli",
            "codex": "codex_cli",
            "gemini": "gemini_cli",
            "ollama": "ollama",
            "hf": "huggingface_local",
            "mock": "mock",
        }
        ptype = type_map.get(provider, "command")
        agent = {
            "agent_id": provider,
            "display_name": f"{provider.title()} ({model})",
            "specialty": model,
            "provider": {"type": ptype, "model": model},
        }
        if ptype in ("ollama", "huggingface_local"):
            agent["provider"]["ollama_model"] = model
        if ptype == "huggingface_local" and not model.startswith("hf.co/"):
            agent["provider"]["hf_model"] = f"hf.co/{model}"
        return agent

    raise ValueError(
        f"Invalid gladiator spec '{spec}'. Use format: provider:model "
        f"(e.g. claude:claude-sonnet-4-6, ollama:llama3.3)"
    )


def _parse_provider_spec(spec: str) -> ProviderConfig:
    """Parse a provider spec like 'claude:claude-opus-4-6' into a ProviderConfig."""
    type_map = {
        "claude": "claude_cli",
        "codex": "codex_cli",
        "gemini": "gemini_cli",
        "ollama": "ollama",
        "hf": "huggingface_local",
        "mock": "mock",
    }
    if ":" not in spec:
        raise ValueError(
            f"Invalid judge spec '{spec}'. Use format: provider:model "
            f"(e.g. claude:claude-opus-4-6)"
        )
    provider, model = spec.split(":", 1)
    ptype = type_map.get(provider, "command")
    kwargs: dict = {"type": ptype, "model": model}
    if ptype in ("ollama", "huggingface_local"):
        kwargs["ollama_model"] = model
    if ptype == "huggingface_local" and not model.startswith("hf.co/"):
        kwargs["hf_model"] = f"hf.co/{model}"
    pricing = _MODEL_PRICING.get(model)
    if pricing:
        kwargs["pricing"] = ProviderPricing(
            prompt_cost_per_1k_tokens=pricing[0],
            completion_cost_per_1k_tokens=pricing[1],
        )
    return ProviderConfig(**kwargs)


def cmd_monitor(args: argparse.Namespace) -> None:
    """Open the live monitor dashboard for an active debate."""
    from colosseum.monitor import run_monitor

    run_id = getattr(args, "run_id", None)
    run_monitor(run_id=run_id)


def _launch_tmux_monitor(run_id: str) -> bool:
    """Split the current tmux pane and launch the monitor in the new pane.

    Returns True if successful, False if not inside tmux.
    """
    if not os.environ.get("TMUX"):
        return False
    try:
        subprocess.Popen(
            [
                "tmux",
                "split-window",
                "-h",
                "-l",
                "70",
                sys.executable,
                "-m",
                "colosseum.monitor",
                run_id,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, OSError):
        return False


def cmd_debate(args: argparse.Namespace) -> None:
    """Run a debate from the terminal."""
    from colosseum.bootstrap import get_orchestrator

    topic = args.topic
    depth = args.depth
    timeout_seconds = args.timeout or 0
    persona_specs = args.personas or []
    json_output = args.json_output
    use_monitor = getattr(args, "monitor", False)
    use_evidence_based_judging = not getattr(args, "disable_evidence_judging", False)
    judge_spec = getattr(args, "judge", None)
    file_paths = getattr(args, "files", None) or []
    dir_path = getattr(args, "dir", None)

    # --mock flag overrides -g
    if args.mock:
        gladiator_specs = ["mock:alpha", "mock:beta"]
    else:
        gladiator_specs = args.gladiators or []

    # Smart default: if -g was omitted, auto-pick from whatever is authed.
    # Uses the auth cache so this is near-instant on a warm run.
    auto_picked = False
    if not gladiator_specs:
        auto_picked = True
        statuses = get_all_tool_statuses(use_cache=True)
        gladiator_specs = _pick_default_gladiators(statuses, count=2)

    if not json_output:
        _print_header()

    if len(gladiator_specs) < 2:
        if json_output:
            import json as _json

            print(
                _json.dumps({"error": f"Need at least 2 gladiators. Got {len(gladiator_specs)}."})
            )
        else:
            if auto_picked:
                print(
                    f"  {GOLD}No authenticated providers found.{RST}\n"
                    f"  Run {CYAN}colosseum quickstart{RST} to set one up,\n"
                    f"  or try {CYAN}colosseum debate --mock -t \"...\"{RST} for a free test.\n"
                )
            else:
                print(f"  {RED}Need at least 2 gladiators. Use -g or --mock.{RST}\n")
        sys.exit(1)

    if auto_picked and not json_output:
        print(
            f"  {DIM}Auto-picked gladiators (override with -g): "
            f"{', '.join(gladiator_specs)}{RST}"
        )

    # Parse gladiators
    agents = []
    for i, spec in enumerate(gladiator_specs):
        try:
            agent = _parse_gladiator(spec)
        except ValueError as e:
            print(f"  {RED}{e}{RST}\n")
            sys.exit(1)

        # Assign persona if provided
        if i < len(persona_specs) and persona_specs[i] != "none":
            from colosseum.personas.loader import PersonaLoader

            loader = PersonaLoader()
            persona = loader.registry.get_persona(persona_specs[i])
            if persona:
                agent["persona_id"] = persona.persona_id
                agent["persona_name"] = persona.name
                agent["persona_content"] = persona.content
            else:
                print(f"  {GOLD}Warning: persona '{persona_specs[i]}' not found, skipping.{RST}")

        # Deduplicate agent_id if same provider used twice
        existing_ids = [a["agent_id"] for a in agents]
        if agent["agent_id"] in existing_ids:
            agent["agent_id"] = f"{agent['agent_id']}_{i}"

        agents.append(agent)

    # Depth profile
    profile = DEPTH_PROFILES.get(depth, DEPTH_PROFILES[3])
    depth_label = DEPTH_LABELS.get(depth, "Standard")

    if not json_output:
        print(f"  {BOLD}Topic:{RST} {topic}")
        print(
            f"  {BOLD}Depth:{RST} {depth} ({depth_label})  {DIM}max {depth} rounds{RST}"
        )
        evidence_policy_label = (
            "Evidence-gated judging"
            if use_evidence_based_judging
            else "Evidence shown, but not used as a hard judging gate"
        )
        judge_label = judge_spec if judge_spec else f"Automated ({evidence_policy_label})"
        print(f"  {BOLD}Judge:{RST} {judge_label}")
        if file_paths or dir_path:
            print(f"  {BOLD}Context:{RST}")
            if dir_path:
                print(f"    {DIM}dir:{RST}  {dir_path}")
            for fp in file_paths:
                print(f"    {DIM}file:{RST} {fp}")
        print(f"  {BOLD}Gladiators:{RST}")
        for a in agents:
            tier_tag = ""
            m = _MODEL_MAP.get(
                f"{a['provider']['type'].replace('_cli', '')}:{a['provider']['model']}"
            )
            if not m:
                ptype = a["provider"]["type"]
                tier_tag = (
                    f" {DIM}(free){RST}" if ptype in ("mock", "ollama", "huggingface_local") else ""
                )
            else:
                tier_tag = f" {DIM}({'free' if m['tier'] == 'free' else 'subscription'}){RST}"
            print(f"    {GOLD}{_display_label(a)}{RST}{tier_tag}")
        print()

    # Build context sources
    context_sources: list[ContextSourceInput] = [
        ContextSourceInput(
            source_id="topic",
            kind=ContextSourceKind.INLINE_TEXT,
            label="Debate topic",
            content=topic,
        )
    ]
    if dir_path:
        context_sources.append(
            ContextSourceInput(
                source_id="project_dir",
                kind=ContextSourceKind.LOCAL_DIRECTORY,
                label=os.path.basename(dir_path.rstrip("/\\")) or dir_path,
                path=dir_path,
            )
        )
    for i, fp in enumerate(file_paths):
        context_sources.append(
            ContextSourceInput(
                source_id=f"file_{i}",
                kind=ContextSourceKind.LOCAL_FILE,
                label=os.path.basename(fp),
                path=fp,
            )
        )

    # Build judge config
    if judge_spec and judge_spec.lower() == "human":
        judge_config = JudgeConfig(
            mode=JudgeMode.HUMAN,
            minimum_confidence_to_stop=profile["minimum_confidence_to_stop"],
            use_evidence_based_judging=use_evidence_based_judging,
        )
    elif judge_spec:
        try:
            judge_provider = _parse_provider_spec(judge_spec)
        except ValueError as e:
            print(f"  {RED}{e}{RST}\n")
            sys.exit(1)
        judge_config = JudgeConfig(
            mode=JudgeMode.AI,
            provider=judge_provider,
            minimum_confidence_to_stop=profile["minimum_confidence_to_stop"],
            use_evidence_based_judging=use_evidence_based_judging,
        )
    else:
        judge_config = JudgeConfig(
            mode=JudgeMode.AUTOMATED,
            minimum_confidence_to_stop=profile["minimum_confidence_to_stop"],
            use_evidence_based_judging=use_evidence_based_judging,
        )

    # New optional args
    lang = getattr(args, "lang", None) or "auto"
    internet_search = getattr(args, "internet_search", False)
    task_type_str = getattr(args, "task_type", None)
    task_type = TaskType(task_type_str) if task_type_str else TaskType.RESEARCH_DESIGN
    report_instructions = getattr(args, "report_instructions", None) or ""

    # Build request
    request = RunCreateRequest(
        project_name="Colosseum",
        encourage_internet_search=internet_search,
        response_language=lang,
        report_instructions=report_instructions,
        task=TaskSpec(
            title=topic[:120],
            problem_statement=topic,
            task_type=task_type,
        ),
        context_sources=context_sources,
        agents=agents,
        judge=judge_config,
        budget_policy=BudgetPolicy(
            max_rounds=depth,
            min_rounds=profile["min_rounds"],
            per_round_token_limit=12000,
            per_agent_message_limit=1,
            min_novelty_threshold=profile["min_novelty_threshold"],
            convergence_threshold=profile["convergence_threshold"],
            planning_timeout_seconds=timeout_seconds,
            round_timeout_seconds=timeout_seconds,
        ),
    )

    # Run orchestrator
    orch = get_orchestrator()

    if json_output:
        # Silent mode: run and output JSON
        import json as _json

        run = asyncio.run(_run_debate_live(orch, request, silent=True))
        if not run:
            print(_json.dumps({"error": "Battle failed."}))
            sys.exit(1)
        result = {
            "run_id": run.run_id,
            "status": run.status.value,
            "topic": run.task.title,
            "agents": [
                {"agent_id": a.agent_id, "display_name": a.display_label} for a in run.agents
            ],
            "plans": [
                {
                    "plan_id": p.plan_id,
                    "display_name": p.display_name,
                    "summary": p.summary,
                    "strengths": p.strengths,
                    "weaknesses": p.weaknesses,
                }
                for p in run.plans
            ],
            "evaluations": [
                {"plan_id": e.plan_id, "overall_score": e.overall_score}
                for e in (run.plan_evaluations or [])
            ],
            "debate_rounds": len(run.debate_rounds),
            "total_tokens": run.budget_ledger.total.total_tokens,
        }
        if run.verdict:
            result["verdict"] = _verdict_json_payload(run.verdict)
        if run.final_report:
            result["final_report"] = run.final_report.model_dump(mode="json")
        print(_json.dumps(result, indent=2))
        return

    print(f"  {DIM}{'─' * 60}{RST}")
    print(f"  {GOLD}The arena gates open...{RST}\n")

    # Launch tmux monitor: auto when in tmux, or when --monitor is passed
    _monitor_launched = False
    if use_monitor or os.environ.get("TMUX"):
        # We need to pre-create the run to know the run_id for the monitor.
        # Create a temporary ExperimentRun to get the ID, then pass it through.
        from colosseum.core.models import ExperimentRun as _ER

        _preview_run = _ER(
            project_name=request.project_name,
            encourage_internet_search=request.encourage_internet_search,
            task=request.task,
            agents=request.agents,
            judge=request.judge,
            budget_policy=request.budget_policy,
        )
        _monitor_launched = _launch_tmux_monitor(_preview_run.run_id)
        if _monitor_launched:
            print(f"  {GREEN}Monitor opened in tmux pane{RST}")
            # Patch the request so _run_debate_live uses the same run_id
            request._monitor_run_id = _preview_run.run_id
        elif os.environ.get("TMUX"):
            print(f"  {GOLD}Failed to open tmux monitor{RST}")
        else:
            print(f"  {GOLD}Not inside tmux — run 'colosseum monitor' in a separate terminal{RST}")

    run = asyncio.run(_run_debate_live(orch, request))

    if not run:
        print(f"  {RED}Battle failed.{RST}\n")
        sys.exit(1)


async def _run_debate_live(orch, request, silent: bool = False) -> ExperimentRun | None:
    """Run the debate with live terminal output and event bus."""
    from colosseum.core.models import (
        ExperimentRun,
        JudgeActionType,
    )
    from colosseum.services.event_bus import DebateEventBus

    # If monitor pre-created a run_id, reuse it
    preset_run_id = getattr(request, "_monitor_run_id", None)
    run = ExperimentRun(
        project_name=request.project_name,
        encourage_internet_search=request.encourage_internet_search,
        response_language=request.response_language,
        report_instructions=request.report_instructions,
        paid_provider_policy=request.paid_provider_policy,
        task=request.task,
        agents=request.agents,
        judge=request.judge,
        budget_policy=request.budget_policy,
    )
    if preset_run_id:
        run.run_id = preset_run_id

    # Initialize event bus for monitor
    bus = DebateEventBus(run.run_id)
    bus.emit(
        "debate_start",
        {
            "topic": run.task.title,
            "token_budget": run.budget_policy.total_token_budget,
            "max_rounds": run.budget_policy.max_rounds,
            "agents": [
                {"agent_id": a.agent_id, "display_name": a.display_label} for a in run.agents
            ],
        },
    )

    spinner = _Spinner()
    try:
        # Phase: context
        if not silent:
            _phase("Freezing context...")
        bus.emit(
            "phase", {"phase": "context", "message": "Freezing context...", "status": "planning"}
        )
        run.context_bundle = orch.context_service.freeze(request.context_sources)
        orch.repository.save_run(run)

        # Phase: planning
        if not silent:
            _phase("Generating plans...")
        bus.emit(
            "phase", {"phase": "planning", "message": "Generating plans...", "status": "planning"}
        )
        pending_plans = 0
        run.status = RunStatus.PLANNING
        async for event_type, event_data in orch._generate_plans_streaming(run):
            bus.emit(event_type, event_data)
            if not silent:
                if event_type == "agent_planning":
                    _agent_status(event_data["display_name"], "crafting strategy...")
                    pending_plans += 1
                    spinner.start("Generating plans...")
                elif event_type == "plan_ready":
                    spinner.stop()
                    pending_plans -= 1
                    _agent_plan(event_data)
                    if pending_plans > 0:
                        spinner.start(f"Waiting for {pending_plans} more plan(s)...")
        spinner.stop()

        run.plan_evaluations = orch.judge_service.evaluate_plans(
            run.plans,
            use_evidence_based_judging=run.judge.use_evidence_based_judging,
        )

        # Emit plan scores
        scores = {}
        for ev in run.plan_evaluations:
            plan = next((p for p in run.plans if p.plan_id == ev.plan_id), None)
            scores[ev.plan_id] = {
                "agent_id": plan.agent_id if plan else "",
                "display_name": _plan_display_label(run, plan) if plan else ev.plan_id[:8],
                "score": ev.overall_score,
            }
        bus.emit("plan_scores", {"scores": scores})

        if not silent:
            # Show plan scores
            print(f"\n  {BOLD}Plan Evaluations:{RST}")
            for ev in run.plan_evaluations:
                plan = next((p for p in run.plans if p.plan_id == ev.plan_id), None)
                name = _plan_display_label(run, plan) if plan else ev.plan_id[:8]
                bar = _score_bar(ev.overall_score)
                print(f"    {name}: {bar} {ev.overall_score:.2f}")
            print()

        # === Human Judge Mode ===
        if run.judge.mode == JudgeMode.HUMAN:
            if silent:
                raise ValueError(
                    "Human judge is incompatible with --json mode. "
                    "Use an AI or automated judge when running with --json."
                )
            run.pause_for_human(orch.judge_service.build_human_packet(run))
            orch.repository.save_run(run)
            bus.emit(
                "phase",
                {"phase": "debate", "message": "Awaiting human judge...", "status": "awaiting_human_judge"},
            )
            while run.status == RunStatus.AWAITING_HUMAN_JUDGE:
                _show_human_packet(run)
                action = _prompt_human_judge(run)
                bus.emit(
                    "phase",
                    {"phase": "debate", "message": "Human judge processing...", "status": "debating"},
                )
                run = await orch.continue_human_run(run.run_id, action)
                orch.repository.save_run(run)
                if run.status == RunStatus.COMPLETED:
                    break
                # Rebuild packet after a requested round and loop
            _verdict(run)
            return run

        # Phase: debate rounds
        while True:
            decision = await orch.judge_service.decide(run)
            run.judge_trace.append(decision)

            bus.emit(
                "judge_decision",
                {
                    "action": decision.action.value,
                    "confidence": decision.confidence,
                    "disagreement_level": decision.disagreement_level,
                    "focus": ", ".join(decision.focus_areas[:3]) if decision.focus_areas else "",
                    "next_round_type": decision.next_round_type.value
                    if decision.next_round_type
                    else "",
                    "reasoning": decision.reasoning[:120],
                    "agenda_title": decision.agenda.title if decision.agenda else "",
                    "agenda_question": decision.agenda.question if decision.agenda else "",
                },
            )

            if not silent:
                _judge_decision(decision, len(run.debate_rounds), run.budget_policy.max_rounds)

            if decision.action == JudgeActionType.FINALIZE:
                break

            if not orch.budget_manager.can_start_round(
                run.budget_policy, run.budget_ledger, len(run.debate_rounds) + 1
            ):
                break

            round_type = decision.next_round_type or RoundType.CRITIQUE
            round_idx = len(run.debate_rounds) + 1
            if not silent:
                _phase(f"Round {round_idx}: {round_type.value}")

            bus.emit(
                "debate_round_start",
                {
                    "round_index": round_idx,
                    "round_type": round_type.value,
                },
            )
            bus.emit(
                "phase",
                {
                    "phase": "debate",
                    "message": f"Round {round_idx}: {round_type.value}",
                    "status": "debating",
                },
            )

            run.status = RunStatus.DEBATING
            debate_round = None
            pending_agents = 0
            async for event_type, event_data in orch.debate_engine.run_round_streaming(
                run,
                round_type=round_type,
                agenda=decision.agenda,
                instructions="Focus on the current judge agenda only.",
            ):
                bus.emit(
                    event_type,
                    event_data
                    if isinstance(event_data, dict)
                    else {
                        "round_index": getattr(event_data, "index", 0),
                        "round_type": getattr(event_data, "round_type", ""),
                    },
                )
                if not silent:
                    if event_type == "agent_thinking":
                        _agent_status(
                            event_data["display_name"],
                            f"thinking... (Round {event_data['round_index']})",
                        )
                        pending_agents += 1
                        spinner.start(f"Round {round_idx} — agents debating...")
                    elif event_type == "agent_message":
                        spinner.stop()
                        pending_agents -= 1
                        _agent_message(event_data)
                        if pending_agents > 0:
                            spinner.start(f"Round {round_idx} — waiting for {pending_agents} more...")
                    elif event_type == "round_complete":
                        spinner.stop()
                if event_type == "round_complete":
                    assert isinstance(event_data, DebateRound)
                    debate_round = event_data
                    bus.emit(
                        "round_complete",
                        {
                            "round_index": debate_round.index,
                            "round_type": debate_round.round_type.value,
                            "messages": len(debate_round.messages),
                            "tokens": debate_round.usage.total_tokens,
                        },
                    )

            if debate_round is not None:
                debate_round.adjudication = orch.judge_service.adjudicate_round(run, debate_round)
                run.debate_rounds.append(debate_round)
                if not silent:
                    _round_summary(debate_round)

            bus.emit(
                "budget_update",
                {
                    "total_tokens": run.budget_ledger.total.total_tokens,
                },
            )

            run.updated_at = datetime.now(timezone.utc)
            orch.repository.save_run(run)

        # Phase: verdict
        if not silent:
            _phase("Rendering final verdict...")
        bus.emit(
            "phase",
            {"phase": "verdict", "message": "Rendering final verdict...", "status": "debating"},
        )
        last_decision = run.judge_trace[-1] if run.judge_trace else None
        run.verdict = await orch.judge_service.finalize(run, last_decision)
        run.final_report = await orch.report_synthesizer.synthesize(run)
        run.status = RunStatus.COMPLETED
        run.stop_reason = last_decision.reasoning if last_decision else "judge_finalize"
        run.updated_at = datetime.now(timezone.utc)
        orch.repository.save_run(run)

        # Emit verdict event
        winner_names = []
        for wid in run.verdict.winning_plan_ids if run.verdict else []:
            plan = next((p for p in run.plans if p.plan_id == wid), None)
            winner_names.append(_plan_display_label(run, plan) if plan else wid[:8])
        bus.emit(
            "verdict",
            {
                "verdict_type": run.verdict.verdict_type.value if run.verdict else "none",
                "winners": winner_names,
                "confidence": run.verdict.confidence if run.verdict else 0,
                "stop_reason": run.stop_reason or "",
                "final_answer": run.final_report.final_answer if run.final_report else "",
            },
        )
        bus.emit("phase", {"phase": "complete", "status": "completed"})

        if not silent:
            _verdict(run)
        return run

    except Exception as exc:
        spinner.stop()
        error_msg = str(exc) or type(exc).__name__
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            error_msg = (
                f"Provider timed out: {error_msg}"
                if str(exc)
                else "Provider timed out. Try increasing depth or using faster models."
            )
        if not silent:
            print(f"\n  {RED}Error: {error_msg}{RST}\n")
        bus.emit("error", {"message": error_msg})
        run.status = RunStatus.FAILED
        run.error_message = error_msg
        orch.repository.save_run(run)
        return None


# ── Terminal rendering helpers ───────────────────────────────────


class _Spinner:
    """Async progress spinner shown while models are generating."""

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._active = False

    async def _run(self, label: str) -> None:
        start = time.monotonic()
        i = 0
        try:
            while self._active:
                elapsed = time.monotonic() - start
                frame = self._FRAMES[i % len(self._FRAMES)]
                sys.stdout.write(f"\r      {DIM}{frame} {label} ({elapsed:.0f}s){RST}  ")
                sys.stdout.flush()
                i += 1
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            pass

    def start(self, label: str) -> None:
        self.stop()
        self._active = True
        self._task = asyncio.create_task(self._run(label))

    def stop(self) -> None:
        self._active = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()


def _phase(msg: str):
    print(f"  {GOLD}{BOLD}>> {msg}{RST}")


def _agent_status(name: str, status: str):
    print(f"    {CYAN}{name}{RST} {DIM}{status}{RST}")


def _agent_plan(data: dict):
    name = data.get("display_name", data.get("agent_id", "?"))
    summary = data.get("summary", "")[:120]
    strengths = data.get("strengths", [])[:2]
    print(f"    {GREEN}Plan ready:{RST} {BOLD}{name}{RST}")
    if summary:
        print(_wrap(summary, indent=6))
    if strengths:
        tags = ", ".join(strengths)
        print(f"      {DIM}Strengths: {tags}{RST}")


def _score_bar(score: float, width: int = 20) -> str:
    filled = int(score * width)
    return f"{GOLD}{'|' * filled}{DIM}{'.' * (width - filled)}{RST}"


def _judge_decision(decision, rounds_done: int, max_rounds: int):
    action = decision.action.value
    if action == "finalize":
        color = RED
        label = "FINALIZE"
    elif action == "continue_debate":
        color = GREEN
        label = "CONTINUE"
    else:
        color = BLUE
        label = action.upper()

    print(
        f"\n  {GOLD}[Judge]{RST} {color}{BOLD}{label}{RST}  "
        f"{DIM}({rounds_done}/{max_rounds} rounds, conf={decision.confidence:.2f}){RST}"
    )
    print(_wrap(decision.reasoning, indent=4))


def _agent_message(data: dict):
    name = data.get("display_name", data.get("agent_id", "?"))
    content = data.get("content", "")
    preview = content[:500] + "..." if len(content) > 500 else content
    tokens = data.get("usage", {}).get("total_tokens", 0)
    novelty = data.get("novelty_score")

    print(f"\n    {CYAN}{BOLD}{name}{RST}  {DIM}{tokens} tok{RST}")
    print(_wrap(preview, indent=6))

    stats = []
    if data.get("critique_count"):
        stats.append(f"critiques={data['critique_count']}")
    if data.get("defense_count"):
        stats.append(f"defenses={data['defense_count']}")
    if data.get("concession_count"):
        stats.append(f"concessions={data['concession_count']}")
    if novelty is not None:
        stats.append(f"novelty={novelty:.2f}")
    if stats:
        print(f"      {DIM}{' · '.join(stats)}{RST}")


def _round_summary(dr):
    tok = dr.usage.total_tokens if dr.usage else 0
    print(f"\n    {DIM}Round {dr.index} complete ({len(dr.messages)} msgs, {tok} tok){RST}")
    if dr.summary.key_disagreements:
        print(f"    Disagreements: {', '.join(dr.summary.key_disagreements[:3])}")
    if dr.summary.moderator_note:
        print(_wrap(dr.summary.moderator_note, indent=4))


def _verdict_json_payload(verdict) -> dict[str, object]:
    """Serialize verdict details for machine-readable CLI output."""
    payload: dict[str, object] = {
        "type": verdict.verdict_type.value,
        "winning_plan_ids": verdict.winning_plan_ids,
        "rationale": verdict.rationale,
        "selected_strengths": verdict.selected_strengths,
        "rejected_risks": verdict.rejected_risks,
        "confidence": verdict.confidence,
        "stop_reason": verdict.stop_reason,
    }
    if verdict.synthesized_plan:
        payload["synthesized_plan"] = {"summary": verdict.synthesized_plan.summary}
    return payload


def _compute_agent_stats(run) -> list[dict]:
    """Compute per-agent debate statistics from the run."""
    stats: dict[str, dict] = {}
    for agent in run.agents:
        stats[agent.agent_id] = {
            "name": _display_label(agent),
            "prompt_tok": 0,
            "completion_tok": 0,
            "total_tok": 0,
            "cost": 0.0,
            "critiques": 0,
            "defenses": 0,
            "concessions": 0,
            "hybrids": 0,
            "total_claims": 0,
            "adopted_claims": 0,
            "novelty_scores": [],
        }

    # Accumulate from budget ledger
    for actor_id, usage in run.budget_ledger.by_actor.items():
        if actor_id in stats:
            stats[actor_id]["prompt_tok"] = usage.prompt_tokens
            stats[actor_id]["completion_tok"] = usage.completion_tokens
            stats[actor_id]["total_tok"] = usage.total_tokens
            stats[actor_id]["cost"] = usage.estimated_cost_usd

    # Accumulate from debate round messages
    for dr in run.debate_rounds:
        for msg in dr.messages:
            s = stats.get(msg.agent_id)
            if not s:
                continue
            s["critiques"] += len(msg.critique_points)
            s["defenses"] += len(msg.defense_points)
            s["concessions"] += len(msg.concessions)
            s["hybrids"] += len(msg.hybrid_suggestions)
            s["total_claims"] += len(msg.critique_points) + len(msg.defense_points)
            s["novelty_scores"].append(msg.novelty_score)

        # Count adopted arguments per agent from adjudication
        if dr.adjudication:
            for adopted in dr.adjudication.adopted_arguments:
                s = stats.get(adopted.agent_id)
                if s:
                    s["adopted_claims"] += 1

    result = []
    for stat in stats.values():
        total = stat["total_claims"]
        adopted = stat["adopted_claims"]
        stat["adoption_pct"] = (adopted / total * 100) if total > 0 else 0.0
        scores = stat.pop("novelty_scores")
        stat["novelty_avg"] = sum(scores) / len(scores) if scores else 0.0
        result.append(stat)
    return result


def _verdict(run):
    v = run.verdict
    if not v:
        print(f"\n  {DIM}No verdict rendered.{RST}\n")
        return

    print(f"\n  {'=' * 60}")
    vtype = v.verdict_type.upper()
    color = MAGENTA if v.verdict_type.value == "merged" else GOLD

    # Find winner names
    winner_names = []
    for wid in v.winning_plan_ids:
        plan = next((p for p in run.plans if p.plan_id == wid), None)
        winner_names.append(_plan_display_label(run, plan) if plan else wid[:8])

    print(f"  {color}{BOLD}  VERDICT: {vtype} — {' & '.join(winner_names)}{RST}")
    print(f"  {'=' * 60}")
    if run.final_report and run.final_report.final_answer:
        print(f"  {CYAN}{BOLD}Answer:{RST}")
        print(_wrap(run.final_report.final_answer, indent=4))
        print()
    print(_wrap(v.rationale, indent=4))

    if v.selected_strengths:
        print(f"\n    {GREEN}Strengths:{RST} {', '.join(v.selected_strengths[:4])}")
    if v.rejected_risks:
        print(f"    {RED}Risks:{RST} {', '.join(v.rejected_risks[:3])}")
    if v.synthesized_plan:
        print(f"\n    {MAGENTA}Merged Plan:{RST}")
        print(_wrap(v.synthesized_plan.summary, indent=6))

    # Per-agent detailed statistics
    agent_stats = _compute_agent_stats(run)
    if agent_stats:
        print(f"\n  {BOLD}Agent Statistics{RST}")
        print(f"  {'─' * 58}")
        for stat in agent_stats:
            cost_str = f"${stat['cost']:.4f}"
            print(
                f"    {CYAN}{BOLD}{stat['name']}{RST}"
            )
            print(
                f"      Tokens: {stat['prompt_tok']:,} prompt + {stat['completion_tok']:,} completion"
                f" = {BOLD}{stat['total_tok']:,}{RST}  Cost: {cost_str}"
            )
            parts = []
            if stat["critiques"]:
                parts.append(f"{stat['critiques']} critiques")
            if stat["defenses"]:
                parts.append(f"{stat['defenses']} defenses")
            if stat["concessions"]:
                parts.append(f"{stat['concessions']} concessions")
            if stat["hybrids"]:
                parts.append(f"{stat['hybrids']} hybrid ideas")
            if parts:
                print(f"      Arguments: {' · '.join(parts)}")
            adoption_pct = stat["adoption_pct"]
            novelty_avg = stat["novelty_avg"]
            bar_len = 12
            filled = int(adoption_pct / 100 * bar_len)
            bar = f"{GREEN}{'|' * filled}{DIM}{'.' * (bar_len - filled)}{RST}"
            print(
                f"      Adoption: {bar} {adoption_pct:.0f}%"
                f"  Novelty: {novelty_avg:.2f}"
            )
        print(f"  {'─' * 58}")

    total_tok = run.budget_ledger.total.total_tokens
    total_cost = run.budget_ledger.total.estimated_cost_usd
    budget_tok = run.budget_policy.total_token_budget
    print(f"\n    {DIM}Confidence: {v.confidence:.2f}  Stop: {v.stop_reason}{RST}")
    print(f"    {DIM}Total: {total_tok:,}/{budget_tok:,} tokens  Cost: ${total_cost:.4f}  Run ID: {run.run_id}{RST}\n")


def _show_human_packet(run) -> None:
    """Display the human judge packet for interactive judging."""
    packet = run.human_judge_packet
    if not packet:
        print(f"  {RED}No judge packet available.{RST}")
        return

    print(f"\n  {'═' * 60}")
    print(f"  {GOLD}{BOLD}HUMAN JUDGE — REVIEW REQUIRED{RST}")
    print(f"  {'─' * 60}")

    # Plan cards
    print(f"\n  {BOLD}Plans:{RST}")
    for card in packet.plan_cards:
        bar = _score_bar(card.overall_score)
        print(f"\n    {CYAN}{BOLD}{card.display_name}{RST}  {bar} {card.overall_score:.2f}")
        if card.summary:
            print(_wrap(card.summary[:200], indent=6))
        if card.strengths:
            print(f"      {GREEN}+ {', '.join(card.strengths[:3])}{RST}")
        if card.weaknesses:
            print(f"      {RED}- {', '.join(card.weaknesses[:2])}{RST}")

    # Last debate round summary
    if run.debate_rounds:
        dr = run.debate_rounds[-1]
        print(f"\n  {BOLD}Last round (Round {dr.index} — {dr.round_type.value}):{RST}")
        if dr.summary.key_disagreements:
            for d in dr.summary.key_disagreements[:3]:
                print(f"    {DIM}• {d}{RST}")
        if dr.summary.moderator_note:
            print(_wrap(dr.summary.moderator_note[:160], indent=4))

    # Key disagreements from packet
    if packet.key_disagreements:
        print(f"\n  {BOLD}Key disagreements:{RST}")
        for d in packet.key_disagreements[:4]:
            print(f"    {DIM}• {d}{RST}")

    # Strongest arguments
    if packet.strongest_arguments:
        print(f"\n  {BOLD}Strongest arguments:{RST}")
        for a in packet.strongest_arguments[:3]:
            print(f"    {DIM}• {a}{RST}")

    print(f"\n  {GOLD}{BOLD}Recommended action:{RST} {packet.recommended_action}")
    rounds_left = run.budget_policy.max_rounds - len(run.debate_rounds)
    print(f"  {DIM}Rounds used: {len(run.debate_rounds)}/{run.budget_policy.max_rounds}  ({rounds_left} remaining){RST}")
    print(f"  {'═' * 60}\n")


def _prompt_human_judge(run) -> HumanJudgeActionRequest:
    """Interactive prompt for the human judge to make a decision."""
    packet = run.human_judge_packet
    rounds_left = run.budget_policy.max_rounds - len(run.debate_rounds)

    print(f"  {BOLD}Your decision:{RST}")
    print(f"    {GOLD}1{RST}  Select a winner")
    print(f"    {GOLD}2{RST}  Merge two plans")
    if rounds_left > 0:
        print(f"    {GOLD}3{RST}  Request another debate round  {DIM}({rounds_left} remaining){RST}")
        print(f"    {GOLD}4{RST}  Request targeted revision  {DIM}({rounds_left} remaining){RST}")
    print()

    while True:
        try:
            choice = input(f"  {BOLD}Choice:{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            choice = "1"

        if choice == "1":
            print(f"\n  {BOLD}Select the winning plan:{RST}")
            for i, card in enumerate(packet.plan_cards, 1):
                print(f"    {GOLD}{i}{RST}  {card.display_name}")
            while True:
                try:
                    sel = input(f"  {BOLD}Plan number:{RST} ").strip()
                except (EOFError, KeyboardInterrupt):
                    sel = "1"
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(packet.plan_cards):
                        break
                except ValueError:
                    pass
                print(f"  {RED}Enter a valid number.{RST}")
            winning_id = packet.plan_cards[idx].plan_id
            try:
                reason = input(f"  {DIM}Rationale (optional, Enter to skip):{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                reason = ""
            return HumanJudgeActionRequest(
                action="select_winner",
                winning_plan_ids=[winning_id],
                instructions=reason or None,
            )

        elif choice == "2":
            if len(packet.plan_cards) < 2:
                print(f"  {RED}Need at least 2 plans to merge.{RST}")
                continue
            print(f"\n  {BOLD}Select two plans to merge:{RST}")
            for i, card in enumerate(packet.plan_cards, 1):
                print(f"    {GOLD}{i}{RST}  {card.display_name}")
            ids: list[str] = []
            for label in ("First", "Second"):
                while True:
                    try:
                        sel = input(f"  {BOLD}{label} plan number:{RST} ").strip()
                    except (EOFError, KeyboardInterrupt):
                        sel = str(len(ids) + 1)
                    try:
                        idx = int(sel) - 1
                        if 0 <= idx < len(packet.plan_cards):
                            ids.append(packet.plan_cards[idx].plan_id)
                            break
                    except ValueError:
                        pass
                    print(f"  {RED}Enter a valid number.{RST}")
            try:
                reason = input(f"  {DIM}Rationale (optional, Enter to skip):{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                reason = ""
            return HumanJudgeActionRequest(
                action="merge_plans",
                winning_plan_ids=ids,
                instructions=reason or None,
            )

        elif choice == "3" and rounds_left > 0:
            try:
                instructions = input(f"  {DIM}Focus instructions (optional):{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                instructions = ""
            return HumanJudgeActionRequest(
                action="request_round",
                round_type=RoundType.CRITIQUE,
                instructions=instructions or None,
            )

        elif choice == "4" and rounds_left > 0:
            try:
                instructions = input(f"  {DIM}Revision target (optional):{RST} ").strip()
            except (EOFError, KeyboardInterrupt):
                instructions = ""
            return HumanJudgeActionRequest(
                action="request_revision",
                round_type=RoundType.TARGETED_REVISION,
                instructions=instructions or None,
            )

        print(f"  {RED}Invalid choice.{RST}")


# ── Review command ────────────────────────────────────────────────

_PHASE_LETTER_MAP = {
    "A": ReviewPhase.PROJECT_RULES,
    "B": ReviewPhase.IMPLEMENTATION,
    "C": ReviewPhase.ARCHITECTURE,
    "D": ReviewPhase.SECURITY_PERFORMANCE,
    "E": ReviewPhase.TEST_COVERAGE,
    "F": ReviewPhase.RED_TEAM,
}

_SEVERITY_COLORS = {
    ReviewSeverity.CRITICAL: RED,
    ReviewSeverity.HIGH: RED,
    ReviewSeverity.MEDIUM: GOLD,
    ReviewSeverity.LOW: CYAN,
    ReviewSeverity.INFO: DIM,
}


def _render_review_report_md(report) -> str:
    """Render a ReviewReport as a Markdown string."""
    lines: list[str] = []
    lines.append("# Code Review Report")
    lines.append("")
    lines.append(f"- **Review ID**: `{report.review_id}`")
    lines.append(f"- **Created**: {report.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"- **Target**: {report.target_description}")
    lines.append(f"- **Phases**: {len(report.phase_results)}")
    if report.reviewed_paths:
        lines.append(f"- **Reviewed Paths**: {', '.join(f'`{p}`' for p in report.reviewed_paths)}")
    if report.git_diff_included:
        lines.append("- **Git Diff**: included")
    lines.append("")

    # Severity summary
    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| Critical | {report.critical_count} |")
    lines.append(f"| High     | {report.high_count} |")
    lines.append(f"| Medium   | {report.medium_count} |")
    lines.append(f"| Low      | {report.low_count} |")
    info_count = report.total_findings - report.critical_count - report.high_count - report.medium_count - report.low_count
    if info_count > 0:
        lines.append(f"| Info     | {info_count} |")
    lines.append(f"| **Total** | **{report.total_findings}** |")
    lines.append("")

    if report.overall_summary:
        lines.append(report.overall_summary)
        lines.append("")

    # Top recommendations
    if report.top_recommendations:
        lines.append("## Top Recommendations")
        lines.append("")
        for i, rec in enumerate(report.top_recommendations, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    # Phase results
    for pr in report.phase_results:
        lines.append(f"## {pr.phase_label}")
        lines.append("")
        if pr.verdict_type:
            lines.append(f"- **Verdict**: {pr.verdict_type.value} (confidence: {pr.confidence:.2f})")
        tok = pr.usage.total_tokens
        cost = pr.usage.estimated_cost_usd
        cost_str = f" (${cost:.4f})" if cost > 0 else ""
        lines.append(f"- **Tokens**: {tok:,}{cost_str}")
        lines.append("")

        if pr.phase_summary:
            lines.append(pr.phase_summary)
            lines.append("")

        if pr.findings:
            lines.append("### Findings")
            lines.append("")
            for f in pr.findings:
                severity_icon = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🔵",
                    "info": "⚪",
                }.get(f.severity.value, "⚪")
                lines.append(f"#### {severity_icon} [{f.severity.value.upper()}] {f.title}")
                lines.append("")
                if f.description and f.description != f.title:
                    lines.append(f.description)
                    lines.append("")
                if f.file_path:
                    loc = f"`{f.file_path}"
                    if f.line_range:
                        loc += f":{f.line_range}"
                    loc += "`"
                    lines.append(f"- **Location**: {loc}")
                if f.recommendation:
                    lines.append(f"- **Recommendation**: {f.recommendation}")
                lines.append("")

    # Usage footer
    total_tok = report.total_usage.total_tokens
    total_cost = report.total_usage.estimated_cost_usd
    lines.append("---")
    lines.append("")
    cost_str = f" (${total_cost:.4f})" if total_cost > 0 else ""
    lines.append(f"*Total tokens: {total_tok:,}{cost_str} | Generated by Colosseum Code Review*")
    lines.append("")

    return "\n".join(lines)


def _save_review_report(report) -> str:
    """Save a ReviewReport as a Markdown file. Returns the file path."""
    from colosseum.core.config import REVIEW_REPORT_ROOT

    REVIEW_REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    ts = report.created_at.strftime("%Y%m%d_%H%M%S")
    filename = f"review_{ts}_{report.review_id[:8]}.md"
    path = REVIEW_REPORT_ROOT / filename
    md = _render_review_report_md(report)
    path.write_text(md, encoding="utf-8")
    return str(path)


def _review_phase_header(label: str, index: int, total: int):
    print(f"\n  {GOLD}{BOLD}>> Phase {index}/{total}: {label}{RST}")


def _review_finding(finding, indent: int = 6):
    color = _SEVERITY_COLORS.get(finding.severity, DIM)
    prefix = " " * indent
    print(f"{prefix}{color}{BOLD}[{finding.severity.value.upper()}]{RST} {finding.title}")
    if finding.description and finding.description != finding.title:
        desc = finding.description[:200]
        print(_wrap(desc, indent=indent + 2))
    if finding.file_path:
        loc = finding.file_path
        if finding.line_range:
            loc += f":{finding.line_range}"
        print(f"{prefix}  {DIM}{loc}{RST}")
    if finding.recommendation:
        print(f"{prefix}  {GREEN}Fix:{RST} {finding.recommendation[:160]}")


def _review_summary(report):
    print(f"\n  {'=' * 60}")
    print(f"  {GOLD}{BOLD}  CODE REVIEW COMPLETE{RST}")
    print(f"  {'=' * 60}")

    # Severity counts
    counts = []
    if report.critical_count:
        counts.append(f"{RED}{BOLD}{report.critical_count} critical{RST}")
    if report.high_count:
        counts.append(f"{RED}{report.high_count} high{RST}")
    if report.medium_count:
        counts.append(f"{GOLD}{report.medium_count} medium{RST}")
    if report.low_count:
        counts.append(f"{CYAN}{report.low_count} low{RST}")
    info_count = report.total_findings - report.critical_count - report.high_count - report.medium_count - report.low_count
    if info_count > 0:
        counts.append(f"{DIM}{info_count} info{RST}")

    print(f"\n    {BOLD}Findings:{RST} {report.total_findings} total — {', '.join(counts)}")

    if report.overall_summary:
        print(f"\n    {BOLD}Summary:{RST}")
        print(_wrap(report.overall_summary[:500], indent=6))

    if report.top_recommendations:
        print(f"\n    {BOLD}Top Recommendations:{RST}")
        for i, rec in enumerate(report.top_recommendations[:5], 1):
            print(f"      {GOLD}{i}.{RST} {rec[:160]}")

    # Usage
    total_tok = report.total_usage.total_tokens
    total_cost = report.total_usage.estimated_cost_usd
    print(f"\n    {DIM}Tokens: {total_tok:,}  Cost: ${total_cost:.4f}  Phases: {len(report.phase_results)}{RST}")
    print(f"    {DIM}Review ID: {report.review_id}{RST}\n")


def cmd_review(args: argparse.Namespace) -> None:
    """Run a multi-phase code review from the terminal."""
    from colosseum.bootstrap import get_review_orchestrator

    target = args.topic
    depth = args.depth
    json_output = args.json_output
    file_paths = getattr(args, "files", None) or []
    dir_path = getattr(args, "dir", None)
    diff_flag = getattr(args, "diff", False)
    rules_path = getattr(args, "rules", None)
    phase_letters = getattr(args, "phases", None)
    timeout_seconds = args.timeout or 0
    response_language = getattr(args, "lang", None) or "auto"

    # --mock flag
    if args.mock:
        gladiator_specs = ["mock:alpha", "mock:beta"]
    else:
        gladiator_specs = args.gladiators or []

    if not json_output:
        _print_header()

    if len(gladiator_specs) < 2:
        if json_output:
            import json as _json
            print(_json.dumps({"error": f"Need at least 2 gladiators. Got {len(gladiator_specs)}."}))
        else:
            print(f"  {RED}Need at least 2 gladiators. Use -g or --mock.{RST}\n")
        sys.exit(1)

    # Parse gladiators
    agents = []
    for i, spec in enumerate(gladiator_specs):
        try:
            agent = _parse_gladiator(spec)
        except ValueError as e:
            print(f"  {RED}{e}{RST}\n")
            sys.exit(1)
        existing_ids = [a["agent_id"] for a in agents]
        if agent["agent_id"] in existing_ids:
            agent["agent_id"] = f"{agent['agent_id']}_{i}"
        agents.append(agent)

    # Parse phases
    if phase_letters:
        phases = []
        for letter in phase_letters:
            upper = letter.upper()
            if upper in _PHASE_LETTER_MAP:
                phases.append(_PHASE_LETTER_MAP[upper])
            else:
                print(f"  {RED}Unknown phase '{letter}'. Use A, B, C, D, E, or F.{RST}\n")
                sys.exit(1)
    else:
        phases = [p for p in ReviewPhase if p != ReviewPhase.RED_TEAM]

    # Git diff
    git_diff = None
    if diff_flag:
        review_dir = dir_path or "."
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD~1"],
                capture_output=True, text=True, timeout=30,
                cwd=review_dir,
            )
            if result.returncode == 0 and result.stdout.strip():
                git_diff = result.stdout
        except Exception:
            pass

    # Rules context
    rules_context = None
    if rules_path:
        try:
            with open(rules_path, encoding="utf-8") as f:
                rules_context = f.read()
        except Exception as e:
            print(f"  {GOLD}Warning: Could not read rules file: {e}{RST}")
    elif dir_path:
        # Auto-detect project rules
        for candidate in ("CLAUDE.md", ".cursorrules", ".editorconfig", "pyproject.toml"):
            try:
                candidate_path = os.path.join(dir_path, candidate)
                with open(candidate_path, encoding="utf-8") as f:
                    content = f.read()
                    if content.strip():
                        rules_context = (rules_context or "") + f"\n--- {candidate} ---\n{content}\n"
            except (FileNotFoundError, OSError):
                pass

    # Build context sources
    context_sources: list[ContextSourceInput] = [
        ContextSourceInput(
            source_id="review_target",
            kind=ContextSourceKind.INLINE_TEXT,
            label="Review target",
            content=target,
        )
    ]
    if dir_path:
        context_sources.append(
            ContextSourceInput(
                source_id="project_dir",
                kind=ContextSourceKind.LOCAL_DIRECTORY,
                label=os.path.basename(dir_path.rstrip("/\\")) or dir_path,
                path=dir_path,
            )
        )
    for i, fp in enumerate(file_paths):
        context_sources.append(
            ContextSourceInput(
                source_id=f"file_{i}",
                kind=ContextSourceKind.LOCAL_FILE,
                label=os.path.basename(fp),
                path=fp,
            )
        )
    if git_diff:
        context_sources.append(
            ContextSourceInput(
                source_id="git_diff",
                kind=ContextSourceKind.INLINE_TEXT,
                label="Git diff (HEAD~1)",
                content=git_diff,
            )
        )

    # Judge config
    judge_spec = getattr(args, "judge", None)
    if judge_spec:
        try:
            judge_provider = _parse_provider_spec(judge_spec)
        except ValueError as e:
            print(f"  {RED}{e}{RST}\n")
            sys.exit(1)
        judge_config = JudgeConfig(mode=JudgeMode.AI, provider=judge_provider)
    else:
        judge_config = JudgeConfig(mode=JudgeMode.AUTOMATED)

    # Depth profile
    profile = DEPTH_PROFILES.get(depth, DEPTH_PROFILES[3])

    request = ReviewCreateRequest(
        project_name="Colosseum",
        target_description=target,
        context_sources=context_sources,
        agents=agents,
        judge=judge_config,
        budget_policy=BudgetPolicy(
            max_rounds=depth,
            min_rounds=profile["min_rounds"],
            total_token_budget=profile.get("token_budget", 80000),
            per_round_token_limit=12000,
            per_agent_message_limit=1,
            min_novelty_threshold=profile["min_novelty_threshold"],
            convergence_threshold=profile["convergence_threshold"],
            planning_timeout_seconds=timeout_seconds,
            round_timeout_seconds=timeout_seconds,
        ),
        phases=phases,
        git_diff=git_diff,
        rules_context=rules_context,
        response_language=response_language,
    )

    orch = get_review_orchestrator()

    if json_output:
        import json as _json
        report = asyncio.run(orch.run_review(request))
        report_path = _save_review_report(report)
        print(_json.dumps(report.model_dump(mode="json"), indent=2, default=str))
        sys.stderr.write(f"Report saved: {report_path}\n")
        return

    # Print header
    print(f"  {BOLD}Review:{RST} {target}")
    print(f"  {BOLD}Phases:{RST} {len(phases)} — {', '.join(p.value for p in phases)}")
    if dir_path:
        print(f"  {BOLD}Dir:{RST} {dir_path}")
    if file_paths:
        print(f"  {BOLD}Files:{RST} {', '.join(file_paths)}")
    if git_diff:
        print(f"  {BOLD}Diff:{RST} included ({len(git_diff)} chars)")
    if rules_context:
        print(f"  {BOLD}Rules:{RST} loaded ({len(rules_context)} chars)")
    if timeout_seconds:
        print(f"  {BOLD}Timeout:{RST} {timeout_seconds}s per phase")
    else:
        print(f"  {BOLD}Timeout:{RST} none")
    if response_language != "auto":
        print(f"  {BOLD}Language:{RST} {response_language}")
    print(f"  {BOLD}Gladiators:{RST}")
    for a in agents:
        print(f"    {GOLD}{_display_label(a)}{RST}")
    print(f"\n  {DIM}{'─' * 60}{RST}")
    print(f"  {GOLD}Code review begins...{RST}\n")

    asyncio.run(_run_review_live(orch, request))


async def _run_review_live(orch, request) -> None:
    """Run review with live streaming output per phase."""
    try:
        review_complete_data = None
        review_report = None
        spinner = _Spinner()
        pending_inner = 0
        async for event_type, event_data in orch.run_review_streaming(request):
            if event_type == "phase_start":
                spinner.stop()
                _review_phase_header(
                    event_data["label"],
                    event_data["index"],
                    event_data["total"],
                )
            elif event_type == "inner_agent_planning":
                pending_inner += 1
                spinner.start(f"{event_data['display_name']} planning...")
            elif event_type == "inner_plan_ready":
                spinner.stop()
                pending_inner -= 1
                name = event_data.get("display_name", "?")
                summary = event_data.get("summary", "")[:100]
                print(f"      {GREEN}Plan:{RST} {BOLD}{name}{RST} — {DIM}{summary}{RST}")
                if pending_inner > 0:
                    spinner.start(f"Waiting for {pending_inner} more plan(s)...")
            elif event_type == "inner_debate_round_start":
                print(f"      {DIM}Round {event_data.get('round_index', '?')}: {event_data.get('round_type', '?')}{RST}")
            elif event_type == "inner_agent_thinking":
                pending_inner += 1
                spinner.start(f"{event_data['display_name']} debating...")
            elif event_type == "inner_agent_message":
                spinner.stop()
                pending_inner -= 1
                name = event_data.get("display_name", "?")
                tok = event_data.get("usage", {}).get("total_tokens", 0)
                print(f"      {CYAN}{name}{RST} {DIM}{tok} tok{RST}")
                if pending_inner > 0:
                    spinner.start("Waiting for remaining agents...")
            elif event_type == "inner_judge_decision":
                spinner.stop()
                action = event_data.get("action", "?")
                conf = event_data.get("confidence", 0)
                print(f"      {GOLD}[Judge]{RST} {action} {DIM}(conf={conf:.2f}){RST}")
            elif event_type == "phase_complete":
                spinner.stop()
                pending_inner = 0
                fc = event_data["findings_count"]
                usage = event_data.get("usage", {})
                tok = usage.get("total_tokens", 0)
                cost = usage.get("estimated_cost_usd", 0)
                cost_str = f"  ${cost:.4f}" if cost > 0 else ""
                print(f"    {GREEN}Done:{RST} {fc} finding(s)  {DIM}{tok} tok{cost_str}{RST}")
                if event_data.get("summary"):
                    print(_wrap(event_data["summary"][:200], indent=6))
            elif event_type == "phase_failed":
                spinner.stop()
                pending_inner = 0
                print(f"    {RED}Failed:{RST} {event_data.get('error', 'unknown')}")
            elif event_type == "review_complete":
                spinner.stop()
                review_complete_data = event_data
            elif event_type == "_review_report":
                review_report = event_data

        # Print final summary
        if review_complete_data:
            total = review_complete_data.get("total_findings", 0)
            print(f"\n  {'=' * 60}")
            print(f"  {GOLD}{BOLD}  CODE REVIEW COMPLETE{RST}")
            print(f"  {'=' * 60}")

            counts = []
            for key, label, color in [
                ("critical_count", "critical", RED),
                ("high_count", "high", RED),
                ("medium_count", "medium", GOLD),
                ("low_count", "low", CYAN),
            ]:
                n = review_complete_data.get(key, 0)
                if n:
                    counts.append(f"{color}{n} {label}{RST}")
            print(f"\n    {BOLD}Findings:{RST} {total} total — {', '.join(counts)}")

            summary = review_complete_data.get("overall_summary", "")
            if summary:
                print(f"\n    {BOLD}Summary:{RST}")
                print(_wrap(summary[:500], indent=6))

        # Save report to markdown file
        if review_report:
            try:
                report_path = _save_review_report(review_report)
                print(f"\n    {GREEN}{BOLD}Report saved:{RST} {report_path}")
            except Exception as save_exc:
                print(f"\n    {GOLD}Warning: could not save report: {save_exc}{RST}")
            print()

    except Exception as exc:
        error_msg = str(exc) or type(exc).__name__
        print(f"\n  {RED}Error: {error_msg}{RST}\n")
        sys.exit(1)


# ── Argument parser ──────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colosseum",
        description="Colosseum — AI Debate Arena",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        examples:
          colosseum debate --topic "Is Rust better than Go?" -g claude:claude-sonnet-4-6 codex:o3
          colosseum debate --topic "Best DB for microservices" -g ollama:llama3.3 ollama:mistral --depth 5
          colosseum debate -t "Monolith vs microservices" -g claude:claude-sonnet-4-6 codex:o3 -p pragmatic_engineer devil_advocate
          colosseum debate -t "Quick test" -g mock:a mock:b --depth 1
          colosseum models
          colosseum local-runtime status
          colosseum personas
          colosseum review -t "Auth impl review" -g claude:claude-sonnet-4-6 codex:o3 --dir . --phases A B C
          colosseum review -t "Quick test" --mock --phases A
          colosseum check
          colosseum serve
        """),
    )
    parser.add_argument("-V", "--version", action="version", version="%(prog)s 0.1.0")
    sub = parser.add_subparsers(dest="command")

    # serve
    sub.add_parser("serve", help="Start the web UI server")

    # models
    sub.add_parser("models", help="List available models")

    # local runtime
    p_local = sub.add_parser("local-runtime", help="Manage the local-model runtime")
    local_sub = p_local.add_subparsers(dest="local_command")
    p_local_status = local_sub.add_parser("status", help="Show local runtime and GPU status")
    p_local_status.add_argument(
        "--ensure-ready",
        action="store_true",
        default=False,
        help="Start the managed runtime first so installed models can be enumerated.",
    )
    p_local_config = local_sub.add_parser("configure", help="Update GPU settings for local models")
    local_gpu_mode = p_local_config.add_mutually_exclusive_group()
    local_gpu_mode.add_argument(
        "--auto-gpu",
        action="store_true",
        default=False,
        help="Expose every detected GPU to the managed runtime.",
    )
    local_gpu_mode.add_argument(
        "--cpu-only",
        action="store_true",
        default=False,
        help="Force the managed runtime to run without GPUs.",
    )
    local_gpu_mode.add_argument(
        "--gpu-count",
        type=int,
        default=None,
        help="Expose the first N detected GPUs to the managed runtime.",
    )
    p_local_config.add_argument(
        "--no-restart",
        action="store_true",
        default=False,
        help="Save settings without restarting the managed runtime immediately.",
    )
    p_local_pull = local_sub.add_parser(
        "pull", help="Download a local model into the managed runtime"
    )
    p_local_pull.add_argument("model", help="Model name or prefix form such as ollama:llama3.3")

    # hf (HuggingFace Hub)
    p_hf = sub.add_parser("hf", help="HuggingFace Hub model operations")
    hf_sub = p_hf.add_subparsers(dest="hf_command")

    p_hf_search = hf_sub.add_parser("search", help="Search HuggingFace Hub for GGUF models")
    p_hf_search.add_argument("query", help="Search query (e.g. 'llama 70b', 'mistral instruct')")
    p_hf_search.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")

    p_hf_pull = hf_sub.add_parser("pull", help="Download a HuggingFace model via Ollama")
    p_hf_pull.add_argument(
        "repo_id", help="HuggingFace repo (e.g. bartowski/Llama-3.3-70B-Instruct-GGUF)"
    )

    hf_sub.add_parser("list", help="List installed HuggingFace models")

    p_hf_register = hf_sub.add_parser(
        "register",
        help="Register a local model (GGUF, safetensors, or HF directory) with Ollama",
    )
    p_hf_register.add_argument("name", help="Model name to create in Ollama")
    p_hf_register.add_argument(
        "--path", required=True,
        help="Path to .gguf file, .safetensors file, or HuggingFace model directory",
    )
    hf_sub.add_parser("tools", help="Check availability of conversion tools (llama.cpp)")

    # personas
    sub.add_parser("personas", help="List available personas")

    # history
    sub.add_parser("history", help="List past battles")

    # show
    p_show = sub.add_parser("show", help="Show a past battle result")
    p_show.add_argument("run_id", help="Run ID (or prefix)")

    # setup
    p_setup = sub.add_parser(
        "setup", help="Install CLI tools and authenticate (interactive wizard)"
    )
    p_setup.add_argument(
        "tools",
        nargs="*",
        default=None,
        help="Specific tools to set up (e.g. claude codex gemini ollama). Defaults to all.",
    )
    p_setup.add_argument(
        "--skip-auth",
        action="store_true",
        default=False,
        help="Skip authentication step (install only)",
    )
    p_setup.add_argument(
        "-y",
        "--yes",
        action="store_true",
        default=False,
        help="Auto-confirm all install/auth prompts",
    )
    p_setup.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Ignore the cached auth status and re-probe every provider.",
    )

    # quickstart
    p_quickstart = sub.add_parser(
        "quickstart",
        help="Fastest path to your first debate — single-provider onboarding",
    )
    p_quickstart.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Ignore the cached auth status and re-probe every provider.",
    )

    # check
    p_check = sub.add_parser("check", help="Verify CLI tool availability and auth")
    p_check.add_argument(
        "--refresh",
        action="store_true",
        default=False,
        help="Ignore the cached auth status and re-probe every provider.",
    )

    # delete
    p_delete = sub.add_parser("delete", help="Delete a past battle run")
    p_delete.add_argument("run_id", help="Run ID (or prefix), or 'all' to delete all runs")
    p_delete.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # debate
    p_debate = sub.add_parser("debate", help="Run a debate from the terminal")
    p_debate.add_argument("-t", "--topic", required=True, help="Debate topic")
    p_debate.add_argument(
        "-g",
        "--gladiators",
        action="extend",
        nargs="+",
        default=None,
        help=(
            "Gladiator specs: provider:model "
            "(e.g. -g claude:claude-sonnet-4-6 ollama:llama3.3). "
            "Omit to auto-pick from authenticated providers."
        ),
    )
    p_debate.add_argument(
        "-d",
        "--depth",
        type=int,
        default=3,
        choices=[1, 2, 3, 4, 5],
        help="Debate depth 1=Quick 2=Brief 3=Standard 4=Thorough 5=Deep (default: 3)",
    )
    p_debate.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Time limit per phase in seconds (applies to planning and each round). Omit for no limit.",
    )
    p_debate.add_argument(
        "-p",
        "--personas",
        nargs="+",
        default=None,
        help="Persona IDs for each gladiator (use 'none' to skip). Order matches -g order.",
    )
    p_debate.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Quick test mode: use 2 mock gladiators (overrides -g)",
    )
    p_debate.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output result as JSON instead of formatted text",
    )
    p_debate.add_argument(
        "--monitor",
        action="store_true",
        default=False,
        help="Open a live monitor in a tmux side pane (requires tmux)",
    )
    p_debate.add_argument(
        "--disable-evidence-judging",
        action="store_true",
        default=False,
        help="Keep surfacing evidence, but do not let thin evidence force more rounds or gate the verdict.",
    )
    p_debate.add_argument(
        "-j",
        "--judge",
        default=None,
        metavar="PROVIDER:MODEL",
        help="Judge spec: provider:model for AI judge (e.g. -j claude:claude-opus-4-6), or 'human' for interactive human judging. Omit for automated judging.",
    )
    p_debate.add_argument(
        "-f",
        "--files",
        nargs="+",
        default=None,
        metavar="PATH",
        help="One or more files to include as context for the debate.",
    )
    p_debate.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Project directory to include as context for the debate.",
    )
    p_debate.add_argument(
        "--lang",
        default=None,
        metavar="LANGUAGE",
        help="Response language (e.g. ko, en, ja). Default: auto-detect.",
    )
    p_debate.add_argument(
        "--internet-search",
        action="store_true",
        default=False,
        help="Encourage gladiators to use internet search during the debate.",
    )
    p_debate.add_argument(
        "--task-type",
        default=None,
        choices=[t.value for t in TaskType],
        metavar="TYPE",
        help=(
            "Task type for the debate. Choices: "
            + ", ".join(t.value for t in TaskType)
            + ". Default: research_design."
        ),
    )
    p_debate.add_argument(
        "--report-instructions",
        default=None,
        metavar="TEXT",
        help="Custom instructions for final report generation.",
    )

    # monitor
    p_monitor = sub.add_parser("monitor", help="Open live monitor dashboard for an active debate")
    p_monitor.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="Run ID to monitor (default: latest active run)",
    )

    # review
    p_review = sub.add_parser("review", help="Run a multi-phase code review")
    p_review.add_argument("-t", "--topic", required=True, help="Review target description")
    p_review.add_argument(
        "-g",
        "--gladiators",
        action="extend",
        nargs="+",
        default=None,
        help="Reviewer specs: provider:model (e.g. -g claude:claude-sonnet-4-6 codex:o3)",
    )
    p_review.add_argument(
        "-d",
        "--depth",
        type=int,
        default=2,
        choices=[1, 2, 3, 4, 5],
        help="Depth per review phase (default: 2)",
    )
    p_review.add_argument(
        "--dir",
        default=None,
        metavar="PATH",
        help="Project directory to review",
    )
    p_review.add_argument(
        "-f",
        "--files",
        nargs="+",
        default=None,
        metavar="PATH",
        help="Specific files to review",
    )
    p_review.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Include git diff HEAD~1 as context",
    )
    p_review.add_argument(
        "--rules",
        default=None,
        metavar="PATH",
        help="Path to project rules file (auto-detected if --dir is set)",
    )
    p_review.add_argument(
        "--phases",
        nargs="+",
        default=None,
        metavar="PHASE",
        help="Review phases: A (rules) B (impl) C (arch) D (security) E (tests) F (red-team). Default: A-E",
    )
    p_review.add_argument(
        "--timeout",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Time limit per phase in seconds. Omit for no limit.",
    )
    p_review.add_argument(
        "--lang",
        default=None,
        metavar="LANGUAGE",
        help="Response language (e.g. ko, en, ja). Default: auto-detect.",
    )
    p_review.add_argument(
        "-j",
        "--judge",
        default=None,
        metavar="PROVIDER:MODEL",
        help="AI judge spec (e.g. -j claude:claude-opus-4-6). Omit for automated.",
    )
    p_review.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Quick test with mock providers",
    )
    p_review.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output result as JSON",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "serve": cmd_serve,
        "setup": cmd_setup,
        "quickstart": cmd_quickstart,
        "models": cmd_models,
        "local-runtime": cmd_local_runtime,
        "hf": cmd_hf,
        "personas": cmd_personas,
        "history": cmd_history,
        "show": cmd_show,
        "delete": cmd_delete,
        "check": cmd_check,
        "debate": cmd_debate,
        "monitor": cmd_monitor,
        "review": cmd_review,
    }
    fn = commands.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
