from __future__ import annotations

from types import SimpleNamespace

from colosseum.core.models import LocalGpuDevice, LocalRuntimeSettings, LocalRuntimeStatus
from colosseum.services.local_runtime import LocalRuntimeService


def test_local_runtime_builds_gpu_env_and_clamps_count(tmp_path):
    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )

    devices = [
        LocalGpuDevice(index=0, backend="nvidia", name="GPU 0", memory_total_mb=24576),
        LocalGpuDevice(index=1, backend="nvidia", name="GPU 1", memory_total_mb=24576),
    ]
    service.detect_gpu_devices = lambda: devices  # type: ignore[method-assign]

    selected = service.selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", gpu_count=4),
        devices,
    )
    assert selected == [0, 1]

    cpu_env = service._build_runtime_env(LocalRuntimeSettings(host="127.0.0.1:11435", gpu_count=0))
    assert cpu_env["CUDA_VISIBLE_DEVICES"] == "-1"


def test_local_runtime_download_normalizes_model_and_uses_managed_host(tmp_path, monkeypatch):
    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )

    monkeypatch.setattr(service, "_ollama_installed", lambda: True)
    monkeypatch.setattr(service, "ensure_runtime_started", lambda: LocalRuntimeStatus())
    monkeypatch.setattr(
        service,
        "get_status",
        lambda: LocalRuntimeStatus(
            ollama_installed=True,
            runtime_running=True,
            installed_models=["llama3.3:latest"],
            installed_models_known=True,
        ),
    )

    captured: dict[str, object] = {}

    def fake_run(cmd, capture_output, text, env, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return SimpleNamespace(returncode=0, stdout="pulled", stderr="")

    monkeypatch.setattr("colosseum.services.local_runtime.subprocess.run", fake_run)

    result = service.download_model("ollama:llama3.3")

    assert result.success is True
    assert result.model == "llama3.3"
    assert captured["cmd"] == ["ollama", "pull", "llama3.3"]
    assert captured["env"]["OLLAMA_HOST"] == "127.0.0.1:11435"
