from __future__ import annotations

import pytest

from loopx.control_plane.quota.heartbeat_recommendation import (
    refine_heartbeat_recommendation,
)

BASE_RECOMMENDATION = {
    "source": "quota.should-run",
    "recommended_mode": "steering_audit_then_one_step",
    "notify": "DONT_NOTIFY",
    "reason": "base recommendation",
    "spend_policy": "spend after validated writeback",
}


def _refine(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "recommendation": BASE_RECOMMENDATION,
        "should_run": True,
        "capability_gate": None,
        "capability_monitor_fallback": None,
        "workspace_guard": None,
        "automation_prompt_upgrade": None,
        "automation_prompt_upgrade_required": False,
        "blocked_priority_fallback": None,
    }
    values.update(overrides)
    return refine_heartbeat_recommendation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("action", "mode", "notify"),
    [
        ("repair_bridge", "repair_capability_bridge", "DONT_NOTIFY"),
        ("ask_owner", "ask_owner_for_capability", "NOTIFY"),
        ("skip", "capability_skip", "DONT_NOTIFY"),
    ],
)
def test_capability_gate_refines_recommendation(
    action: str,
    mode: str,
    notify: str,
) -> None:
    recommendation = _refine(
        capability_gate={"action": action, "reason": f"{action} reason"},
    )

    assert recommendation["recommended_mode"] == mode
    assert recommendation["notify"] == notify
    assert recommendation["reason"] == f"{action} reason"


def test_monitor_fallback_preserves_base_recommendation() -> None:
    recommendation = _refine(
        capability_gate={"action": "skip", "reason": "missing capability"},
        capability_monitor_fallback={"selected": True},
    )

    assert recommendation == BASE_RECOMMENDATION


def test_automation_upgrade_overrides_workspace_and_capability_guidance() -> None:
    recommendation = _refine(
        capability_gate={"action": "repair_bridge", "reason": "repair capability"},
        workspace_guard={"reason": "repair workspace"},
        automation_prompt_upgrade={"reason": "upgrade automation"},
        automation_prompt_upgrade_required=True,
    )

    assert recommendation["recommended_mode"] == "automation_prompt_upgrade"
    assert recommendation["notify"] == "DONT_NOTIFY"
    assert recommendation["reason"] == "upgrade automation"


def test_workspace_guard_overrides_capability_guidance() -> None:
    recommendation = _refine(
        capability_gate={"action": "ask_owner", "reason": "ask owner"},
        workspace_guard={"reason": "repair workspace"},
    )

    assert recommendation["recommended_mode"] == "repair_agent_workspace"
    assert recommendation["notify"] == "DONT_NOTIFY"
    assert recommendation["reason"] == "repair workspace"


def test_blocked_priority_fallback_only_notifies_for_runnable_turn() -> None:
    fallback = {
        "notify_user": True,
        "reason": "blocked priority requires notice",
    }

    runnable = _refine(blocked_priority_fallback=fallback)
    skipped = _refine(should_run=False, blocked_priority_fallback=fallback)

    assert runnable["blocked_priority_fallback"] == fallback
    assert runnable["notify"] == "NOTIFY"
    assert runnable["reason"] == "blocked priority requires notice"
    assert "blocked_priority_fallback" not in skipped
    assert skipped["notify"] == "DONT_NOTIFY"
