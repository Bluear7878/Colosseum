"""Tests for HuggingFace Hub integration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from colosseum.core.models import (
    HFPullRequest,
    HFRegisterRequest,
    HFSearchResponse,
    LocalModelDownloadResult,
    LocalRuntimeSettings,
    LocalRuntimeStatus,
)
from colosseum.services.hf_hub import (
    HuggingFaceHubService,
    _detect_model_format,
    _find_convert_script,
)
from colosseum.services.local_runtime import LocalRuntimeService


# ── normalize_model_name ──


def test_normalize_preserves_hf_co_prefix():
    assert LocalRuntimeService.normalize_model_name("hf.co/org/model") == "hf.co/org/model"


def test_normalize_strips_hf_colon_prefix():
    assert LocalRuntimeService.normalize_model_name("hf:custom-model") == "custom-model"


def test_normalize_strips_ollama_prefix():
    assert LocalRuntimeService.normalize_model_name("ollama:llama3.3") == "llama3.3"


def test_normalize_passthrough():
    assert LocalRuntimeService.normalize_model_name("llama3.3") == "llama3.3"


# ── HuggingFaceHubService.pull ──


def test_pull_delegates_to_runtime_with_hf_prefix():
    mock_runtime = MagicMock(spec=LocalRuntimeService)
    mock_runtime.download_model.return_value = LocalModelDownloadResult(
        success=True,
        model="hf.co/bartowski/test",
        message="ok",
        status=LocalRuntimeStatus(
            settings=LocalRuntimeSettings(host="127.0.0.1:11435"),
            ollama_installed=True,
            runtime_running=True,
        ),
    )
    service = HuggingFaceHubService(runtime_service=mock_runtime)
    result = service.pull("bartowski/test")
    mock_runtime.download_model.assert_called_once_with("hf.co/bartowski/test")
    assert result.success


# ── HuggingFaceHubService.list_hf_models ──


def test_list_hf_models_filters_prefix():
    mock_runtime = MagicMock(spec=LocalRuntimeService)
    mock_runtime.list_installed_models.return_value = [
        "llama3.3:latest",
        "hf.co/bartowski/Llama-3.3-70B:latest",
        "mistral:latest",
        "hf.co/TheBloke/phi-2-GGUF:latest",
    ]
    service = HuggingFaceHubService(runtime_service=mock_runtime)
    result = service.list_hf_models()
    assert result == [
        "hf.co/bartowski/Llama-3.3-70B:latest",
        "hf.co/TheBloke/phi-2-GGUF:latest",
    ]


# ── HuggingFaceHubService.search ──


def test_search_parses_hf_api_response():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": "bartowski/Llama-3.3-70B-Instruct-GGUF",
            "downloads": 50000,
            "likes": 120,
            "tags": ["gguf", "llama"],
            "pipeline_tag": "text-generation",
        },
        {
            "id": "TheBloke/Mistral-7B-v0.1-GGUF",
            "downloads": 30000,
            "likes": 80,
            "tags": ["gguf"],
        },
    ]
    mock_response.raise_for_status = MagicMock()

    with patch("colosseum.services.hf_hub.httpx.get", return_value=mock_response):
        service = HuggingFaceHubService(runtime_service=MagicMock())
        result = service.search("llama", limit=10)

    assert isinstance(result, HFSearchResponse)
    assert result.query == "llama"
    assert len(result.results) == 2
    assert result.results[0].repo_id == "bartowski/Llama-3.3-70B-Instruct-GGUF"
    assert result.results[0].downloads == 50000
    assert result.results[1].author == "TheBloke"


def test_search_handles_http_error():
    import httpx

    with patch("colosseum.services.hf_hub.httpx.get", side_effect=httpx.ConnectError("fail")):
        service = HuggingFaceHubService(runtime_service=MagicMock())
        result = service.search("test")

    assert result.results == []
    assert result.total == 0


# ── _detect_model_format ──


def test_detect_gguf_file(tmp_path):
    f = tmp_path / "model.gguf"
    f.write_bytes(b"fake")
    assert _detect_model_format(f) == "gguf"


def test_detect_safetensors_file(tmp_path):
    f = tmp_path / "model.safetensors"
    f.write_bytes(b"fake")
    assert _detect_model_format(f) == "hf_file"


def test_detect_bin_file(tmp_path):
    f = tmp_path / "pytorch_model.bin"
    f.write_bytes(b"fake")
    assert _detect_model_format(f) == "hf_file"


def test_detect_hf_directory(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"fake")
    assert _detect_model_format(tmp_path) == "hf_dir"


def test_detect_directory_with_gguf(tmp_path):
    (tmp_path / "model.gguf").write_bytes(b"fake")
    assert _detect_model_format(tmp_path) == "gguf"


def test_detect_unknown_file(tmp_path):
    f = tmp_path / "model.txt"
    f.write_text("not a model")
    assert _detect_model_format(f) == "unknown"


# ── register_model: GGUF path ──


def test_register_model_missing_path():
    service = HuggingFaceHubService(runtime_service=MagicMock())
    result = service.register_model(
        HFRegisterRequest(name="test", model_path="/nonexistent/model.gguf")
    )
    assert not result.success
    assert "not found" in result.message


def test_register_model_gguf_success(tmp_path):
    gguf_file = tmp_path / "model.gguf"
    gguf_file.write_bytes(b"fake gguf data")

    mock_runtime = MagicMock(spec=LocalRuntimeService)
    mock_runtime.ensure_runtime_started.return_value = None
    mock_runtime.provider_env.return_value = {"OLLAMA_HOST": "127.0.0.1:11435"}

    with patch("colosseum.services.hf_hub.subprocess.run") as mock_run:
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="success", stderr="")
        service = HuggingFaceHubService(runtime_service=mock_runtime)
        result = service.register_model(
            HFRegisterRequest(name="my-model", model_path=str(gguf_file))
        )

    assert result.success
    assert result.name == "my-model"
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "ollama"
    assert call_args[1] == "create"
    assert call_args[2] == "my-model"


def test_register_model_unknown_format(tmp_path):
    txt_file = tmp_path / "model.txt"
    txt_file.write_text("not a model")
    service = HuggingFaceHubService(runtime_service=MagicMock())
    result = service.register_model(
        HFRegisterRequest(name="test", model_path=str(txt_file))
    )
    assert not result.success
    assert "Unrecognized" in result.message


# ── register_model: conversion path ──


def test_register_model_safetensors_no_convert_script(tmp_path):
    sf = tmp_path / "model.safetensors"
    sf.write_bytes(b"fake")

    with patch("colosseum.services.hf_hub._find_convert_script", return_value=None):
        service = HuggingFaceHubService(runtime_service=MagicMock())
        result = service.register_model(
            HFRegisterRequest(name="test", model_path=str(sf))
        )

    assert not result.success
    assert "convert_hf_to_gguf.py" in result.message


def test_register_model_hf_dir_conversion_success(tmp_path):
    model_dir = tmp_path / "my-model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    (model_dir / "model.safetensors").write_bytes(b"fake")

    mock_runtime = MagicMock(spec=LocalRuntimeService)
    mock_runtime.ensure_runtime_started.return_value = None
    mock_runtime.provider_env.return_value = {"OLLAMA_HOST": "127.0.0.1:11435"}

    def fake_subprocess_run(cmd, **_kwargs):
        if "convert_hf_to_gguf" in str(cmd):
            outfile_idx = cmd.index("--outfile") + 1
            from pathlib import Path as P
            P(cmd[outfile_idx]).write_bytes(b"fake gguf")
            return SimpleNamespace(returncode=0, stdout="converted", stderr="")
        if cmd[0] == "ollama":
            return SimpleNamespace(returncode=0, stdout="created", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unknown cmd")

    with (
        patch("colosseum.services.hf_hub._find_convert_script", return_value="/fake/convert_hf_to_gguf.py"),
        patch("colosseum.services.hf_hub.subprocess.run", side_effect=fake_subprocess_run),
    ):
        service = HuggingFaceHubService(runtime_service=mock_runtime)
        result = service.register_model(
            HFRegisterRequest(name="my-model", model_path=str(model_dir))
        )

    assert result.success
    assert result.name == "my-model"


# ── Pydantic validation ──


def test_hf_pull_request_requires_slash():
    with pytest.raises(Exception):
        HFPullRequest(repo_id="no-slash-here")


def test_hf_pull_request_accepts_valid():
    req = HFPullRequest(repo_id="org/model")
    assert req.repo_id == "org/model"


# ── Tool detection ──


def test_find_convert_script_env_var(tmp_path):
    script = tmp_path / "convert_hf_to_gguf.py"
    script.write_text("# fake")
    with patch.dict("os.environ", {"LLAMA_CPP_CONVERT_SCRIPT": str(script)}):
        assert _find_convert_script() == str(script)
