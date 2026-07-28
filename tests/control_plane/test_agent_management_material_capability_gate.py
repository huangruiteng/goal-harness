from __future__ import annotations

import pytest

from loopx.control_plane.agents.management_projection import (
    build_agent_management_projection,
)


GOAL_ID = "material-capability-fixture"
AGENT_ID = "agent-reviewer"


def _status_payload() -> dict[str, object]:
    return {
        "goal_filter": GOAL_ID,
        "run_history": {
            "goals": [
                {
                    "id": GOAL_ID,
                    "coordination": {"registered_agents": [AGENT_ID]},
                }
            ]
        },
        "todo_index": {
            "items": [
                {
                    "role": "agent",
                    "todo_id": "todo_material_review",
                    "goal_id": GOAL_ID,
                    "status": "open",
                    "task_class": "advancement_task",
                    "claimed_by": AGENT_ID,
                    "text": "Review the material-aware handoff.",
                    "handoff_note": {
                        "schema_version": "handoff_note_v0",
                        "handoff_id": "handoff_material_review",
                        "todo_id": "todo_material_review",
                        "goal_id": GOAL_ID,
                        "from_agent": "agent-builder",
                        "to_agent": AGENT_ID,
                        "intent": "independent_review",
                        "summary": "Review the bounded implementation evidence.",
                    },
                }
            ]
        },
        "agent_material_frontiers": [
            {
                "schema_version": "agent_material_frontier_v0",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "items": [
                    {
                        "material_id": "runtime-contract",
                        "state": "required_unread",
                        "relation": "required",
                        "purpose": "review the current contract",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "available_capabilities",
    [None, [], ["network"], ["external_evidence_poll"]],
)
def test_material_frontier_is_not_projected_without_material_capability(
    available_capabilities: object,
) -> None:
    projection = build_agent_management_projection(
        _status_payload(),
        available_capabilities=available_capabilities,
    )

    row = projection["agents"][0]
    assert "material_frontier" not in row
    assert "handoff_note" not in row
    assert "material_frontier_count" not in projection["source_summary"]


@pytest.mark.parametrize(
    "available_capabilities",
    [["material_lifecycle"], ["network", "material-lifecycle"]],
)
def test_material_frontier_is_projected_with_material_capability(
    available_capabilities: object,
) -> None:
    projection = build_agent_management_projection(
        _status_payload(),
        available_capabilities=available_capabilities,
    )

    row = projection["agents"][0]
    assert row["material_frontier"]["schema_version"] == (
        "agent_material_handoff_projection_v0"
    )
    assert row["material_frontier"]["summary"]["required_unread_count"] == 1
    assert row["handoff_note"]["schema_version"] == "handoff_note_v1"
    assert projection["source_summary"]["material_frontier_count"] == 1
