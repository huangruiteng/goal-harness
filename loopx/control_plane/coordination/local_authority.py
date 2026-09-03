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
    if (
        payload.get("status") != "loaded"
        or payload.get("source_authority") != "file_v0"
        or payload.get("decision_read_from_provider") is not True
        or payload.get("legacy_fallback_used") is not False
        or not isinstance(todos, list)
        or any(not isinstance(item, Mapping) for item in todos)
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


def todo_summary_items(fields: dict[str, Any], role: str) -> list[dict[str, Any]]:
    summary = fields.get(f"{role}_todos") if isinstance(fields, dict) else None
    if not isinstance(summary, dict):
        return []
    return [item for item in summary.get("items") or [] if isinstance(item, dict)]


def merge_legacy_todo_projection_fields(
    *, markdown_fields: dict[str, Any], event_fields: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve the pre-cutover event-over-Markdown compatibility projection."""

    from ..todos.active_state_editing import TODO_SECTION_HEADINGS
    from ..todos.contract import build_todo_id, normalize_todo_id
    from ..todos.todo_summary import compact_todo_group

    merged: dict[str, Any] = {}
    merged_items: dict[str, list[dict[str, Any]]] = {"user": [], "agent": []}
    overlay: dict[str, Any] = {
        "schema_version": "todo_list_projection_overlay_v0",
        "base": "markdown_active_state",
        "overlay": "event_projection",
    }
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    markdown_ids: set[str] = set()
    markdown_ids_by_role: dict[str, set[str]] = {"user": set(), "agent": set()}
    event_ids: set[str] = set()
    event_order: list[str] = []
    for role in ("user", "agent"):
        for item in todo_summary_items(markdown_fields, role):
            todo_id = normalize_todo_id(item.get("todo_id")) or build_todo_id(
                role=role,
                source_section=item.get("source_section"),
                index=item.get("index"),
                text=item.get("text"),
            )
            if todo_id not in by_id:
                order.append(todo_id)
            markdown_ids.add(todo_id)
            markdown_ids_by_role[role].add(todo_id)
            by_id[todo_id] = dict(item)
    for role in ("user", "agent"):
        for item in todo_summary_items(event_fields, role):
            todo_id = normalize_todo_id(item.get("todo_id")) or build_todo_id(
                role=role,
                source_section=item.get("source_section"),
                index=item.get("index"),
                text=item.get("text"),
            )
            if todo_id not in by_id:
                order.append(todo_id)
            if todo_id not in event_ids:
                event_order.append(todo_id)
                event_ids.add(todo_id)
            by_id[todo_id] = dict(item)
    overlay.update(
        markdown_only_todo_ids=[
            todo_id
            for role in ("user", "agent")
            for todo_id in sorted(markdown_ids_by_role[role] - event_ids)
        ],
        event_only_todo_ids=[todo_id for todo_id in event_order if todo_id not in markdown_ids],
        overlaid_todo_ids=[todo_id for todo_id in event_order if todo_id in markdown_ids],
    )
    for todo_id in order:
        item = by_id[todo_id]
        merged_items["user" if item.get("role") == "user" else "agent"].append(item)
    resume_items = [*merged_items["user"], *merged_items["agent"]]
    for role in ("user", "agent"):
        source_section = str(
            (markdown_fields.get(f"{role}_todos") or {}).get("source_section")
            or (event_fields.get(f"{role}_todos") or {}).get("source_section")
            or TODO_SECTION_HEADINGS[role]
        )
        summary = compact_todo_group(
            merged_items[role],
            source_section=source_section,
            role=role,
            resume_source_items=resume_items,
            item_limit=None,
        )
        if summary:
            merged[f"{role}_todos"] = summary
    return merged, overlay


def legacy_or_canonical_todo_fields(
    *,
    runtime_root: Path,
    goal_id: str,
    goal: dict[str, Any],
    state_file: Path,
    rollout_events: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    """Select the Todo authority and build its existing CLI read model."""

    from ...status import active_state_event_projection_fields
    from ..todos.active_state_todo_parser import parse_active_state_todos

    canonical = read_canonical_todos_if_promoted(
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    if canonical is not None:
        return (
            canonical_todo_summary_fields(
                canonical["todos"],
                rollout_events=rollout_events,
            ),
            "file_authority",
            {},
            None,
            canonical,
        )
    if not state_file.exists():
        raise ValueError(f"active state file does not exist: {state_file}")
    event_fields = active_state_event_projection_fields(
        goal,
        state_path=state_file,
        item_limit=None,
        rollout_events=rollout_events,
    )
    markdown_fields = parse_active_state_todos(
        state_file.read_text(encoding="utf-8"),
        goal=goal,
        state_path=state_file,
        item_limit=None,
        rollout_events=rollout_events,
    )
    event_has_todos = bool(event_fields.get("user_todos") or event_fields.get("agent_todos"))
    markdown_has_todos = bool(
        markdown_fields.get("user_todos") or markdown_fields.get("agent_todos")
    )
    if event_has_todos and markdown_has_todos:
        fields, overlay = merge_legacy_todo_projection_fields(
            markdown_fields=markdown_fields,
            event_fields=event_fields,
        )
        return fields, "event_projection_with_markdown_overlay", event_fields, overlay, None
    if event_has_todos:
        return event_fields, "event_projection", event_fields, None, None
    return markdown_fields, "markdown_active_state", event_fields, None, None
