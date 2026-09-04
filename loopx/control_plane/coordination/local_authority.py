"""Python adapter for provider-first local coordination reads.

TypeScript remains the semantic owner of canonical projection validation.  The
Python CLI only detects whether cutover is engaged, invokes that owner, and
fails closed instead of consulting the legacy Markdown projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..effect_runtime import effect_runtime_result
from .legacy_writer_fence import legacy_coordination_writer_fence_path


LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA = (
    "loopx_local_coordination_todo_list_request_v0"
)
LOCAL_COORDINATION_TODO_LIST_METHOD = "coordination.local_authority.todo_list"


class LocalCoordinationAuthorityUnavailable(RuntimeError):
    """Canonical coordination state cannot safely answer a post-cutover read."""

    def __init__(self, message: str, *, code: str, payload: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.payload = dict(payload)


def read_canonical_todos_if_promoted(
    *, runtime_root: Path, goal_id: str
) -> dict[str, Any] | None:
    """Return canonical Todos after cutover, or ``None`` before cutover.

    Presence of the durable writer fence is the mode switch. Once present,
    every malformed, missing, or unavailable provider response is terminal for
    this read; callers must never recover by reading Markdown.
    """

    fence_path = legacy_coordination_writer_fence_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    try:
        fence_path.stat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise LocalCoordinationAuthorityUnavailable(
            "local coordination authority mode cannot be inspected",
            code="local_authority_mode_read_failed",
            payload={"source_authority": "unknown_fail_closed"},
        ) from exc

    result = effect_runtime_result(
        LOCAL_COORDINATION_TODO_LIST_METHOD,
        {
            "schema_version": LOCAL_COORDINATION_TODO_LIST_REQUEST_SCHEMA,
            "runtime_root": str(runtime_root.expanduser().resolve(strict=False)),
            "goal_id": goal_id,
        },
    )
    if not isinstance(result, Mapping):
        raise LocalCoordinationAuthorityUnavailable(
            "local coordination authority returned an invalid Todo list",
            code="local_authority_todo_list_invalid_result",
            payload={"source_authority": "file_v0"},
        )
    payload = dict(result)
    todos = payload.get("todos")
    todo_read_model = payload.get("todo_read_model")
    if (
        payload.get("status") != "loaded"
        or payload.get("source_authority") != "file_v0"
        or payload.get("decision_read_from_provider") is not True
        or payload.get("legacy_fallback_used") is not False
        or not isinstance(todos, list)
        or any(not isinstance(item, Mapping) for item in todos)
        or not isinstance(todo_read_model, Mapping)
        or todo_read_model.get("schema_version")
        != "loopx_todo_canonical_read_record_v0"
        or todo_read_model.get("todo_count") != len(todos)
    ):
        raise LocalCoordinationAuthorityUnavailable(
            str(payload.get("reason") or "canonical Todo authority is unavailable"),
            code=str(payload.get("reason_code") or "local_authority_todo_list_unavailable"),
            payload=payload,
        )
    payload["todos"] = [dict(item) for item in todos]
    return payload


def canonical_todo_summary_fields(
    todos: list[dict[str, Any]],
    *,
    rollout_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Adapt canonical records into the existing Todo summary read model."""

    from ..todos.active_state_editing import TODO_SECTION_HEADINGS
    from ..todos.todo_summary import compact_todo_group

    fields: dict[str, Any] = {}
    for role in ("user", "agent"):
        items = [
            item
            for item in todos
            if ("user" if item.get("role") == "user" else "agent") == role
        ]
        summary = compact_todo_group(
            items,
            source_section=TODO_SECTION_HEADINGS[role],
            role=role,
            resume_source_items=todos,
            rollout_events=rollout_events,
            item_limit=None,
        )
        if summary:
            fields[f"{role}_todos"] = summary
    return fields
