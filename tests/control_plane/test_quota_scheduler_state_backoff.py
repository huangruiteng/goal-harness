from __future__ import annotations

"""Decision-table tests for scheduler stateful-backoff progression rules.

These tests extract the pure, independently verifiable rules from
``examples/control_plane/quota-scheduler-state-ack-smoke.py`` so that
implementation output cannot become the oracle.

Each parametrized table row is a (input, expected_output) pair derived
from the smoke's documented progression contracts.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from loopx.control_plane.agents.agent_scope_frontier import AgentScopeFrontierAction
from loopx.control_plane.scheduler.ack import build_scheduler_ack_plan
from loopx.control_plane.scheduler.execution_context import (
    SchedulerRuntimeProfile,
    scheduler_execution_context_for_runtime_profile,
)
from loopx.control_plane.scheduler.scheduler_hint import (
    build_scheduler_hint as _build_scheduler_hint,
)
from loopx.control_plane.scheduler.state import (
    load_scheduler_state,
    write_scheduler_state,
)

AGENT_SCOPE_ACTIONS = [action.value for action in AgentScopeFrontierAction]
APP_SCHEDULER_CONTEXT = scheduler_execution_context_for_runtime_profile(
    SchedulerRuntimeProfile.CODEX_APP_HEARTBEAT
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _build_hint(
    payload: dict,
    *,
    scheduler_state: dict | None = None,
    codex_app_current_rrule: str | None = None,
    include_detail: bool = False,
) -> dict:
    return _build_scheduler_hint(
        deepcopy(payload),
        agent_scope_frontier_actions=AGENT_SCOPE_ACTIONS,
        scheduler_execution_context=APP_SCHEDULER_CONTEXT,
        codex_app_scheduler_state=scheduler_state,
        codex_app_current_rrule=codex_app_current_rrule,
        include_detail=include_detail,
    )


def _state_from_hint(hint: dict) -> dict:
    stateful = hint["codex_app"]["stateful_backoff"]
    last_rrule = (
        hint["codex_app"].get("recommended_rrule")
        or hint["codex_app"]["stateful_backoff"].get("current_rrule")
        or "FREQ=MINUTELY;INTERVAL=10"
    )
    return {
        "schema_version": "loopx_scheduler_state_v0",
        "goal_id": "test-goal",
        "agent_id": "codex-test",
        "surface": "codex_app",
        "state_key": stateful["state_key"],
        "reset_token": stateful["reset_token"],
        "identity_signature": stateful["identity_signature"],
        "progression_index": stateful["progression_index"],
        "progression_minutes": hint["codex_app"]["example_progression_minutes"],
        "last_applied_rrule": last_rrule,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _wait_payload() -> dict:
    return {
        "goal_id": "test-goal",
        "agent_identity": {"agent_id": "codex-test"},
        "should_run": False,
        "effective_action": AgentScopeFrontierAction.AGENT_SCOPE_WAIT.value,
        "recommended_action": "Wait for reassignment.",
        "heartbeat_recommendation": {
            "recommended_mode": AgentScopeFrontierAction.AGENT_SCOPE_WAIT.value,
            "notify": "DONT_NOTIFY",
            "spend_policy": "no spend while waiting for reassignment",
        },
        "execution_obligation": {"must_attempt_work": False, "spend_policy": "do not spend"},
        "automation_liveness": {"automation_action": "", "spend_policy": "automation liveness spend policy"},
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": AgentScopeFrontierAction.AGENT_SCOPE_WAIT.value,
            "user_channel": {"action_required": False},
            "agent_channel": {"must_attempt": False, "delivery_allowed": False, "quiet_noop_allowed": True},
        },
    }


def _monitor_wait_payload() -> dict:
    return {
        "goal_id": "test-goal",
        "agent_identity": {"agent_id": "codex-test"},
        "should_run": False,
        "effective_action": "monitor_quiet_skip",
        "recommended_action": "Wait for material monitor evidence.",
        "heartbeat_recommendation": {
            "recommended_mode": "monitor_quiet_until_material_transition",
            "notify": "DONT_NOTIFY",
            "spend_policy": "no spend while the monitor target is unchanged",
        },
        "execution_obligation": {"must_attempt_work": False, "spend_policy": "do not spend"},
        "automation_liveness": {"automation_action": "keep_active_quiet", "spend_policy": "no quota spend for unchanged monitor-only polls"},
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": "monitor_quiet_skip",
            "user_channel": {"action_required": False},
            "agent_channel": {"must_attempt": False, "delivery_allowed": False, "quiet_noop_allowed": True},
        },
    }


def _active_payload() -> dict:
    return {
        "goal_id": "test-goal",
        "agent_identity": {"agent_id": "codex-test"},
        "should_run": True,
        "effective_action": "normal_run",
        "recommended_action": "Run the active work cadence smoke.",
        "heartbeat_recommendation": {
            "recommended_mode": "run_first_read_only_map",
            "notify": "DONT_NOTIFY",
            "spend_policy": "spend once after validated writeback",
        },
        "execution_obligation": {"must_attempt_work": True, "spend_policy": "spend after validation"},
        "automation_liveness": {"automation_action": "execute_bounded_work", "spend_policy": "spend after validation"},
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": "bounded_delivery",
            "user_channel": {"action_required": False},
            "agent_channel": {"must_attempt": True, "delivery_allowed": True, "quiet_noop_allowed": False},
        },
    }


# ── backoff progression decision table ───────────────────────────────────────


@pytest.mark.parametrize(
    "progression_steps, expected_rrule, expected_apply, expected_status",
    [
        (0, "FREQ=MINUTELY;INTERVAL=10", True, "missing"),
        (1, "FREQ=MINUTELY;INTERVAL=20", True, "same_identity"),
        (2, "FREQ=MINUTELY;INTERVAL=30", True, "same_identity"),
        (3, "FREQ=MINUTELY;INTERVAL=60", True, "same_identity"),
        (4, None,              False, "same_identity"),
    ],
)
def test_wait_backoff_progression_decision_table(
    progression_steps: int,
    expected_rrule: str | None,
    expected_apply: bool,
    expected_status: str,
) -> None:
    """Reassign-wait backoff doubles interval 10→20→30→60 then caps.

    Each call passes the state derived from the previous hint, mimicking
    the pattern from quota-scheduler-state-ack-smoke.py:
        first = build_scheduler_hint(payload)
        second = build_scheduler_hint(payload, state=state_from(first))
        third = build_scheduler_hint(payload, state=state_from(second))
    """
    payload = _wait_payload()
    hint = None
    state = None

    for _ in range(progression_steps):
        hint = _build_hint(payload, scheduler_state=state)
        state = _state_from_hint(hint)

    result = _build_hint(payload, scheduler_state=state)
    backoff = result["codex_app"]["stateful_backoff"]
    got_rrule = result["codex_app"].get("recommended_rrule")
    assert got_rrule == expected_rrule, f"step={progression_steps}: rrule mismatch"
    assert backoff["apply_needed"] == expected_apply, f"step={progression_steps}: apply mismatch"
    assert backoff["state_status"] == expected_status, f"step={progression_steps}: status mismatch"


def test_wait_backoff_reset_on_recommended_action_change() -> None:
    """When recommended_action changes, state resets to interval=10."""
    payload = _wait_payload()
    first = _build_hint(payload)
    state = _state_from_hint(first)
    # Progress three steps
    for _ in range(3):
        state = _state_from_hint(_build_hint(payload, scheduler_state=state))

    # Change recommended_action — should force reset
    changed = dict(_wait_payload())
    changed["recommended_action"] = "A new reassignment candidate appeared."
    reset = _build_hint(changed, scheduler_state=state)
    reset_backoff = reset["codex_app"]["stateful_backoff"]
    assert reset["codex_app"]["recommended_rrule"] == "FREQ=MINUTELY;INTERVAL=10"
    assert reset_backoff["state_status"] == "reset_required"
    assert reset_backoff["apply_needed"] is True


def test_wait_backoff_negative_wrong_identity_signature_triggers_reset() -> None:
    """Mutation: a wrong identity_signature in stored state resets the chain."""
    payload = _wait_payload()
    first = _build_hint(payload)
    state = _state_from_hint(first)
    # Mutate the identity signature
    state["identity_signature"] = "wrong-signature"
    state["reset_token"] = "wrong-token"
    result = _build_hint(payload, scheduler_state=state)
    backoff = result["codex_app"]["stateful_backoff"]
    assert backoff["state_status"] in {"reset_required", "missing"}

    # Verify the reset produces a fresh interval=10
    assert result["codex_app"]["recommended_rrule"] == "FREQ=MINUTELY;INTERVAL=10"


# ── monitor-wait progression decision table ──────────────────────────────────


@pytest.mark.parametrize(
    "progression_steps, expected_rrule, expected_apply",
    [
        (0, "FREQ=MINUTELY;INTERVAL=15", True),
        (1, "FREQ=MINUTELY;INTERVAL=30", True),
        (2, "FREQ=MINUTELY;INTERVAL=60", True),
        (3, None,              False),
    ],
)
def test_monitor_wait_progression_decision_table(
    progression_steps: int,
    expected_rrule: str | None,
    expected_apply: bool,
) -> None:
    """Monitor-wait progression: 15→30→60 then caps at steady-state."""
    payload = _monitor_wait_payload()
    hint = None
    state = None

    for _ in range(progression_steps):
        hint = _build_hint(payload, scheduler_state=state)
        state = _state_from_hint(hint)

    result = _build_hint(payload, scheduler_state=state)
    backoff = result["codex_app"]["stateful_backoff"]
    got_rrule = result["codex_app"].get("recommended_rrule")
    assert got_rrule == expected_rrule, f"step={progression_steps}"
    assert backoff["apply_needed"] == expected_apply, f"step={progression_steps}"


def test_monitor_identity_ignores_recommended_action_text_changes() -> None:
    """Changing recommended_action on same monitor target preserves identity."""
    payload = _monitor_wait_payload()
    first = _build_hint(payload)
    first_backoff = first["codex_app"]["stateful_backoff"]

    second_payload = dict(_monitor_wait_payload())
    second_payload["recommended_action"] = (
        "Goal-level controller text changed but monitor target is unchanged."
    )
    second = _build_hint(second_payload, scheduler_state=_state_from_hint(first))
    second_backoff = second["codex_app"]["stateful_backoff"]
    assert second_backoff["state_status"] == "same_identity"
    assert second_backoff["identity_signature"] == first_backoff["identity_signature"]
    assert second_backoff["reset_token"] == first_backoff["reset_token"]


# ── active work ──────────────────────────────────────────────────────────────


def test_active_work_keeps_initial_3_minute_cadence() -> None:
    """Active work always uses FREQ=MINUTELY;INTERVAL=3 regardless of history."""
    payload = _active_payload()
    first = _build_hint(payload)
    assert first["action"] == "run_now"
    assert first["codex_app"]["recommended_rrule"] == "FREQ=MINUTELY;INTERVAL=3"
    assert "same_identity_action" not in first["codex_app"]["stateful_backoff"]


def test_active_work_repairs_stale_backoff_state_to_initial() -> None:
    """Stale backoff state with wrong rrule gets repaired to interval=3."""
    payload = _active_payload()
    first = _build_hint(payload)
    stale_state = _state_from_hint(first)
    stale_state["progression_index"] = 1
    stale_state["last_applied_rrule"] = "FREQ=MINUTELY;INTERVAL=6"

    repaired = _build_hint(payload, scheduler_state=stale_state)
    assert repaired["codex_app"]["recommended_rrule"] == "FREQ=MINUTELY;INTERVAL=3"
    assert repaired["codex_app"]["stateful_backoff"]["progression_index"] == 0


def test_active_work_is_quiet_after_ack() -> None:
    """After acknowledging active work rrule, no further apply needed."""
    payload = _active_payload()
    first = _build_hint(payload)
    state = _state_from_hint(first)
    steady = _build_hint(payload, scheduler_state=state)
    steady_backoff = steady["codex_app"]["stateful_backoff"]
    assert steady_backoff["apply_needed"] is False
    assert "recommended_rrule" not in steady["codex_app"]


def test_active_work_detailed_hint_exposes_same_identity_policy() -> None:
    """Cold-path detail documents the active-work same-identity policy."""
    detailed = _build_hint(deepcopy(_active_payload()), include_detail=True)
    assert (
        detailed["cold_path_detail"]["stateful_backoff_detail"]["same_identity_action"]
        == "keep_initial_interval_while_active_work"
    )


# ── stale ack tolerance decision table ───────────────────────────────────────


FROZEN_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _make_monitor_window_payload(minutes_until_due: int = 59) -> dict:
    due_at = FROZEN_NOW + timedelta(minutes=minutes_until_due)
    expires_at = FROZEN_NOW + timedelta(minutes=minutes_until_due + 60)
    payload = _monitor_wait_payload()
    payload["agent_todo_summary"] = {
        "current_agent_claimed_monitor_items": [
            {
                "todo_id": "todo_monitor_stale",
                "priority": "P1",
                "task_class": "continuous_monitor",
                "target_key": "monitor-stale-ack",
                "cadence": "3m",
                "next_due_at": due_at.isoformat(),
                "expires_at": expires_at.isoformat(),
            }
        ],
        "monitor_open_items": [],
    }
    return payload


@pytest.mark.parametrize(
    "applied_offset_minutes, expected_ok, expected_stale",
    [
        (30, True,  False),
        (31, True,  True),
        (32, True,  True),
        (33, False, False),
        (29, False, False),
    ],
)
def test_monitor_stale_ack_tolerance_decision_table(
    applied_offset_minutes: int,
    expected_ok: bool,
    expected_stale: bool,
) -> None:
    """2-minute tolerance window for monitor-wait stale ack hints."""
    payload = _make_monitor_window_payload()
    first = _build_hint(payload)
    current = _build_hint(payload, scheduler_state=_state_from_hint(first))
    current_app = current["codex_app"]
    ack_args = current_app["ack_hint"]["args"]
    expected_rrule = current_app["recommended_rrule"]

    plan = build_scheduler_ack_plan(
        {"scheduler_hint": current},
        agent_id=ack_args["agent_id"],
        state_key=ack_args["state_key"],
        applied_rrule=f"FREQ=MINUTELY;INTERVAL={applied_offset_minutes}",
        reset_token=ack_args["reset_token"],
        identity_signature=ack_args["identity_signature"],
    )
    assert plan["ok"] == expected_ok, plan
    if expected_stale:
        assert plan.get("stale_hint_accepted") is True, plan
        assert plan["expected_rrule"] == expected_rrule, plan
    elif not expected_ok:
        assert "does not match expected" in str(plan.get("reason", "")), plan


# ── ack plan validation decision table ───────────────────────────────────────


def _ack_fixture() -> tuple[dict, dict]:
    payload = _active_payload()
    first = _build_hint(payload)
    return first, first["codex_app"]["stateful_backoff"]


def test_ack_plan_rejects_missing_agent_id() -> None:
    first, backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id=None,
        state_key=backoff["state_key"],
        applied_rrule=first["codex_app"]["recommended_rrule"],
    )
    assert plan["ok"] is False
    assert "--agent-id" in plan["reason"]


def test_ack_plan_rejects_wrong_state_key() -> None:
    first, _backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id="codex-test",
        state_key="wrong.state.key",
        applied_rrule=first["codex_app"]["recommended_rrule"],
    )
    assert plan["ok"] is False
    assert "--state-key" in plan["reason"]


def test_ack_plan_rejects_wrong_reset_token() -> None:
    first, backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id="codex-test",
        state_key=backoff["state_key"],
        applied_rrule=first["codex_app"]["recommended_rrule"],
        reset_token="wrong-reset-token",
    )
    assert plan["ok"] is False
    assert "--reset-token" in plan["reason"]


def test_ack_plan_rejects_wrong_identity_signature() -> None:
    first, backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id="codex-test",
        state_key=backoff["state_key"],
        applied_rrule=first["codex_app"]["recommended_rrule"],
        identity_signature="wrong-identity",
    )
    assert plan["ok"] is False
    assert "--identity-signature" in plan["reason"]


def test_ack_plan_rejects_missing_rrule() -> None:
    first, backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id="codex-test",
        state_key=backoff["state_key"],
    )
    assert plan["ok"] is False
    assert "--applied-rrule" in plan["reason"]


def test_ack_plan_rejects_mismatched_rrule() -> None:
    first, backoff = _ack_fixture()
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": first},
        agent_id="codex-test",
        state_key=backoff["state_key"],
        applied_rrule="FREQ=MINUTELY;INTERVAL=99",
    )
    assert plan["ok"] is False
    assert "does not match expected" in plan["reason"]


def test_ack_plan_already_applied_returns_early_ok() -> None:
    payload = _active_payload()
    first = _build_hint(payload)
    state = _state_from_hint(first)
    steady = _build_hint(payload, scheduler_state=state)
    steady_backoff = steady["codex_app"]["stateful_backoff"]
    plan = build_scheduler_ack_plan(
        {"scheduler_hint": steady},
        agent_id="codex-test",
        state_key=steady_backoff["state_key"],
    )
    assert plan == {"ok": True, "already_applied": True, "applied_rrule": ""}


# ── scheduler state scope validation ─────────────────────────────────────────


def test_cross_agent_state_write_is_rejected(tmp_path) -> None:
    payload = _active_payload()
    first = _build_hint(payload)
    state = _state_from_hint(first)
    corrupt = dict(state)
    corrupt["agent_id"] = "codex-other-agent"
    with pytest.raises(ValueError, match="target scope or schema"):
        write_scheduler_state(
            tmp_path, corrupt, goal_id="test-goal", agent_id="codex-test"
        )


def test_corrupt_stored_state_ignored_on_load(tmp_path) -> None:
    import json
    payload = _active_payload()
    first = _build_hint(payload)
    valid_state = _state_from_hint(first)
    write_scheduler_state(tmp_path, valid_state, goal_id="test-goal", agent_id="codex-test")
    loaded = load_scheduler_state(tmp_path, goal_id="test-goal", agent_id="codex-test")
    assert loaded == valid_state

    corrupt = dict(valid_state)
    corrupt["agent_id"] = "codex-other-agent"
    state_files = list(tmp_path.rglob("*.json"))
    assert state_files
    state_files[0].write_text(json.dumps(corrupt, sort_keys=True) + "\n", encoding="utf-8")
    assert load_scheduler_state(tmp_path, goal_id="test-goal", agent_id="codex-test") is None


def test_monitor_target_change_negative_does_not_continue_same_chain() -> None:
    """Mutation: a different monitor target should NOT continue the same backoff."""
    first = _monitor_wait_payload()
    first_hint = _build_hint(first)
    state = _state_from_hint(first_hint)
    second = _monitor_wait_payload()
    second["agent_todo_summary"] = {
        "current_agent_claimed_monitor_items": [
            {
                "todo_id": "todo_different_target",
                "priority": "P1",
                "task_class": "continuous_monitor",
                "target_key": "different-target",
                "cadence": "5m",
            }
        ]
    }
    result = _build_hint(second, scheduler_state=state)
    backoff = result["codex_app"]["stateful_backoff"]
    assert backoff["state_status"] in {"reset_required", "missing"}
