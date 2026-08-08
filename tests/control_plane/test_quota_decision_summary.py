from __future__ import annotations

from loopx.control_plane.quota.decision_summary import quota_plan_items


def test_quota_plan_items_flattens_state_groups() -> None:
    plan = {
        "groups": {
            "run": [],
            "waiting": [
                {"goal_id": "goal-a"},
                {"goal_id": "goal-b"},
            ],
            "unknown": [{"goal_id": "goal-c"}],
        }
    }

    assert quota_plan_items(plan) == [
        {"goal_id": "goal-a"},
        {"goal_id": "goal-b"},
        {"goal_id": "goal-c"},
    ]


def test_quota_plan_items_ignores_non_mapping_groups() -> None:
    assert quota_plan_items(
        {"groups": {"run": "not-a-list", "waiting": [{"goal_id": "goal-a"}]}}
    ) == [{"goal_id": "goal-a"}]
