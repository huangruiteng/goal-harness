"""Decision-free authority projection and transport for native lease acquire."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ...history import load_registry
from ...paths import resolve_runtime_root
from ..goals.active_state_event_projection import (
    state_event_log_candidates as _state_event_log_candidates,
)
from ..goals.path_resolution import resolve_goal_local_path
from ..todos.contract import normalize_todo_id
from ..todos.handoff_mode import HANDOFF_MODE_LEGACY
from .local_lease_record import TASK_LEASE_SCHEMA_VERSION, TaskLeaseError

TASK_LEASE_ACQUIRE_NATIVE_SCHEMA_VERSION = "loopx_task_lease_acquire_native_v0"
TASK_LEASE_AUTHORITY_SNAPSHOT_ATTEMPTS = 3


def _authority_source_receipt(source_id: str, path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve(strict=False)
    try:
        content = resolved.read_bytes()
    except FileNotFoundError:
        return {
            "source_id": source_id,
            "path": str(resolved),
            "state": "missing",
            "sha256": None,
        }
    return {
        "source_id": source_id,
        "path": str(resolved),
        "state": "file",
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _registry_goal(registry: dict[str, Any], goal_id: str) -> dict[str, Any] | None:
    from ...registry import registry_goals

    return next(
        (
            dict(goal)
            for goal in registry_goals(registry)
            if str(goal.get("id") or "") == goal_id
        ),
        None,
    )


def _task_lease_authority_source_paths(
    *,
    registry_path: Path,
    registry: dict[str, Any],
    goal_id: str,
) -> tuple[dict[str, Any] | None, Path | None, list[tuple[str, Path]]]:
    from ...rollout_event_log import rollout_event_log_path
    from ...state_refresh import resolve_goal_state
    sources: list[tuple[str, Path]] = [("registry", registry_path)]
    goal = _registry_goal(registry, goal_id)
    if goal is None:
        return None, None, sources
    try:
        _goal, _project, state_file = resolve_goal_state(
            registry=registry,
            goal_id=goal_id,
            project_override=None,
            state_file_override=None,
        )
    except (OSError, ValueError):
        return goal, None, sources
    sources.append(("active_state", state_file))
    for index, path in enumerate(
        _state_event_log_candidates(
            goal,
            state_path=state_file,
            resolve_goal_local_path=resolve_goal_local_path,
        )
    ):
        sources.append((f"state_event_{index}", path))
    projection_runtime_root = resolve_runtime_root(
        registry,
        None,
        registry_path=registry_path,
    )
    sources.append(
        (
            "rollout_events",
            rollout_event_log_path(projection_runtime_root, goal_id),
        )
    )
    unique: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for source_id, path in sources:
        key = str(path.expanduser().resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        unique.append((source_id, path))
    return goal, state_file, unique


def _raw_registered_agent_candidates(goal: dict[str, Any]) -> list[Any]:
    coordination = goal.get("coordination")
    spawn_policy = goal.get("spawn_policy")
    return [
        coordination.get("registered_agents")
        if isinstance(coordination, dict)
        else None,
        goal.get("registered_agents"),
        spawn_policy.get("registered_agents")
        if isinstance(spawn_policy, dict)
        else None,
    ]


def _compact_task_lease_todo_fact(todo: dict[str, Any]) -> dict[str, Any] | None:
    todo_id = normalize_todo_id(todo.get("todo_id"))
    if not todo_id:
        return None
    return {
        "todo_id": todo_id,
        "status": todo.get("status"),
        "claimed_by": todo.get("claimed_by"),
        "excluded_agents": todo.get("excluded_agents"),
    }


def _compact_task_lease_todos(projection: dict[str, Any]) -> list[dict[str, Any]]:
    todos: list[dict[str, Any]] = []
    for raw_todo in projection.get("todos") or []:
        if not isinstance(raw_todo, dict):
            continue
        compact_todo = _compact_task_lease_todo_fact(raw_todo)
        if compact_todo is not None:
            todos.append(compact_todo)
    return todos


def _task_lease_authority_projection(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
    goal: dict[str, Any] | None,
    state_file: Path | None,
) -> tuple[Any, list[Any], list[dict[str, Any]], dict[str, Any] | None]:
    from ...todos import list_goal_todos
    from ..goals.active_state_metadata import parse_state_frontmatter

    if goal is None:
        return HANDOFF_MODE_LEGACY, [], [], None

    handoff_mode: Any = HANDOFF_MODE_LEGACY
    if state_file is not None and state_file.exists():
        handoff_mode = parse_state_frontmatter(
            state_file.read_text(encoding="utf-8")
        ).get("handoff_mode")
    try:
        projection = list_goal_todos(
            registry_path=registry_path,
            goal_id=goal_id,
        )
    except (OSError, ValueError) as exc:
        projection_error = {
            "code": "todo_projection_unavailable",
            "message": "cannot resolve todo projection for task lease",
            "payload": {
                "goal_id": goal_id,
                "todo_id": todo_id,
                "error": str(exc),
            },
        }
        return (
            handoff_mode,
            _raw_registered_agent_candidates(goal),
            [],
            projection_error,
        )
    return (
        handoff_mode,
        _raw_registered_agent_candidates(goal),
        _compact_task_lease_todos(projection),
        None,
    )


def _authority_source_identity(
    sources: list[tuple[str, Path]],
) -> list[tuple[str, str]]:
    return [
        (source_id, str(path.expanduser().resolve(strict=False)))
        for source_id, path in sources
    ]


def _task_lease_authority_snapshot_attempt(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
) -> dict[str, Any] | None:
    registry_receipt_before = _authority_source_receipt("registry", registry_path)
    registry = load_registry(registry_path)
    goal, state_file, sources = _task_lease_authority_source_paths(
        registry_path=registry_path,
        registry=registry,
        goal_id=goal_id,
    )
    receipts_before = [
        _authority_source_receipt(source_id, path) for source_id, path in sources
    ]
    if receipts_before[0] != registry_receipt_before:
        return None

    handoff_mode, registered_candidates, todos, projection_error = (
        _task_lease_authority_projection(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            goal=goal,
            state_file=state_file,
        )
    )

    registry_after = load_registry(registry_path)
    _goal_after, _state_file_after, sources_after = _task_lease_authority_source_paths(
        registry_path=registry_path,
        registry=registry_after,
        goal_id=goal_id,
    )
    if _authority_source_identity(sources_after) != _authority_source_identity(sources):
        return None
    receipts_after = [
        _authority_source_receipt(source_id, path) for source_id, path in sources_after
    ]
    if receipts_before != receipts_after:
        return None
    return {
        "handoff_mode": handoff_mode,
        "registered_agent_candidates": registered_candidates,
        "todos": todos,
        "todo_projection_error": projection_error,
        "source_receipts": receipts_after,
    }


def task_lease_acquire_authority_facts(
    *,
    registry_path: Path,
    goal_id: str,
    todo_id: str,
) -> dict[str, Any]:
    """Project a source-stable, decision-free acquire input snapshot."""

    for _attempt in range(TASK_LEASE_AUTHORITY_SNAPSHOT_ATTEMPTS):
        facts = _task_lease_authority_snapshot_attempt(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
        )
        if facts is not None:
            return facts
    raise TaskLeaseError(
        "task-lease authority sources changed while preparing acquire; retry",
        code="authority_source_changed",
        payload={"goal_id": goal_id, "todo_id": todo_id},
    )


def execute_native_task_lease_acquire(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    owner: str,
    idempotency_key: str,
    ttl_seconds: int | None = None,
    write_scopes: list[str] | None = None,
    expected_version: int | None = None,
    _legacy_provider_projection: bool = False,
) -> dict[str, Any]:
    """Transport one compact acquire request to the native TypeScript owner."""

    from ..effect_runtime import effect_runtime_result

    for attempt in range(TASK_LEASE_AUTHORITY_SNAPSHOT_ATTEMPTS):
        authority = task_lease_acquire_authority_facts(
            registry_path=registry_path,
            goal_id=str(goal_id or ""),
            todo_id=str(todo_id or ""),
        )
        request = {
            "schema_version": TASK_LEASE_ACQUIRE_NATIVE_SCHEMA_VERSION,
            "runtime_root": str(runtime_root),
            "goal_id": goal_id,
            "todo_id": todo_id,
            "owner": owner,
            "idempotency_key": idempotency_key,
            "ttl_seconds": ttl_seconds,
            "write_scopes": list(write_scopes or []),
            "expected_version": expected_version,
            "authority": authority,
        }
        payload = effect_runtime_result(
            "task_lease.acquire.native",
            request,
            timeout=15.0,
        )
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != TASK_LEASE_SCHEMA_VERSION
            or payload.get("action") != "acquire"
            or not isinstance(payload.get("ok"), bool)
        ):
            raise RuntimeError("native task-lease acquire result shape mismatch")
        if (
            payload.get("error_code") == "authority_source_changed"
            and attempt + 1 < TASK_LEASE_AUTHORITY_SNAPSHOT_ATTEMPTS
        ):
            continue
        result = dict(payload)
        if _legacy_provider_projection and result.get("ok") is True:
            result["handoff_mode"] = (
                authority.get("handoff_mode") or HANDOFF_MODE_LEGACY
            )
            result.pop("settlement", None)
        return result
    raise RuntimeError("native task-lease acquire exhausted source-CAS retries")
