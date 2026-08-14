"""Tests for the rich Decision action vocabulary (plan/new_plan.md §5, P1).

PolicyEngine decisions now expose an actionable verb
``ALLOW / DENY / DEFER / RETRY / BLOCK / CANCEL / ESCALATE`` alongside the
normalized outcome, plus optional scheduler-facing hints
(``max_attempts``, ``priority``, ``required_capability``, ``resource_class``).
"""

from __future__ import annotations

from loopx.control_plane.policy import PolicyEngine, Decision
from loopx.control_plane.policy.decision import (
    DECISION_ACTION_MAP,
    DECISION_MAP,
    default_action_for_outcome,
    normalize_quota_decision,
)


def test_default_action_maps_from_outcome() -> None:
    assert default_action_for_outcome("run") == "ALLOW"
    assert default_action_for_outcome("deny") == "DENY"
    assert default_action_for_outcome("wait") == "DEFER"


def test_decision_action_map_outcomes() -> None:
    # Every rich action has a stable normalized outcome + reason.
    assert DECISION_ACTION_MAP["ALLOW"] == ("run", "allow")
    assert DECISION_ACTION_MAP["DENY"] == ("deny", "deny")
    assert DECISION_ACTION_MAP["DEFER"][0] == "wait"
    assert DECISION_ACTION_MAP["RETRY"][0] == "wait"
    assert DECISION_ACTION_MAP["BLOCK"][0] == "wait"
    assert DECISION_ACTION_MAP["CANCEL"] == ("deny", "cancel")
    assert DECISION_ACTION_MAP["ESCALATE"][0] == "wait"
    assert set(DECISION_ACTION_MAP) == {
        "ALLOW",
        "DENY",
        "DEFER",
        "RETRY",
        "BLOCK",
        "CANCEL",
        "ESCALATE",
    }


def test_decision_rich_action_derived_when_unspecified() -> None:
    run = Decision(outcome="run", reason="ok", source="quota")
    assert run.rich_action == "ALLOW"
    deny = Decision(outcome="deny", reason="no", source="capability")
    assert deny.rich_action == "DENY"
    wait = Decision(outcome="wait", reason="later", source="quota")
    assert wait.rich_action == "DEFER"


def test_decision_explicit_rich_action_and_hints() -> None:
    decision = Decision(
        outcome="wait",
        reason="transient_error",
        source="quota",
        action="RETRY",
        max_attempts=3,
        priority=80,
        required_capability="python",
        resource_class="gpu",
    )
    payload = decision.to_dict()
    assert payload["action"] == "RETRY"
    assert payload["max_attempts"] == 3
    assert payload["priority"] == 80
    assert payload["required_capability"] == "python"
    assert payload["resource_class"] == "gpu"
    # Round-trips losslessly.
    restored = Decision.from_dict(payload)
    assert restored == decision


def test_quota_decision_carries_rich_action() -> None:
    decision = normalize_quota_decision("run")
    assert decision.outcome == "run"
    assert decision.rich_action == "ALLOW"


def test_policy_engine_decision_rich_action_via_normalization() -> None:
    # Every normalized outcome exposes the matching rich action through
    # ``rich_action``, so existing consumers keep working unchanged.
    engine = PolicyEngine()
    for raw_decision, (outcome, _reason) in DECISION_MAP.items():
        normalized = normalize_quota_decision(raw_decision)
        assert normalized.outcome == outcome
        assert normalized.rich_action == default_action_for_outcome(outcome)
    assert engine is not None  # engine facade imports cleanly
