from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from threading import Lock

from colosseum.core.config import (
    DEFAULT_LOCAL_RUNTIME_HOST,
    LOCAL_RUNTIME_LOG_PATH,
    LOCAL_RUNTIME_PID_PATH,
    LOCAL_RUNTIME_SETTINGS_PATH,
)
from colosseum.core.models import (
    LocalGpuDevice,
    LocalModelDownloadResult,
    LocalRuntimeConfigUpdate,
    LocalRuntimeSettings,
    LocalRuntimeStatus,
)


class LocalRuntimeService:
    """Manage the dedicated Ollama runtime Colosseum uses for local models."""

    READY_TIMEOUT_SECONDS = 20.0
    STOP_TIMEOUT_SECONDS = 10.0

    def __init__(
        self,
        settings_path: Path | None = None,
        pid_path: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.settings_path = settings_path or LOCAL_RUNTIME_SETTINGS_PATH
        self.pid_path = pid_path or LOCAL_RUNTIME_PID_PATH
        self.log_path = log_path or LOCAL_RUNTIME_LOG_PATH
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def normalize_model_name(model_name: str) -> str:
        """Normalize UI/CLI model IDs into the tag Ollama expects."""
        normalized = str(model_name or "").strip()
        normalized = re.sub(r"^(ollama|hf|huggingface):", "", normalized)
        return normalized.strip()

    def load_settings(self) -> LocalRuntimeSettings:
        """Load persisted runtime settings, falling back to safe defaults."""
        default_settings = LocalRuntimeSettings(host=DEFAULT_LOCAL_RUNTIME_HOST)
        try:
            raw = self.settings_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return default_settings

        try:
            return LocalRuntimeSettings.model_validate_json(raw)
        except Exception:
            return default_settings

    def save_settings(self, update: LocalRuntimeConfigUpdate) -> LocalRuntimeSettings:
        """Persist a partial runtime settings update."""
        with self._lock:
            current = self.load_settings()
            merged_update: dict[str, object] = {}
            if "gpu_count" in update.model_fields_set:
                merged_update["gpu_count"] = update.gpu_count
            if "auto_start" in update.model_fields_set:
                merged_update["auto_start"] = update.auto_start
            merged = current.model_copy(update=merged_update)
            self.settings_path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")
            return merged

    def provider_env(self) -> dict[str, str]:
        """Return runtime-specific environment variables for local providers."""
        settings = self.load_settings()
        return {
            "OLLAMA_HOST": settings.host,
            "COLOSSEUM_LOCAL_RUNTIME_MANAGED": "1",
        }

    def detect_gpu_devices(self) -> list[LocalGpuDevice]:
        """Detect host GPUs Colosseum can expose to the managed runtime."""
        devices = self._detect_nvidia_devices()
        return devices

    def selected_gpu_indices(
        self,
        settings: LocalRuntimeSettings | None = None,
        devices: list[LocalGpuDevice] | None = None,
    ) -> list[int]:
        """Resolve the visible GPU indices from the current settings."""
        settings = settings or self.load_settings()
        devices = devices if devices is not None else self.detect_gpu_devices()
        if not devices:
            return []
        if settings.gpu_count is None:
            return [device.index for device in devices]
        if settings.gpu_count <= 0:
            return []
        return [device.index for device in devices[: settings.gpu_count]]

    def get_status(self, ensure_ready: bool = False) -> LocalRuntimeStatus:
        """Return the managed runtime status for the UI and CLI."""
        if ensure_ready and self._ollama_installed():
            try:
                self.ensure_runtime_started()
            except RuntimeError:
                pass

        settings = self.load_settings()
        devices = self.detect_gpu_devices()
        selected_gpu_indices = self.selected_gpu_indices(settings, devices)
        runtime_running = self._runtime_ready(settings.host)
        managed_pid = self._read_pid()
        if managed_pid and not self._pid_is_running(managed_pid):
            self._clear_pid()
            managed_pid = None

        installed_models: list[str] = []
        installed_models_known = False
        if runtime_running:
            installed_models = self.list_installed_models()
            installed_models_known = True

        return LocalRuntimeStatus(
            settings=settings,
            ollama_installed=self._ollama_installed(),
            ollama_version=self._ollama_version(),
            runtime_running=runtime_running,
            managed_pid=managed_pid,
            gpu_devices=devices,
            selected_gpu_indices=selected_gpu_indices,
            selected_gpu_count=len(selected_gpu_indices),
            installed_models=installed_models,
            installed_models_known=installed_models_known,
            runtime_note=self._build_runtime_note(
                settings, devices, selected_gpu_indices, runtime_running
            ),
        )

    def update_settings(self, update: LocalRuntimeConfigUpdate) -> LocalRuntimeStatus:
        """Persist settings and optionally restart the managed runtime."""
        self.save_settings(update)
        if update.restart_runtime and self._ollama_installed():
            self.restart_runtime()
        return self.get_status()

    def ensure_runtime_started(self) -> LocalRuntimeStatus:
        """Start the managed runtime on demand when local models need it."""
        settings = self.load_settings()
        if self._runtime_ready(settings.host):
            return self.get_status()
        if not settings.auto_start:
            raise RuntimeError(
                "Managed local runtime is disabled for auto-start. Re-enable it or start it explicitly."
            )
        return self.start_runtime()

    def start_runtime(self) -> LocalRuntimeStatus:
        """Start the dedicated Ollama runtime using the persisted GPU settings."""
        if not self._ollama_installed():
            raise RuntimeError("Ollama is not installed. Install it before starting local models.")

        with self._lock:
            settings = self.load_settings()
            if self._runtime_ready(settings.host):
                return self.get_status()

            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_env = os.environ.copy()
            runtime_env.update(self._build_runtime_env(settings))

            with self.log_path.open("ab") as log_handle:
                process = subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    env=runtime_env,
                    start_new_session=True,
                )

            self.pid_path.write_text(f"{process.pid}\n", encoding="utf-8")

        self._wait_for_ready(settings.host, process.pid)
        return self.get_status()

    def stop_runtime(self) -> LocalRuntimeStatus:
        """Stop the managed runtime if Colosseum started it."""
        with self._lock:
            pid = self._read_pid()
            if pid is None:
                return self.get_status()

            self._terminate_pid(pid)
            self._clear_pid()
            return self.get_status()

    def restart_runtime(self) -> LocalRuntimeStatus:
        """Restart the managed runtime so new GPU settings take effect."""
        try:
            self.stop_runtime()
        except Exception:
            self._clear_pid()
        return self.start_runtime()

    def list_installed_models(self) -> list[str]:
        """List models installed in the managed Ollama runtime."""
        settings = self.load_settings()
        if not self._runtime_ready(settings.host):
            return []
        env = os.environ.copy()
        env.update(self.provider_env())
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
        if result.returncode != 0:
            return []

        models: list[str] = []
        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            models.append(parts[0])
        return models

    def download_model(self, model_name: str) -> LocalModelDownloadResult:
        """Download a missing model into the managed runtime."""
        normalized = self.normalize_model_name(model_name)
        if not normalized:
            raise RuntimeError("Choose a model name before downloading.")
        if not self._ollama_installed():
            raise RuntimeError(
                "Ollama is not installed. Install it before downloading local models."
            )

        self.ensure_runtime_started()
        env = os.environ.copy()
        env.update(self.provider_env())
        result = subprocess.run(
            ["ollama", "pull", normalized],
            capture_output=True,
            text=True,
            env=env,
        )
        success = result.returncode == 0
        message = result.stdout.strip() or result.stderr.strip() or "Download finished."
        status = self.get_status()
        return LocalModelDownloadResult(
            success=success,
            model=normalized,
            message=message[-800:],
            status=status,
        )

    def model_is_installed(self, model_name: str) -> bool:
        """Check whether a model tag is already installed in the managed runtime."""
        normalized = self.normalize_model_name(model_name)
        if not normalized:
            return False

        installed = self.list_installed_models()
        target_aliases = {normalized, f"{normalized}:latest"}
        for item in installed:
            if item in target_aliases:
                return True
            if item.endswith(":latest") and item[:-7] == normalized:
                return True
        return False

    def _build_runtime_env(self, settings: LocalRuntimeSettings) -> dict[str, str]:
        """Build the environment block used to launch the managed runtime."""
        env = self.provider_env()
        devices = self.detect_gpu_devices()
        selected_indices = self.selected_gpu_indices(settings, devices)
        if devices:
            backend = devices[0].backend
            if settings.gpu_count == 0:
                if backend == "nvidia":
                    env["CUDA_VISIBLE_DEVICES"] = "-1"
                elif backend == "amd":
                    env["ROCR_VISIBLE_DEVICES"] = ""
            elif selected_indices:
                visible_devices = ",".join(str(index) for index in selected_indices)
                if backend == "nvidia":
                    env["CUDA_VISIBLE_DEVICES"] = visible_devices
                elif backend == "amd":
                    env["ROCR_VISIBLE_DEVICES"] = visible_devices
        return env

    def _detect_nvidia_devices(self) -> list[LocalGpuDevice]:
        if not shutil_which("nvidia-smi"):
            return []
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        devices: list[LocalGpuDevice] = []
        for line in result.stdout.strip().splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                memory_total_mb = int(parts[2])
            except ValueError:
                memory_total_mb = None
            try:
                index = int(parts[0])
            except ValueError:
                continue
            devices.append(
                LocalGpuDevice(
                    index=index,
                    backend="nvidia",
                    name=parts[1] or f"GPU {index}",
                    memory_total_mb=memory_total_mb,
                    driver_version=parts[3] or None,
                )
            )
        return devices

    def _ollama_installed(self) -> bool:
        return shutil_which("ollama") is not None

    def _ollama_version(self) -> str | None:
        if not self._ollama_installed():
            return None
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout or "")
        if match:
            return match.group(1)
        return None

    def _runtime_ready(self, host: str) -> bool:
        if not self._ollama_installed():
            return False
        env = os.environ.copy()
        env["OLLAMA_HOST"] = host
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
        except Exception:
            return False
        return result.returncode == 0

    def _wait_for_ready(self, host: str, pid: int) -> None:
        deadline = time.monotonic() + self.READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._runtime_ready(host):
                return
            if not self._pid_is_running(pid):
                break
            time.sleep(0.4)
        raise RuntimeError(
            "Managed Ollama runtime did not become ready. "
            f"Recent log output:\n{self._read_log_tail()}"
        )

    def _terminate_pid(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            os.kill(pid, signal.SIGTERM)

        deadline = time.monotonic() + self.STOP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if not self._pid_is_running(pid):
                return
            time.sleep(0.25)

        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError:
            os.kill(pid, signal.SIGKILL)

    def _read_pid(self) -> int | None:
        try:
            raw = self.pid_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _clear_pid(self) -> None:
        self.pid_path.unlink(missing_ok=True)

    def _pid_is_running(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _read_log_tail(self, max_bytes: int = 1600) -> str:
        try:
            data = self.log_path.read_bytes()
        except FileNotFoundError:
            return "(no runtime log yet)"
        if not data:
            return "(runtime log is empty)"
        return data[-max_bytes:].decode("utf-8", errors="replace")

    def _build_runtime_note(
        self,
        settings: LocalRuntimeSettings,
        devices: list[LocalGpuDevice],
        selected_gpu_indices: list[int],
        runtime_running: bool,
    ) -> str:
        state_label = "running" if runtime_running else "stopped"
        if not self._ollama_installed():
            return "Ollama is not installed. Install it to use local models."
        if not devices:
            return f"Managed runtime is {state_label}. No compatible GPUs detected; local models will run on CPU."
        if settings.gpu_count is None:
            return f"Managed runtime is {state_label}. Auto mode will expose all {len(devices)} detected GPU(s)."
        if settings.gpu_count == 0:
            return f"Managed runtime is {state_label}. CPU-only mode is selected."
        requested = settings.gpu_count
        actual = len(selected_gpu_indices)
        if requested > len(devices):
            return (
                f"Managed runtime is {state_label}. Requested {requested} GPU(s), "
                f"but only {len(devices)} were detected, so Colosseum will use {actual}."
            )
        return f"Managed runtime is {state_label}. Colosseum will use the first {actual} GPU(s)."


def shutil_which(binary: str) -> str | None:
    """Small wrapper to keep the service import surface minimal."""
    import shutil

    return shutil.which(binary)
