"""Transaction-capture orchestration for legacy Todo and lease writers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ...history import load_registry
from ...registry import find_registry_goal
from . import local_authority_shadow_outbox as outbox
from .local_authority_shadow_projection import LEASE_PARTITION
from .runtime_shadow import resolve_coordination_runtime_shadow_config


def begin_todo_runtime_shadow_capture(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    state_path: Path,
    write_class: str,
    original_text: str,
) -> outbox.TodoPartitionCapture:
    """Create the default-off transaction capture while the Todo lock is held."""

    try:
        registry = load_registry(registry_path)
        goal = find_registry_goal(registry, goal_id)
        enabled = resolve_coordination_runtime_shadow_config(goal).enabled
        from ...rollout_event_log import load_rollout_events, rollout_event_log_path
        from ..todos.todo_index import MAX_TODO_INDEX_ROLLOUT_EVENTS_PER_GOAL
        from .local_authority_shadow_adapter import todo_partition_projector

        events = load_rollout_events(
            rollout_event_log_path(runtime_root, goal_id),
            limit=MAX_TODO_INDEX_ROLLOUT_EVENTS_PER_GOAL,
        )
        projector = todo_partition_projector(
            goal,
            state_path=state_path,
            rollout_events=events,
        )
    except Exception:
        enabled = False
        projector = None
    return outbox.TodoPartitionCapture.begin(
        enabled=enabled,
        runtime_root=runtime_root,
        goal_id=goal_id,
        state_path=state_path,
        write_class=write_class,
        original_text=original_text,
        projector=projector,
    )


def settle_todo_runtime_shadow_capture(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    write_class: str,
    capture: outbox.TodoPartitionCapture,
) -> dict[str, Any]:
    """Boundedly drain one transaction capture after releasing the Todo lock."""

    from .local_authority_shadow_adapter import (
        capture_evidence,
        drain_local_authority_shadow_outbox,
        observe_todo_local_authority_commit,
    )

    drain = (
        drain_local_authority_shadow_outbox(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
        )
        if capture.outcome.entry_id is not None
        else None
    )
    payload["coordination_runtime_shadow"] = capture_evidence(
        goal_id=goal_id,
        capture=capture.outcome,
        drain=drain,
    )
    return observe_todo_local_authority_commit(
        payload,
        registry_path,
        goal_id,
        write_class,
        runtime_root=runtime_root,
    )


def settle_lease_runtime_shadow_capture(
    payload: dict[str, Any],
    *,
    registry_path: Path | None,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    """Turn the TS writer capture receipt into bounded runtime-shadow evidence."""

    raw = payload.pop("coordination_runtime_shadow_capture", None)
    if not isinstance(raw, Mapping) or registry_path is None:
        return payload
    capture = outbox.CaptureOutcome(
        entry_id=str(raw["entry_id"]) if isinstance(raw.get("entry_id"), str) else None,
        partition=LEASE_PARTITION,
        seq=int(raw["seq"]) if isinstance(raw.get("seq"), int) else None,
        source_bytes_digest=(
            str(raw["source_bytes_digest"])
            if isinstance(raw.get("source_bytes_digest"), str)
            else None
        ),
        failure=dict(raw["failure"]) if isinstance(raw.get("failure"), Mapping) else None,
    )
    from .local_authority_shadow_adapter import (
        capture_evidence,
        drain_local_authority_shadow_outbox,
    )

    drain = (
        drain_local_authority_shadow_outbox(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
        )
        if capture.entry_id is not None
        else None
    )
    payload["coordination_runtime_shadow"] = capture_evidence(
        goal_id=goal_id,
        capture=capture,
        drain=drain,
    )
    return payload


__all__ = [
    "begin_todo_runtime_shadow_capture",
    "settle_lease_runtime_shadow_capture",
    "settle_todo_runtime_shadow_capture",
]
