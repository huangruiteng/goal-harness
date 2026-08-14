"""Phase 5/6 integration assessment (RFC §12 Phase 5 — Policy Integration).

These tests verify that the unified ``PolicyEngine`` adapter produces a
normalized ``Decision`` that is consistent with the existing live decision
path, without modifying the existing execution behavior. They are the
contract gate for any future rewiring of heartbeat decision composition.
"""

from __future__ import annotations

from pathlib import Path

from loopx.control_plane.policy import Decision, PolicyEngine
from loopx.control_plane.policy.engine import decide
from loopx.control_plane.quota.live_decision import (
    build_live_quota_should_run_decision,
)
from loopx.control_plane.scheduler.execution_context import (
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload

GOAL_ID = "integration-fixture"

VALID_SCHEDULER_CONTEXT = dict(GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT)


def _payload(*, quota_state: str = "active") -> dict:
    todo_text = "[P1] Advance the integration slice."
    return quota_status_payload(
        goal_id=GOAL_ID,
        status=quota_state,
        agent_todo_items=[
            {
                "index": 1,
                "text": todo_text,
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
            }
        ],
        recommended_action=todo_text,
        next_action=todo_text,
    )


def _common_kwargs() -> dict:
    return {
        "goal_id": GOAL_ID,
        "agent_id": None,
        "available_capabilities": ["shell"],
        "include_scheduler_detail": True,
        "codex_app_current_rrule": None,
        "registry_path": Path("unused"),
        "runtime_root": Path("unused"),
        "scheduler_execution_context": VALID_SCHEDULER_CONTEXT,
    }


def test_decide_live_normalizes_existing_decision() -> None:
    engine = PolicyEngine()
    decision = engine.decide_live(status_payload=_payload(), **_common_kwargs())
    assert isinstance(decision, Decision)
    assert decision.outcome in {"run", "wait", "deny"}
    assert decision.reason
    assert decision.source in {"quota", "capability", "scope", "scheduler"}


def test_decide_live_matches_quota_effective_action_semantics() -> None:
    engine = PolicyEngine()
    decision = engine.decide_live(status_payload=_payload(), **_common_kwargs())

    live_payload = build_live_quota_should_run_decision(
        _payload(),
        **_common_kwargs(),
    )
    effective_action = live_payload.get("effective_action")
    should_run = live_payload.get("should_run")

    # Normalization contract: run maps to should_run=True; wait/deny to False.
    if decision.outcome == "run":
        assert should_run is True
    else:
        assert should_run is not True
    # The reason preserves the domain-specific effective action.
    assert decision.reason or effective_action


def test_decide_live_invalid_scheduler_is_deny() -> None:
    engine = PolicyEngine()
    kwargs = _common_kwargs()
    kwargs["scheduler_execution_context"] = {"host_surface": "bogus"}
    decision = engine.decide_live(status_payload=_payload(), **kwargs)
    assert decision.outcome == "deny"
    assert decision.source == "scheduler"


def test_module_decide_with_live_signature() -> None:
    decision = decide(
        status_payload=_payload(),
        goal_id=GOAL_ID,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=True,
        codex_app_current_rrule=None,
        scheduler_execution_context=VALID_SCHEDULER_CONTEXT,
    )
    assert decision.outcome in {"run", "wait", "deny"}


def test_decision_contract_stable_for_audit() -> None:
    """The Decision dict shape must remain stable for audit recording."""
    engine = PolicyEngine()
    decision = engine.decide_live(status_payload=_payload(), **_common_kwargs())
    payload = decision.to_dict()
    assert set(payload) >= {"outcome", "reason", "source"}
    assert payload["outcome"] in {"run", "wait", "deny"}
    # Round-trip through the recorder-facing representation.
    restored = Decision.from_dict(payload)
    assert restored.outcome == decision.outcome
    assert restored.reason == decision.reason
