from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from .external_wait_contract import TodoExternalWaitAuthoringError

TODO_RESUME_NORMALIZE_REQUEST_SCHEMA_VERSION = "todo_resume_normalize_request_v0"
TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION = "todo_resume_evaluation_request_v0"
TODO_RESUME_EVALUATION_SCHEMA_VERSION = "todo_resume_evaluation_v0"
TODO_EXTERNAL_WAIT_REQUEST_SCHEMA_VERSION = "todo_external_wait_request_v0"
TODO_EXTERNAL_WAIT_TRANSITION_SCHEMA_VERSION = "todo_external_wait_transition_v0"

TODO_RESUME_KIND_TODO_DONE = "todo_done"
TODO_RESUME_KIND_PR_MERGED = "pr_merged"
TODO_RESUME_KIND_CAPACITY_AVAILABLE = "capacity_available"
TODO_RESUME_KIND_MONITOR_CHANGED = "monitor_changed"
TODO_RESUME_KIND_VALUES = {
    TODO_RESUME_KIND_TODO_DONE,
    TODO_RESUME_KIND_PR_MERGED,
    TODO_RESUME_KIND_CAPACITY_AVAILABLE,
    TODO_RESUME_KIND_MONITOR_CHANGED,
}

_TODO_ID_PATTERN = re.compile(r"^todo_[a-z0-9_-]{3,64}$")
_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9_:-]{0,63}$")
_RESUME_WHEN_PATTERN = re.compile(
    r"^[a-z][a-z0-9_-]{0,31}(?::[a-z0-9_.:@-]{1,96})?$"
)
_RESUME_PR_MERGED_PATTERN = re.compile(
    r"^pr_merged:(?:[a-z\d_.-]{1,80}/[a-z\d_.-]{1,100})?#[1-9]\d{0,8}$"
)

_RESUME_ITEM_FIELDS = (
    "todo_id",
    "role",
    "status",
    "task_class",
    "archive_state",
    "source_section",
    "claimed_by",
    "task_repository",
    "resume_when",
    "resume_ready",
    "resume_monitor_generation",
    "material_change_generation",
)

# The TypeScript reducer remains authoritative for event-kind and merge
# matching.  Its transport adapter only retains fields that can contribute a
# PR reference; an event without one cannot affect that reducer.  Keeping this
# projection bounded prevents unrelated long-running Goal history from making a
# small resume-condition request exceed the managed Effect runtime request limit.
_PR_EVENT_FIELDS = ("event_id", "event_kind", "pr_ref", "recorded_at")


def normalize_todo_generation(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def normalize_todo_resume_when(value: Any) -> str | None:
    """Read a persisted public-safe resume token without starting the runtime."""

    candidate = " ".join(str(value or "").strip().split()).lower()
    if candidate and _RESUME_PR_MERGED_PATTERN.match(candidate):
        return candidate
    if candidate and _RESUME_WHEN_PATTERN.match(candidate):
        return candidate
    return None


def normalize_supported_todo_resume_when(value: Any) -> str | None:
    """Read only resume kinds whose evaluator is shipped by LoopX."""

    candidate = normalize_todo_resume_when(value)
    if not candidate:
        return None
    kind, separator, target = candidate.partition(":")
    if kind in {TODO_RESUME_KIND_TODO_DONE, TODO_RESUME_KIND_MONITOR_CHANGED}:
        return candidate if separator and _TODO_ID_PATTERN.match(target) else None
    if kind == TODO_RESUME_KIND_PR_MERGED:
        return candidate if _RESUME_PR_MERGED_PATTERN.match(candidate) else None
    if kind == TODO_RESUME_KIND_CAPACITY_AVAILABLE:
        return candidate if separator and _CAPABILITY_PATTERN.match(target) else None
    return None


def require_supported_todo_resume_when(value: Any) -> str | None:
    """Validate new authoring through the TypeScript Todo-domain contract."""

    if value is None or not str(value).strip():
        return None
    normalized = normalize_todo_resume_when_via_runtime(value)
    if normalized:
        return normalized
    raise ValueError(
        "resume_when must use a supported condition: todo_done:<todo_id>, "
        "monitor_changed:<monitor_todo_id>, pr_merged:[owner/repo]#<number>, "
        "or capacity_available:<capability>"
    )


def _compact_item(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field: value[field]
        for field in _RESUME_ITEM_FIELDS
        if value.get(field) is not None
    }


def _compact_pr_rollout_events(
    values: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for value in values or []:
        if not isinstance(value, Mapping):
            continue
        event = {
            field: value[field]
            for field in _PR_EVENT_FIELDS
            if value.get(field) is not None
        }
        code_refs = value.get("code_refs")
        if isinstance(code_refs, Mapping) and code_refs.get("pr_ref") is not None:
            event["code_refs"] = {"pr_ref": code_refs["pr_ref"]}
        source_refs = value.get("source_refs")
        if isinstance(source_refs, list):
            compact_refs = [
                {
                    field: ref[field]
                    for field in ("kind", "ref")
                    if ref.get(field) is not None
                }
                for ref in source_refs
                if isinstance(ref, Mapping)
            ]
            compact_refs = [ref for ref in compact_refs if ref]
            if compact_refs:
                event["source_refs"] = compact_refs
        if any(field in event for field in ("pr_ref", "code_refs", "source_refs")):
            compact.append(event)
    return compact


def normalize_todo_resume_when_via_runtime(value: Any) -> str | None:
    """Normalize new resume authoring through the Todo-domain TS contract."""

    try:
        result = effect_runtime_result(
            "todo.resume_condition.normalize",
            {
                "schema_version": TODO_RESUME_NORMALIZE_REQUEST_SCHEMA_VERSION,
                "resume_when": value,
            },
        )
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if result is None:
        return None
    if not isinstance(result, str):
        raise RuntimeError("TypeScript Todo resume normalization shape mismatch")
    return result


def evaluate_todo_resume_conditions(
    items: list[dict[str, Any]],
    *,
    source_items: list[dict[str, Any]],
    rollout_events: list[dict[str, Any]] | None = None,
    available_capabilities: Any = None,
    kinds: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return TS-owned resume conditions keyed by the waiting Todo id."""

    request: dict[str, Any] = {
        "schema_version": TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION,
        "items": [_compact_item(item) for item in items if item.get("todo_id")],
        "source_items": [
            _compact_item(item) for item in source_items if item.get("todo_id")
        ],
        "rollout_events": _compact_pr_rollout_events(rollout_events),
    }
    if available_capabilities is not None:
        request["available_capabilities"] = sorted(
            {
                str(item).strip().lower()
                for item in available_capabilities
                if str(item).strip()
            }
        )
    if kinds is not None:
        request["kinds"] = kinds
    try:
        result = effect_runtime_result("todo.resume_condition.evaluate", request)
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, Mapping) or (
        result.get("schema_version") != TODO_RESUME_EVALUATION_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript Todo resume evaluation shape mismatch")
    conditions: dict[str, dict[str, Any]] = {}
    for row in result.get("conditions", []):
        if not isinstance(row, Mapping) or not isinstance(row.get("condition"), Mapping):
            continue
        todo_id = str(row.get("todo_id") or "").strip()
        if todo_id:
            conditions[todo_id] = dict(row["condition"])
    return conditions


def plan_todo_external_wait_transition(
    *,
    todo_id: str,
    resume_when: str,
    successor_todo_ids: list[str],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate and plan one atomic open-Todo external-wait transition in TS."""

    try:
        result = effect_runtime_result(
            "todo.external_wait.plan",
            {
                "schema_version": TODO_EXTERNAL_WAIT_REQUEST_SCHEMA_VERSION,
                "todo_id": todo_id,
                "resume_when": resume_when,
                "successor_todo_ids": successor_todo_ids,
                "items": [
                    _compact_item(item) for item in items if item.get("todo_id")
                ],
            },
        )
    except EffectRuntimeRejected as exc:
        resume_kind, _, target_todo_id = resume_when.partition(":")
        raise TodoExternalWaitAuthoringError(
            str(exc),
            code=exc.diagnostic_code,
            monitor_todo_id=(
                target_todo_id if resume_kind == TODO_RESUME_KIND_MONITOR_CHANGED else None
            ),
            successor_todo_ids=successor_todo_ids,
        ) from None
    if not isinstance(result, Mapping) or (
        result.get("schema_version") != TODO_EXTERNAL_WAIT_TRANSITION_SCHEMA_VERSION
    ):
        raise RuntimeError("TypeScript Todo external-wait transition shape mismatch")
    return dict(result)
