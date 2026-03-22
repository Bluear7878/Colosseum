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

    selected = service.resolve_selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[0, 1, 2, 3]),
        devices,
    )
    assert selected == [0, 1]

    cpu_env = service._build_runtime_env(LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[]))
    assert cpu_env["CUDA_VISIBLE_DEVICES"] == "-1"


def test_local_runtime_selected_gpu_indices_logic(tmp_path):
    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )
    devices = [
        LocalGpuDevice(index=0, backend="nvidia", name="GPU 0", memory_total_mb=8192),
        LocalGpuDevice(index=1, backend="nvidia", name="GPU 1", memory_total_mb=16384),
        LocalGpuDevice(index=2, backend="nvidia", name="GPU 2", memory_total_mb=24576),
    ]

    # None (auto) → all indices
    assert service.resolve_selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=None), devices
    ) == [0, 1, 2]

    # Empty list → CPU only
    assert service.resolve_selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[]), devices
    ) == []

    # Specific indices
    assert service.resolve_selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[1]), devices
    ) == [1]

    # Out-of-range indices are filtered
    assert service.resolve_selected_gpu_indices(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[0, 5]), devices
    ) == [0]

    # Build env: specific GPU 1 only
    env = service._build_runtime_env(
        LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[1])
    )
    # Need to patch detect_gpu_devices
    service.detect_gpu_devices = lambda: devices  # type: ignore[method-assign]
    env2 = service._build_runtime_env(LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[1]))
    assert env2["CUDA_VISIBLE_DEVICES"] == "1"

    env3 = service._build_runtime_env(LocalRuntimeSettings(host="127.0.0.1:11435", selected_gpu_indices=[0, 2]))
    assert env3["CUDA_VISIBLE_DEVICES"] == "0,2"


def test_llmfit_installed_and_version(tmp_path, monkeypatch):
    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )
    # Not installed
    monkeypatch.setattr("colosseum.services.local_runtime.shutil_which", lambda name: None if name == "llmfit" else "/usr/bin/ollama")
    assert service._llmfit_installed() is False
    assert service._llmfit_version() is None

    # Installed with version output
    import types
    monkeypatch.setattr("colosseum.services.local_runtime.shutil_which", lambda name: "/usr/local/bin/" + name)
    monkeypatch.setattr(
        "colosseum.services.local_runtime.subprocess.run",
        lambda cmd, **kwargs: types.SimpleNamespace(returncode=0, stdout="llmfit 0.7.4\n", stderr=""),
    )
    assert service._llmfit_installed() is True
    assert service._llmfit_version() == "0.7.4"


def test_check_model_fit_llmfit_not_installed(tmp_path, monkeypatch):
    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )
    monkeypatch.setattr(service, "_llmfit_installed", lambda: False)
    result = service.check_model_fit("llama3.3")
    assert result.fit_level == "unknown"
    assert result.can_run is None
    assert "llmfit" in result.message.lower()


def test_check_model_fit_success(tmp_path, monkeypatch):
    import json

    service = LocalRuntimeService(
        settings_path=tmp_path / "runtime.json",
        pid_path=tmp_path / "runtime.pid",
        log_path=tmp_path / "runtime.log",
    )
    monkeypatch.setattr(service, "_llmfit_installed", lambda: True)

    # Mock subprocess.Popen
    class FakeProc:
        def terminate(self): pass
        def wait(self, timeout=None): pass
        def kill(self): pass

    monkeypatch.setattr("colosseum.services.local_runtime.subprocess.Popen", lambda *a, **kw: FakeProc())

    # Mock urllib.request.urlopen to simulate health + model response
    model_resp_data = json.dumps({"models": [{"fit_level": "Good", "run_mode": "Gpu"}]}).encode()

    class FakeResp:
        def __init__(self, data: bytes) -> None:
            self._data = data
        def read(self) -> bytes:
            return self._data
        def __enter__(self) -> "FakeResp":
            return self
        def __exit__(self, *args: object) -> None:
            pass

    def fake_urlopen(url, timeout=None):
        if "/health" in str(url):
            return FakeResp(b"ok")
        return FakeResp(model_resp_data)

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

    result = service.check_model_fit("llama3.3")
    assert result.fit_level == "good"
    assert result.can_run is True
    assert result.run_mode == "gpu"


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
