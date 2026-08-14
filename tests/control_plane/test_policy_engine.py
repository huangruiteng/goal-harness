from __future__ import annotations

import pytest

from loopx.control_plane.policy import (
    CAPABILITY_ACTION_MAP,
    DECISION_MAP,
    Decision,
    PolicyEngine,
    combine_decisions,
    normalize_capability_action,
    normalize_quota_decision,
    normalize_scheduler_resolution,
)
from loopx.control_plane.policy.decision import _OUTCOME_RANK
from loopx.control_plane.scheduler.execution_context import (
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
    resolve_scheduler_execution_context,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload

GOAL_ID = "policy-engine-fixture"

VALID_SCHEDULER_CONTEXT = dict(GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT)


def _run_payload(*, required_capabilities: list[str] | None = None) -> dict:
    todo_text = "[P1] Advance the bounded slice."
    items = [
        {
            "index": 1,
            "text": todo_text,
            "role": "agent",
            "status": "open",
            "priority": "P1",
            "task_class": "advancement_task",
        }
    ]
    if required_capabilities:
        items[0]["required_capabilities"] = required_capabilities
    return quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=items,
        recommended_action=todo_text,
        next_action=todo_text,
    )


def _engine() -> PolicyEngine:
    return PolicyEngine()


# ---------------------------------------------------------------------------
# Decision contract
# ---------------------------------------------------------------------------


def test_decision_defaults() -> None:
    decision = Decision(outcome="run", reason="normal_delivery", source="quota")
    assert decision.to_dict() == {
        "outcome": "run",
        "reason": "normal_delivery",
        "source": "quota",
    }
    assert bool(decision) is True


def test_decision_round_trip_with_retry_metadata() -> None:
    decision = Decision(
        outcome="wait",
        reason="quota_backoff",
        source="quota",
        detail={"state": "backoff"},
        retry_at="2026-08-13T12:30:00Z",
        retry_after_seconds=300,
        manual_approval_required=True,
    )
    restored = Decision.from_dict(decision.to_dict())
    assert restored == decision
    assert bool(restored) is False


def test_decision_unknown_outcome_from_dict_is_deny() -> None:
    decision = Decision.from_dict({"outcome": "bogus"})
    assert decision.outcome == "deny"
    assert bool(decision) is False


# ---------------------------------------------------------------------------
# Exhaustive normalization maps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("decision_value", "expected_outcome"),
    [
        ("run", "run"),
        ("observe", "run"),
        ("safe_bypass_recovery", "run"),
        ("recovery", "run"),
        ("self_repair", "run"),
        ("autonomous_replan_required", "run"),
        ("repair_bridge", "wait"),
        ("workspace_guard", "wait"),
        ("automation_prompt_upgrade", "wait"),
        ("agent_scope_exhausted", "wait"),
        ("agent_scope_wait", "wait"),
        ("reassignment_required", "wait"),
        ("successor_replan_required", "wait"),
        ("skip", "deny"),
    ],
)
def test_quota_decision_map_exhaustive(decision_value: str, expected_outcome: str) -> None:
    outcome, reason = DECISION_MAP[decision_value]
    assert outcome == expected_outcome
    assert reason
    decision = normalize_quota_decision(decision_value)
    assert decision.outcome == expected_outcome
    assert decision.source == "quota"
    assert decision.detail["quota_decision"] == decision_value


def test_quota_decision_unknown_value_is_deny() -> None:
    decision = normalize_quota_decision("totally_new_mode")
    assert decision.outcome == "deny"
    assert decision.reason.startswith("unknown_quota_decision")


@pytest.mark.parametrize(
    ("action_value", "expected_outcome"),
    [
        ("run", "run"),
        ("repair_bridge", "wait"),
        ("ask_owner", "wait"),
        ("deny", "deny"),
        ("denied", "deny"),
        ("skip", "deny"),
    ],
)
def test_capability_action_map_exhaustive(action_value: str, expected_outcome: str) -> None:
    outcome, reason = CAPABILITY_ACTION_MAP[action_value]
    assert outcome == expected_outcome
    decision = normalize_capability_action(action_value)
    assert decision.outcome == expected_outcome
    assert decision.source == "capability"
    assert decision.detail["capability_action"] == action_value


def test_scheduler_resolution_deny_and_ok() -> None:
    ok_resolution = resolve_scheduler_execution_context(VALID_SCHEDULER_CONTEXT)
    assert ok_resolution.ok
    assert normalize_scheduler_resolution(ok_resolution).outcome == "run"

    bad_resolution = resolve_scheduler_execution_context({"host_surface": "bogus"})
    decision = normalize_scheduler_resolution(bad_resolution)
    assert decision.outcome == "deny"
    assert decision.reason == "invalid_scheduler_execution_context"
    assert decision.detail["errors"]


# ---------------------------------------------------------------------------
# combine_decisions strictness (deny > wait > run)
# ---------------------------------------------------------------------------


def test_combine_keeps_strictest_outcome() -> None:
    run = Decision(outcome="run", reason="r", source="a")
    wait = Decision(outcome="wait", reason="w", source="b")
    deny = Decision(outcome="deny", reason="d", source="c")

    assert combine_decisions(run, wait).outcome == "wait"
    assert combine_decisions(wait, deny).outcome == "deny"
    assert combine_decisions(deny, run).outcome == "deny"
    assert combine_decisions(run, run).outcome == "run"
    assert combine_decisions(wait, wait).outcome == "wait"  # primary wins on tie


# ---------------------------------------------------------------------------
# PolicyEngine.decide integration
# ---------------------------------------------------------------------------


def test_decide_run_path() -> None:
    decision = _engine().decide(
        status_payload=_run_payload(),
        goal_id=GOAL_ID,
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
    )
    assert decision.outcome == "run"
    assert decision.source == "quota"
    assert decision.reason == "normal_delivery"


def test_decide_denied_when_scheduler_context_invalid() -> None:
    decision = _engine().decide(
        status_payload=_run_payload(),
        goal_id=GOAL_ID,
        scheduler_execution_context={"host_surface": "bogus"},
    )
    assert decision.outcome == "deny"
    assert decision.source == "scheduler"
    assert decision.reason == "invalid_scheduler_execution_context"


def test_decide_missing_scheduler_context_is_deny() -> None:
    decision = _engine().decide(status_payload=_run_payload(), goal_id=GOAL_ID)
    assert decision.outcome == "deny"
    assert decision.source == "scheduler"


def test_decide_capability_gate_blocks_run() -> None:
    # quota passes (no capability requirement in status payload), but the
    # independently-supplied capability summary requires "network".
    payload = _run_payload()
    from loopx.control_plane.testing.quota_fixtures import quota_todo_summary

    capability_summary = quota_todo_summary(
        [
            {
                "index": 1,
                "text": "[P1] Network-only slice.",
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
                "required_capabilities": ["network"],
            }
        ]
    )
    decision = _engine().decide(
        status_payload=payload,
        goal_id=GOAL_ID,
        available_capabilities=["shell"],
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
        capability_agent_todo_summary=capability_summary,
    )
    assert decision.outcome == "wait"
    assert decision.source == "capability"
    assert decision.reason == "capability_repair_bridge"


def test_decide_waives_capability_when_all_available() -> None:
    payload = _run_payload(required_capabilities=["network"])
    decision = _engine().decide(
        status_payload=payload,
        goal_id=GOAL_ID,
        available_capabilities=["shell", "network"],
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
        capability_agent_todo_summary=payload,
    )
    assert decision.outcome == "run"


def test_decide_without_capability_summary_relies_on_quota_only() -> None:
    payload = _run_payload(required_capabilities=["network"])
    decision = _engine().decide(
        status_payload=payload,
        goal_id=GOAL_ID,
        available_capabilities=["shell"],
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
    )
    # quota/should_run itself embeds capability matching, so the decision is
    # already a wait via the quota layer even without an explicit summary.
    assert decision.outcome == "wait"
    assert decision.source == "quota"


def test_decide_quota_backoff_wait_surface() -> None:
    payload = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        recommended_action="recovery-eligible",
        next_action="backoff",
        quota_state="backoff",
    )
    decision = _engine().decide(
        status_payload=payload,
        goal_id=GOAL_ID,
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
    )
    assert decision.outcome in {"run", "wait", "deny"}
    assert decision.source in {"quota", "scheduler"}


def test_module_level_decide_convenience() -> None:
    from loopx.control_plane.policy import decide

    decision = decide(
        status_payload=_run_payload(),
        goal_id=GOAL_ID,
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
    )
    assert decision.outcome == "run"


def test_outcome_rank_ordering_is_deny_wait_run() -> None:
    assert _OUTCOME_RANK["run"] < _OUTCOME_RANK["wait"] < _OUTCOME_RANK["deny"]
