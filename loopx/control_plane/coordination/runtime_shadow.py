"""Default-off Python adapter for the Stage 2C coordination runtime shadow.

The legacy Todo and task-lease writers remain canonical.  Callers may invoke
this adapter only after their primary mutation commits; every shadow outcome is
returned as evidence and must not change the primary command result.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..effect_runtime import effect_runtime_result


RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION = "loopx_coordination_runtime_shadow_config_v0"
RUNTIME_SHADOW_REQUEST_SCHEMA_VERSION = "loopx_coordination_runtime_shadow_commit_v0"
RUNTIME_SHADOW_METHOD = "coordination.runtime_shadow.commit"
RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA_VERSION = (
    "loopx_coordination_runtime_shadow_inspect_v0"
)
RUNTIME_SHADOW_INSPECT_METHOD = "coordination.runtime_shadow.inspect"
RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA_VERSION = (
    "loopx_coordination_runtime_shadow_bootstrap_v0"
)
RUNTIME_SHADOW_BOOTSTRAP_METHOD = "coordination.runtime_shadow.bootstrap"
RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA_VERSION = (
    "loopx_coordination_runtime_shadow_rollback_v0"
)
RUNTIME_SHADOW_ROLLBACK_METHOD = "coordination.runtime_shadow.rollback"
RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA_VERSION = (
    "loopx_coordination_runtime_shadow_qualify_v0"
)
RUNTIME_SHADOW_QUALIFY_METHOD = "coordination.runtime_shadow.qualify"
RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA_VERSION = (
    "loopx_coordination_runtime_shadow_todo_read_v0"
)
RUNTIME_SHADOW_TODO_READ_METHOD = "coordination.runtime_shadow.todo_read_candidate"


@dataclass(frozen=True)
class CoordinationRuntimeShadowConfig:
    enabled: bool
    provider: str | None
    reason_code: str


def resolve_coordination_runtime_shadow_config(
    goal: Mapping[str, Any] | None,
) -> CoordinationRuntimeShadowConfig:
    """Resolve one explicit file-shadow opt-in without changing legacy defaults."""

    if not isinstance(goal, Mapping):
        return CoordinationRuntimeShadowConfig(False, None, "goal_missing")
    coordination = goal.get("coordination")
    if not isinstance(coordination, Mapping):
        return CoordinationRuntimeShadowConfig(False, None, "configuration_absent")
    configured = coordination.get("runtime_shadow")
    if configured is None:
        return CoordinationRuntimeShadowConfig(False, None, "configuration_absent")
    if not isinstance(configured, Mapping):
        return CoordinationRuntimeShadowConfig(False, None, "configuration_invalid")
    if configured.get("enabled") is not True:
        return CoordinationRuntimeShadowConfig(False, None, "explicitly_disabled")
    if configured.get("schema_version") != RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION:
        return CoordinationRuntimeShadowConfig(False, None, "schema_mismatch")
    provider = configured.get("provider")
    if provider != "file_v0":
        return CoordinationRuntimeShadowConfig(False, None, "provider_unsupported")
    return CoordinationRuntimeShadowConfig(True, provider, "explicit_opt_in")


RuntimeInvoker = Callable[..., object]

_TODO_PROJECTION_FIELDS = (
    "todo_id",
    "role",
    "status",
    "task_class",
    "action_kind",
    "task_domain",
    "task_repository",
    "continuation_policy",
    "claimed_by",
    "bound_agent",
    "goal_bound",
    "blocks_agent",
    "excluded_agents",
    "global_gate",
    "required_write_scopes",
    "successor_todo_ids",
    "superseding_todo_id",
    "no_followup",
    "updated_at",
)

_LEASE_PROJECTION_FIELDS = (
    "todo_id",
    "owner",
    "write_scopes",
    "version",
    "lease_epoch",
    "acquired_at",
    "updated_at",
    "expires_at",
    "released_at",
    "status",
)


def load_task_lease_runtime_shadow_records(
    *,
    runtime_root: Path,
    goal_id: str,
) -> list[dict[str, object]]:
    """Read compact legacy lease records for a post-commit shadow snapshot."""

    lease_directory = runtime_root / "goals" / goal_id / "task-leases"
    if not lease_directory.exists():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(lease_directory.glob("todo_*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError(f"task lease is not an object: {path.name}")
        todo_id = value.get("todo_id")
        if not isinstance(todo_id, str) or not todo_id:
            raise ValueError(f"task lease omits todo_id: {path.name}")
        records.append(
            {
                field: value[field]
                for field in _LEASE_PROJECTION_FIELDS
                if field in value and value[field] is not None
            }
        )
    records.sort(key=lambda item: str(item["todo_id"]))
    return records


def build_todo_runtime_shadow_projection(
    *,
    goal_id: str,
    todos: object,
    leases: object = None,
) -> dict[str, object]:
    """Reduce the legacy Todo read model to coordination-owned JSON fields."""

    compact: list[dict[str, object]] = []
    if isinstance(todos, list):
        for item in todos:
            if not isinstance(item, Mapping):
                continue
            todo_id = item.get("todo_id")
            if not isinstance(todo_id, str) or not todo_id:
                continue
            projected = {
                field: item[field]
                for field in _TODO_PROJECTION_FIELDS
                if field in item and item[field] is not None
            }
            compact.append(projected)
    compact.sort(key=lambda item: str(item["todo_id"]))
    compact_leases: list[dict[str, object]] = []
    if isinstance(leases, list):
        for item in leases:
            if not isinstance(item, Mapping):
                continue
            todo_id = item.get("todo_id")
            if not isinstance(todo_id, str) or not todo_id:
                continue
            compact_leases.append(
                {
                    field: item[field]
                    for field in _LEASE_PROJECTION_FIELDS
                    if field in item and item[field] is not None
                }
            )
    compact_leases.sort(key=lambda item: str(item["todo_id"]))
    return {
        "schema_version": "loopx_coordination_runtime_shadow_projection_v0",
        "goal_id": goal_id,
        "source_authority": "legacy_markdown_and_task_lease",
        "todos": compact,
        "leases": compact_leases,
    }


def dispatch_coordination_runtime_shadow(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    operation_id: str,
    event_kind: str,
    source_version: str,
    projection: Mapping[str, Any],
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Mirror a committed mutation, isolating all shadow failures from truth."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_dispatch_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }

    request = {
        "schema_version": RUNTIME_SHADOW_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "operation_id": operation_id,
        "event_kind": event_kind,
        "source_version": source_version,
        "projection": dict(projection),
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_dispatch_v0",
            "status": "failed",
            "reason_code": "shadow_runtime_unavailable",
            "reason": str(exc),
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_dispatch_v0",
            "status": "failed",
            "reason_code": "shadow_runtime_result_invalid",
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    return dict(result)


def bootstrap_coordination_runtime_shadow(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    operation_id: str,
    source_version: str,
    projection: Mapping[str, Any],
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Import one legacy baseline into an empty shadow without promoting it."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_bootstrap_result_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    request = {
        "schema_version": RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "operation_id": operation_id,
        "source_version": source_version,
        "projection": dict(projection),
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_BOOTSTRAP_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_bootstrap_result_v0",
            "status": "failed",
            "reason_code": "shadow_bootstrap_runtime_unavailable",
            "reason": str(exc),
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_bootstrap_result_v0",
            "status": "failed",
            "reason_code": "shadow_bootstrap_runtime_result_invalid",
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    return dict(result)


def rollback_coordination_runtime_shadow(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    operation_id: str,
    expected_provider_revision: str,
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Quarantine one revision-fenced pre-promotion file shadow lineage."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_rollback_result_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    request = {
        "schema_version": RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "operation_id": operation_id,
        "expected_provider_revision": expected_provider_revision,
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_ROLLBACK_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_rollback_result_v0",
            "status": "failed",
            "reason_code": "shadow_rollback_runtime_unavailable",
            "reason": str(exc),
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_rollback_result_v0",
            "status": "failed",
            "reason_code": "shadow_rollback_runtime_result_invalid",
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    return dict(result)


def inspect_coordination_runtime_shadow(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    projection: Mapping[str, Any],
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Read parity evidence without allowing the shadow to drive decisions."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_inspection_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "parity_matches": False,
            "bootstrap_required": False,
            "decision_read_from_shadow": False,
        }
    request = {
        "schema_version": RUNTIME_SHADOW_INSPECT_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "projection": dict(projection),
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_INSPECT_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_inspection_v0",
            "status": "failed",
            "reason_code": "shadow_runtime_unavailable",
            "reason": str(exc),
            "parity_matches": False,
            "bootstrap_required": False,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_inspection_v0",
            "status": "failed",
            "reason_code": "shadow_runtime_result_invalid",
            "parity_matches": False,
            "bootstrap_required": False,
            "decision_read_from_shadow": False,
        }
    return dict(result)


def qualify_coordination_runtime_shadow(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    projection: Mapping[str, Any],
    minimum_operations: int,
    required_event_kinds: list[str],
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Qualify coverage across a shadow lineage without serving from it."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_qualification_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "qualified": False,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    request = {
        "schema_version": RUNTIME_SHADOW_QUALIFY_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "projection": dict(projection),
        "minimum_operations": minimum_operations,
        "required_event_kinds": list(required_event_kinds),
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_QUALIFY_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_qualification_v0",
            "status": "failed",
            "reason_code": "shadow_qualification_runtime_unavailable",
            "reason": str(exc),
            "qualified": False,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_qualification_v0",
            "status": "failed",
            "reason_code": "shadow_qualification_runtime_result_invalid",
            "qualified": False,
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }
    return dict(result)


def read_coordination_runtime_shadow_todo_candidate(
    *,
    goal: Mapping[str, Any] | None,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    projection: Mapping[str, Any],
    runtime_invoker: RuntimeInvoker = effect_runtime_result,
) -> dict[str, object]:
    """Read one parity-matched file Todo as pre-promotion evidence only."""

    config = resolve_coordination_runtime_shadow_config(goal)
    if not config.enabled:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_todo_read_result_v0",
            "status": "disabled",
            "reason_code": config.reason_code,
            "read_candidate_qualified": False,
            "decision_read_from_shadow": False,
        }
    request = {
        "schema_version": RUNTIME_SHADOW_TODO_READ_REQUEST_SCHEMA_VERSION,
        "runtime_root": str(runtime_root.expanduser().resolve()),
        "goal_id": goal_id,
        "todo_id": todo_id,
        "projection": dict(projection),
    }
    try:
        result = runtime_invoker(RUNTIME_SHADOW_TODO_READ_METHOD, request)
    except Exception as exc:
        return {
            "schema_version": "loopx_coordination_runtime_shadow_todo_read_result_v0",
            "status": "failed",
            "reason_code": "shadow_todo_read_runtime_unavailable",
            "reason": str(exc),
            "read_candidate_qualified": False,
            "decision_read_from_shadow": False,
        }
    if not isinstance(result, Mapping):
        return {
            "schema_version": "loopx_coordination_runtime_shadow_todo_read_result_v0",
            "status": "failed",
            "reason_code": "shadow_todo_read_runtime_result_invalid",
            "read_candidate_qualified": False,
            "decision_read_from_shadow": False,
        }
    return dict(result)
