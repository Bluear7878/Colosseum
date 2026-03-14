"""Tests for the event bus and monitor system."""

from __future__ import annotations

from pathlib import Path

from colosseum.monitor import MonitorState, render
from colosseum.services.event_bus import DebateEventBus, EventReader


def test_event_bus_write_and_read(tmp_path: Path):
    bus = DebateEventBus("test-run-001", root=tmp_path)
    bus.emit("debate_start", {"topic": "Test topic", "max_rounds": 3})
    bus.emit("phase", {"phase": "context"})
    bus.emit("agent_planning", {"agent_id": "a1", "display_name": "Alice"})

    reader = EventReader(bus.path)
    events = reader.read_all()
    assert len(events) == 3
    assert events[0]["type"] == "debate_start"
    assert events[0]["data"]["topic"] == "Test topic"
    assert events[1]["type"] == "phase"
    assert events[2]["type"] == "agent_planning"


def test_event_reader_incremental(tmp_path: Path):
    bus = DebateEventBus("test-run-002", root=tmp_path)
    reader = EventReader(bus.path)

    bus.emit("phase", {"phase": "init"})
    batch1 = reader.read_new()
    assert len(batch1) == 1

    bus.emit("phase", {"phase": "context"})
    bus.emit("phase", {"phase": "planning"})
    batch2 = reader.read_new()
    assert len(batch2) == 2
    assert batch2[0]["data"]["phase"] == "context"

    # No new events
    batch3 = reader.read_new()
    assert len(batch3) == 0


def test_monitor_state_processes_events():
    state = MonitorState()

    state.process_event(
        {
            "ts": "2026-03-13T10:00:00+00:00",
            "type": "debate_start",
            "run_id": "abc123",
            "data": {
                "topic": "Rust vs Go",
                "token_budget": 80000,
                "max_rounds": 5,
                "agents": [
                    {"agent_id": "claude", "display_name": "Claude"},
                    {"agent_id": "codex", "display_name": "Codex"},
                ],
            },
        }
    )
    assert state.run_id == "abc123"
    assert state.topic == "Rust vs Go"
    assert state.token_budget == 80000
    assert state.max_rounds == 5
    assert "claude" in state.agents
    assert "codex" in state.agents

    state.process_event(
        {
            "ts": "2026-03-13T10:00:01+00:00",
            "type": "phase",
            "run_id": "abc123",
            "data": {"phase": "planning", "status": "planning"},
        }
    )
    assert state.phase == "planning"
    assert "init" in state.completed_phases
    assert "context" in state.completed_phases

    state.process_event(
        {
            "ts": "2026-03-13T10:00:02+00:00",
            "type": "agent_thinking",
            "run_id": "abc123",
            "data": {"agent_id": "claude", "display_name": "Claude", "round_index": 1},
        }
    )
    assert "thinking" in state.agents["claude"]["status"]

    state.process_event(
        {
            "ts": "2026-03-13T10:00:03+00:00",
            "type": "agent_message",
            "run_id": "abc123",
            "data": {
                "agent_id": "claude",
                "display_name": "Claude",
                "novelty_score": 0.85,
                "usage": {"total_tokens": 1200},
            },
        }
    )
    assert "responded" in state.agents["claude"]["status"]
    assert state.agents["claude"]["tokens"] == 1200
    assert state.total_tokens == 1200

    state.process_event(
        {
            "ts": "2026-03-13T10:00:04+00:00",
            "type": "judge_decision",
            "run_id": "abc123",
            "data": {
                "action": "continue_debate",
                "confidence": 0.72,
                "disagreement_level": 0.65,
                "focus": "correctness, performance",
                "next_round_type": "rebuttal",
            },
        }
    )
    assert state.last_judge_action == "continue_debate"
    assert state.last_judge_confidence == 0.72

    state.process_event(
        {
            "ts": "2026-03-13T10:00:05+00:00",
            "type": "verdict",
            "run_id": "abc123",
            "data": {
                "verdict_type": "winner",
                "winners": ["Claude"],
                "confidence": 0.88,
                "final_answer": "Choose Claude's approach because it is more reliable.",
            },
        }
    )
    assert state.verdict_type == "winner"
    assert "more reliable" in state.final_answer
    assert state.status == "completed"


def test_render_produces_output():
    state = MonitorState()
    state.run_id = "test-run"
    state.topic = "Test topic"
    state.status = "debating"
    state.phase = "debate"
    state.completed_phases = {"init", "context", "planning"}
    state.total_tokens = 40000
    state.token_budget = 80000
    state.rounds_done = 2
    state.max_rounds = 5
    state.agents = {
        "a1": {"name": "Claude", "status": "thinking...", "tokens": 20000},
        "a2": {"name": "Codex", "status": "responded", "tokens": 20000},
    }
    state.last_judge_action = "continue_debate"
    state.last_judge_confidence = 0.72
    state.last_judge_disagreement = 0.5
    state.verdict_type = "winner"
    state.verdict_winners = ["Claude"]
    state.verdict_confidence = 0.88
    state.final_answer = "Choose Claude's approach because it directly answers the user's question."

    output = render(state, term_height=40)
    assert "COLOSSEUM MONITOR" in output
    assert "test-run" in output
    assert "DEBATING" in output
    assert "Claude" in output
    assert "Codex" in output
    assert "CONTINUE_DEBATE" in output
    assert "Final Answer" in output
    assert "directly answers" in output
    assert "user's question" in output


def test_event_bus_path_for(tmp_path: Path):
    path = DebateEventBus.event_path_for("my-run", root=tmp_path)
    assert path == tmp_path / "my-run" / "events.jsonl"
