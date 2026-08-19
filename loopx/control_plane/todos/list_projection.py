from __future__ import annotations

from typing import Any, Literal

AGENT_LANE_TODO_LIST_PROJECTION_SCHEMA_VERSION = "agent_lane_todo_list_projection_v0"
AGENT_LANE_TODO_LIST_SUMMARY_SCHEMA_VERSION = (
    "agent_lane_todo_list_summary_compaction_v0"
)
EXPLICIT_LIMIT_TODO_LIST_SUMMARY_SCHEMA_VERSION = (
    "explicit_limit_todo_list_summary_compaction_v0"
)
AGENT_LANE_TODO_LIST_ITEM_LIMIT = 12
AGENT_LANE_TODO_LIST_TEXT_LIMIT = 180
AGENT_LANE_HOT_PATH_VIEW: Literal["agent_lane_hot_path"] = "agent_lane_hot_path"
EXPLICIT_LIMIT_COLD_PATH_VIEW: Literal["explicit_limit_cold_path"] = (
    "explicit_limit_cold_path"
)
TodoListProjectionView = Literal[
    "agent_lane_hot_path",
    "explicit_limit_cold_path",
]

_RETAINED_LANE_LIMITS = {
    "items": AGENT_LANE_TODO_LIST_ITEM_LIMIT,
    "first_open_items": 3,
    "first_executable_items": 3,
    "deferred_items": 3,
    "monitor_due_items": 2,
    "monitor_schedule_gap_items": 2,
    "blocker_items": 2,
    "resume_blocked_items": 2,
    "active_next_action_items": 3,
    "active_next_action_executable_items": 3,
}
_RETAINED_DICTS = {
    "monitor_writeback",
    "source_proof",
    "terminal_closure_proof",
}
_ITEM_FIELDS = (
    "schema_version",
    "index",
    "todo_id",
    "role",
    "status",
    "priority",
    "text",
    "title",
    "note",
    "task_class",
    "action_kind",
    "task_domain",
    "capability_binding_ref",
    "task_repository",
    "continuation_policy",
    "required_capabilities",
    "target_capabilities",
    "claimed_by",
    "bound_agent",
    "goal_bound",
    "blocks_agent",
    "global_gate",
    "unblocks_todo_id",
    "successor_todo_ids",
    "completion_continuation",
    "completion_recovery",
    "resume_when",
    "resume_ready",
    "target_key",
    "cadence",
    "next_due_at",
    "expires_at",
    "watch_only",
)


def _compact_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) <= AGENT_LANE_TODO_LIST_TEXT_LIMIT:
        return text
    return text[: AGENT_LANE_TODO_LIST_TEXT_LIMIT - 3].rstrip() + "..."


def _compact_item(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    compact: dict[str, Any] = {}
    for key in _ITEM_FIELDS:
        child = value.get(key)
        if child is None:
            continue
        compact[key] = (
            _compact_text(child) if key in {"text", "title", "note"} else child
        )
    return compact


def todo_item_relations(item: dict[str, Any]) -> dict[str, Any]:
    """Project the stable relationship fields for one todo list item."""

    relations: dict[str, Any] = {}
    for key in (
        "claimed_by",
        "bound_agent",
        "goal_bound",
        "blocks_agent",
        "excluded_agents",
        "global_gate",
        "unblocks_todo_id",
        "successor_todo_ids",
        "completion_continuation",
        "completion_recovery",
        "superseded_by",
        "resume_when",
        "resume_condition",
        "resume_ready",
        "decision_scope",
        "required_decision_scopes",
        "required_write_scopes",
        "required_capabilities",
        "target_capabilities",
        "task_class",
        "action_kind",
        "continuation_policy",
        "target_key",
        "cadence",
        "next_due_at",
        "expires_at",
    ):
        value = item.get(key)
        if value is not None and value != []:
            relations[key] = value
    return relations


def compact_agent_lane_todo_summary(
    summary: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    """Bound one agent-lane list summary while retaining actionable identities."""
    compact: dict[str, Any] = {}
    compacted_lanes: dict[str, dict[str, int]] = {}
    omitted_nonempty_lane_count = 0
    omitted_nonempty_dict_count = 0
    for key, value in summary.items():
        if isinstance(value, list):
            limit = _RETAINED_LANE_LIMITS.get(key)
            if limit is None:
                omitted_nonempty_lane_count += bool(value)
                continue
            if key == "items":
                retained = [
                    item
                    for item in value
                    if not isinstance(item, dict) or item.get("status") != "done"
                ]
            else:
                retained = value
            compact[key] = [_compact_item(item) for item in retained[:limit]]
            if len(retained) > limit:
                compacted_lanes[key] = {"shown": limit, "total": len(retained)}
            continue
        if isinstance(value, dict):
            if key in _RETAINED_DICTS:
                compact[key] = value
            else:
                omitted_nonempty_dict_count += bool(value)
            continue
        compact[key] = value
    compact["payload_compaction"] = {
        "schema_version": AGENT_LANE_TODO_LIST_SUMMARY_SCHEMA_VERSION,
        "role": role,
        "item_limit": AGENT_LANE_TODO_LIST_ITEM_LIMIT,
        "item_text_limit": AGENT_LANE_TODO_LIST_TEXT_LIMIT,
        "terminal_items_in_hot_path": False,
        "compacted_lanes": compacted_lanes,
        "omitted_nonempty_lane_count": omitted_nonempty_lane_count,
        "omitted_nonempty_dict_count": omitted_nonempty_dict_count,
        "full_detail_cold_path": (
            "todo list with --role, --status, or --todo-id; "
            "todo list without --agent-id; or active state"
        ),
    }
    return compact


def compact_explicit_limit_todo_summary(
    summary: dict[str, Any],
    *,
    role: str,
    item_limit: int,
) -> dict[str, Any]:
    """Bound every item-bearing lane for the explicit-limit cold path."""
    compact: dict[str, Any] = {}
    compacted_lanes: dict[str, dict[str, int]] = {}
    omitted_nonempty_dict_count = 0
    for key, value in summary.items():
        if isinstance(value, list):
            compact[key] = [_compact_item(item) for item in value[:item_limit]]
            if len(value) > item_limit:
                compacted_lanes[key] = {
                    "shown": item_limit,
                    "total": len(value),
                }
            continue
        if isinstance(value, dict):
            if key in _RETAINED_DICTS:
                compact[key] = value
            else:
                omitted_nonempty_dict_count += bool(value)
            continue
        compact[key] = value
    compact["payload_compaction"] = {
        "schema_version": EXPLICIT_LIMIT_TODO_LIST_SUMMARY_SCHEMA_VERSION,
        "view": EXPLICIT_LIMIT_COLD_PATH_VIEW,
        "role": role,
        "item_limit": item_limit,
        "item_text_limit": AGENT_LANE_TODO_LIST_TEXT_LIMIT,
        "compacted_lanes": compacted_lanes,
        "omitted_nonempty_dict_count": omitted_nonempty_dict_count,
        "full_detail_cold_path": "todo list without --limit or active state",
    }
    return compact


AGENT_LANE_OVERLAY_FULL_DETAIL_COLD_PATH = (
    "todo list without --agent-id or active state"
)
EXPLICIT_LIMIT_OVERLAY_FULL_DETAIL_COLD_PATH = (
    "todo list without --limit or active state"
)


def compact_todo_projection_overlay(
    value: Any,
    *,
    full_detail_cold_path: str = AGENT_LANE_OVERLAY_FULL_DETAIL_COLD_PATH,
) -> Any:
    if not isinstance(value, dict):
        return value
    compact = {
        key: child for key, child in value.items() if not isinstance(child, list)
    }
    for key, child in value.items():
        if isinstance(child, list):
            compact[f"{key.removesuffix('_todo_ids')}_count"] = len(child)
    compact["full_detail_cold_path"] = full_detail_cold_path
    return compact


def todo_list_projection_contract(
    *,
    matched_todo_count: int,
    returned_todo_count: int,
    view: TodoListProjectionView = AGENT_LANE_HOT_PATH_VIEW,
    item_limit_per_role: int = AGENT_LANE_TODO_LIST_ITEM_LIMIT,
    full_detail_cold_paths: tuple[str, ...] = (
        "todo list with --role, --status, or --todo-id",
        "todo list without --agent-id",
        "active state",
    ),
) -> dict[str, Any]:
    return {
        "schema_version": AGENT_LANE_TODO_LIST_PROJECTION_SCHEMA_VERSION,
        "view": view,
        "matched_todo_count": matched_todo_count,
        "returned_todo_count": returned_todo_count,
        "item_limit_per_role": item_limit_per_role,
        "counts_cover_full_match": True,
        "full_detail_cold_paths": list(full_detail_cold_paths),
    }
