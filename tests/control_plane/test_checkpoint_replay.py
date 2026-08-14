from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.runtime.checkpoint import (
    Checkpoint,
    build_checkpoint,
    compute_state_hash,
    load_checkpoints,
    load_latest_checkpoint,
    remove_checkpoints,
    verify_checkpoint_integrity,
    write_checkpoint,
)
from loopx.control_plane.runtime.replay import (
    REPLAY_SCHEMA_VERSION,
    ReplayViolationError,
    load_task_events,
    partition_events_after_checkpoint,
    recover_task_state,
    replay_audit_record,
    replay_from_checkpoint,
    replay_task,
    state_digest,
    verify_replay_equivalence,
)

GOAL_ID = "checkpoint-fixture"
TODO_ID = "todo-1"


def _events() -> list[dict]:
    return [
        {"event_id": "E1", "todo_id": TODO_ID, "delta": 1, "kind": "inc"},
        {"event_id": "E2", "todo_id": TODO_ID, "delta": 2, "kind": "inc"},
        {"event_id": "E3", "todo_id": TODO_ID, "delta": 3, "kind": "inc"},
        {"event_id": "E4", "todo_id": TODO_ID, "delta": 4, "kind": "inc"},
    ]


def _apply(state, event) -> dict:
    return {"count": int(state.get("count") or 0) + int(event.get("delta") or 0)}


def _snapshot_after_events(events) -> dict:
    return replay_task(events, apply=_apply)


# ---------------------------------------------------------------------------
# Checkpoint construction + integrity
# ---------------------------------------------------------------------------


def test_build_checkpoint_derives_hash_and_id() -> None:
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot={"count": 3},
    )
    assert checkpoint.schema_version == REPLAY_SCHEMA_VERSION
    assert checkpoint.state_hash == compute_state_hash({"count": 3})
    assert checkpoint.checkpoint_id.startswith(f"{GOAL_ID}:{TODO_ID}:E2:")
    assert verify_checkpoint_integrity(checkpoint)


def test_checkpoint_round_trip() -> None:
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot={"count": 3},
    )
    restored = Checkpoint.from_dict(checkpoint.to_dict())
    assert restored == checkpoint


def test_checkpoint_integrity_detects_tampering() -> None:
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot={"count": 3},
    )
    tampered = Checkpoint(
        checkpoint_id=checkpoint.checkpoint_id,
        goal_id=checkpoint.goal_id,
        todo_id=checkpoint.todo_id,
        run_id=checkpoint.run_id,
        last_event_id=checkpoint.last_event_id,
        state_snapshot={"count": 999},
        state_hash=checkpoint.state_hash,
        created_at=checkpoint.created_at,
    )
    assert verify_checkpoint_integrity(tampered) is False


# ---------------------------------------------------------------------------
# Idempotent checkpoint persistence
# ---------------------------------------------------------------------------


def test_write_checkpoint_appends_once(tmp_path: Path) -> None:
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot={"count": 3},
    )
    _, first_new = write_checkpoint(tmp_path, checkpoint)
    _, second_new = write_checkpoint(tmp_path, checkpoint)
    assert first_new is True
    assert second_new is False
    assert len(load_checkpoints(tmp_path, GOAL_ID, TODO_ID)) == 1


def test_write_distinct_checkpoints_appends(tmp_path: Path) -> None:
    first = build_checkpoint(
        goal_id=GOAL_ID, todo_id=TODO_ID, run_id="run-1", last_event_id="E1", state_snapshot={"count": 1}
    )
    second = build_checkpoint(
        goal_id=GOAL_ID, todo_id=TODO_ID, run_id="run-1", last_event_id="E2", state_snapshot={"count": 3}
    )
    write_checkpoint(tmp_path, first)
    write_checkpoint(tmp_path, second)
    assert len(load_checkpoints(tmp_path, GOAL_ID, TODO_ID)) == 2


def test_load_latest_checkpoint_returns_newest(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        build_checkpoint(
            goal_id=GOAL_ID, todo_id=TODO_ID, run_id="r1", last_event_id="E1", state_snapshot={"count": 1}
        ),
    )
    write_checkpoint(
        tmp_path,
        build_checkpoint(
            goal_id=GOAL_ID, todo_id=TODO_ID, run_id="r1", last_event_id="E2", state_snapshot={"count": 3}
        ),
    )
    latest = load_latest_checkpoint(tmp_path, GOAL_ID, TODO_ID)
    assert latest is not None
    assert latest.last_event_id == "E2"
    assert latest.state_snapshot == {"count": 3}


def test_remove_checkpoints(tmp_path: Path) -> None:
    write_checkpoint(
        tmp_path,
        build_checkpoint(
            goal_id=GOAL_ID, todo_id=TODO_ID, run_id="r1", last_event_id="E1", state_snapshot={"count": 1}
        ),
    )
    assert load_latest_checkpoint(tmp_path, GOAL_ID, TODO_ID) is not None
    assert remove_checkpoints(tmp_path, GOAL_ID, TODO_ID) is True
    assert load_latest_checkpoint(tmp_path, GOAL_ID, TODO_ID) is None


# ---------------------------------------------------------------------------
# Replay determinism + idempotency
# ---------------------------------------------------------------------------


def test_replay_is_deterministic() -> None:
    events = _events()
    assert replay_task(events, apply=_apply) == replay_task(events, apply=_apply)


def test_replay_side_effect_free_does_not_mutate_inputs() -> None:
    events = _events()
    snapshot = list(events)
    replay_task(events, apply=_apply)
    assert events == snapshot


def test_replay_is_idempotent_when_applied_twice_from_same_base() -> None:
    events = _events()
    first = replay_task(events, apply=_apply)
    second = replay_task(events, apply=_apply, initial_state=first)
    assert second["count"] == 20  # first pass: 1+2+3+4=10; second pass adds 10 more


def test_replay_from_checkpoint_equals_full_replay() -> None:
    events = _events()
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot=_snapshot_after_events(events[:2]),
    )
    after = partition_events_after_checkpoint(
        events, checkpoint, event_id_of=lambda e: str(e.get("event_id") or "")
    )
    assert [e["event_id"] for e in after] == ["E3", "E4"]
    recovered = replay_from_checkpoint(checkpoint, after, apply=_apply)
    assert recovered == _snapshot_after_events(events) == {"count": 10}


def test_verify_replay_equivalence() -> None:
    events = _events()
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot=_snapshot_after_events(events[:2]),
    )
    after = partition_events_after_checkpoint(
        events, checkpoint, event_id_of=lambda e: str(e.get("event_id") or "")
    )
    equivalent, message = verify_replay_equivalence(
        events,
        checkpoint=checkpoint,
        events_after_checkpoint=after,
        apply=_apply,
    )
    assert equivalent is True
    assert "equals" in message


def test_replay_without_checkpoint_starts_empty() -> None:
    events = _events()
    state = replay_from_checkpoint(None, events, apply=_apply)
    assert state == {"count": 10}


def test_replay_schema_mismatch_raises() -> None:
    checkpoint = Checkpoint(
        checkpoint_id="x",
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="r",
        last_event_id="E1",
        schema_version=REPLAY_SCHEMA_VERSION + 1,
        state_snapshot={"count": 1},
        state_hash=compute_state_hash({"count": 1}),
    )
    with pytest.raises(ReplayViolationError):
        replay_from_checkpoint(checkpoint, [], apply=_apply)


def test_replay_tampered_checkpoint_raises() -> None:
    checkpoint = Checkpoint(
        checkpoint_id="x",
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="r",
        last_event_id="E1",
        schema_version=REPLAY_SCHEMA_VERSION,
        state_snapshot={"count": 999},
        state_hash=compute_state_hash({"count": 1}),
    )
    with pytest.raises(ReplayViolationError):
        replay_from_checkpoint(checkpoint, [], apply=_apply)


def test_partition_events_after_checkpoint_none_returns_all() -> None:
    events = _events()
    assert partition_events_after_checkpoint(events, None, event_id_of=lambda e: str(e.get("event_id") or "")) == events


# ---------------------------------------------------------------------------
# Full recovery workflow over a runtime root
# ---------------------------------------------------------------------------


def _write_index(tmp_path: Path, events: list[dict]) -> Path:
    index_path = tmp_path / "goals" / GOAL_ID / "runs" / "index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        "\n".join(json.dumps(e) for e in events) + "\n",
        encoding="utf-8",
    )
    return index_path


def test_recover_task_state_full_flow(tmp_path: Path) -> None:
    events = _events()
    _write_index(tmp_path, events)
    checkpoint = build_checkpoint(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        run_id="run-1",
        last_event_id="E2",
        state_snapshot=_snapshot_after_events(events[:2]),
    )
    write_checkpoint(tmp_path, checkpoint)

    state, used, replayed = recover_task_state(
        tmp_path,
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        apply=_apply,
    )
    assert used is not None
    assert used.last_event_id == "E2"
    assert [e["event_id"] for e in replayed] == ["E3", "E4"]
    assert state == {"count": 10}


def test_recover_task_state_without_checkpoint(tmp_path: Path) -> None:
    _write_index(tmp_path, _events())
    state, used, replayed = recover_task_state(
        tmp_path,
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        apply=_apply,
    )
    assert used is None
    assert len(replayed) == 4
    assert state == {"count": 10}


def test_load_task_events_filters_other_todos(tmp_path: Path) -> None:
    _write_index(
        tmp_path,
        [
            {"event_id": "E1", "todo_id": TODO_ID, "delta": 1},
            {"event_id": "X1", "todo_id": "other", "delta": 99},
        ],
    )
    events = load_task_events(tmp_path, GOAL_ID, TODO_ID)
    assert [e["event_id"] for e in events] == ["E1"]


def test_replay_audit_record_shape() -> None:
    record = replay_audit_record(
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        state={"count": 10},
        checkpoint=None,
        events_replayed=_events(),
        events_total=4,
        equivalent=True,
    )
    assert record["goal_id"] == GOAL_ID
    assert record["events_replayed"] == 4
    assert record["equivalent"] is True
    assert record["state_hash"] == state_digest({"count": 10})
    assert "recorded_at" in record
