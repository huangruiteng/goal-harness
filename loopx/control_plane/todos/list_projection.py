from __future__ import annotations

from typing import Any

AGENT_LANE_TODO_LIST_PROJECTION_SCHEMA_VERSION = "agent_lane_todo_list_projection_v0"
AGENT_LANE_TODO_LIST_SUMMARY_SCHEMA_VERSION = (
    "agent_lane_todo_list_summary_compaction_v0"
)
AGENT_LANE_TODO_LIST_ITEM_LIMIT = 12
AGENT_LANE_TODO_LIST_TEXT_LIMIT = 180

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
    "resume_when",
    "resume_ready",
    "target_key",
    "cadence",
    "next_due_at",
    "expires_at",
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


def compact_todo_projection_overlay(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    compact = {
        key: child for key, child in value.items() if not isinstance(child, list)
    }
    for key, child in value.items():
        if isinstance(child, list):
            compact[f"{key.removesuffix('_todo_ids')}_count"] = len(child)
    compact["full_detail_cold_path"] = "todo list without --agent-id or active state"
    return compact


def todo_list_projection_contract(
    *,
    matched_todo_count: int,
    returned_todo_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": AGENT_LANE_TODO_LIST_PROJECTION_SCHEMA_VERSION,
        "view": "agent_lane_hot_path",
        "matched_todo_count": matched_todo_count,
        "returned_todo_count": returned_todo_count,
        "item_limit_per_role": AGENT_LANE_TODO_LIST_ITEM_LIMIT,
        "counts_cover_full_match": True,
        "full_detail_cold_paths": [
            "todo list with --role, --status, or --todo-id",
            "todo list without --agent-id",
            "active state",
        ],
    }
