"""HuggingFace Hub endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from colosseum.core.models import (
    HFPullRequest,
    HFRegisterRequest,
    HFRegisterResult,
    HFSearchResponse,
    LocalModelDownloadResult,
)

router = APIRouter(prefix="/hf", tags=["huggingface"])


def _get_service():
    from colosseum.services.hf_hub import HuggingFaceHubService

    return HuggingFaceHubService()


@router.get("/search", response_model=HFSearchResponse)
async def search_hf_models(q: str, limit: int = 20) -> HFSearchResponse:
    """Search HuggingFace Hub for GGUF-compatible models."""
    if not q or not q.strip():
        raise HTTPException(status_code=422, detail="Search query is required.")
    service = _get_service()
    return await asyncio.to_thread(service.search, q.strip(), limit)


@router.post("/pull", response_model=LocalModelDownloadResult)
async def pull_hf_model(request: HFPullRequest) -> LocalModelDownloadResult:
    """Pull a HuggingFace model via Ollama."""
    service = _get_service()
    try:
        return await asyncio.to_thread(service.pull, request.repo_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/models")
async def list_hf_models() -> list[str]:
    """List installed HuggingFace-sourced models."""
    service = _get_service()
    return await asyncio.to_thread(service.list_hf_models)


@router.post("/register", response_model=HFRegisterResult)
async def register_gguf_model(request: HFRegisterRequest) -> HFRegisterResult:
    """Register a local model (GGUF, safetensors, or HF directory) with Ollama."""
    service = _get_service()
    try:
        return await asyncio.to_thread(service.register_model, request)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools")
async def conversion_tools() -> dict[str, str | None]:
    """Check availability of llama.cpp conversion tools."""
    service = _get_service()
    return service.conversion_tools_available()
