"""Deterministic, side-effect-free Task state replay.

RFC C4 (Task Checkpoint and Replay) + §10.4 Replay Requirements:

* Replay must be deterministic, idempotent, side-effect free, and
  schema-version aware.
* It reconstructs *state*, never external side effects (API calls, email,
  LLM invocation, file mutation must not run during replay).
* The contract is::

      replay(events) == replay(events)

  and::

      checkpoint + events_after_checkpoint == full_replay(events)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    Checkpoint,
    compute_state_hash,
    load_latest_checkpoint,
    verify_checkpoint_integrity,
)
from .time import now_utc_iso

#: Replay context marker: the apply callback may tag derived state.
REPLAY_SCHEMA_VERSION = CHECKPOINT_SCHEMA_VERSION

#: A state transition function: ``new_state = apply(state, event)``.
StateTransition = Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]

#: An event filter over the raw event stream.
EventFilter = Callable[[Mapping[str, Any]], bool]


class ReplayViolationError(RuntimeError):
    """Raised when replay invariants are violated (non-determinism, side
    effects, or schema mismatch)."""


def replay_task(
    events: Sequence[Mapping[str, Any]],
    *,
    initial_state: Mapping[str, Any] | None = None,
    apply: StateTransition,
    schema_version: int = REPLAY_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Deterministically fold ``events`` into state via ``apply``.

    ``apply`` must be a pure transition (no I/O, no mutation of inputs).
    """
    state: dict[str, Any] = dict(initial_state or {})
    for event in events:
        state = dict(apply(state, event))
    return state


def replay_from_checkpoint(
    checkpoint: Checkpoint | None,
    events_after_checkpoint: Sequence[Mapping[str, Any]],
    *,
    apply: StateTransition,
    schema_version: int = REPLAY_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Recover current Task state from a checkpoint plus subsequent events.

    When no checkpoint exists, replay starts from an empty state.
    """
    if checkpoint is None:
        return replay_task(
            events_after_checkpoint,
            apply=apply,
            schema_version=schema_version,
        )
    if checkpoint.schema_version != schema_version:
        raise ReplayViolationError(
            f"checkpoint schema {checkpoint.schema_version} does not match "
            f"replay schema {schema_version}"
        )
    if not verify_checkpoint_integrity(checkpoint):
        raise ReplayViolationError("checkpoint state hash mismatch; refusing to replay")
    return replay_task(
        events_after_checkpoint,
        initial_state=checkpoint.state_snapshot,
        apply=apply,
        schema_version=schema_version,
    )


def verify_replay_equivalence(
    events: Sequence[Mapping[str, Any]],
    *,
    checkpoint: Checkpoint | None,
    events_after_checkpoint: Sequence[Mapping[str, Any]],
    apply: StateTransition,
    schema_version: int = REPLAY_SCHEMA_VERSION,
) -> tuple[bool, str]:
    """Verify that ``checkpoint + events_after`` equals ``full_replay``.

    Returns ``(is_equivalent, explanation)``.
    """
    full = replay_task(events, apply=apply, schema_version=schema_version)
    recovered = replay_from_checkpoint(
        checkpoint,
        events_after_checkpoint,
        apply=apply,
        schema_version=schema_version,
    )
    if full == recovered:
        return True, "recovered state equals full replay"
    return False, "recovered state diverges from full replay"


def partition_events_after_checkpoint(
    events: Sequence[Mapping[str, Any]],
    checkpoint: Checkpoint | None,
    *,
    event_id_of: Callable[[Mapping[str, Any]], str],
) -> list[dict[str, Any]]:
    """Return events strictly after the checkpoint's ``last_event_id``.

    ``event_id_of`` extracts the stable event id from an event record. Events
    whose id is missing are treated as after-checkpoint (conservative).
    """
    if checkpoint is None:
        return [dict(event) for event in events]
    last = str(checkpoint.last_event_id or "").strip()
    if not last:
        return [dict(event) for event in events]
    # Locate the checkpoint boundary by event id; keep everything after it.
    for index, event in enumerate(events):
        if str(event_id_of(event) or "").strip() == last:
            return [dict(event) for event in events[index + 1 :]]
    # Boundary event not found in the stream: replay conservatively from the
    # beginning (checkpoint state is still applied first, so duplicates are
    # tolerated by deterministic transitions).
    return [dict(event) for event in events]


# ---------------------------------------------------------------------------
# Persisted event loading for a single Task (read-only)
# ---------------------------------------------------------------------------


def load_task_events(
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    *,
    filter_event: EventFilter | None = None,
) -> list[dict[str, Any]]:
    """Load run-index records for one Task as a replayable event stream.

    This is a read projection over the existing run index; it never mutates.
    """
    index_path = Path(runtime_root) / "goals" / goal_id / "runs" / "index.jsonl"
    if not index_path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        if str(record.get("todo_id") or "").strip() != str(todo_id).strip():
            continue
        if filter_event is not None and not filter_event(record):
            continue
        events.append(record)
    return events


def recover_task_state(
    runtime_root: Path,
    *,
    goal_id: str,
    todo_id: str,
    apply: StateTransition,
    filter_event: EventFilter | None = None,
    schema_version: int = REPLAY_SCHEMA_VERSION,
) -> tuple[dict[str, Any], Checkpoint | None, list[dict[str, Any]]]:
    """Full recovery workflow: latest checkpoint + subsequent events.

    Returns ``(state, checkpoint_used, events_replayed)``.
    """
    events = load_task_events(runtime_root, goal_id, todo_id, filter_event=filter_event)
    checkpoint = load_latest_checkpoint(runtime_root, goal_id, todo_id)
    events_after = partition_events_after_checkpoint(
        events,
        checkpoint,
        event_id_of=lambda event: str(event.get("event_id") or event.get("generated_at") or ""),
    )
    state = replay_from_checkpoint(
        checkpoint,
        events_after,
        apply=apply,
        schema_version=schema_version,
    )
    return state, checkpoint, events_after


def state_digest(state: Mapping[str, Any]) -> str:
    """Content hash of replayed state (for equality checks / persistence)."""
    return compute_state_hash(dict(state))


def replay_audit_record(
    *,
    goal_id: str,
    todo_id: str,
    state: Mapping[str, Any],
    checkpoint: Checkpoint | None,
    events_replayed: Sequence[Mapping[str, Any]],
    events_total: int,
    equivalent: bool,
) -> dict[str, Any]:
    """Build a public-safe replay audit record (no task contents)."""
    return {
        "goal_id": str(goal_id),
        "todo_id": str(todo_id),
        "schema_version": REPLAY_SCHEMA_VERSION,
        "checkpoint_used": checkpoint.to_dict() if checkpoint else None,
        "events_replayed": len(events_replayed),
        "events_total": int(events_total),
        "equivalent": bool(equivalent),
        "state_hash": state_digest(state),
        "recorded_at": now_utc_iso(),
    }
