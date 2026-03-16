from __future__ import annotations

from fastapi.testclient import TestClient

from colosseum.core.models import LocalModelDownloadResult, LocalRuntimeStatus
from colosseum.main import create_app


class FakeLocalRuntimeService:
    def get_status(self, ensure_ready: bool = False) -> LocalRuntimeStatus:
        return LocalRuntimeStatus(
            ollama_installed=True,
            runtime_running=ensure_ready,
            installed_models=["llama3.3:latest"] if ensure_ready else [],
            installed_models_known=ensure_ready,
        )

    def update_settings(self, update) -> LocalRuntimeStatus:
        indices = update.selected_gpu_indices if update.selected_gpu_indices is not None else []
        return LocalRuntimeStatus(
            ollama_installed=True,
            runtime_running=True,
            selected_gpu_indices=indices,
            selected_gpu_count=len(indices),
            installed_models=["llama3.3:latest"],
            installed_models_known=True,
        )

    def download_model(self, model: str) -> LocalModelDownloadResult:
        return LocalModelDownloadResult(
            success=True,
            model=model.replace("ollama:", ""),
            message="downloaded",
            status=LocalRuntimeStatus(
                ollama_installed=True,
                runtime_running=True,
                installed_models=["llama3.3:latest"],
                installed_models_known=True,
            ),
        )


def test_local_runtime_api_endpoints(monkeypatch):
    monkeypatch.setenv("COLOSSEUM_DISABLE_STARTUP_PROBE", "1")
    monkeypatch.setattr("colosseum.api.routes_setup.LocalRuntimeService", FakeLocalRuntimeService)

    client = TestClient(create_app())

    status_response = client.get("/local-runtime/status", params={"ensure_ready": "true"})
    assert status_response.status_code == 200
    assert status_response.json()["runtime_running"] is True

    config_response = client.post("/local-runtime/config", json={"selected_gpu_indices": [0, 1]})
    assert config_response.status_code == 200
    assert config_response.json()["selected_gpu_count"] == 2

    download_response = client.post("/local-models/download", json={"model": "ollama:llama3.3"})
    assert download_response.status_code == 200
    assert download_response.json()["model"] == "llama3.3"
