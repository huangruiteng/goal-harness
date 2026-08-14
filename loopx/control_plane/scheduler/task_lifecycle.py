"""Task lifecycle: lease, retry, idempotency and capability matching.

This module closes the automation loop for the resident scheduler by giving the
append-only task queue a real lifecycle, per ``plan/new_plan.md`` P0/P1:

* **Lease** — a claimed task carries a ``lease_until`` timestamp and an
  ``attempt`` counter. A worker that crashes or is killed after ``claimed``
  becomes a *zombie*; the scheduler expires its lease and re-enqueues the task
  (``claimed -> expired -> pending``) so it is not stuck forever.
* **Retry** — a failed task transitions ``claimed -> failed -> retry_wait``
  (with a backoff window) and then ``retry_wait -> pending`` when the retry
  delay elapses, up to ``max_attempts``; exhausting attempts leaves the task in
  ``failed`` (promotable to ``dead_letter`` via :func:`dead_letter_exhausted`
  for explicit operator attention).
* **Idempotency** — tasks are keyed by a ``task_id`` that encodes the todo and a
  ``generation`` (``todo_id:generation:N``). A duplicate event or a re-execution
  of the same todo at a different generation never collides with the same
  logical work item, while within one generation enqueue stays idempotent.
* **Capability matching** — ``eligible(worker, task)`` matches a worker's
  declared capabilities against a task's ``required_capabilities``, so a claim
  prefers the oldest pending task a given worker is actually able to run.

Every mutation is idempotent and file-backed; the store remains an append-only
JSONL (rewritten in place for status transitions, same as ``claim_next_task``).
All entry statuses are backward compatible with the existing
``pending`` / ``claimed`` / ``done`` lifecycle.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..runtime.time import now_utc_iso
from .event_driven_dispatch import (
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_DONE,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUSES,
    TASK_QUEUE_ENTRY_SCHEMA_VERSION,
    load_task_queue,
)

# Extended lifecycle states (superset of pending/claimed/done).
QUEUE_STATUS_RUNNING = "running"
QUEUE_STATUS_EXPIRED = "expired"
QUEUE_STATUS_FAILED = "failed"
QUEUE_STATUS_RETRY_WAIT = "retry_wait"
QUEUE_STATUS_CANCELLED = "cancelled"
QUEUE_STATUS_DEAD_LETTER = "dead_letter"

EXTENDED_QUEUE_STATUSES = QUEUE_STATUSES | {
    QUEUE_STATUS_RUNNING,
    QUEUE_STATUS_EXPIRED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_RETRY_WAIT,
    QUEUE_STATUS_CANCELLED,
    QUEUE_STATUS_DEAD_LETTER,
}

# Statuses that still occupy their logical todo (idempotency domain).
_ACTIVE_STATUSES = {
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_CLAIMED,
    QUEUE_STATUS_RUNNING,
    QUEUE_STATUS_RETRY_WAIT,
}

DEFAULT_LEASE_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 30

TASK_ID_SEPARATOR = ":generation:"


# ---------------------------------------------------------------------------
# Idempotency: generation-aware task id
# ---------------------------------------------------------------------------


def build_task_id(todo_id: str, generation: int = 0) -> str:
    """Return a generation-aware task id: ``todo_id:generation:N``."""
    normalized = str(todo_id or "").strip()
    try:
        gen = int(generation)
    except (TypeError, ValueError):
        gen = 0
    return f"{normalized}{TASK_ID_SEPARATOR}{max(0, gen)}"


def parse_task_id(task_id: str) -> tuple[str, int] | None:
    """Split a task id back into ``(todo_id, generation)`` or None."""
    text = str(task_id or "").strip()
    if not text or TASK_ID_SEPARATOR not in text:
        return None
    todo_id, _, raw_gen = text.rpartition(TASK_ID_SEPARATOR)
    try:
        generation = int(raw_gen)
    except ValueError:
        return None
    return todo_id, generation


def task_generation(task_id: str | None) -> int:
    """Extract the generation from a task id (0 when absent/undeterminable)."""
    parsed = parse_task_id(task_id or "")
    return parsed[1] if parsed else 0


# ---------------------------------------------------------------------------
# Worker capability matching
# ---------------------------------------------------------------------------


def normalize_worker_capabilities(capabilities: Sequence[str] | None) -> set[str]:
    """Normalize a worker's declared capabilities to a lowercase token set.

    Accepts a list, tuple, or a comma/space-separated string.
    """
    result: set[str] = set()
    values: Sequence[str]
    if isinstance(capabilities, str):
        values = (capabilities,)
    else:
        values = capabilities or ()
    for value in values:
        for token in str(value or "").replace(",", " ").split():
            token = token.strip().lower()
            if token:
                result.add(token)
    return result


def normalize_required_capabilities(value: Any) -> list[str]:
    """Normalize a task's required capabilities to a lowercase token list."""
    tokens: list[str] = []
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, (list, tuple)):
        raw = value
    else:
        return tokens
    for item in raw:
        for token in str(item or "").replace(",", " ").split():
            token = token.strip().lower()
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def task_required_capabilities(entry: Mapping[str, Any]) -> list[str]:
    """Read the normalized required capabilities from a task entry."""
    return normalize_required_capabilities(entry.get("required_capabilities"))


def eligible(
    worker: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    registry: Any = None,
) -> bool:
    """Whether ``worker`` may run ``task`` based on required capabilities.

    A task with no required capabilities is eligible for any worker. A task with
    required capabilities is eligible only for a worker that declares all of
    them. Workers declare capabilities via ``worker["capabilities"]`` (list or
    comma-separated string) or the ``capabilities`` keyword on claim.

    When ``registry`` (a ``CapabilityRegistry``) is supplied, a task that carries
    a ``capability_binding_ref`` (``<capability-id>:<key>``) is additionally
    gated on that capability pack being ``ready`` in its provider lifecycle and
    on the worker declaring the pack id as a capability token. This is the
    bridge to the legacy capability-pack system; without a registry the function
    is identical to the original token-only matching.
    """
    binding = task.get("capability_binding_ref")
    if registry is not None or binding:
        from ..capabilities_bridge import eligible_bridged

        return eligible_bridged(worker, task, registry=registry)
    required = task_required_capabilities(task)
    if not required:
        return True
    worker_caps = normalize_worker_capabilities(worker.get("capabilities"))
    return all(cap in worker_caps for cap in required)


def worker_satisfies_capabilities(
    capabilities: Sequence[str] | None,
    required_capabilities: Sequence[str] | None,
) -> bool:
    """Convenience form of :func:`eligible` given raw capability lists."""
    worker_caps = normalize_worker_capabilities(capabilities)
    required = normalize_required_capabilities(required_capabilities)
    return all(cap in worker_caps for cap in required)


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _read_entries(path: Path) -> list[dict[str, Any]]:
    """Read all valid queue entries from a JSONL path (empty when absent)."""
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


def _write_entries(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    """Atomically rewrite the queue JSONL from an entry list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        "".join(json.dumps(dict(e), sort_keys=True, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# Lease
# ---------------------------------------------------------------------------


def lease_expiry(
    lease_seconds: int | float | None = None,
    *,
    recorded_at: str | None = None,
    now: float | None = None,
) -> float:
    """Compute the absolute epoch-second lease expiry for a claimed task."""
    lease = DEFAULT_LEASE_SECONDS if lease_seconds is None else max(1, float(lease_seconds))
    base = now if now is not None else time.time()
    return base + lease


def is_expired(entry: Mapping[str, Any], *, now: float | None = None) -> bool:
    """Whether a claimed/running task has outlived its lease.

    A claimed/running task **without a ``lease_until``** is treated as an expired
    zombie: it was claimed by older code (or a crash before the lease was
    written) and there is no active worker holding it, so it must be reclaimed.
    This recovers legacy ``claimed`` entries (e.g. ``claimed: 4`` stale tasks in
    the website1 session) that would otherwise be stuck forever.
    """
    status = str(entry.get("status") or "")
    if status not in {QUEUE_STATUS_CLAIMED, QUEUE_STATUS_RUNNING}:
        return False
    raw = entry.get("lease_until")
    if raw is None:
        return True  # claimed/running without a lease = zombie
    try:
        lease_until = float(raw)
    except (TypeError, ValueError):
        return True
    current = now if now is not None else time.time()
    return current >= lease_until


def expire_stale_leases(
    path: Path,
    *,
    worker_id: str | None = None,
    recorded_at: str | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Re-enqueue claimed/running tasks whose lease has expired (zombie recovery).

    Transitions ``claimed|running -> expired -> pending`` so a crashed worker's
    task is reclaimed. Returns the list of re-enqueued (expired) entries.
    """
    entries = _read_entries(path)
    reenqueued: list[dict[str, Any]] = []
    changed = False
    stamp = recorded_at or now_utc_iso()
    for entry in entries:
        if is_expired(entry, now=now):
            entry["status"] = QUEUE_STATUS_PENDING
            entry["lease_until"] = None
            entry["expired_at"] = stamp
            entry["expired_by"] = worker_id
            entry.pop("claimed_by", None)
            entry.pop("claimed_at", None)
            reenqueued.append(dict(entry))
            changed = True
    if changed:
        _write_entries(path, entries)
    return reenqueued


# ---------------------------------------------------------------------------
# Claim with capability matching + lease
# ---------------------------------------------------------------------------


def claim_next_eligible_task(
    path: Path,
    *,
    worker_id: str,
    capabilities: Sequence[str] | None = None,
    lease_seconds: int | float | None = None,
    recorded_at: str | None = None,
    now: float | None = None,
    registry: Any = None,
) -> dict[str, Any] | None:
    """Claim the oldest pending task the worker can run, with a fresh lease.

    Returns the claimed entry (with ``claimed_by``, ``claimed_at``,
    ``lease_until``, ``attempt``) or None when no eligible task is available.

    When ``registry`` is supplied, capability-pack bindings
    (``capability_binding_ref``) are resolved through the registry (see
    :func:`eligible`).
    """
    entries = _read_entries(path)
    claimed: dict[str, Any] | None = None
    for entry in entries:
        if entry.get("status") != QUEUE_STATUS_PENDING:
            continue
        if not eligible({"capabilities": capabilities}, entry, registry=registry):
            continue
        entry["status"] = QUEUE_STATUS_CLAIMED
        entry["claimed_by"] = str(worker_id).strip()
        entry["claimed_at"] = recorded_at or now_utc_iso()
        entry["lease_until"] = lease_expiry(
            lease_seconds, recorded_at=recorded_at, now=now
        )
        try:
            entry["attempt"] = int(entry.get("attempt") or 0) + 1
        except (TypeError, ValueError):
            entry["attempt"] = 1
        claimed = entry
        break
    if claimed is None:
        return None
    _write_entries(path, entries)
    return claimed


# ---------------------------------------------------------------------------
# Completion / failure / retry / dead-letter
# ---------------------------------------------------------------------------


def complete_task(
    path: Path,
    *,
    task_id: str,
    worker_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any] | None:
    """Transition a claimed/running task to ``done`` (idempotent).

    Returns the updated entry, or None if no matching task was found. A task is
    matched by ``task_id`` (falling back to ``todo_id`` when the task_id has no
    generation marker) and the claiming worker.
    """
    entries = _read_entries(path)
    stamp = recorded_at or now_utc_iso()
    target: dict[str, Any] | None = None
    for entry in entries:
        if _entry_matches(entry, task_id) and entry.get("status") in {
            QUEUE_STATUS_CLAIMED,
            QUEUE_STATUS_RUNNING,
        }:
            if worker_id and str(entry.get("claimed_by") or "") not in {
                "",
                str(worker_id),
            }:
                continue
            target = entry
            break
    if target is None:
        return None
    target["status"] = QUEUE_STATUS_DONE
    target["completed_at"] = stamp
    target["lease_until"] = None
    target["completed_by"] = worker_id
    _write_entries(path, entries)
    return target


def _entry_matches(entry: Mapping[str, Any], task_id: str) -> bool:
    """Match an entry by task_id, or by todo_id when the task_id is plain."""
    text = str(task_id or "").strip()
    if not text:
        return False
    if str(entry.get("task_id") or "") == text:
        return True
    if TASK_ID_SEPARATOR not in text and str(entry.get("todo_id") or "") == text:
        return True
    return False


def fail_task(
    path: Path,
    *,
    task_id: str,
    worker_id: str | None = None,
    error: str | None = None,
    transient: bool = True,
    max_attempts: int | None = None,
    retry_backoff_seconds: int | float | None = None,
    recorded_at: str | None = None,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Transition a claimed/running task on failure.

    * transient failure with attempts remaining -> ``retry_wait`` (with a
      ``retry_at`` backoff window so it is not immediately re-claimed);
    * permanent failure or retries exhausted -> ``failed``.
    """
    entries = _read_entries(path)
    stamp = recorded_at or now_utc_iso()
    target: dict[str, Any] | None = None
    for entry in entries:
        if _entry_matches(entry, task_id) and entry.get("status") in {
            QUEUE_STATUS_CLAIMED,
            QUEUE_STATUS_RUNNING,
        }:
            if worker_id and str(entry.get("claimed_by") or "") not in {
                "",
                str(worker_id),
            }:
                continue
            target = entry
            break
    if target is None:
        return None
    try:
        attempt = int(target.get("attempt") or 1)
    except (TypeError, ValueError):
        attempt = 1
    max_attempts_value = DEFAULT_MAX_ATTEMPTS if max_attempts is None else int(max_attempts)
    retry_allowed = transient and attempt < max(1, max_attempts_value)
    target["failed_at"] = stamp
    target["last_error"] = str(error or "").strip() or None
    target["lease_until"] = None
    if retry_allowed:
        backoff = (
            DEFAULT_RETRY_BACKOFF_SECONDS
            if retry_backoff_seconds is None
            else max(0, float(retry_backoff_seconds))
        )
        retry_at = (now if now is not None else time.time()) + backoff
        target["status"] = QUEUE_STATUS_RETRY_WAIT
        target["retry_at"] = retry_at
        target["retry_count"] = attempt
    else:
        target["status"] = QUEUE_STATUS_FAILED
        target.pop("retry_at", None)
    _write_entries(path, entries)
    return target


def promote_retry_ready(
    path: Path,
    *,
    recorded_at: str | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Move ``retry_wait`` tasks whose backoff has elapsed back to ``pending``."""
    entries = _read_entries(path)
    current = now if now is not None else time.time()
    stamp = recorded_at or now_utc_iso()
    promoted: list[dict[str, Any]] = []
    changed = False
    for entry in entries:
        if entry.get("status") != QUEUE_STATUS_RETRY_WAIT:
            continue
        retry_at = entry.get("retry_at")
        if retry_at is None:
            entry["status"] = QUEUE_STATUS_PENDING
            entry.pop("retry_at", None)
            entry["retry_promoted_at"] = stamp
            promoted.append(dict(entry))
            changed = True
            continue
        try:
            when = float(retry_at)
        except (TypeError, ValueError):
            when = 0.0
        if current >= when:
            entry["status"] = QUEUE_STATUS_PENDING
            entry.pop("retry_at", None)
            entry["retry_promoted_at"] = stamp
            promoted.append(dict(entry))
            changed = True
    if changed:
        _write_entries(path, entries)
    return promoted


def cancel_task(
    path: Path,
    *,
    task_id: str,
    reason: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any] | None:
    """Cancel a pending/claimed/running/retry_wait task -> ``cancelled``."""
    entries = _read_entries(path)
    stamp = recorded_at or now_utc_iso()
    target: dict[str, Any] | None = None
    for entry in entries:
        if _entry_matches(entry, task_id) and entry.get("status") in {
            QUEUE_STATUS_PENDING,
            QUEUE_STATUS_CLAIMED,
            QUEUE_STATUS_RUNNING,
            QUEUE_STATUS_RETRY_WAIT,
        }:
            target = entry
            break
    if target is None:
        return None
    target["status"] = QUEUE_STATUS_CANCELLED
    target["cancelled_at"] = stamp
    target["cancel_reason"] = str(reason or "").strip() or None
    target["lease_until"] = None
    _write_entries(path, entries)
    return target


def requeue_failed(
    path: Path,
    *,
    task_id: str,
    worker_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any] | None:
    """Manually move a ``failed``/``dead_letter``/``cancelled`` task to ``pending``."""
    entries = _read_entries(path)
    stamp = recorded_at or now_utc_iso()
    target: dict[str, Any] | None = None
    for entry in entries:
        if _entry_matches(entry, task_id) and entry.get("status") in {
            QUEUE_STATUS_FAILED,
            QUEUE_STATUS_DEAD_LETTER,
            QUEUE_STATUS_CANCELLED,
        }:
            target = entry
            break
    if target is None:
        return None
    target["status"] = QUEUE_STATUS_PENDING
    target["requeued_at"] = stamp
    target["requeued_by"] = worker_id
    target.pop("retry_at", None)
    target["lease_until"] = None
    _write_entries(path, entries)
    return target


def dead_letter_exhausted(
    path: Path,
    *,
    task_id: str,
    worker_id: str | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any] | None:
    """Explicitly move a failed task to ``dead_letter`` (operator attention)."""
    entries = _read_entries(path)
    stamp = recorded_at or now_utc_iso()
    target: dict[str, Any] | None = None
    for entry in entries:
        if _entry_matches(entry, task_id) and entry.get("status") in {
            QUEUE_STATUS_FAILED,
            QUEUE_STATUS_RETRY_WAIT,
        }:
            target = entry
            break
    if target is None:
        return None
    target["status"] = QUEUE_STATUS_DEAD_LETTER
    target["dead_lettered_at"] = stamp
    target["dead_lettered_by"] = worker_id
    target["lease_until"] = None
    target.pop("retry_at", None)
    _write_entries(path, entries)
    return target


# ---------------------------------------------------------------------------
# Views / reconciliation
# ---------------------------------------------------------------------------


def reconcile_queue(
    path: Path,
    *,
    worker_id: str | None = None,
    recorded_at: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run the idle-maintenance passes in order (zombie + retry promotion).

    Returns a summary of expired leases and retry promotions. Intended to be
    called at the top of each resident scheduler tick so the queue stays clean
    even when workers crash or tasks need retry.
    """
    expired = expire_stale_leases(path, worker_id=worker_id, recorded_at=recorded_at, now=now)
    promoted = promote_retry_ready(path, recorded_at=recorded_at, now=now)
    return {
        "ok": True,
        "expired_leases": [e.get("todo_id") for e in expired],
        "expired_count": len(expired),
        "retry_promoted": [e.get("todo_id") for e in promoted],
        "retry_promoted_count": len(promoted),
    }


def extended_queue_view(path: Path) -> dict[str, Any]:
    """A queue view that counts the extended lifecycle statuses."""
    view = load_task_queue(path)
    entries = _read_entries(path)
    counts: dict[str, int] = {}
    for status in EXTENDED_QUEUE_STATUSES:
        counts[status] = sum(1 for e in entries if e.get("status") == status)
    view["extended"] = {
        "running_count": counts[QUEUE_STATUS_RUNNING],
        "expired_count": counts[QUEUE_STATUS_EXPIRED],
        "failed_count": counts[QUEUE_STATUS_FAILED],
        "retry_wait_count": counts[QUEUE_STATUS_RETRY_WAIT],
        "cancelled_count": counts[QUEUE_STATUS_CANCELLED],
        "dead_letter_count": counts[QUEUE_STATUS_DEAD_LETTER],
    }
    return view


__all__ = [
    "QUEUE_STATUS_RUNNING",
    "QUEUE_STATUS_EXPIRED",
    "QUEUE_STATUS_FAILED",
    "QUEUE_STATUS_RETRY_WAIT",
    "QUEUE_STATUS_CANCELLED",
    "QUEUE_STATUS_DEAD_LETTER",
    "EXTENDED_QUEUE_STATUSES",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_BACKOFF_SECONDS",
    "TASK_ID_SEPARATOR",
    "build_task_id",
    "parse_task_id",
    "task_generation",
    "normalize_worker_capabilities",
    "normalize_required_capabilities",
    "task_required_capabilities",
    "eligible",
    "worker_satisfies_capabilities",
    "lease_expiry",
    "is_expired",
    "expire_stale_leases",
    "claim_next_eligible_task",
    "complete_task",
    "fail_task",
    "promote_retry_ready",
    "cancel_task",
    "requeue_failed",
    "dead_letter_exhausted",
    "reconcile_queue",
    "extended_queue_view",
]
