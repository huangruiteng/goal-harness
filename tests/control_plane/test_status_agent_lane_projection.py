from __future__ import annotations

import json

from loopx.control_plane.status.agent_lane_projection import (
    compact_agent_lane_status_payload_for_display,
)
from loopx.control_plane.todos.quota_summary import (
    compact_agent_lane_todos_for_status_display,
)

AGENT_ID = "codex-quality"
GOAL_ID = "status-budget-goal"


def _todo(index: int, *, role: str, task_class: str = "advancement_task") -> dict:
    reason = "measured simplification evidence " * 24
    return {
        "schema_version": "todo_item_v0",
        "index": index,
        "todo_id": f"todo_{role}_{index:03d}",
        "text": f"[P1] {role} action {index}: {reason}",
        "status": "open",
        "priority": "P1",
        "task_class": task_class,
        "action_kind": "production_shaped_status_budget_fixture",
        "claimed_by": AGENT_ID if role == "agent" else None,
        "blocks_agent": AGENT_ID if task_class == "user_gate" else None,
        "required_capabilities": ["network", "filesystem_write"],
        "reason": reason,
    }


def _todo_summary(items: list[dict], *, role: str) -> dict:
    user_gate = items[0] if role == "user" else None
    return {
        "schema_version": "todo_summary_v0",
        "source_section": f"{role.title()} Todo",
        "total_count": len(items) + 80,
        "open_count": len(items),
        "done_count": 60,
        "deferred_count": 20,
        "claimed_open_count": len(items) if role == "agent" else 0,
        "unclaimed_open_count": 0 if role == "agent" else len(items),
        "items": items,
        "first_open_items": items,
        "first_executable_items": items,
        "backlog_items": items,
        "executable_backlog_items": items,
        "deferred_items": items,
        "claimed_open_items": items,
        "claimed_advancement_open_items": items,
        "monitor_open_items": items,
        "monitor_due_items": items,
        "active_next_action_items": items,
        "gate_open_items": [user_gate] if user_gate else [],
        "user_action_items": items if role == "user" else [],
    }


def _project_asset_todo_summary(items: list[dict]) -> dict:
    return {
        "schema_version": "todo_summary_v0",
        "source_section": "project_asset",
        "open": len(items),
        "done": 60,
        "total": len(items) + 80,
        "items": items,
        "next": items[0]["text"],
        "next_index": items[0]["index"],
        "next_claimed_by": items[0].get("claimed_by"),
        "deferred_items": items,
        "first_executable_items": items,
        "projection_view": {"kind": "bounded"},
        "detail_pointer": {"command": "loopx todo list"},
    }


def test_agent_lane_status_bounds_production_shaped_duplicate_projection() -> None:
    reason = "measured simplification evidence " * 24
    agent_items = [_todo(index, role="agent") for index in range(120)]
    user_items = [
        _todo(1, role="user", task_class="user_gate"),
        *[_todo(index, role="user") for index in range(2, 42)],
    ]
    frontier = {
        "schema_version": "goal_frontier_projection_v0",
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "replan_required": True,
        "remaining_advancement_frontier": {
            "current_agent_claimed_advancement_count": 1,
            "unclaimed_advancement_count": 0,
        },
        "acceptance_gaps": [
            {
                "kind": "acceptance_gap",
                "state": "open",
                "agent_id": AGENT_ID,
                "acceptance_summary": reason,
                "replan_trigger_summary": reason,
            }
        ],
        "vision_continuation_audit": {
            "schema_version": "vision_continuation_audit_v0",
            "agent_id": AGENT_ID,
            "required": True,
            "decision": "acceptance_gap_open",
            "trigger_count": 1,
            "required_before_closeout": [reason] * 12,
            "vision_gap_judge": {
                "schema_version": "vision_gap_judge_v0",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "done": False,
                "decision": "continue",
                "reason": reason,
                "agent_judge_instruction": reason * 8,
            },
        },
    }
    interaction = {
        "agent_id": AGENT_ID,
        "mode": "bounded_delivery",
        "user_action_required": False,
        "agent_must_attempt": True,
    }
    item = {
        "goal_id": GOAL_ID,
        "status": "active_state_agent_todo",
        "waiting_on": "codex",
        "recommended_action": agent_items[0]["text"],
        "agent_todos": _todo_summary(agent_items, role="agent"),
        "user_todos": _todo_summary(user_items, role="user"),
        "goal_frontier_projection": frontier,
        "goal_channel_projection": {
            "schema_version": "goal_channel_projection_v0",
            "goal_id": GOAL_ID,
            "next_action": agent_items[0]["text"],
            "agent_todos": agent_items,
            "user_todos": user_items,
            "recent_events": [{"summary": reason}] * 40,
            "active_leases": [{"agent_id": AGENT_ID}] * 20,
            "source_warnings": [reason] * 20,
        },
        "agent_interaction_summary": interaction,
        "project_asset": {
            "owner": "codex",
            "next_action": agent_items[0]["text"],
            "agent_todos": _project_asset_todo_summary(agent_items),
            "user_todos": _project_asset_todo_summary(user_items),
            "goal_frontier_projection": frontier,
            "agent_interaction_summary": interaction,
        },
    }
    payload = {
        "attention_queue": {"items": [item]},
        "run_history": {
            "available": True,
            "run_count": 400,
            "goal_count": 1,
            "recent_runs": [
                {
                    "goal_id": GOAL_ID,
                    "agent_id": AGENT_ID if index % 2 == 0 else "codex-other",
                    "classification": "status_fixture",
                    "generated_at": f"2026-01-01T00:{index:02d}:00+00:00",
                    "recommended_action": reason,
                    "detail": reason * 4,
                }
                for index in range(20)
            ],
            "goals": [{"id": GOAL_ID, "latest_runs": [{"detail": reason}] * 20}],
        },
        "agent_management_projection": {
            "schema_version": "agent_management_projection_v0",
            "goal_id": GOAL_ID,
            "agents": [
                {
                    "agent_id": f"codex-{index}",
                    "current_todo": {"text": reason},
                    "evidence_refs": [reason] * 8,
                }
                for index in range(12)
            ]
            + [{"agent_id": AGENT_ID, "current_todo": agent_items[0]}],
        },
    }

    compact_agent_lane_todos_for_status_display(payload)
    compact_agent_lane_status_payload_for_display(payload, agent_id=AGENT_ID)

    compact_item = payload["attention_queue"]["items"][0]
    assert compact_item["agent_todos"]["items"][0]["todo_id"] == "todo_agent_000"
    assert compact_item["agent_todos"]["open_count"] == 120
    assert compact_item["user_todos"]["gate_open_items"][0]["blocks_agent"] == AGENT_ID
    assert (
        compact_item["project_asset"]["agent_todos"]["payload_reference"][
            "canonical_path"
        ]
        == "attention_queue.items[].agent_todos"
    )
    assert "goal_frontier_projection" not in compact_item
    compact_frontier = compact_item["project_asset"]["goal_frontier_projection"]
    assert compact_frontier["replan_required"] is True
    assert (
        compact_frontier["vision_continuation_audit"]["vision_gap_judge"]["decision"]
        == "continue"
    )
    assert (
        compact_item["project_asset"]["agent_interaction_summary"]["agent_must_attempt"]
        is True
    )
    assert payload["run_history"]["latest_agent_run"]["agent_id"] == AGENT_ID
    assert payload["agent_management_projection"]["agents"][0]["agent_id"] == AGENT_ID
    assert len(json.dumps(payload, ensure_ascii=False, indent=2)) < 30_000
