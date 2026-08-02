from __future__ import annotations

from typing import Any

import pytest

from loopx.control_plane.quota.decision_summary import (
    refine_quota_recommended_action,
)


def _refine(selected_action: str = "base action", **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "task_orchestration_contract": None,
        "capability_gate": None,
        "capability_monitor_fallback": None,
        "work_lane_contract": None,
        "workspace_guard": None,
        "automation_prompt_upgrade": None,
        "automation_prompt_upgrade_required": False,
        "replan_obligation": None,
        "replan_decision_allowed": False,
    }
    values.update(overrides)
    return refine_quota_recommended_action(selected_action, **values)


def test_task_orchestration_precedes_base_action() -> None:
    selected = _refine(
        task_orchestration_contract={
            "coordinator_obligation": "coordinate eligible peers",
        },
    )

    assert selected == "coordinate eligible peers"


def test_capability_monitor_fallback_precedes_task_orchestration() -> None:
    selected = _refine(
        task_orchestration_contract={
            "coordinator_obligation": "coordinate eligible peers",
        },
        capability_monitor_fallback={"selected": True},
        work_lane_contract={"action": "repair monitor metadata"},
    )

    assert selected == "repair monitor metadata"


@pytest.mark.parametrize("action", ["repair_bridge", "ask_owner", "skip"])
def test_non_run_capability_gate_uses_owner_action(action: str) -> None:
    selected = _refine(
        capability_gate={
            "action": action,
            "owner_action": f"{action} owner action",
            "reason": f"{action} reason",
        },
    )

    assert selected == f"{action} owner action"


def test_due_monitor_attempt_suppresses_capability_gate_override() -> None:
    selected = _refine(
        capability_gate={
            "action": "ask_owner",
            "owner_action": "ask for capability",
        },
        work_lane_contract={
            "monitor_kind": "todo_monitor_due",
            "must_attempt_work": True,
        },
    )

    assert selected == "base action"


def test_run_capability_gate_replaces_a_blocked_selected_action() -> None:
    selected = _refine(
        selected_action="blocked task",
        capability_gate={
            "action": "run",
            "blocked_candidates": [{"text": "blocked task"}],
            "runnable_candidates": [{"text": "runnable task"}],
        },
    )

    assert selected == "runnable task"


def test_unknown_capability_action_preserves_selected_action() -> None:
    selected = _refine(
        capability_gate={
            "action": "unknown",
            "blocked_candidates": [{"text": "base action"}],
            "runnable_candidates": [{"text": "runnable task"}],
        },
    )

    assert selected == "base action"


def test_workspace_guard_precedes_capability_gate() -> None:
    selected = _refine(
        capability_gate={
            "action": "ask_owner",
            "owner_action": "ask for capability",
        },
        workspace_guard={"required_action": "move to independent worktree"},
    )

    assert selected == "move to independent worktree"


def test_automation_upgrade_precedes_workspace_guard() -> None:
    selected = _refine(
        workspace_guard={"required_action": "move to independent worktree"},
        automation_prompt_upgrade={
            "recommended_action": "upgrade automation prompt",
        },
        automation_prompt_upgrade_required=True,
    )

    assert selected == "upgrade automation prompt"


def test_replan_precedes_other_recommendation_refinements() -> None:
    selected = _refine(
        automation_prompt_upgrade={
            "recommended_action": "upgrade automation prompt",
        },
        automation_prompt_upgrade_required=True,
        replan_obligation={"recommended_action": "replan the frontier"},
        replan_decision_allowed=True,
    )

    assert selected == "replan the frontier"
