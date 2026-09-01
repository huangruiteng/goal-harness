"""Post-commit bridge from legacy local authority into a file shadow.

The adapter deliberately owns no lifecycle decision. It is entered only after
the existing Markdown or task-lease writer has succeeded, projects public-safe
facts, and asks the TypeScript authority-store boundary to retain an
observation. Missing configuration is a zero-effect fast path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ...file_lock import LockAcquireTimeoutError, exclusive_file_lock
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...registry import find_registry_goal
from ..effect_runtime import effect_runtime_result


LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA = "loopx_local_authority_shadow_config_v0"
LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA = "loopx_local_authority_shadow_request_v0"
LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA = "loopx_local_authority_shadow_projection_v0"
LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA = "loopx_local_authority_shadow_evidence_v0"
_CONFIG_FIELDS = {"schema_version", "mode"}
_PROJECTION_ATTEMPTS = 3
_CONFLICT_RETRY_ATTEMPTS = 3
_EVIDENCE_OUTCOMES = {
    "advanced",
    "replayed",
    "ambiguous_reconciled",
    "ambiguous_unproved",
    "unavailable",
    "failed",
    "protocol_mismatch",
    "conflict_retry_required",
}
_TODO_FIELDS = (
    "todo_id",
    "role",
    "status",
    "claimed_by",
    "bound_agent",
    "goal_bound",
    "blocks_agent",
    "excluded_agents",
    "global_gate",
    "task_class",
    "action_kind",
    "required_write_scopes",
    "required_capabilities",
    "continuation_policy",
    "successor_todo_ids",
    "no_followup",
    "completion_continuation",
)
_LEASE_FIELDS = (
    "todo_id",
    "owner",
    "idempotency_key",
    "write_scopes",
    "version",
    "lease_epoch",
    "acquired_at",
    "updated_at",
    "expires_at",
    "released_at",
    "status",
)


def _base_evidence(
    *,
    goal_id: str,
    outcome: str,
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA,
        "outcome": outcome,
        "reason_code": reason_code,
        "goal_id": goal_id,
        "operation_id": None,
        "source_digest": None,
        "primary_authority": "legacy_local",
        "candidate_provider": "file",
        "candidate_read_for_decision": False,
        "provider_to_local_writes": False,
        "primary_writeback_preserved": True,
        "store_identity": None,
        "provider_revision": None,
        "cursor": None,
    }


def _shadow_config(registry: dict[str, Any], goal_id: str) -> dict[str, str] | None:
    goal = find_registry_goal(registry, goal_id)
    coordination = goal.get("coordination") if isinstance(goal, dict) else None
    if not isinstance(coordination, dict) or "authority_shadow" not in coordination:
        return None
    raw = coordination.get("authority_shadow")
    if (
        not isinstance(raw, dict)
        or set(raw) != _CONFIG_FIELDS
        or raw.get("schema_version") != LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA
        or raw.get("mode") != "file_one_way"
    ):
        raise ValueError("authority_shadow must be a closed file_one_way config")
    return {"mode": "file_one_way"}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _compact_todo(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    todo_id = str(raw.get("todo_id") or "").strip()
    if not todo_id:
        return None
    compact = {field: raw[field] for field in _TODO_FIELDS if field in raw}
    compact["todo_id"] = todo_id
    if "status" not in compact and isinstance(raw.get("done"), bool):
        compact["status"] = "done" if raw["done"] else "open"
    return json.loads(_canonical(compact))


def _compact_lease(path: Path, *, goal_id: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("task lease must contain an object")
    if raw.get("goal_id") != goal_id or raw.get("todo_id") != path.stem:
        raise ValueError("task lease identity does not match its shadow source")
    return json.loads(
        _canonical({field: raw[field] for field in _LEASE_FIELDS if field in raw})
    )


def _source_projection(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    from ...control_plane.todos.handoff_mode import goal_handoff_mode_for_goal
    from ...todos import list_goal_todos

    todo_payload = list_goal_todos(
        registry_path=registry_path,
        goal_id=goal_id,
        runtime_root_arg=str(runtime_root),
    )
    todos = [
        compact
        for raw in todo_payload.get("todos") or []
        if (compact := _compact_todo(raw)) is not None
    ]
    todos.sort(key=lambda item: str(item["todo_id"]))
    lease_dir = runtime_root / "goals" / goal_id / "task-leases"
    leases = (
        [
            _compact_lease(path, goal_id=goal_id)
            for path in sorted(lease_dir.glob("*.json"))
        ]
        if lease_dir.exists()
        else []
    )
    projection = {
        "schema_version": LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA,
        "goal_id": goal_id,
        "handoff_mode": goal_handoff_mode_for_goal(
            registry_path=registry_path,
            goal_id=goal_id,
        ),
        "todos": todos,
        "leases": leases,
    }
    return json.loads(_canonical(projection))


def _stable_projection(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
) -> dict[str, Any]:
    previous = _source_projection(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    for _attempt in range(_PROJECTION_ATTEMPTS):
        current = _source_projection(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
        )
        if current == previous:
            return current
        previous = current
    raise RuntimeError("local authority sources did not stabilize for shadowing")


def _valid_evidence(
    result: object,
    *,
    goal_id: str,
    operation_id: str,
    source_digest: str,
) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        result.get("schema_version") == LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA
        and result.get("outcome") in _EVIDENCE_OUTCOMES
        and result.get("goal_id") == goal_id
        and result.get("operation_id") == operation_id
        and result.get("source_digest") == source_digest
        and result.get("primary_authority") == "legacy_local"
        and result.get("candidate_provider") == "file"
        and result.get("candidate_read_for_decision") is False
        and result.get("provider_to_local_writes") is False
        and result.get("primary_writeback_preserved") is True
        and (
            result.get("reason_code") is None
            or isinstance(result.get("reason_code"), str)
        )
    )


def observe_local_authority_commit(
    *,
    registry_path: Path,
    runtime_root: Path | None,
    goal_id: str,
    source_operation: str,
) -> dict[str, Any] | None:
    """Record one local post-commit observation without changing its verdict."""

    if not goal_id or goal_id in {".", ".."} or "/" in goal_id or "\\" in goal_id:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="invalid_shadow_goal_id",
        )
    try:
        registry = load_registry(registry_path)
        config = _shadow_config(registry, goal_id)
    except Exception:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="invalid_shadow_config",
        )
    if config is None:
        return None

    try:
        if runtime_root is None:
            runtime_root = resolve_runtime_root(
                registry,
                None,
                registry_path=registry_path,
            )
        # Candidate-provider bytes live outside the legacy per-goal runtime
        # tree. State migration may copy that tree, but it must never copy a
        # store identity or revision and accidentally create a second lineage.
        shadow_root = runtime_root / "authority-shadow" / "file" / goal_id
        with exclusive_file_lock(
            shadow_root / "observation",
            timeout_seconds=1.0,
            operation="local_authority_shadow_observe",
        ):
            result: dict[str, Any] | None = None
            for _attempt in range(_CONFLICT_RETRY_ATTEMPTS):
                projection = _stable_projection(
                    registry_path=registry_path,
                    runtime_root=runtime_root,
                    goal_id=goal_id,
                )
                source_digest = (
                    "sha256:" + hashlib.sha256(_canonical(projection)).hexdigest()
                )
                operation_id = (
                    "local-shadow:"
                    + hashlib.sha256(
                        _canonical(
                            {
                                "goal_id": goal_id,
                                "source_operation": source_operation,
                                "source_digest": source_digest,
                            }
                        )
                    ).hexdigest()
                )
                raw_result = effect_runtime_result(
                    "coordination.local_authority_shadow.record",
                    {
                        "schema_version": LOCAL_AUTHORITY_SHADOW_REQUEST_SCHEMA,
                        "mode": config["mode"],
                        "runtime_root": str(runtime_root),
                        "goal_id": goal_id,
                        "operation_id": operation_id,
                        "source_operation": source_operation,
                        "source_digest": source_digest,
                        "source_projection": projection,
                    },
                    timeout=15.0,
                )
                if not _valid_evidence(
                    raw_result,
                    goal_id=goal_id,
                    operation_id=operation_id,
                    source_digest=source_digest,
                ):
                    return _base_evidence(
                        goal_id=goal_id,
                        outcome="failed",
                        reason_code="shadow_evidence_invalid",
                    )
                result = dict(raw_result)
                if result["outcome"] != "conflict_retry_required":
                    return result
            if result is not None:
                return result
    except LockAcquireTimeoutError:
        return _base_evidence(
            goal_id=goal_id,
            outcome="unavailable",
            reason_code="shadow_observation_lock_timeout",
        )
    except Exception:
        return _base_evidence(
            goal_id=goal_id,
            outcome="failed",
            reason_code="shadow_observation_failed",
        )
    return _base_evidence(
        goal_id=goal_id,
        outcome="failed",
        reason_code="shadow_observation_failed",
    )


__all__ = [
    "LOCAL_AUTHORITY_SHADOW_CONFIG_SCHEMA",
    "LOCAL_AUTHORITY_SHADOW_EVIDENCE_SCHEMA",
    "observe_local_authority_commit",
]
