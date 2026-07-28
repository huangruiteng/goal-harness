from __future__ import annotations

from typing import Any

from loopx.quota import FOCUS_WAIT_REASON, build_quota_plan


def _goal(goal_id: str, *, quota: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": goal_id,
        "registry_member": True,
        **({"quota": quota} if quota is not None else {}),
    }


def _status_payload(
    *,
    goal: dict[str, Any],
    attention: dict[str, Any],
) -> dict[str, Any]:
    return {
        "ok": True,
        "registry": None,
        "runtime_root": "/tmp/loopx-runtime",
        "goal_count": 1,
        "run_count": 0,
        "attention_queue": {"items": [attention]},
        "run_history": {"goals": [goal]},
    }


def _only_plan_item(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    plan = build_quota_plan(payload, mode="plan")
    populated_groups = [
        (state, items)
        for state, items in plan["groups"].items()
        if items
    ]
    assert len(populated_groups) == 1, plan
    state, items = populated_groups[0]
    assert len(items) == 1, plan
    return state, items[0]


def test_project_asset_quota_is_authoritative_over_focus_wait_markers() -> None:
    goal_id = "asset-quota"
    attention = {
        "goal_id": goal_id,
        "waiting_on": "codex",
        "lifecycle_phase": "focus_wait",
        "quota": {
            "compute": 0.8,
            "state": "eligible",
            "reason": "attention quota",
        },
        "project_asset": {
            "quota": {
                "compute": 0.4,
                "state": "eligible",
                "reason": "project asset quota",
            }
        },
    }

    state, item = _only_plan_item(
        _status_payload(goal=_goal(goal_id), attention=attention)
    )

    assert state == "eligible"
    assert item["quota"] == {
        "compute": 0.4,
        "state": "eligible",
        "reason": "project asset quota",
    }
    assert item["project_asset_source"] == "project_asset"


def test_attention_quota_receives_focus_wait_override() -> None:
    goal_id = "attention-quota"
    attention = {
        "goal_id": goal_id,
        "waiting_on": "codex",
        "lifecycle_flags": ["continuation_boundary"],
        "quota": {
            "compute": 0.8,
            "state": "eligible",
            "reason": "attention quota",
        },
    }

    state, item = _only_plan_item(
        _status_payload(goal=_goal(goal_id), attention=attention)
    )

    assert state == "focus_wait"
    assert item["quota"]["compute"] == 0.8
    assert item["quota"]["reason"] == FOCUS_WAIT_REASON
    assert item["quota"]["blocked_action_scope"] == "delivery_focus"
    assert item["quota"]["focus_wait"] is True


def test_goal_quota_projection_is_reused_without_recomputing_state() -> None:
    goal_id = "goal-quota"
    attention = {
        "goal_id": goal_id,
        "waiting_on": "codex",
        "severity": "info",
    }

    state, item = _only_plan_item(
        _status_payload(
            goal=_goal(
                goal_id,
                quota={
                    "compute": 0.3,
                    "window_hours": 2,
                    "slot_minutes": 10,
                    "spent_slots": 1,
                },
            ),
            attention=attention,
        )
    )

    assert state == "waiting"
    assert item["quota"] == {
        "compute": 0.3,
        "window_hours": 2,
        "slot_minutes": 10,
        "spent_slots": 1,
    }


def test_quota_status_fallback_runs_when_no_quota_projection_exists() -> None:
    goal_id = "default-quota"
    attention = {
        "goal_id": goal_id,
        "waiting_on": "codex",
        "severity": "info",
    }

    state, item = _only_plan_item(
        _status_payload(goal=_goal(goal_id), attention=attention)
    )

    assert state == "eligible"
    assert item["quota"]["compute"] == 1.0
    assert item["quota"]["allowed_slots"] == 1440
    assert item["quota"]["spent_slots"] == 0
    assert item["quota"]["reason"] == (
        "1 compute quota; eligible for the next automatic agent turn"
    )
