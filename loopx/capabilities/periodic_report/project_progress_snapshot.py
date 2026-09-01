from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ...control_plane.todos.active_state_todo_parser import parse_active_state_todos
from ...registry import find_registry_goal, read_json, resolve_state_file


_META_ACTION_KINDS = frozenset(
    {
        "consume_periodic_report_intent",
        "repair_periodic_report_intent_consumption",
        "repair_periodic_report_editorial",
    }
)


def build_project_progress_snapshot(
    *, registry_path: Path, goal_id: str, agent_id: str, completed_at: str
) -> dict[str, Any] | None:
    """Build a bounded public-safe progress snapshot at a stage boundary."""

    registry = read_json(registry_path)
    goal = find_registry_goal(registry, goal_id)
    if not isinstance(goal, Mapping):
        raise ValueError("periodic-report Goal is not registered")
    repo = Path(str(goal.get("repo") or "")).expanduser()
    state_path = resolve_state_file(repo, str(goal.get("state_file") or ""))
    if state_path is None or not state_path.is_file():
        raise ValueError("periodic-report active state is unavailable")
    return build_project_progress_snapshot_from_state(
        state_text=state_path.read_text(encoding="utf-8"),
        goal=dict(goal),
        state_path=state_path,
        goal_id=goal_id,
        agent_id=agent_id,
        completed_at=completed_at,
    )


def build_project_progress_snapshot_from_state(
    *,
    state_text: str,
    goal: Mapping[str, Any],
    state_path: Path,
    goal_id: str,
    agent_id: str,
    completed_at: str,
) -> dict[str, Any] | None:
    """Build a progress snapshot from one already-read authoritative state."""

    parsed = parse_active_state_todos(
        state_text,
        goal=dict(goal),
        state_path=state_path,
        item_limit=None,
    )
    agent_summary = parsed.get("agent_todos")
    items = agent_summary.get("items") if isinstance(agent_summary, Mapping) else []
    stage_time = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))

    def not_after_stage(item: Mapping[str, Any]) -> bool:
        raw = str(item.get("updated_at") or item.get("completed_at") or "").strip()
        if not raw:
            return True
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")) <= stage_time
        except ValueError:
            return False

    done = [
        dict(item)
        for item in items or []
        if isinstance(item, Mapping)
        and item.get("status") == "done"
        and str(item.get("claimed_by") or "") == agent_id
        and not_after_stage(item)
        and str(item.get("action_kind") or "") not in _META_ACTION_KINDS
    ]
    done.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    progress_items: list[dict[str, Any]] = []
    for index, item in enumerate(done[:6]):
        summary = " ".join(
            str(
                item.get("evidence") or item.get("note") or item.get("text") or ""
            ).split()
        )
        title = " ".join(str(item.get("text") or "Completed project work").split())
        progress_items.append(
            {
                "item_id": f"completed_{index + 1}",
                "title": title[:240],
                "summary": summary[:360] or "Validated completion is durably recorded.",
                "content_kind": "outcome",
                "value_rank": 10 + index,
                "source_ref": f"todo:{item.get('todo_id')}",
                "completed_at": str(
                    item.get("completed_at") or item.get("updated_at") or ""
                ),
            }
        )
    open_items = [
        dict(item)
        for item in items or []
        if isinstance(item, Mapping)
        and item.get("status") == "open"
        and str(item.get("claimed_by") or "") == agent_id
        and not_after_stage(item)
        and item.get("task_class") != "continuous_monitor"
        and item.get("action_kind")
        not in {
            "consume_periodic_report_intent",
            "repair_periodic_report_intent_consumption",
        }
    ]
    if open_items:
        next_item = open_items[0]
        progress_items.append(
            {
                "item_id": "next_action",
                "title": "Next action",
                "summary": " ".join(str(next_item.get("text") or "").split())[:360],
                "content_kind": "next_action",
                "value_rank": 90,
                "source_ref": f"todo:{next_item.get('todo_id')}",
            }
        )
    if not progress_items:
        return None
    return {
        "schema_version": "periodic_report_project_progress_projection_v0",
        "goal_id": goal_id,
        "observed_at": completed_at,
        "language": "zh-CN",
        "items": progress_items,
    }


__all__ = [
    "build_project_progress_snapshot",
    "build_project_progress_snapshot_from_state",
]
