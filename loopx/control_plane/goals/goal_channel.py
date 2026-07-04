from __future__ import annotations

from typing import Any, Callable


GoalChannelProjectionBuilder = Callable[..., dict[str, Any]]


def attach_goal_channel_projection(
    item: dict[str, Any],
    *,
    goal: dict[str, Any],
    goal_latest_runs: list[dict[str, Any]],
    build_goal_channel_projection: GoalChannelProjectionBuilder,
) -> None:
    """Attach a read-only frontstage projection to a status attention item."""

    run_history_goal = dict(goal)
    run_history_goal["latest_runs"] = goal_latest_runs
    quota_payload: dict[str, Any] = {
        "status": item.get("status"),
        "waiting_on": item.get("waiting_on"),
        "recommended_action": item.get("recommended_action"),
    }
    if isinstance(item.get("quota"), dict):
        quota_payload["quota"] = item["quota"]
    item["goal_channel_projection"] = build_goal_channel_projection(
        goal_id=str(item.get("goal_id") or goal.get("id") or ""),
        status_item=item,
        quota_payload=quota_payload,
        run_history_goal=run_history_goal,
    )
