from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane.scheduler.event_driven_dispatch import (
    EVENT_DRIVEN_DISPATCH_ENV,
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_PENDING,
    TASK_DISPATCHED_EVENT_KIND,
    TASK_ENQUEUED_EVENT_KIND,
    TASK_QUEUE_ENTRY_SCHEMA_VERSION,
    TASK_READY_EVENT_KIND,
    advance_ready_todo_ids,
    build_event_driven_dispatch,
    claim_next_task,
    enqueue_tasks,
    event_driven_dispatch_enabled,
    load_task_queue,
    record_task_event,
    task_queue_path,
)
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path


def _gate_items() -> list[dict[str, Any]]:
    """todo_first is a completed handoff gate that unlocks advancement todo_second."""
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


def test_advance_ready_todo_ids_pure() -> None:
    ready = advance_ready_todo_ids(_gate_items())
    assert ready == ["todo_second"]


def test_advance_ready_todo_ids_blocked_when_gate_open() -> None:
    items = _gate_items()
    items[0]["status"] = "open"
    assert advance_ready_todo_ids(items) == []


def test_advance_ready_unconstrained_open_advancement_todo() -> None:
    # An independent open advancement todo with no handoff gate dependency must
    # still be READY so a resident Worker can claim it (RFC "initial READY todos").
    items = [
        {
            "todo_id": "todo_solo",
            "text": "independent advancement",
            "task_class": "advancement_task",
            "status": "open",
        },
    ]
    assert advance_ready_todo_ids(items) == ["todo_solo"]


def test_advance_ready_skips_open_handoff_gate_itself() -> None:
    # An open gate (has excluded_agents) must not be advanced as a free task.
    items = [
        {
            "todo_id": "todo_gate",
            "text": "await user",
            "status": "open",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_next",
        },
        {
            "todo_id": "todo_next",
            "text": "followup",
            "task_class": "advancement_task",
            "status": "open",
        },
    ]
    # todo_next is gated by todo_gate (open) so neither is READY yet.
    assert advance_ready_todo_ids(items) == []


def test_advance_ready_skips_done_and_gated_successor() -> None:
    items = [
        {
            "todo_id": "todo_done_solo",
            "text": "already done",
            "task_class": "advancement_task",
            "status": "done",
        },
        {
            "todo_id": "todo_gate",
            "text": "await user",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_gated",
        },
        {
            "todo_id": "todo_gated",
            "text": "gated followup",
            "task_class": "advancement_task",
            "status": "open",
            "unblocks_todo_id": "todo_gate",
        },
        {
            "todo_id": "todo_free",
            "text": "free advancement",
            "task_class": "advancement_task",
            "status": "open",
        },
    ]
    # todo_gated is a cleared gate's successor (READY); todo_free is unconstrained.
    assert advance_ready_todo_ids(items) == ["todo_free", "todo_gated"]


def test_advance_ready_excludes_terminal_gate_successor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: a handoff gate successor already 'done' must NOT be READY.

    This reproduces the website1 color session bug: stale successors left over
    from a previous (font) task were enqueued and claimed by the event-driven
    scheduler even though the authoritative markdown state considered them done.
    """
    items = [
        {
            "todo_id": "todo_font_done",  # stale successor, already done
            "text": "old font task that is finished",
            "task_class": "advancement_task",
            "status": "done",
            "unblocks_todo_id": "todo_gate",
        },
        {
            "todo_id": "todo_gate",
            "text": "setup gate",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_font_done",
        },
        {
            "todo_id": "todo_color",
            "text": "change color to green",
            "task_class": "advancement_task",
            "status": "open",
        },
    ]
    ready = advance_ready_todo_ids(items)
    # Only the current open color task is READY; the done font successor is not.
    assert "todo_font_done" not in ready
    assert ready == ["todo_color"]


def test_build_event_driven_dispatch_skips_terminal_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: a done successor is never enqueued or claimed."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-terminal"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {
            "todo_id": "todo_gate",
            "text": "setup gate",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_stale",
        },
        {
            "todo_id": "todo_stale",
            "text": "stale done successor",
            "task_class": "advancement_task",
            "status": "done",
            "unblocks_todo_id": "todo_gate",
        },
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        completed_todo_id="todo_gate",
        event_log_path=event_log,
        worker_id="worker_one",
        recorded_at="2026-08-14T00:00:00Z",
    )
    dispatch = payload["event_driven_dispatch"]
    # The stale done successor must not be enqueued nor dispatched.
    assert "todo_stale" not in dispatch.get("newly_enqueued", [])
    assert dispatch.get("dispatched") is None


def test_event_driven_dispatch_emits_closure_when_no_ready_successors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no ready successors remain, the Closure Evaluator emits goal_closure_ready."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-closure"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {
            "todo_id": "todo_gate",
            "text": "setup gate",
            "status": "done",
            "excluded_agents": ["agent_worker"],
            "unblocks_todo_id": "todo_only",
        },
        {
            "todo_id": "todo_only",
            "text": "the only advancement",
            "task_class": "advancement_task",
            "status": "done",  # already done -> not READY
            "unblocks_todo_id": "todo_gate",
        },
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        completed_todo_id="todo_gate",
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    closure = (payload["event_driven_dispatch"] or {}).get("closure")
    assert closure is not None
    assert closure.get("ready") is True
    assert closure.get("reason") == "no_followup_work"
    # The goal_closure_ready event is actually recorded.
    kinds = [e["event_kind"] for e in load_rollout_events(event_log, limit=10)]
    assert "goal_closure_ready" in kinds


def test_event_driven_dispatch_no_closure_when_ready_work_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-no-close"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),  # todo_second is READY
        completed_todo_id="todo_first",
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    # With ready work remaining, closure is NOT evaluated (None) — no premature close.
    closure = (payload["event_driven_dispatch"] or {}).get("closure")
    assert closure is None
    kinds = [e["event_kind"] for e in load_rollout_events(event_log, limit=10)]
    assert "goal_closure_ready" not in kinds


def test_event_driven_dispatch_no_close_when_blocked_todo_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked (unfinished) todo must block goal closure, even with no READY successors."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-blocked"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {"todo_id": "todo_done", "status": "done", "goal_id": goal_id},
        {"todo_id": "todo_blocked", "status": "blocked", "goal_id": goal_id},
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    closure = (payload["event_driven_dispatch"] or {}).get("closure")
    assert closure is not None
    assert closure.get("ready") is False
    assert closure.get("reason") == "blocked_work_pending"
    kinds = [e["event_kind"] for e in load_rollout_events(event_log, limit=10)]
    assert "goal_closure_ready" not in kinds
    assert "goal_closed" not in kinds


def test_event_driven_dispatch_no_close_when_deferred_todo_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deferred (unscheduled) todo must block goal closure."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-deferred"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {"todo_id": "todo_done", "status": "done", "goal_id": goal_id},
        {"todo_id": "todo_deferred", "status": "deferred", "goal_id": goal_id},
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    closure = (payload["event_driven_dispatch"] or {}).get("closure")
    assert closure is not None
    assert closure.get("ready") is False
    assert closure.get("reason") == "deferred_work_pending"
    kinds = [e["event_kind"] for e in load_rollout_events(event_log, limit=10)]
    assert "goal_closure_ready" not in kinds
    assert "goal_closed" not in kinds


def test_event_driven_dispatch_acceptance_closes_goal_in_one_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With acceptance criteria + evidence satisfied and no work left, one dispatch
    atomically emits goal_closure_ready AND goal_closed (no manual goal-closure)."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-one-tick-close"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [{"todo_id": "todo_done", "status": "done", "goal_id": goal_id}]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
        acceptance_criteria=[{"criterion_id": "c1", "description": "done"}],
        evidence=[{"criterion_ids": ["c1"], "kind": "grep", "ref": "f", "ok": True}],
    )
    closure = (payload["event_driven_dispatch"] or {}).get("closure")
    assert closure is not None
    assert closure.get("ready") is True
    assert closure.get("tri_state") == "CLOSE"
    kinds = [e["event_kind"] for e in load_rollout_events(event_log, limit=20)]
    assert "goal_closure_ready" in kinds
    assert "goal_closed" in kinds


def test_event_driven_dispatch_close_ignores_non_advancement_open_todos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open continuous_monitor / user_gate / user_action todo must NOT block
    goal closure: it is not executable advancement work and lives on its own
    lifecycle. (Regression: these were previously miscounted as `ready_todo_ids`,
    wedging the goal in RUN forever.)"""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-non-advancement"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {"todo_id": "todo_done", "status": "done", "goal_id": goal_id,
         "task_class": "advancement_task", "action_kind": "edit"},
        {"todo_id": "todo_mon", "status": "open", "goal_id": goal_id,
         "task_class": "continuous_monitor"},
        {"todo_id": "todo_gate", "status": "open", "goal_id": goal_id,
         "task_class": "user_gate"},
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    dispatch = payload["event_driven_dispatch"]
    assert dispatch["ready_successors"] == []
    closure = dispatch.get("closure")
    assert closure is not None
    assert closure.get("ready") is True
    assert closure.get("tri_state") == "CLOSE"


def test_event_driven_dispatch_open_advancement_still_blocks_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open advancement todo still blocks closure (executable work remains)."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-open-advancement"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    items = [
        {"todo_id": "todo_done", "status": "done", "goal_id": goal_id,
         "task_class": "advancement_task", "action_kind": "edit"},
        {"todo_id": "todo_open", "status": "open", "goal_id": goal_id,
         "task_class": "advancement_task", "action_kind": "edit"},
    ]
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=items,
        event_log_path=event_log,
        recorded_at="2026-08-14T00:00:00Z",
    )
    dispatch = payload["event_driven_dispatch"]
    assert dispatch["ready_successors"] == ["todo_open"]
    assert dispatch.get("closure") is None


def test_event_driven_dispatch_disabled_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    goal_id = "dispatch-disabled"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        event_log_path=event_log,
        worker_id="worker_one",
        use_event_driven=False,
    )
    assert payload.get("disabled") is True
    assert payload.get("ok") is True
    # No queue file, no rollout events written.
    assert not task_queue_path(tmp_path, goal_id=goal_id).exists()
    assert not event_log.exists()


def test_event_driven_dispatch_enabled_full_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-on"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        event_log_path=event_log,
        worker_id="worker_one",
        recorded_at="2026-08-13T00:00:00Z",
    )
    assert payload.get("disabled") is not True
    dispatch = payload["event_driven_dispatch"]
    assert dispatch["ready_successors"] == ["todo_second"]
    assert dispatch["newly_enqueued"] == ["todo_second"]
    assert dispatch["dispatched"] == {
        "todo_id": "todo_second",
        "claimed_by": "worker_one",
        "status": QUEUE_STATUS_CLAIMED,
    }
    queue = dispatch["queue"]
    assert queue["pending_count"] == 0
    assert queue["claimed_count"] == 1
    assert queue["claimed_todo_ids"] == ["todo_second"]

    # Public audit events: task_ready, task_enqueued, task_dispatched.
    events = load_rollout_events(event_log)
    kinds = [event.get("event_kind") for event in events]
    assert TASK_READY_EVENT_KIND in kinds
    assert TASK_ENQUEUED_EVENT_KIND in kinds
    assert TASK_DISPATCHED_EVENT_KIND in kinds
    for event in events:
        assert event.get("goal_id") == goal_id


def test_event_driven_dispatch_records_registered_agent_id_on_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-agent"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        event_log_path=event_log,
        worker_id="worker_one",
        agent_id="agent_registered",
        recorded_at="2026-08-13T00:00:00Z",
    )
    events = load_rollout_events(event_log)
    dispatched = [e for e in events if e.get("event_kind") == TASK_DISPATCHED_EVENT_KIND]
    assert len(dispatched) == 1
    # The registered LoopX agent identity is recorded, not the raw claimer.
    assert dispatched[0].get("agent_id") == "agent_registered"


def test_event_driven_dispatch_agent_id_falls_back_to_worker_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-agent-fallback"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        event_log_path=event_log,
        worker_id="worker_one",
        recorded_at="2026-08-13T00:00:00Z",
    )
    events = load_rollout_events(event_log)
    dispatched = [e for e in events if e.get("event_kind") == TASK_DISPATCHED_EVENT_KIND]
    assert len(dispatched) == 1
    # Without an explicit agent_id, the claimer (worker_id) is recorded,
    # preserving legacy behavior.
    assert dispatched[0].get("agent_id") == "worker_one"


def test_event_driven_dispatch_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-idem"
    event_log = rollout_event_log_path(tmp_path, goal_id)
    kwargs: dict[str, Any] = dict(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        event_log_path=event_log,
        recorded_at="2026-08-13T00:00:00Z",
    )
    first = build_event_driven_dispatch(**kwargs)
    second = build_event_driven_dispatch(**kwargs)
    assert first["event_driven_dispatch"]["newly_enqueued"] == ["todo_second"]
    # Second tick: the READY successor is already queued, so nothing new is
    # enqueued and the queue is not duplicated.
    assert second["event_driven_dispatch"]["newly_enqueued"] == []
    assert second["event_driven_dispatch"]["queue"]["pending_count"] == 1
    # Events remain deduplicated by (goal_id, event_kind, todo_id).
    events = load_rollout_events(event_log)
    ready_count = sum(1 for e in events if e.get("event_kind") == TASK_READY_EVENT_KIND)
    enqueued_count = sum(1 for e in events if e.get("event_kind") == TASK_ENQUEUED_EVENT_KIND)
    assert ready_count == 1
    assert enqueued_count == 1


def test_enqueue_tasks_idempotent_and_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="queue")
    first = enqueue_tasks(
        queue,
        goal_id="queue",
        todo_ids=["todo_a", "todo_b"],
        recorded_at="2026-08-13T00:00:00Z",
    )
    assert first["newly_enqueued"] == ["todo_a", "todo_b"]
    second = enqueue_tasks(
        queue,
        goal_id="queue",
        todo_ids=["todo_b", "todo_c"],
        recorded_at="2026-08-13T00:00:00Z",
    )
    assert second["newly_enqueued"] == ["todo_c"]
    assert second["skipped_duplicates"] == ["todo_b"]

    view = load_task_queue(queue)
    assert view["pending_count"] == 3
    assert view["pending_todo_ids"] == ["todo_a", "todo_b", "todo_c"]

    claimed = claim_next_task(queue, worker_id="worker_one")
    assert claimed is not None
    assert claimed["todo_id"] == "todo_a"
    assert claimed["status"] == QUEUE_STATUS_CLAIMED
    assert claimed["claimed_by"] == "worker_one"
    view = load_task_queue(queue)
    assert view["claimed_todo_ids"] == ["todo_a"]
    assert view["pending_todo_ids"] == ["todo_b", "todo_c"]


def test_record_task_event_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    event_log = rollout_event_log_path(tmp_path, "events")
    first = record_task_event(
        event_log,
        goal_id="events",
        event_kind=TASK_READY_EVENT_KIND,
        todo_id="todo_x",
        recorded_at="2026-08-13T00:00:00Z",
    )
    second = record_task_event(
        event_log,
        goal_id="events",
        event_kind=TASK_READY_EVENT_KIND,
        todo_id="todo_x",
        recorded_at="2026-08-13T00:00:01Z",
    )
    assert first["new"] is True
    assert second["new"] is False
    assert len(load_rollout_events(event_log)) == 1


def test_queue_entries_schema_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="schema")
    enqueue_tasks(queue, goal_id="schema", todo_ids=["todo_x"], recorded_at="2026-08-13T00:00:00Z")
    raw = queue.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(raw[0])
    assert entry["schema_version"] == TASK_QUEUE_ENTRY_SCHEMA_VERSION
    assert entry["status"] == QUEUE_STATUS_PENDING


def test_claim_next_task_empty_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="empty")
    assert claim_next_task(queue, worker_id="worker_one") is None


def test_claim_next_task_with_capability_and_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    from loopx.control_plane.scheduler.task_lifecycle import claim_next_eligible_task

    queue = task_queue_path(tmp_path, goal_id="cap")
    enqueue_tasks(
        queue,
        goal_id="cap",
        todo_ids=["todo_gpu", "todo_py"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = [
        json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    entries[0]["required_capabilities"] = ["gpu"]
    entries[1]["required_capabilities"] = ["python"]
    queue.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
        encoding="utf-8",
    )
    # A python-only worker cannot claim the gpu task; claims the python task with a lease.
    claimed = claim_next_task(
        queue,
        worker_id="worker_py",
        capabilities=["python"],
        lease_seconds=120,
    )
    assert claimed is not None
    assert claimed["todo_id"] == "todo_py"
    assert claimed["status"] == QUEUE_STATUS_CLAIMED
    assert claimed["lease_until"] is not None
    assert claimed["attempt"] == 1


def test_claim_next_task_binding_requires_pack_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A legacy capability_binding_ref requires the bound pack token in claim."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="binding-token")
    enqueue_tasks(
        queue,
        goal_id="binding-token",
        todo_ids=["todo_bound"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = [
        json.loads(line)
        for line in queue.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries[0]["capability_binding_ref"] = "issue-fix:feasibility_v0"
    queue.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
        encoding="utf-8",
    )
    # A worker without the pack token cannot claim the bound task.
    assert claim_next_task(queue, worker_id="worker_shell", capabilities=["shell"]) is None
    # A worker declaring the pack token can.
    claimed = claim_next_task(queue, worker_id="worker_issue", capabilities=["issue_fix"])
    assert claimed is not None
    assert claimed["todo_id"] == "todo_bound"
    assert claimed["claimed_by"] == "worker_issue"


def test_claim_next_task_binding_fails_closed_for_unknown_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binding to a pack unknown to the registry is not claimable at all."""
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    queue = task_queue_path(tmp_path, goal_id="binding-unknown")
    enqueue_tasks(
        queue,
        goal_id="binding-unknown",
        todo_ids=["todo_mystery"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = [
        json.loads(line)
        for line in queue.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    entries[0]["capability_binding_ref"] = "unknown-pack:xyz"
    queue.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
        encoding="utf-8",
    )
    # Even a worker declaring a plausible token cannot claim a pack that the
    # registry does not know (fail closed).
    assert claim_next_task(queue, worker_id="worker_unk", capabilities=["unknown_pack"]) is None


def test_build_event_driven_dispatch_reconciles_zombie_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from loopx.control_plane.scheduler.task_lifecycle import claim_next_eligible_task

    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-reconcile"
    queue = task_queue_path(tmp_path, goal_id=goal_id)
    # Seed a zombie: enqueue + claim with a short lease, then advance time past it.
    enqueue_tasks(queue, goal_id=goal_id, todo_ids=["todo_first"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(queue, worker_id="w1", lease_seconds=10, now=1000.0)
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        recorded_at="2026-08-14T00:11:00Z",
        reconcile=True,
    )
    # The zombie lease is expired by the reconcile pass and re-enqueued.
    reconcile = (payload["event_driven_dispatch"] or {}).get("reconcile") or {}
    assert reconcile.get("expired_count") == 1
    assert reconcile.get("expired_leases") == ["todo_first"]


def test_build_event_driven_dispatch_capability_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    goal_id = "dispatch-cap"
    queue = task_queue_path(tmp_path, goal_id=goal_id)
    enqueue_tasks(
        queue,
        goal_id=goal_id,
        todo_ids=["todo_gated"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = [
        json.loads(line) for line in queue.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    entries[0]["required_capabilities"] = ["gpu"]
    queue.write_text(json.dumps(entries[0], sort_keys=True) + "\n", encoding="utf-8")
    # A python-only worker is not eligible for the gpu task, so it stays pending
    # and is never claimed by the python worker.
    payload = build_event_driven_dispatch(
        runtime_root=tmp_path,
        goal_id=goal_id,
        items=_gate_items(),
        completed_todo_id="todo_first",
        worker_id="worker_py",
        worker_capabilities=["python"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    dispatched = (payload["event_driven_dispatch"] or {}).get("dispatched")
    # The python worker claims the (non-gated) READY successor, never the gpu task.
    assert dispatched is not None
    assert dispatched["todo_id"] != "todo_gated"
    # The gpu task remains pending in the queue (never claimed by a python worker).
    view = load_task_queue(queue)
    assert "todo_gated" in view["pending_todo_ids"]
    assert "todo_gated" not in view["claimed_todo_ids"]


def test_event_driven_dispatch_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    # The new architecture is ON by default (master switch), so an unset feature
    # env inherits the master switch.
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    monkeypatch.delenv("LOOPX_NEW_ARCHITECTURE", raising=False)
    assert event_driven_dispatch_enabled() is True
    # An explicit flag always wins over the master switch.
    assert event_driven_dispatch_enabled(use_event_driven=False) is False
    assert event_driven_dispatch_enabled(use_event_driven=True) is True
    # The feature env var still wins over the master switch default.
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "0")
    assert event_driven_dispatch_enabled() is False
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "1")
    assert event_driven_dispatch_enabled() is True
    monkeypatch.setenv(EVENT_DRIVEN_DISPATCH_ENV, "true")
    assert event_driven_dispatch_enabled() is True
    # The master switch can turn the whole new architecture off.
    monkeypatch.delenv(EVENT_DRIVEN_DISPATCH_ENV, raising=False)
    monkeypatch.setenv("LOOPX_NEW_ARCHITECTURE", "0")
    assert event_driven_dispatch_enabled() is False
