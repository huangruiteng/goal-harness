"""Tests for the task lifecycle module (lease, retry, idempotency, capability).

Covers ``plan/new_plan.md`` P0/P1:
* lease expiry re-enqueues zombie tasks (``claimed|running -> expired -> pending``);
* retry with backoff and ``max_attempts`` (``failed -> retry_wait -> pending``,
  ``failed`` on exhausted attempts, ``dead_letter`` escalation);
* generation-aware ``task_id`` idempotency;
* capability-matched claiming.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.control_plane.scheduler.event_driven_dispatch import (
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_DONE,
    QUEUE_STATUS_PENDING,
    enqueue_tasks,
    task_queue_path,
)
from loopx.control_plane.scheduler.task_lifecycle import (
    QUEUE_STATUS_CANCELLED,
    QUEUE_STATUS_DEAD_LETTER,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_RETRY_WAIT,
    TASK_ID_SEPARATOR,
    build_task_id,
    cancel_task,
    claim_next_eligible_task,
    complete_task,
    dead_letter_exhausted,
    eligible,
    expire_stale_leases,
    extended_queue_view,
    fail_task,
    is_expired,
    parse_task_id,
    promote_retry_ready,
    reconcile_queue,
    requeue_failed,
    task_generation,
    worker_satisfies_capabilities,
)


def _queue(tmp_path: Path, goal_id: str = "goal") -> Path:
    return task_queue_path(tmp_path, goal_id=goal_id)


def _raw_entries(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------------------------------------------------------------------------
# Generation-aware task id (idempotency)
# ---------------------------------------------------------------------------


def test_build_and_parse_task_id() -> None:
    task_id = build_task_id("todo_a", generation=3)
    assert task_id == f"todo_a{TASK_ID_SEPARATOR}3"
    assert parse_task_id(task_id) == ("todo_a", 3)
    assert task_generation(task_id) == 3


def test_build_task_id_defaults_generation_zero() -> None:
    assert build_task_id("todo_a") == f"todo_a{TASK_ID_SEPARATOR}0"
    assert task_generation(build_task_id("todo_a")) == 0


def test_parse_task_id_plain_todo_returns_none() -> None:
    assert parse_task_id("todo_a") is None
    assert task_generation("todo_a") == 0


# ---------------------------------------------------------------------------
# Capability matching
# ---------------------------------------------------------------------------


def test_eligible_task_without_requirements_any_worker() -> None:
    assert eligible({"capabilities": []}, {"todo_id": "t"}) is True
    assert eligible({"capabilities": ["python"]}, {"todo_id": "t"}) is True


def test_eligible_matches_all_required_capabilities() -> None:
    task = {"required_capabilities": ["python", "gpu"]}
    assert eligible({"capabilities": ["python", "gpu"]}, task) is True
    assert eligible({"capabilities": ["python"]}, task) is False
    assert eligible({"capabilities": []}, task) is False


def test_worker_satisfies_capabilities_normalizes_tokens() -> None:
    assert worker_satisfies_capabilities(["python", "gpu"], ["PYTHON"]) is True
    assert worker_satisfies_capabilities("python, gpu", "python") is True
    assert worker_satisfies_capabilities(["python"], ["latex"]) is False


# ---------------------------------------------------------------------------
# Claim with lease + capability matching
# ---------------------------------------------------------------------------


def test_claim_next_eligible_task_adds_lease_and_attempt(
    tmp_path: Path,
) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claimed = claim_next_eligible_task(path, worker_id="worker_one", lease_seconds=100, now=1000.0)
    assert claimed is not None
    assert claimed["status"] == QUEUE_STATUS_CLAIMED
    assert claimed["claimed_by"] == "worker_one"
    assert claimed["lease_until"] == 1100.0
    assert claimed["attempt"] == 1


def test_claim_next_eligible_task_capability_gate(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(
        path,
        goal_id="goal",
        todo_ids=["todo_gpu", "todo_py"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = _raw_entries(path)
    gpu = entries[0]
    gpu["required_capabilities"] = ["gpu"]
    py = entries[1]
    py["required_capabilities"] = ["python"]
    path.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in [gpu, py]),
        encoding="utf-8",
    )
    # Worker with only python cannot claim the gpu task; claims the python one.
    claimed = claim_next_eligible_task(path, worker_id="w1", capabilities=["python"])
    assert claimed is not None
    assert claimed["todo_id"] == "todo_py"
    # A worker with gpu claims the gpu task next.
    claimed2 = claim_next_eligible_task(path, worker_id="w2", capabilities=["gpu"])
    assert claimed2 is not None
    assert claimed2["todo_id"] == "todo_gpu"


def test_claim_next_eligible_task_none_when_no_eligible(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(
        path,
        goal_id="goal",
        todo_ids=["todo_gpu"],
        recorded_at="2026-08-14T00:00:00Z",
    )
    entries = _raw_entries(path)
    entries[0]["required_capabilities"] = ["gpu"]
    path.write_text(json.dumps(entries[0], sort_keys=True) + "\n", encoding="utf-8")
    assert claim_next_eligible_task(path, worker_id="w1", capabilities=["python"]) is None


# ---------------------------------------------------------------------------
# Lease expiry (zombie recovery)
# ---------------------------------------------------------------------------


def test_is_expired_only_for_claimed_running() -> None:
    claimed = {"status": QUEUE_STATUS_CLAIMED, "lease_until": 100.0}
    assert is_expired(claimed, now=101.0) is True
    assert is_expired(claimed, now=100.0) is True
    assert is_expired(claimed, now=99.0) is False
    pending = {"status": QUEUE_STATUS_PENDING, "lease_until": 1.0}
    assert is_expired(pending, now=100.0) is False


def test_expire_stale_leases_reenqueues_zombie(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_zombie"], recorded_at="2026-08-14T00:00:00Z")
    claimed = claim_next_eligible_task(path, worker_id="w1", lease_seconds=10, now=1000.0)
    assert claimed is not None
    assert is_expired(claimed, now=1005.0) is False
    expired = expire_stale_leases(path, now=1011.0, worker_id="scheduler")
    assert [e["todo_id"] for e in expired] == ["todo_zombie"]
    view = extended_queue_view(path)
    # The zombie task was re-enqueued to pending (not stuck in claimed).
    entries = _raw_entries(path)
    assert entries[0]["status"] == QUEUE_STATUS_PENDING
    assert entries[0]["expired_at"] is not None
    assert view["pending_count"] == 1
    assert view["extended"]["expired_count"] == 0  # expired is transient, not terminal


def test_expire_stale_leases_leaves_fresh_claimed_alone(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_fresh"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    assert expire_stale_leases(path, now=1010.0) == []
    entries = _raw_entries(path)
    assert entries[0]["status"] == QUEUE_STATUS_CLAIMED


def test_expire_stale_leases_recovers_legacy_unleased_zombie(
    tmp_path: Path,
) -> None:
    """Regression: claimed entries WITHOUT a lease_until (legacy/old-code zombies)
    must be reclaimed, not stuck forever.

    This reproduces the website1 session's ``claimed: 4`` stale queue — four
    tasks claimed by an older run without leases, which blocked the event-driven
    path from making progress (pending=0, nothing claimable).
    """
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_stale"], recorded_at="2026-08-14T00:00:00Z")
    # Simulate an old-code claim: status=claimed but NO lease_until written.
    entries = _raw_entries(path)
    entries[0]["status"] = QUEUE_STATUS_CLAIMED
    entries[0]["claimed_by"] = "ghost_worker"
    path.write_text(
        "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
        encoding="utf-8",
    )
    # A claimed entry without a lease is treated as an expired zombie.
    assert is_expired(entries[0]) is True
    reclaimed = expire_stale_leases(path, worker_id="scheduler")
    assert [e["todo_id"] for e in reclaimed] == ["todo_stale"]
    # The zombie is back to pending and claimable again.
    re_entries = _raw_entries(path)
    assert re_entries[0]["status"] == QUEUE_STATUS_PENDING
    assert re_entries[0].get("expired_by") == "scheduler"


# ---------------------------------------------------------------------------
# Completion / failure / retry / dead letter
# ---------------------------------------------------------------------------


def test_complete_task_transitions_to_done(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    completed = complete_task(path, task_id="todo_a", worker_id="w1")
    assert completed is not None
    assert completed["status"] == QUEUE_STATUS_DONE
    assert completed["lease_until"] is None
    # Re-completing the same task is a no-op (already done).
    assert complete_task(path, task_id="todo_a", worker_id="w1") is None


def test_complete_task_respects_claimer(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    # A different worker cannot complete someone else's claimed task.
    assert complete_task(path, task_id="todo_a", worker_id="w2") is None


def test_fail_task_transient_retry_wait_then_promote(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    failed = fail_task(
        path,
        task_id="todo_a",
        worker_id="w1",
        error="boom",
        transient=True,
        max_attempts=3,
        retry_backoff_seconds=60,
        now=1010.0,
    )
    assert failed is not None
    assert failed["status"] == QUEUE_STATUS_RETRY_WAIT
    assert failed["retry_at"] == 1070.0
    # Backoff not elapsed -> stays in retry_wait.
    assert promote_retry_ready(path, now=1069.0) == []
    # Backoff elapsed -> promoted to pending.
    promoted = promote_retry_ready(path, now=1070.0)
    assert [e["todo_id"] for e in promoted] == ["todo_a"]
    entries = _raw_entries(path)
    assert entries[0]["status"] == QUEUE_STATUS_PENDING


def test_fail_task_permanent_when_not_transient(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    failed = fail_task(path, task_id="todo_a", worker_id="w1", transient=False)
    assert failed is not None
    assert failed["status"] == QUEUE_STATUS_FAILED
    assert failed.get("retry_at") is None


def test_fail_task_dead_letter_when_attempts_exhausted(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    # First claim attempts = 1; max_attempts=1 -> no retry allowed -> failed.
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    failed = fail_task(
        path,
        task_id="todo_a",
        worker_id="w1",
        transient=True,
        max_attempts=1,
        now=1001.0,
    )
    assert failed["status"] == QUEUE_STATUS_FAILED
    # Explicit dead-letter escalation.
    dead = dead_letter_exhausted(path, task_id="todo_a", worker_id="scheduler")
    assert dead is not None
    assert dead["status"] == QUEUE_STATUS_DEAD_LETTER


def test_requeue_failed_returns_to_pending(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    fail_task(path, task_id="todo_a", worker_id="w1", transient=False)
    requeued = requeue_failed(path, task_id="todo_a", worker_id="scheduler")
    assert requeued is not None
    assert requeued["status"] == QUEUE_STATUS_PENDING


def test_cancel_task(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    cancelled = cancel_task(path, task_id="todo_a", reason="owner nixed it")
    assert cancelled is not None
    assert cancelled["status"] == QUEUE_STATUS_CANCELLED
    assert cancelled["cancel_reason"] == "owner nixed it"
    view = extended_queue_view(path)
    assert view["extended"]["cancelled_count"] == 1


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_reconcile_queue_handles_zombie_and_retry(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    # Task A: zombie (claimed, lease expired).
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a", "todo_b"], recorded_at="2026-08-14T00:00:00Z")
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=10, now=1000.0)
    # Task B: retry_wait whose backoff has elapsed.
    claim_next_eligible_task(path, worker_id="w1", lease_seconds=100, now=1000.0)
    fail_task(path, task_id="todo_b", worker_id="w1", transient=True, max_attempts=3, retry_backoff_seconds=5, now=1001.0)
    result = reconcile_queue(path, now=1012.0)
    assert result["expired_count"] == 1
    assert result["expired_leases"] == ["todo_a"]
    assert result["retry_promoted_count"] == 1
    assert result["retry_promoted"] == ["todo_b"]


def test_extended_queue_view_counts_states(tmp_path: Path) -> None:
    path = _queue(tmp_path)
    enqueue_tasks(path, goal_id="goal", todo_ids=["todo_a"], recorded_at="2026-08-14T00:00:00Z")
    view = extended_queue_view(path)
    assert view["pending_count"] == 1
    assert view["extended"]["dead_letter_count"] == 0
