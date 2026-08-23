from __future__ import annotations

from typing import Any

import pytest

from loopx.control_plane.quota.should_run import build_quota_should_run
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
)

GOAL_ID = "boundary-selection-fixture"
AGENT_ID = "codex-main"


def test_workspace_and_boundary_guards_check_the_selected_todo_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    research = quota_todo_item(
        todo_id="todo_research001",
        index=1,
        priority="P1",
        title="Research the current provider contract.",
        claimed_by=AGENT_ID,
        required_capabilities=["network"],
    )
    later_implementation = quota_todo_item(
        todo_id="todo_implementation001",
        index=2,
        priority="P1",
        title="Implement the later capability adapter.",
        claimed_by=AGENT_ID,
        required_write_scopes=["skills/**"],
    )
    status = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[research, later_implementation],
        recommended_action=research["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID],
            "write_scope": ["docs/**"],
        },
        claim_scope_agent_id=AGENT_ID,
    )
    workspace_guard_selected_todo: dict[str, Any] = {}

    def _record_workspace_guard_selection(
        *args: object,
        selected_todo: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> dict[str, Any] | None:
        workspace_guard_selected_todo.update(selected_todo or {})
        if (selected_todo or {}).get("required_write_scopes"):
            return {
                "schema_version": "agent_workspace_guard_v1",
                "reason": "selected writing todo requires an independent worktree",
                "required_action": "move to the assigned worktree",
            }
        return None

    monkeypatch.setattr(
        "loopx.control_plane.quota.should_run.build_agent_workspace_guard",
        _record_workspace_guard_selection,
    )

    packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        available_capabilities=["network"],
    )

    assert packet["selected_todo"]["todo_id"] == research["todo_id"]
    assert workspace_guard_selected_todo["todo_id"] == research["todo_id"]
    assert packet["effective_action"] == "normal_run"
    assert packet["normal_delivery_allowed"] is True
    assert packet["self_repair_allowed"] is False
    assert "workspace_guard" not in packet
    assert "boundary_projection_gap" not in packet


def test_boundary_projection_preserves_a_guarded_continuation_selection() -> None:
    queue_head = quota_todo_item(
        todo_id="todo_research001",
        index=1,
        priority="P1",
        title="Research the next provider contract.",
        claimed_by=AGENT_ID,
    )
    in_flight = quota_todo_item(
        todo_id="todo_implementation001",
        index=2,
        priority="P1",
        title="Continue the in-flight capability adapter.",
        claimed_by=AGENT_ID,
        required_write_scopes=["skills/**"],
    )
    status = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[queue_head, in_flight],
        recommended_action=queue_head["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID],
            "write_scope": ["docs/**"],
        },
        claim_scope_agent_id=AGENT_ID,
        latest_runs=[
            {
                "generated_at": "2026-08-23T00:00:00Z",
                "classification": "bounded_implementation_progress",
                "progress_scope": "agent_lane",
                "agent_id": AGENT_ID,
                "todo_id": in_flight["todo_id"],
                "delivery_outcome": "outcome_progress",
                "recommended_action": in_flight["text"],
            }
        ],
    )

    packet = build_quota_should_run(
        status,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert packet["selected_todo"]["todo_id"] == in_flight["todo_id"]
    assert packet["agent_lane_next_action"]["selected_by"] == "in_flight_todo"
    assert packet["effective_action"] == "boundary_projection_repair"
    assert packet["normal_delivery_allowed"] is False
    assert packet["self_repair_allowed"] is True
    assert (
        packet["boundary_projection_gap"]["selected_todo"]["todo_id"]
        == (in_flight["todo_id"])
    )
    assert packet["boundary_projection_gap"]["missing_write_scopes"] == ["skills/**"]
