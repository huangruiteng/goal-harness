from __future__ import annotations

from loopx.control_plane.quota.selected_todo_projection import (
    selected_todo_projection,
)


def test_selected_todo_preserves_capability_binding_ref() -> None:
    selected = selected_todo_projection(
        agent_lane_next_action={
            "source": "agent_lane_next_action",
            "todo_id": "todo_binding001",
            "text": "Advance the admitted issue fix.",
            "task_class": "advancement_task",
            "action_kind": "issue_fix_branch_validation",
            "target_key": "issue-fix:owner/repo:issue_42",
            "capability_binding_ref": "issue-fix:feasibility-a1b2c3d4",
        },
        work_lane_contract=None,
    )

    assert selected is not None
    assert selected["capability_binding_ref"] == (
        "issue-fix:feasibility-a1b2c3d4"
    )
