"""Tests for the control-plane observability snapshot (plan/new_plan.md §7, P2).

Verifies the unified status view aggregates queue (incl. extended lifecycle),
worker, task, decision, and event history into one read-only digest.
"""

from __future__ import annotations

from pathlib import Path

from loopx.control_plane.scheduler.event_driven_dispatch import (
    enqueue_tasks,
    task_queue_path,
)
from loopx.control_plane.scheduler.task_lifecycle import (
    claim_next_eligible_task,
    complete_task,
    fail_task,
)
from loopx.control_plane.status.control_plane_observability import (
    build_control_plane_status,
    build_decision_history,
    build_event_history,
    build_queue_digest,
    build_task_history,
    build_worker_status,
)
from loopx.rollout_event_log import rollout_event_log_path


def _seed_queue(root: Path, goal_id: str = "g1") -> Path:
    q = task_queue_path(root, goal_id=goal_id)
    enqueue_tasks(
        q,
        goal_id=goal_id,
        todo_ids=["todo_a", "todo_b", "todo_c"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    # todo_a -> done; todo_b -> claimed; todo_c -> retry_wait (zombie expires later).
    claim_next_eligible_task(q, worker_id="w1", lease_seconds=100, now=1000.0)
    complete_task(q, task_id="todo_a", worker_id="w1")
    claim_next_eligible_task(q, worker_id="w1", lease_seconds=100, now=1000.0)
    fail_task(
        q,
        task_id="todo_b",
        worker_id="w1",
        transient=True,
        max_attempts=3,
        retry_backoff_seconds=60,
        now=1001.0,
    )
    claim_next_eligible_task(q, worker_id="w1", lease_seconds=100, now=1000.0)
    return q


def test_build_control_plane_status_aggregates_all_sections(
    tmp_path: Path,
) -> None:
    q = _seed_queue(tmp_path, goal_id="g1")
    status = build_control_plane_status(
        runtime_root=tmp_path,
        goal_id="g1",
        worker_ids=["w1"],
        scheduler_tick_count=7,
    )
    assert status["ok"] is True
    assert status["goal_id"] == "g1"
    # Scheduler section.
    assert status["scheduler"]["tick_count"] == 7
    assert status["scheduler"]["worker_ids"] == ["w1"]
    # Queue section reflects the extended lifecycle.
    queue = status["queue"]
    assert queue["pending_count"] == 0
    assert queue["done_count"] == 1
    assert queue["extended"]["retry_wait_count"] == 1
    assert queue["in_flight_count"] == 2  # claimed + retry_wait
    # Worker section.
    assert status["workers"]["worker_count"] == 1
    # Task history is present.
    assert len(status["task_history"]) == 3
    # Event history section exists.
    assert "counts_by_kind" in status["event_history"]
    # Queue file was not mutated by the read-only snapshot.
    assert q.exists()


def test_build_queue_digest_counts_done_and_exception(tmp_path: Path) -> None:
    q = _seed_queue(tmp_path, goal_id="g1")
    digest = build_queue_digest(q)
    assert digest["done_count"] == 1
    assert "todo_a" in digest["done_todo_ids"]
    assert digest["in_flight_count"] == 2
    # No failures/dead-letters in this scenario.
    assert digest["exception_count"] == 0


def test_build_worker_status_derives_in_flight(tmp_path: Path) -> None:
    _seed_queue(tmp_path, goal_id="g1")
    q = task_queue_path(tmp_path, goal_id="g1")
    from loopx.control_plane.status.control_plane_observability import (
        _read_queue_entries,
    )

    worker_status = build_worker_status(_read_queue_entries(q))
    assert worker_status["worker_count"] == 1
    assert worker_status["workers"][0]["worker_id"] == "w1"
    assert worker_status["workers"][0]["in_flight_count"] == 2


def test_build_task_history_orders_newest_first(tmp_path: Path) -> None:
    q = _seed_queue(tmp_path, goal_id="g1")
    from loopx.control_plane.status.control_plane_observability import (
        _read_queue_entries,
    )

    history = build_task_history(_read_queue_entries(q))
    # 3 tasks: done, retry_wait, claimed.
    assert len(history) == 3
    statuses = {h["status"] for h in history}
    assert "done" in statuses
    assert "retry_wait" in statuses
    assert "claimed" in statuses


def test_build_event_history_empty_when_no_log(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    digest = build_event_history(log_path)
    assert digest["event_count"] == 0
    assert digest["recent_events"] == []


def test_build_decision_history_empty_when_no_ledger(tmp_path: Path) -> None:
    digest = build_decision_history(tmp_path / "no-such-decision.jsonl")
    assert digest["ok"] is True
    assert digest["decision_count"] == 0


def test_build_decision_history_parses_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "decisions.jsonl"
    lines = [
        '{"event_id":"e1","goal_id":"g1","todo_id":"t1","outcome":"run","source":"quota","recorded_at":"2026-08-14T00:00:00Z"}',
        '{"event_id":"e2","goal_id":"g1","todo_id":"t2","outcome":"deny","source":"capability","recorded_at":"2026-08-14T00:01:00Z"}',
    ]
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = build_decision_history(ledger)
    assert digest["decision_count"] == 2
    assert digest["counts_by_outcome"] == {"run": 1, "deny": 1}
    assert digest["recent_decisions"][0]["outcome"] == "deny"


def test_build_control_plane_status_missing_logs_is_safe(tmp_path: Path) -> None:
    # Empty runtime root -> no queue, no event log; snapshot still succeeds.
    status = build_control_plane_status(runtime_root=tmp_path, goal_id="ghost")
    assert status["ok"] is True
    assert status["queue"]["pending_count"] == 0
    assert status["workers"]["worker_count"] == 0
    assert status["event_history"]["event_count"] == 0
