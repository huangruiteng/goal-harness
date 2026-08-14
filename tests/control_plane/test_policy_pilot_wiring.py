"""RFC §12 Phase 5 pilot wiring tests.

These tests cover the opt-in wiring added to ``build_live_quota_should_run_decision``:

* default behavior is unchanged (no ``policy_decision`` key, no env flags);
* enabling ``use_policy_engine`` attaches the unified decision and verifies
  consistency against the legacy quota payload;
* enabling ``record_policy_decisions`` writes ``policy_decision`` audit events
  to the goal rollout event log (transition-only, deduplicated);
* a deliberately diverged unified decision raises ``PolicyIntegrationError``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loopx.control_plane.policy import Decision
from loopx.control_plane.policy.decision_events import policy_decision_events
from loopx.control_plane.quota.live_decision import (
    PolicyIntegrationError,
    build_live_quota_should_run_decision,
)
from loopx.control_plane.scheduler.execution_context import (
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.rollout_event_log import rollout_event_log_path

GOAL_ID = "pilot-wiring-fixture"

VALID_SCHEDULER_CONTEXT = dict(GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT)


def _payload(*, quota_state: str = "active") -> dict:
    todo_text = "[P1] Advance the pilot wiring slice."
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


def _common_kwargs(runtime_root: Path) -> dict:
    return {
        "goal_id": GOAL_ID,
        "agent_id": None,
        "available_capabilities": ["shell"],
        "include_scheduler_detail": True,
        "codex_app_current_rrule": None,
        "registry_path": Path("unused"),
        "runtime_root": runtime_root,
        "scheduler_execution_context": VALID_SCHEDULER_CONTEXT,
    }


def test_default_behavior_unchanged(tmp_path: Path) -> None:
    """With no env flag the new architecture is ON by default, so the unified
    policy_decision is attached while the legacy fields remain intact."""
    payload = build_live_quota_should_run_decision(
        _payload(),
        **_common_kwargs(tmp_path),
    )
    assert "policy_decision" in payload
    assert payload.get("should_run") is True
    assert payload.get("decision") in {"run", "observe"}


def test_master_switch_off_restores_legacy_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With LOOPX_NEW_ARCHITECTURE=0 the new architecture is off and the legacy
    payload shape (no policy_decision) is restored."""
    monkeypatch.setenv("LOOPX_NEW_ARCHITECTURE", "0")
    payload = build_live_quota_should_run_decision(
        _payload(),
        **_common_kwargs(tmp_path),
    )
    assert "policy_decision" not in payload
    assert payload.get("should_run") is True
    assert payload.get("decision") in {"run", "observe"}


def test_use_policy_engine_attaches_unified_decision(tmp_path: Path) -> None:
    payload = build_live_quota_should_run_decision(
        _payload(),
        use_policy_engine=True,
        **_common_kwargs(tmp_path),
    )
    policy_decision = payload.get("policy_decision")
    assert isinstance(policy_decision, dict)
    assert policy_decision["outcome"] in {"run", "wait", "deny"}
    assert policy_decision["source"] in {"quota", "capability", "scope", "scheduler"}
    # Consistency: unified outcome must agree with the legacy should_run flag.
    if policy_decision["outcome"] == "run":
        assert payload.get("should_run") is True
    else:
        assert payload.get("should_run") is not True


def test_use_policy_engine_env_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOPX_USE_POLICY_ENGINE", "1")
    payload = build_live_quota_should_run_decision(
        _payload(),
        **_common_kwargs(tmp_path),
    )
    assert "policy_decision" in payload


def test_record_policy_decisions_writes_audit_event(tmp_path: Path) -> None:
    payload = build_live_quota_should_run_decision(
        _payload(),
        use_policy_engine=True,
        record_policy_decisions=True,
        **_common_kwargs(tmp_path),
    )
    assert "policy_decision" in payload
    log_path = rollout_event_log_path(tmp_path, GOAL_ID)
    assert log_path.exists()
    events = policy_decision_events(
        [_line_to_event(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    )
    assert len(events) >= 1
    event = events[-1]
    assert event["event_kind"] == "policy_decision"
    assert event["goal_id"] == GOAL_ID
    assert event["status"] in {"run", "wait", "deny"}
    assert event["decision_fingerprint"]


def test_record_policy_decisions_is_transition_deduplicated(tmp_path: Path) -> None:
    kwargs = _common_kwargs(tmp_path)
    for _ in range(3):
        build_live_quota_should_run_decision(
            _payload(),
            use_policy_engine=True,
            record_policy_decisions=True,
            **kwargs,
        )
    log_path = rollout_event_log_path(tmp_path, GOAL_ID)
    events = policy_decision_events(
        [_line_to_event(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    )
    # Identical decisions collapse into a single transition event.
    assert len(events) == 1


def test_invalid_scheduler_context_does_not_raise_deny_is_legit(tmp_path: Path) -> None:
    """Root-cause regression: an invalid scheduler execution-context makes the
    PolicyEngine deny (scheduler layer) even though the legacy quota payload
    still reports ``should_run`` (quota only). This is the intended stricter
    ``deny > wait > run`` combination, not a divergence — it must not raise.
    """
    kwargs = _common_kwargs(tmp_path)
    kwargs["scheduler_execution_context"] = {
        "presenter": "non_loopx",
        "outer_controller": "unsupported",
    }
    payload = build_live_quota_should_run_decision(
        _payload(),
        use_policy_engine=True,
        **kwargs,
    )
    # The composed policy decision denies via the scheduler layer...
    policy_decision = payload["policy_decision"]
    assert policy_decision["outcome"] == "deny"
    assert policy_decision["source"] == "scheduler"
    # ...while the legacy quota flag may still be permissive; this coexistence
    # is valid and must not have raised PolicyIntegrationError.


def test_policy_integration_error_on_permissive_drift() -> None:
    """A composed ``run`` against a non-running quota is a real policy bypass
    and must raise (the only genuine divergence left after the root-cause fix).
    Directly exercises ``_verify_policy_decision_consistency`` to isolate the
    source-aware check.
    """
    from loopx.control_plane.quota import live_decision as live_decision_module

    verify = live_decision_module._verify_policy_decision_consistency
    # Composed layer (capability) returning ``run`` over a non-running quota.
    with pytest.raises(live_decision_module.PolicyIntegrationError):
        verify(
            {"should_run": False, "decision": "skip"},
            Decision(outcome="run", reason="forced_permissive", source="capability"),
        )


def test_stricter_composed_deny_over_quota_run_is_accepted() -> None:
    """A composed stricter layer (scheduler/capability) may deny/wait over a
    quota ``run`` — the intended ``deny > wait > run`` combination.
    """
    from loopx.control_plane.quota import live_decision as live_decision_module

    verify = live_decision_module._verify_policy_decision_consistency
    verify(
        {"should_run": True, "decision": "run"},
        Decision(outcome="deny", reason="invalid_scheduler_execution_context", source="scheduler"),
    )
    verify(
        {"should_run": True, "decision": "run"},
        Decision(outcome="wait", reason="capability_repair_bridge", source="capability"),
    )


def test_quota_source_must_match_exactly() -> None:
    """When PolicyEngine consumed only the quota layer (source == quota), the
    outcome must agree with the legacy ``should_run`` exactly.
    """
    from loopx.control_plane.quota import live_decision as live_decision_module

    verify = live_decision_module._verify_policy_decision_consistency
    # quota-source deny over a running quota is a genuine single-layer mismatch.
    with pytest.raises(live_decision_module.PolicyIntegrationError):
        verify(
            {"should_run": True, "decision": "run"},
            Decision(outcome="deny", reason="forced_divergence", source="quota"),
        )
    # quota-source run over a running quota is consistent.
    verify(
        {"should_run": True, "decision": "run"},
        Decision(outcome="run", reason="normal_delivery", source="quota"),
    )


def test_policy_integration_error_on_divergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A deliberately diverged unified decision must raise instead of silently
    changing behavior."""
    from loopx.control_plane.quota import live_decision as live_decision_module

    class _DivergedEngine:
        def decide_live(self, **_: object) -> Decision:
            return Decision(outcome="deny", reason="forced_divergence", source="quota")

    monkeypatch.setattr(live_decision_module, "PolicyEngine", lambda: _DivergedEngine())
    with pytest.raises(PolicyIntegrationError):
        build_live_quota_should_run_decision(
            _payload(),
            use_policy_engine=True,
            **_common_kwargs(tmp_path),
        )


def _line_to_event(line: str) -> dict:
    import json

    return json.loads(line)
