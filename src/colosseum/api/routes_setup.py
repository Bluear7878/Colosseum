"""Setup and discovery endpoints."""

from __future__ import annotations

import asyncio
import subprocess as _sp

from fastapi import APIRouter, HTTPException

from colosseum.core.models import (
    LocalModelDownloadRequest,
    LocalModelDownloadResult,
    LocalModelFitResult,
    LocalRuntimeConfigUpdate,
    LocalRuntimeStatus,
)
from colosseum.services.local_runtime import LocalRuntimeService

router = APIRouter()


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/setup/status")
async def setup_status() -> list[dict]:
    """Return install/auth status of all CLI provider tools."""
    from colosseum.cli import get_all_tool_statuses

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, get_all_tool_statuses)


@router.get("/models")
async def list_models() -> list[dict]:
    """Return dynamically discovered model list from installed CLIs."""
    from colosseum.cli import discover_models

    return await asyncio.to_thread(discover_models)


@router.get("/cli-versions")
async def cli_versions() -> dict:
    """Return cached CLI version info."""
    from colosseum.cli import get_cli_versions

    return get_cli_versions()


@router.post("/models/refresh")
async def refresh_models() -> list[dict]:
    """Force re-probe all provider models."""
    from colosseum.cli import probe_all_models

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, probe_all_models)


@router.get("/local-runtime/status", response_model=LocalRuntimeStatus)
async def local_runtime_status(ensure_ready: bool = False) -> LocalRuntimeStatus:
    """Return managed local-runtime status, GPU inventory, and installed models."""
    service = LocalRuntimeService()
    return await asyncio.to_thread(service.get_status, ensure_ready)


@router.post("/local-runtime/config", response_model=LocalRuntimeStatus)
async def update_local_runtime_config(
    update: LocalRuntimeConfigUpdate,
) -> LocalRuntimeStatus:
    """Persist local-runtime settings and restart the managed runtime if requested."""
    service = LocalRuntimeService()
    try:
        return await asyncio.to_thread(service.update_settings, update)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/local-models/download", response_model=LocalModelDownloadResult)
async def download_local_model(
    request: LocalModelDownloadRequest,
) -> LocalModelDownloadResult:
    """Download a local model into the managed Ollama runtime."""
    service = LocalRuntimeService()
    try:
        result = await asyncio.to_thread(service.download_model, request.model)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.success:
        raise HTTPException(status_code=500, detail=result.message)
    return result


@router.get("/local-models/fit-check", response_model=LocalModelFitResult)
async def check_local_model_fit(model: str) -> LocalModelFitResult:
    """Check whether a local model can run on current hardware using llmfit."""
    if not model or not model.strip():
        raise HTTPException(status_code=422, detail="model query parameter is required.")
    service = LocalRuntimeService()
    return await asyncio.to_thread(service.check_model_fit, model)


@router.post("/setup/auth/{tool_name}")
async def trigger_auth(tool_name: str) -> dict:
    """Launch CLI login for a provider tool (opens browser for OAuth)."""
    from colosseum.cli import CLI_AUTH_INFO

    if tool_name not in CLI_AUTH_INFO:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    info = CLI_AUTH_INFO[tool_name]
    login_cmd = info.get("login")
    if not login_cmd:
        return {"status": "no_login_required", "tool": tool_name}

    try:
        _sp.Popen(login_cmd.split(), stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        return {"status": "initiated", "tool": tool_name, "login_cmd": login_cmd}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"Tool '{tool_name}' is not installed") from exc
    except Exception as exc:  # pragma: no cover - API guard
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/setup/install/{tool_name}")
async def install_tool(tool_name: str) -> dict:
    """Attempt to install a CLI tool by name."""
    import shutil

    from colosseum.cli import CLI_AUTH_INFO, _check_tool_status

    if tool_name not in CLI_AUTH_INFO:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

    info = CLI_AUTH_INFO[tool_name]
    requires = info.get("install_requires")
    if requires and not shutil.which(requires):
        return {
            "success": False,
            "tool": tool_name,
            "error": f"Prerequisite '{requires}' not found. Install Node.js first: https://nodejs.org/",
        }

    install_cmd = info["install_cmd"]
    try:
        result = _sp.run(install_cmd, shell=True, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and shutil.which(info["cmd"]):
            status = _check_tool_status(tool_name, info)
            return {"success": True, "tool": tool_name, "status": status}
        return {
            "success": False,
            "tool": tool_name,
            "error": result.stderr.strip()[:300] or "Install failed",
        }
    except _sp.TimeoutExpired:
        return {"success": False, "tool": tool_name, "error": "Install timed out"}
    except Exception as exc:  # pragma: no cover - API guard
        return {"success": False, "tool": tool_name, "error": str(exc)}
