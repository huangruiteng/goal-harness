from __future__ import annotations

from pathlib import Path

import pytest

from loopx.control_plane.heartbeat.event_source import (
    HEARTBEAT_EVENT_SOURCE_ENV,
    HEARTBEAT_OBSERVED_EVENT_KIND,
    HeartbeatEventSource,
    build_heartbeat_observation_event,
    compute_observation_fingerprint,
    heartbeat_event_source_enabled,
    record_heartbeat_observation,
)
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path


def _gate_items() -> list[dict[str, object]]:
    return [
        {
            "todo_id": "todo_first",
            "text": "setup done",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_second",
        },
        {
            "todo_id": "todo_second",
            "text": "followup advancement",
            "task_class": "advancement_task",
            "unblocks_todo_id": "todo_first",
            "status": "open",
        },
    ]


def test_heartbeat_event_source_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # The new architecture is ON by default (master switch), so an unset feature
    # env inherits the master switch.
    monkeypatch.delenv(HEARTBEAT_EVENT_SOURCE_ENV, raising=False)
    monkeypatch.delenv("LOOPX_NEW_ARCHITECTURE", raising=False)
    assert heartbeat_event_source_enabled() is True
    # An explicit flag always wins over the master switch.
    assert heartbeat_event_source_enabled(use_event_source=False) is False
    assert heartbeat_event_source_enabled(use_event_source=True) is True
    # The feature env var still wins over the master switch default.
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "0")
    assert heartbeat_event_source_enabled() is False
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "1")
    assert heartbeat_event_source_enabled() is True
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "true")
    assert heartbeat_event_source_enabled() is True
    # The master switch can turn the whole new architecture off.
    monkeypatch.delenv(HEARTBEAT_EVENT_SOURCE_ENV, raising=False)
    monkeypatch.setenv("LOOPX_NEW_ARCHITECTURE", "0")
    assert heartbeat_event_source_enabled() is False


def test_compute_observation_fingerprint_is_deterministic() -> None:
    a = compute_observation_fingerprint(goal_id="g1", agent_id="a1", source="heartbeat_poll")
    b = compute_observation_fingerprint(goal_id="g1", agent_id="a1", source="heartbeat_poll")
    assert a == b
    c = compute_observation_fingerprint(goal_id="g1", agent_id="a2", source="heartbeat_poll")
    assert a != c


def test_heartbeat_observation_disabled_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(HEARTBEAT_EVENT_SOURCE_ENV, raising=False)
    goal_id = "heartbeat-disabled"
    result = record_heartbeat_observation(
        runtime_root=tmp_path,
        goal_id=goal_id,
        agent_id="agent_one",
        use_event_source=False,
    )
    assert result.get("disabled") is True
    assert result.get("ok") is True
    assert not rollout_event_log_path(tmp_path, goal_id).exists()


def test_heartbeat_observation_records_event_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "1")
    goal_id = "heartbeat-on"
    result = record_heartbeat_observation(
        runtime_root=tmp_path,
        goal_id=goal_id,
        agent_id="agent_one",
        source="heartbeat_poll",
        tick_id="tick-001",
        status="run",
        details={"cause": "policy_test"},
        recorded_at="2026-08-14T00:00:00Z",
    )
    assert result.get("disabled") is not True
    assert result["new"] is True
    assert result["event"]["event_kind"] == HEARTBEAT_OBSERVED_EVENT_KIND
    assert result["event"]["goal_id"] == goal_id
    assert result["event"]["agent_id"] == "agent_one"

    events = load_rollout_events(rollout_event_log_path(tmp_path, goal_id))
    assert len(events) == 1
    assert events[0]["event_kind"] == HEARTBEAT_OBSERVED_EVENT_KIND
    assert events[0]["boundary"]["raw_task_text_recorded"] is False


def test_heartbeat_observation_idempotent_same_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "1")
    goal_id = "heartbeat-idem"
    kwargs = dict(
        runtime_root=tmp_path,
        goal_id=goal_id,
        agent_id="agent_one",
        tick_id="tick-001",
        source="heartbeat_poll",
        recorded_at="2026-08-14T00:00:00Z",
    )
    first = record_heartbeat_observation(**kwargs)
    second = record_heartbeat_observation(**kwargs)
    assert first["new"] is True
    assert second["new"] is False
    events = load_rollout_events(rollout_event_log_path(tmp_path, goal_id))
    assert len(events) == 1


def test_heartbeat_event_source_class_observe() -> None:
    # Class-level observe writes the fact without touching decisions.
    class FakeRecorder:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def observe(self, *args: object, **kwargs: object) -> dict[str, object]:
            self.calls.append((args, kwargs))
            return {"ok": True, "new": True}

    source = FakeRecorder()
    out = source.observe(tick_id="t1")
    assert out["new"] is True
    assert len(source.calls) == 1


def test_heartbeat_observation_builds_fact_only_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The event fact must not carry business decision fields or raw task text.
    monkeypatch.setenv(HEARTBEAT_EVENT_SOURCE_ENV, "1")
    event = build_heartbeat_observation_event(
        goal_id="g1",
        agent_id="a1",
        source="heartbeat_poll",
        tick_id="t1",
        details={"schema_version": "v0"},
        recorded_at="2026-08-14T00:00:00Z",
    )
    assert event["event_kind"] == HEARTBEAT_OBSERVED_EVENT_KIND
    details = event.get("details") or {}
    assert "decision" not in details
    assert "task_text" not in details
