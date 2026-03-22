"""Public API routing surface for the Colosseum FastAPI application."""

from __future__ import annotations

from fastapi import APIRouter

from .routes_personas import router as personas_router
from .routes_personas import (
    create_persona,
    delete_persona,
    generate_persona,
    get_persona,
    list_personas,
)
from .routes_quotas import router as quotas_router
from .routes_quotas import list_provider_quotas, update_provider_quotas
from .routes_runs import router as runs_router
from .routes_runs import (
    cancel_debate,
    continue_human_run,
    create_run,
    create_run_stream,
    download_run_markdown,
    download_run_pdf,
    get_run,
    list_runs,
    skip_round,
)
from .routes_setup import router as setup_router
from .routes_setup import (
    cli_versions,
    healthcheck,
    install_tool,
    download_local_model,
    list_models,
    local_runtime_status,
    refresh_models,
    setup_status,
    trigger_auth,
    update_local_runtime_config,
)
from .routes_hf import router as hf_router
from .routes_hf import (
    conversion_tools,
    list_hf_models,
    pull_hf_model,
    register_gguf_model,
    search_hf_models,
)

router = APIRouter()
for child_router in (setup_router, runs_router, quotas_router, personas_router, hf_router):
    router.include_router(child_router)

__all__ = [
    "router",
    "healthcheck",
    "setup_status",
    "list_models",
    "cli_versions",
    "refresh_models",
    "local_runtime_status",
    "update_local_runtime_config",
    "download_local_model",
    "trigger_auth",
    "install_tool",
    "create_run",
    "create_run_stream",
    "list_runs",
    "skip_round",
    "cancel_debate",
    "list_provider_quotas",
    "update_provider_quotas",
    "get_run",
    "download_run_pdf",
    "download_run_markdown",
    "continue_human_run",
    "list_personas",
    "generate_persona",
    "get_persona",
    "create_persona",
    "delete_persona",
    "search_hf_models",
    "pull_hf_model",
    "list_hf_models",
    "register_gguf_model",
    "conversion_tools",
]
