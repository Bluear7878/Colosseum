"""Event bus for real-time debate progress tracking.

Writes structured events to a JSONL file that can be tailed by the monitor.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from colosseum.core.config import ARTIFACT_ROOT


class DebateEventBus:
    """Writes debate events to a JSONL file for real-time monitoring."""

    def __init__(self, run_id: str, root: Path | None = None) -> None:
        self.run_id = run_id
        self.root = root or ARTIFACT_ROOT
        self._event_path = self.root / run_id / "events.jsonl"
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        self._event_path.write_text("", encoding="utf-8")

    def emit(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "run_id": self.run_id,
            "data": data or {},
        }
        with self._event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
            f.flush()

    @property
    def path(self) -> Path:
        return self._event_path

    @staticmethod
    def event_path_for(run_id: str, root: Path | None = None) -> Path:
        return (root or ARTIFACT_ROOT) / run_id / "events.jsonl"


class EventReader:
    """Reads events from a JSONL file, supporting tail-like behavior."""

    def __init__(self, event_path: Path) -> None:
        self.event_path = event_path
        self._offset = 0

    def read_new(self) -> list[dict]:
        """Read any new events since last read."""
        if not self.event_path.exists():
            return []
        events = []
        with self.event_path.open("r", encoding="utf-8") as f:
            f.seek(self._offset)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            self._offset = f.tell()
        return events

    def read_all(self) -> list[dict]:
        """Read all events from the beginning."""
        if not self.event_path.exists():
            return []
        events = []
        with self.event_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return events
