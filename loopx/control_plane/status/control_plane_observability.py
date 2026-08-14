"""Control-plane observability snapshot (plan/new_plan.md §7, P2).

Builds a single operator/agent-visible status view of the event-driven control
plane: scheduler, worker pool, task queue (including the extended lifecycle
states), task history, decision history, and rollout event history.

The snapshot is *read-only*: it never mutates state. It composes existing read
models (``load_task_queue``, ``extended_queue_view``, the rollout event log, and
the policy decision ledger) into one digest for debugging and monitoring.

Nothing here is required for scheduling correctness; it is purely observational.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from ...rollout_event_log import (
    load_rollout_events,
    rollout_event_log_path,
    summarize_rollout_events,
)
from ..scheduler.event_driven_dispatch import (
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_DONE,
    TASK_QUEUE_ENTRY_SCHEMA_VERSION,
    task_queue_path,
)
from ..scheduler.task_lifecycle import extended_queue_view


def _read_queue_entries(path: Path) -> list[dict[str, Any]]:
    """Read raw queue entries (empty when the file is absent or malformed)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed.get("schema_version") == TASK_QUEUE_ENTRY_SCHEMA_VERSION:
            entries.append(parsed)
    return entries

# Default limits for history digests (kept small so snapshots stay cheap).
DEFAULT_EVENT_HISTORY_LIMIT = 200
DEFAULT_DECISION_HISTORY_LIMIT = 100
DEFAULT_TASK_HISTORY_LIMIT = 200

# Queue statuses considered "in flight" (claimed or retrying).
_IN_FLIGHT_STATUSES = {
    QUEUE_STATUS_CLAIMED,
    "running",
    "retry_wait",
}

# Terminal / exception statuses of interest for an operator.
_EXCEPTION_STATUSES = {"failed", "dead_letter", "cancelled"}


def build_task_history(
    entries: Sequence[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_TASK_HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    """A compact chronological task history from queue entries (newest first).

    Each entry carries the todo, generation-aware task id, lifecycle status,
    claimer, attempt count, and key timestamps. Oldest entries are truncated to
    ``limit``.
    """
    ordered = list(entries)
    ordered.sort(key=lambda e: str(e.get("created_at") or ""))
    selected = ordered[-max(0, limit):]
    selected.reverse()
    history: list[dict[str, Any]] = []
    for entry in selected:
        history.append(
            {
                "todo_id": entry.get("todo_id"),
                "task_id": entry.get("task_id"),
                "status": entry.get("status"),
                "claimed_by": entry.get("claimed_by"),
                "attempt": entry.get("attempt"),
                "required_capabilities": entry.get("required_capabilities"),
                "created_at": entry.get("created_at"),
                "claimed_at": entry.get("claimed_at"),
                "completed_at": entry.get("completed_at"),
                "failed_at": entry.get("failed_at"),
                "last_error": entry.get("last_error"),
                "retry_at": entry.get("retry_at"),
            }
        )
    return history


def build_worker_status(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Worker status derived from queue entries: who holds which tasks.

    Reports per-worker in-flight claims and any capability declarations carried
    on the claimed entry. Purely derived from the queue (no external registry
    dependency).
    """
    by_worker: dict[str, dict[str, Any]] = {}
    for entry in entries:
        status = str(entry.get("status") or "")
        claimed_by = str(entry.get("claimed_by") or "")
        if status not in _IN_FLIGHT_STATUSES or not claimed_by:
            continue
        worker = by_worker.setdefault(
            claimed_by,
            {"worker_id": claimed_by, "in_flight": [], "task_ids": []},
        )
        worker["in_flight"].append(
            {
                "todo_id": entry.get("todo_id"),
                "status": status,
                "attempt": entry.get("attempt"),
                "required_capabilities": entry.get("required_capabilities"),
            }
        )
        worker["task_ids"].append(str(entry.get("todo_id") or ""))
    workers = list(by_worker.values())
    for worker in workers:
        worker["in_flight_count"] = len(worker["in_flight"])
    return {"worker_count": len(workers), "workers": workers}


def build_queue_digest(path: Path) -> dict[str, Any]:
    """Queue status: standard view + extended lifecycle counts + in-flight tally."""
    view = extended_queue_view(path)
    extended = view.get("extended") or {}
    entries = _read_queue_entries(path)
    done_todo_ids = [
        str(e.get("todo_id")) for e in entries if e.get("status") == QUEUE_STATUS_DONE
    ]
    return {
        "ok": True,
        "pending_count": view.get("pending_count", 0),
        "claimed_count": view.get("claimed_count", 0),
        "done_count": view.get("done_count", 0),
        "pending_todo_ids": view.get("pending_todo_ids", []),
        "claimed_todo_ids": view.get("claimed_todo_ids", []),
        "done_todo_ids": done_todo_ids,
        "extended": extended,
        "in_flight_count": int(extended.get("running_count", 0))
        + view.get("claimed_count", 0)
        + int(extended.get("retry_wait_count", 0)),
        "exception_count": sum(
            int(extended.get(k, 0))
            for k in ("failed_count", "dead_letter_count", "cancelled_count")
        ),
    }


def build_event_history(
    log_path: Path,
    *,
    limit: int = DEFAULT_EVENT_HISTORY_LIMIT,
) -> dict[str, Any]:
    """Rollout event history digest: recent events + per-kind counts."""
    events = load_rollout_events(log_path, limit=limit)
    summary = summarize_rollout_events(events)
    history = []
    for event in events[-limit:]:
        history.append(
            {
                "event_id": event.get("event_id"),
                "event_kind": event.get("event_kind"),
                "goal_id": event.get("goal_id"),
                "todo_id": event.get("todo_id"),
                "recorded_at": event.get("recorded_at"),
            }
        )
    history.reverse()
    return {
        "event_count": len(events),
        "counts_by_kind": summary.get("counts_by_kind", {}),
        "recent_events": history,
    }


def build_decision_history(
    decision_event_log_path: Path,
    *,
    limit: int = DEFAULT_DECISION_HISTORY_LIMIT,
) -> dict[str, Any]:
    """Policy decision history digest from the decision ledger.

    Falls back to an empty digest when the ledger path does not exist (decisions
    are opt-in and may not be recorded).
    """
    try:
        lines = decision_event_log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"ok": True, "decision_count": 0, "counts_by_outcome": {}, "recent_decisions": []}
    import json

    decisions: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            decisions.append(parsed)
    counts = Counter(str(d.get("outcome") or d.get("decision") or "unknown") for d in decisions)
    recent = decisions[-max(0, limit):]
    recent.reverse()
    compact = []
    for d in recent:
        compact.append(
            {
                "event_id": d.get("event_id"),
                "goal_id": d.get("goal_id"),
                "todo_id": d.get("todo_id"),
                "outcome": d.get("outcome") or d.get("decision"),
                "action": d.get("action"),
                "source": d.get("source"),
                "recorded_at": d.get("recorded_at"),
            }
        )
    return {
        "ok": True,
        "decision_count": len(decisions),
        "counts_by_outcome": dict(counts),
        "recent_decisions": compact,
    }


def build_control_plane_status(
    *,
    runtime_root: Path,
    goal_id: str,
    event_log_path: Path | None = None,
    decision_event_log_path: Path | None = None,
    worker_ids: Sequence[str] = (),
    scheduler_tick_count: int | None = None,
    event_history_limit: int = DEFAULT_EVENT_HISTORY_LIMIT,
    decision_history_limit: int = DEFAULT_DECISION_HISTORY_LIMIT,
    task_history_limit: int = DEFAULT_TASK_HISTORY_LIMIT,
) -> dict[str, Any]:
    """Build a unified control-plane status snapshot for ``goal_id``.

    Aggregates scheduler, worker, queue, task, decision, and event history into a
    single read-only digest. Safe to call any time; missing logs yield empty
    sections rather than raising.
    """
    queue_path = task_queue_path(runtime_root, goal_id=goal_id)
    entries = _read_queue_entries(queue_path)

    log_path = event_log_path or rollout_event_log_path(runtime_root, goal_id)

    return {
        "ok": True,
        "goal_id": str(goal_id or "").strip(),
        "schema_version": "loopx_control_plane_status_v0",
        "scheduler": {
            "goal_id": str(goal_id or "").strip(),
            "tick_count": scheduler_tick_count,
            "worker_ids": [str(w) for w in worker_ids],
        },
        "queue": build_queue_digest(queue_path),
        "workers": build_worker_status(entries),
        "task_history": build_task_history(entries, limit=task_history_limit),
        "decision_history": build_decision_history(
            decision_event_log_path, limit=decision_history_limit
        )
        if decision_event_log_path is not None
        else {"ok": True, "decision_count": 0, "counts_by_outcome": {}, "recent_decisions": []},
        "event_history": build_event_history(log_path, limit=event_history_limit),
    }


__all__ = [
    "DEFAULT_EVENT_HISTORY_LIMIT",
    "DEFAULT_DECISION_HISTORY_LIMIT",
    "DEFAULT_TASK_HISTORY_LIMIT",
    "build_control_plane_status",
    "build_queue_digest",
    "build_worker_status",
    "build_task_history",
    "build_event_history",
    "build_decision_history",
]
