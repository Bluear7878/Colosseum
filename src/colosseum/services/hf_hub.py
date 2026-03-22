"""HuggingFace Hub integration service using Ollama as execution backend.

Supports:
- Searching HuggingFace Hub for GGUF models
- Pulling HF models via ``ollama pull hf.co/<org>/<model>``
- Registering local GGUF files directly with Ollama
- Converting safetensors / PyTorch models to GGUF via llama.cpp
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

from colosseum.core.models import (
    HFModelSearchResult,
    HFRegisterRequest,
    HFRegisterResult,
    HFSearchResponse,
    LocalModelDownloadResult,
)
from colosseum.services.local_runtime import LocalRuntimeService

_log = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"
HF_SEARCH_TIMEOUT = 15.0

_CONVERT_SCRIPT_NAMES = ("convert_hf_to_gguf.py", "convert-hf-to-gguf.py")

# File extensions that indicate a HuggingFace / PyTorch model needing conversion
_HF_MODEL_EXTENSIONS = {".safetensors", ".bin", ".pt", ".pth"}


def _find_convert_script() -> str | None:
    """Locate ``convert_hf_to_gguf.py`` from llama.cpp."""
    env_path = os.environ.get("LLAMA_CPP_CONVERT_SCRIPT")
    if env_path and Path(env_path).is_file():
        return env_path

    llama_dir = os.environ.get("LLAMA_CPP_DIR")
    if llama_dir:
        for name in _CONVERT_SCRIPT_NAMES:
            candidate = Path(llama_dir) / name
            if candidate.is_file():
                return str(candidate)

    for name in _CONVERT_SCRIPT_NAMES:
        found = shutil.which(name)
        if found:
            return found

    for base in ("/usr/local/bin", "/usr/bin", str(Path.home() / ".local" / "bin")):
        for name in _CONVERT_SCRIPT_NAMES:
            candidate = Path(base) / name
            if candidate.is_file():
                return str(candidate)

    return None


def _detect_model_format(model_path: Path) -> str:
    """Detect the format of a model path.

    Returns one of: "gguf", "hf_dir", "hf_file", "unknown".
    """
    if model_path.is_file():
        ext = model_path.suffix.lower()
        if ext == ".gguf":
            return "gguf"
        if ext in _HF_MODEL_EXTENSIONS:
            return "hf_file"
        return "unknown"

    if model_path.is_dir():
        if (model_path / "config.json").exists():
            return "hf_dir"
        if list(model_path.glob("*.safetensors")) or list(model_path.glob("*.bin")):
            return "hf_dir"
        if list(model_path.glob("*.gguf")):
            return "gguf"
        return "unknown"

    return "unknown"


class HuggingFaceHubService:
    """Search, pull, and manage HuggingFace Hub models via Ollama backend."""

    def __init__(self, runtime_service: LocalRuntimeService | None = None) -> None:
        self._runtime = runtime_service or LocalRuntimeService()

    # ── Search ──

    def search(self, query: str, limit: int = 20) -> HFSearchResponse:
        """Search HuggingFace Hub for GGUF-compatible models."""
        params = {
            "search": query,
            "filter": "gguf",
            "sort": "downloads",
            "direction": "-1",
            "limit": str(min(limit, 100)),
        }
        try:
            resp = httpx.get(
                f"{HF_API_BASE}/models",
                params=params,
                timeout=HF_SEARCH_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            _log.warning("HuggingFace Hub search failed: %s", exc)
            return HFSearchResponse(query=query, results=[], total=0)

        results: list[HFModelSearchResult] = []
        for item in data if isinstance(data, list) else []:
            repo_id = item.get("id") or item.get("modelId") or ""
            if not repo_id:
                continue
            author = repo_id.split("/")[0] if "/" in repo_id else ""
            model_name = repo_id.split("/")[-1] if "/" in repo_id else repo_id
            results.append(
                HFModelSearchResult(
                    repo_id=repo_id,
                    author=author,
                    model_name=model_name,
                    downloads=item.get("downloads", 0),
                    likes=item.get("likes", 0),
                    tags=item.get("tags", []),
                    pipeline_tag=item.get("pipeline_tag"),
                    last_modified=item.get("lastModified"),
                )
            )

        return HFSearchResponse(query=query, results=results, total=len(results))

    # ── Pull ──

    def pull(self, repo_id: str) -> LocalModelDownloadResult:
        """Pull a HuggingFace model via ``ollama pull hf.co/<repo_id>``."""
        hf_tag = f"hf.co/{repo_id.strip()}"
        return self._runtime.download_model(hf_tag)

    # ── List ──

    def list_hf_models(self) -> list[str]:
        """Return installed models that originated from HuggingFace Hub."""
        all_models = self._runtime.list_installed_models()
        return [m for m in all_models if m.startswith("hf.co/")]

    # ── Register (smart: handles GGUF, safetensors, directories) ──

    def register_model(self, request: HFRegisterRequest) -> HFRegisterResult:
        """Register a model with Ollama, converting from HF format if needed."""
        model_path = Path(request.model_path).resolve()
        if not model_path.exists():
            return HFRegisterResult(
                success=False,
                name=request.name,
                message=f"Path not found: {model_path}",
            )

        fmt = _detect_model_format(model_path)

        if fmt == "gguf":
            gguf_file = model_path
            if model_path.is_dir():
                gguf_file = list(model_path.glob("*.gguf"))[0]
            return self._register_with_ollama(request.name, gguf_file)

        if fmt in ("hf_dir", "hf_file"):
            return self._convert_and_register(request, model_path, fmt)

        return HFRegisterResult(
            success=False,
            name=request.name,
            message=(
                f"Unrecognized model format at {model_path}. "
                "Supported: .gguf files, .safetensors/.bin files, "
                "or HuggingFace model directories with config.json."
            ),
        )

    # Backwards compat alias
    def register_gguf(self, request: HFRegisterRequest) -> HFRegisterResult:
        return self.register_model(request)

    # ── Tool availability ──

    @staticmethod
    def conversion_tools_available() -> dict[str, str | None]:
        """Check availability of the llama.cpp conversion script."""
        return {
            "convert_script": _find_convert_script(),
        }

    # ── Internal methods ──

    def _convert_and_register(
        self,
        request: HFRegisterRequest,
        model_path: Path,
        fmt: str,
    ) -> HFRegisterResult:
        """Convert a HF model to GGUF (F16) and register with Ollama."""
        convert_script = _find_convert_script()
        if not convert_script:
            return HFRegisterResult(
                success=False,
                name=request.name,
                message=(
                    "convert_hf_to_gguf.py not found. "
                    "Install llama.cpp and set LLAMA_CPP_DIR, or add "
                    "convert_hf_to_gguf.py to your PATH.\n"
                    "  git clone https://github.com/ggerganov/llama.cpp\n"
                    "  pip install -r llama.cpp/requirements.txt"
                ),
            )

        model_dir = model_path.parent if fmt == "hf_file" else model_path

        with tempfile.TemporaryDirectory(prefix="colosseum_gguf_") as tmpdir:
            output_gguf = Path(tmpdir) / f"{request.name}-f16.gguf"

            _log.info("Converting %s → GGUF (f16)...", model_dir)
            convert_result = subprocess.run(
                [
                    sys.executable, convert_script,
                    str(model_dir),
                    "--outfile", str(output_gguf),
                    "--outtype", "f16",
                ],
                capture_output=True,
                text=True,
                timeout=1800,  # 30 min max for large models
            )
            if convert_result.returncode != 0:
                error = convert_result.stderr.strip() or convert_result.stdout.strip()
                return HFRegisterResult(
                    success=False,
                    name=request.name,
                    message=f"GGUF conversion failed:\n{error[-800:]}",
                )

            if not output_gguf.exists():
                return HFRegisterResult(
                    success=False,
                    name=request.name,
                    message="Conversion completed but output GGUF file not found.",
                )

            result = self._register_with_ollama(request.name, output_gguf)
            result.gguf_path = str(output_gguf)
            return result

    def _register_with_ollama(self, name: str, gguf_path: Path) -> HFRegisterResult:
        """Create an Ollama model from a GGUF file via Modelfile."""
        self._runtime.ensure_runtime_started()

        modelfile_content = f"FROM {gguf_path}\n"
        fd, modelfile_path = tempfile.mkstemp(suffix=".Modelfile", prefix="colosseum_")
        try:
            os.write(fd, modelfile_content.encode("utf-8"))
            os.close(fd)

            env = os.environ.copy()
            env.update(self._runtime.provider_env())
            result = subprocess.run(
                ["ollama", "create", name, "-f", modelfile_path],
                capture_output=True,
                text=True,
                env=env,
            )
            success = result.returncode == 0
            message = result.stdout.strip() or result.stderr.strip() or "Model registered."
            return HFRegisterResult(
                success=success,
                name=name,
                message=message[-800:],
                gguf_path=str(gguf_path),
            )
        finally:
            Path(modelfile_path).unlink(missing_ok=True)
