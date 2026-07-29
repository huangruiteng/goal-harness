from __future__ import annotations

from typing import Any

from loopx.control_plane.goals.goal_frontier import (
    GOAL_TERMINAL_SOURCE_COMPLETENESS_SCHEMA_VERSION,
    GOAL_TERMINAL_STATE_SCHEMA_VERSION,
)
from loopx.control_plane.quota.decision_summary import (
    QuotaRunDecision,
    resolve_quota_run_decision,
)


def _resolve(**overrides: Any) -> QuotaRunDecision:
    values: dict[str, Any] = {
        "normal_delivery_allowed": True,
        "recovery_delivery_allowed": False,
        "self_repair_allowed": False,
        "stall_self_repair": None,
        "state": "eligible",
        "quota": {"state": "eligible"},
        "reason": "eligible",
        "capability_gate": None,
        "capability_monitor_fallback": None,
        "workspace_guard": None,
        "automation_prompt_upgrade": None,
        "automation_prompt_upgrade_required": False,
        "replan_obligation": None,
        "goal_health_ok": True,
        "inbox_reply_due": False,
        "agent_frontier_id": "agent-a",
        "registered_agent_ids": ["agent-a"],
        "goal_frontier_projection": None,
        "task_orchestration_contract": None,
    }
    values.update(overrides)
    return resolve_quota_run_decision(**values)


def test_base_eligible_decision_runs_normally() -> None:
    decision = _resolve()

    assert decision.should_run is True
    assert decision.normal_delivery_allowed is True
    assert decision.effective_action == "normal_run"


def test_workspace_guard_overrides_capability_repair() -> None:
    decision = _resolve(
        capability_gate={"action": "repair_bridge", "reason": "repair capability"},
        workspace_guard={"reason": "use independent worktree"},
    )

    assert decision.should_run is True
    assert decision.capability_repair_allowed is False
    assert decision.workspace_repair_allowed is True
    assert decision.effective_action == "agent_workspace_repair"
    assert decision.reason == "use independent worktree"


def test_automation_upgrade_precedes_inbox_reply() -> None:
    decision = _resolve(
        automation_prompt_upgrade={"reason": "refresh prompt identity"},
        automation_prompt_upgrade_required=True,
        inbox_reply_due=True,
    )

    assert decision.should_run is False
    assert decision.normal_delivery_allowed is False
    assert decision.effective_action == "automation_prompt_upgrade_required"
    assert decision.reason == "refresh prompt identity"


def test_inbox_reply_prevents_replan_and_precedes_normal_delivery() -> None:
    decision = _resolve(
        replan_obligation={"required": True, "agent_id": "agent-a"},
        inbox_reply_due=True,
    )

    assert decision.replan_decision_allowed is False
    assert decision.should_run is True
    assert decision.normal_delivery_allowed is True
    assert decision.effective_action == "lark_inbox_reply_due"


def test_replan_precedes_normal_delivery() -> None:
    decision = _resolve(
        replan_obligation={"required": True, "agent_id": "agent-a"},
    )

    assert decision.replan_decision_allowed is True
    assert decision.should_run is True
    assert decision.normal_delivery_allowed is False
    assert decision.effective_action == "autonomous_replan_required"


def test_terminal_closure_precedes_automation_upgrade() -> None:
    projection = {
        "terminal_state": {
            "schema_version": GOAL_TERMINAL_STATE_SCHEMA_VERSION,
            "kind": "no_followup",
            "derived": True,
            "source": "validated_goal_closure",
        },
        "source_completeness": {
            "schema_version": GOAL_TERMINAL_SOURCE_COMPLETENESS_SCHEMA_VERSION,
            "user_todos": "valid",
            "agent_todos": "valid",
        },
        "normalized_progress": {
            "user_open_count": 0,
            "agent_open_count": 0,
            "agent_advancement_open_count": 0,
            "agent_monitor_open_count": 0,
            "agent_monitor_due_count": 0,
        },
        "remaining_advancement_frontier": {
            "current_agent_claimed_advancement_count": 0,
            "unclaimed_advancement_count": 0,
            "other_agent_claimed_advancement_count": 0,
        },
        "monitor_only_lanes": {
            "present": False,
            "quiet_until_material_transition": False,
        },
        "deferred_successors": {
            "ready_count": 0,
            "blocked_count": 0,
            "current_agent_ready_count": 0,
        },
        "acceptance_gaps": [],
        "autonomy_blockers": [],
        "replan_required": False,
    }
    decision = _resolve(
        automation_prompt_upgrade={"reason": "refresh prompt identity"},
        automation_prompt_upgrade_required=True,
        goal_frontier_projection=projection,
    )

    assert decision.should_run is False
    assert decision.state == "terminal_no_followup"
    assert decision.effective_action == "terminal_no_followup"
    assert decision.quota["state"] == "terminal_no_followup"


def test_task_orchestration_refines_normal_run_action() -> None:
    decision = _resolve(
        task_orchestration_contract={
            "coordinator_obligation": "coordinate eligible peers"
        }
    )

    assert decision.should_run is True
    assert decision.normal_delivery_allowed is True
    assert decision.effective_action == "coordinate_task_bundle"
