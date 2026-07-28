from __future__ import annotations

from typing import Any


QUOTA_CLI_TODO_SUMMARY_COMPACTION_SCHEMA_VERSION = (
    "quota_cli_todo_summary_compaction_v0"
)
QUOTA_CLI_TODO_SUMMARY_DETAIL_COMMAND = (
    "quota should-run --include-detail agent-todos"
)
QUOTA_CLI_USER_TODO_SUMMARY_COMPACTION_SCHEMA_VERSION = (
    "quota_cli_user_todo_summary_compaction_v0"
)
QUOTA_CLI_USER_TODO_SUMMARY_DETAIL_COMMAND = (
    "quota should-run --include-detail user-todos"
)
QUOTA_CLI_GOAL_BOUNDARY_COMPACTION_SCHEMA_VERSION = (
    "quota_cli_goal_boundary_compaction_v0"
)
QUOTA_CLI_GOAL_BOUNDARY_DETAIL_COMMAND = (
    "quota should-run --include-detail goal-boundary"
)
_RETAINED_AGENT_ITEM_LANES = {
    "first_executable_items": 3,
    "unclaimed_priority_open_items": 3,
    "monitor_due_items": 1,
    "monitor_capability_blocked_due_items": 2,
    "monitor_schedule_gap_items": 1,
    "current_agent_blocker_items": 2,
}
_RETAINED_USER_ITEM_LANES = {
    "first_open_items": 3,
    "gate_open_items": 3,
    "active_next_action_items": 3,
}
_RETAINED_AGENT_ITEM_FIELDS = (
    "schema_version",
    "todo_id",
    "index",
    "text",
    "status",
    "priority",
    "task_class",
    "action_kind",
    "claimed_by",
    "bound_agent",
    "goal_bound",
    "blocks_agent",
    "global_gate",
    "task_repository",
    "required_capabilities",
    "required_write_scopes",
    "excluded_agents",
    "unblocks_todo_id",
    "continuation_policy",
    "resume_when",
    "target_key",
    "cadence",
    "next_due_at",
    "expires_at",
    "last_checked_at",
    "consecutive_no_change",
    "material_change",
    "result_hash",
    "reason",
)
_RETAINED_SUCCESSION_WARNING_TODO_IDS = 3


def _compact_agent_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    return {
        key: item[key]
        for key in _RETAINED_AGENT_ITEM_FIELDS
        if key in item
    }


def _compact_nested_item_lists(
    value: dict[str, Any],
    *,
    omitted_lanes: dict[str, int],
    path: str,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, child in value.items():
        if isinstance(child, list) and key.endswith("items"):
            if path == "todo_succession_warning":
                todo_ids = [
                    str(item.get("todo_id"))
                    for item in child
                    if isinstance(item, dict) and item.get("todo_id")
                ][:_RETAINED_SUCCESSION_WARNING_TODO_IDS]
                if todo_ids:
                    compact["todo_ids"] = todo_ids
            if child:
                omitted_lanes[f"{path}.{key}"] = len(child)
            continue
        compact[key] = child
    return compact


def _compact_agent_todo_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    omitted_lanes: dict[str, int] = {}
    for key, value in summary.items():
        if isinstance(value, list):
            limit = _RETAINED_AGENT_ITEM_LANES.get(key)
            if limit is None:
                if value:
                    omitted_lanes[key] = len(value)
                continue
            compact[key] = [
                _compact_agent_item(item)
                for item in value[:limit]
            ]
            if len(value) > limit:
                omitted_lanes[key] = len(value) - limit
            continue
        if isinstance(value, dict):
            compact[key] = _compact_nested_item_lists(
                value,
                omitted_lanes=omitted_lanes,
                path=key,
            )
            continue
        compact[key] = value

    compact["payload_compaction"] = {
        "schema_version": QUOTA_CLI_TODO_SUMMARY_COMPACTION_SCHEMA_VERSION,
        "retained_item_lanes": sorted(
            lane
            for lane in _RETAINED_AGENT_ITEM_LANES
            if lane != "current_agent_blocker_items" or summary.get(lane)
        ),
        "omitted_lanes": omitted_lanes,
        "full_detail_cold_path": QUOTA_CLI_TODO_SUMMARY_DETAIL_COMMAND,
    }
    return compact


def _compact_user_todo_summary(summary: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    omitted_lanes: dict[str, int] = {}
    for key, value in summary.items():
        if isinstance(value, list):
            limit = _RETAINED_USER_ITEM_LANES.get(key)
            if limit is None:
                if value:
                    omitted_lanes[key] = len(value)
                continue
            compact[key] = value[:limit]
            if len(value) > limit:
                omitted_lanes[key] = len(value) - limit
            continue
        if isinstance(value, dict):
            compact[key] = _compact_nested_item_lists(
                value,
                omitted_lanes=omitted_lanes,
                path=key,
            )
            continue
        compact[key] = value

    compact["payload_compaction"] = {
        "schema_version": QUOTA_CLI_USER_TODO_SUMMARY_COMPACTION_SCHEMA_VERSION,
        "retained_item_lanes": sorted(_RETAINED_USER_ITEM_LANES),
        "omitted_lanes": omitted_lanes,
        "full_detail_cold_path": QUOTA_CLI_USER_TODO_SUMMARY_DETAIL_COMMAND,
    }
    return compact


def _compact_goal_boundary(boundary: dict[str, Any]) -> dict[str, Any]:
    authority = boundary.get("checkpointed_boundary_authority")
    if not isinstance(authority, dict) or not isinstance(
        authority.get("entries"),
        list,
    ):
        return boundary

    compact_authority = dict(authority)
    entries = compact_authority.pop("entries")
    compact_authority["payload_compaction"] = {
        "schema_version": QUOTA_CLI_GOAL_BOUNDARY_COMPACTION_SCHEMA_VERSION,
        "omitted_entry_count": len(entries),
        "full_detail_cold_path": QUOTA_CLI_GOAL_BOUNDARY_DETAIL_COMMAND,
    }
    compact = dict(boundary)
    compact["checkpointed_boundary_authority"] = compact_authority
    return compact


def compact_quota_should_run_cli_payload(
    payload: dict[str, Any],
    *,
    include_todo_summary_detail: bool = False,
    include_user_todo_summary_detail: bool = False,
    include_goal_boundary_detail: bool = False,
) -> dict[str, Any]:
    """Bound CLI-only diagnostics after the full decision is computed."""

    compact = payload
    compacted_roles: list[str] = []
    summary = payload.get("agent_todo_summary")
    if not include_todo_summary_detail and isinstance(summary, dict):
        compact = dict(compact)
        compact["agent_todo_summary"] = _compact_agent_todo_summary(summary)
        compacted_roles.append("agent")

    user_summary = payload.get("user_todo_summary")
    if not include_user_todo_summary_detail and isinstance(user_summary, dict):
        compact = dict(compact)
        compact["user_todo_summary"] = _compact_user_todo_summary(user_summary)
        compacted_roles.append("user")

    if compacted_roles:
        compact["todo_summary_projection"] = {
            "schema_version": QUOTA_CLI_TODO_SUMMARY_COMPACTION_SCHEMA_VERSION,
            "mode": "compact_hot_path",
            "compacted_roles": compacted_roles,
            "detail_ref": (
                QUOTA_CLI_TODO_SUMMARY_DETAIL_COMMAND
                if compacted_roles[0] == "agent"
                else QUOTA_CLI_USER_TODO_SUMMARY_DETAIL_COMMAND
            ),
        }
    goal_boundary = payload.get("goal_boundary")
    if not include_goal_boundary_detail and isinstance(goal_boundary, dict):
        compact_goal_boundary = _compact_goal_boundary(goal_boundary)
        if compact_goal_boundary is not goal_boundary:
            compact = dict(compact)
            compact["goal_boundary"] = compact_goal_boundary
    return compact
