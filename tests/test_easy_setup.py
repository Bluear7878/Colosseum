"""Tests for the easy-setup features: auth cache, quickstart helpers,
and smart default gladiator picking."""

from __future__ import annotations

import time

import pytest

from colosseum import cli as cli_mod
from colosseum.cli import (
    _AUTH_CACHE_TTL_SECONDS,
    _default_model_for,
    _get_cached_auth,
    _pick_default_gladiators,
    _set_cached_auth,
    clear_auth_cache,
)


@pytest.fixture(autouse=True)
def isolated_auth_cache(tmp_path, monkeypatch):
    """Redirect the auth cache file into a tmp dir so tests never touch the
    user's real ~/.colosseum/auth_cache.json."""
    cache_file = tmp_path / "auth_cache.json"
    monkeypatch.setattr(cli_mod, "_auth_cache_path", lambda: cache_file)
    yield
    # Defensive cleanup — fixture isolation alone should be enough.
    if cache_file.exists():
        cache_file.unlink()


# ── Auth cache ───────────────────────────────────────────────────


def test_cache_roundtrip_persists_values():
    clear_auth_cache()
    assert _get_cached_auth("claude") is None

    _set_cached_auth("claude", True, "authenticated")
    entry = _get_cached_auth("claude")

    assert entry is not None
    assert entry["auth_ok"] is True
    assert entry["auth_detail"] == "authenticated"


def test_cache_expires_after_ttl():
    _set_cached_auth("codex", True, "authenticated")

    # Manually rewrite the timestamp to just past the TTL boundary.
    stale_time = time.time() - (_AUTH_CACHE_TTL_SECONDS + 60)
    import json

    path = cli_mod._auth_cache_path()
    data = json.loads(path.read_text())
    data["codex"]["timestamp"] = stale_time
    path.write_text(json.dumps(data))

    assert _get_cached_auth("codex") is None, "stale entry must not be returned"


def test_clear_auth_cache_removes_file():
    _set_cached_auth("gemini", False, "not authenticated")
    assert _get_cached_auth("gemini") is not None

    clear_auth_cache()
    assert _get_cached_auth("gemini") is None


def test_check_tool_status_uses_cache(monkeypatch):
    """When a fresh cache entry exists, the expensive probe must be skipped."""
    # Pretend the `claude` binary is on PATH so the installed branch runs.
    monkeypatch.setattr(cli_mod.shutil, "which", lambda cmd: "/fake/" + cmd)

    # Any subprocess.run call would be a 30s probe — fail hard if it happens
    # for the auth probe. (The version check runs first; let it through by
    # returning a cheap stub.)
    call_log: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        call_log.append(list(cmd))

        class R:
            stdout = "v1.0.0"
            stderr = ""
            returncode = 0

        return R()

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)

    _set_cached_auth("claude", True, "authenticated")

    info = cli_mod.CLI_AUTH_INFO["claude"]
    status = cli_mod._check_tool_status("claude", info, use_cache=True)

    assert status["auth_ok"] is True
    assert status["auth_detail"] == "authenticated"
    # Only the version check should have fired — no "say ok" probe.
    probe_calls = [c for c in call_log if "say ok" in " ".join(c)]
    assert probe_calls == [], f"auth probe should be skipped, got: {probe_calls}"


def test_check_tool_status_refresh_bypasses_cache(monkeypatch):
    """use_cache=False must re-run the probe even if the cache is fresh."""
    monkeypatch.setattr(cli_mod.shutil, "which", lambda cmd: "/fake/" + cmd)

    probe_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        cmd_str = " ".join(cmd)
        if "say ok" in cmd_str:
            probe_count["n"] += 1

        class R:
            stdout = "ok"
            stderr = ""
            returncode = 0

        return R()

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        cli_mod, "LocalRuntimeService", lambda: _DummyRuntime()
    )  # harmless

    _set_cached_auth("claude", True, "authenticated")

    info = cli_mod.CLI_AUTH_INFO["claude"]
    cli_mod._check_tool_status("claude", info, use_cache=False)

    assert probe_count["n"] == 1, "refresh must re-run the probe"


class _DummyRuntime:
    """Avoid spinning up the real LocalRuntimeService in tests."""

    def get_status(self):
        class S:
            class settings:
                host = "http://localhost:11434"

            runtime_running = False

        return S()


# ── Smart default gladiator picking ──────────────────────────────


def test_pick_defaults_prefers_paid_cli_first():
    """Preferred ordering: claude > codex > gemini > ollama."""
    statuses = [
        {"tool": "claude", "installed": True, "auth_ok": True},
        {"tool": "codex", "installed": True, "auth_ok": True},
        {"tool": "gemini", "installed": True, "auth_ok": True},
        {"tool": "ollama", "installed": True, "auth_ok": True},
    ]
    picks = _pick_default_gladiators(statuses, count=2)

    assert len(picks) == 2
    assert picks[0].startswith("claude:")
    assert picks[1].startswith("codex:")


def test_pick_defaults_skips_unauthed_tools():
    statuses = [
        {"tool": "claude", "installed": True, "auth_ok": False},  # installed, not authed
        {"tool": "codex", "installed": False, "auth_ok": False},  # missing
        {"tool": "gemini", "installed": True, "auth_ok": True},
        {"tool": "ollama", "installed": True, "auth_ok": True},
    ]
    picks = _pick_default_gladiators(statuses, count=2)

    assert picks[0].startswith("gemini:")
    assert picks[1] == "ollama:llama3.2"


def test_pick_defaults_returns_empty_when_nothing_ready():
    statuses = [
        {"tool": "claude", "installed": True, "auth_ok": False},
        {"tool": "codex", "installed": False, "auth_ok": False},
        {"tool": "gemini", "installed": False, "auth_ok": False},
        {"tool": "ollama", "installed": False, "auth_ok": False},
    ]
    assert _pick_default_gladiators(statuses) == []


def test_pick_defaults_ollama_only_still_works():
    """A user with only Ollama should still be able to auto-run a debate
    against two local models. _default_model_for returns one ollama model
    and the caller can deduplicate; here we just verify the helper doesn't
    crash when ollama is the sole ready provider."""
    statuses = [
        {"tool": "ollama", "installed": True, "auth_ok": True},
    ]
    picks = _pick_default_gladiators(statuses, count=2)
    assert picks == ["ollama:llama3.2"]


def test_default_model_for_known_tools():
    assert _default_model_for("ollama") == "ollama:llama3.2"
    # Paid CLIs: must return a "provider:model" spec pointing at a real
    # registry entry.
    for tool in ("claude", "codex", "gemini"):
        spec = _default_model_for(tool)
        assert spec is not None and spec.startswith(f"{tool}:")


def test_default_model_for_unknown_tool_is_none():
    assert _default_model_for("nosuch") is None
