from __future__ import annotations

import json

import pytest

from loopx.control_plane.scheduler.ack import (
    build_codex_app_scheduler_ack_event,
    build_scheduler_ack_plan,
)
from loopx.control_plane.scheduler.scheduler_hint import (
    build_codex_app_scheduler_ack_hint,
)
from loopx.control_plane.scheduler.state import (
    CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    CODEX_APP_SURFACE,
    SCHEDULER_STATE_SCHEMA_VERSION,
    load_scheduler_state,
    write_scheduler_state,
)


AGENT_ID = "codex-scheduler-ack-table"
EXPECTED_RRULE = "FREQ=MINUTELY;INTERVAL=30"
RESET_TOKEN = "reset-token"
IDENTITY_SIGNATURE = "identity-signature"
STALE_WITHIN = "FREQ=MINUTELY;INTERVAL=31"


def _decision(*, cadence_class: str = "active_work") -> dict:
    return {
        "goal_id": "goal-ack-decision-table",
        "scheduler_hint": {
            "cadence_class": cadence_class,
            "codex_app": {
                "recommended_rrule": EXPECTED_RRULE,
                "example_progression_minutes": [15, 30, 60],
                "stateful_backoff": {
                    "state_key": CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
                    "current_rrule": EXPECTED_RRULE,
                    "progression_index": 1,
                    "apply_needed": True,
                    "ack_needed": False,
                    "reset_token": RESET_TOKEN,
                    "identity_signature": IDENTITY_SIGNATURE,
                },
            },
        }
    }


ACK_DECISION_CASES = [
    {
        "id": "exact_apply_ack",
        "rrule": EXPECTED_RRULE,
        "expected": {"ok": True, "already_applied": False},
    },
    {
        "id": "exact_host_match_ack",
        "rrule": EXPECTED_RRULE,
        "apply": False,
        "ack": True,
        "expected": {"ok": True, "host_match_ack": True},
    },
    {
        "id": "monitor_stale_hint_within_tolerance",
        "cadence": "monitor_wait",
        "rrule": STALE_WITHIN,
        "proof": True,
        "expected": {"ok": True, "stale_hint_accepted": True},
    },
    {
        "id": "monitor_stale_hint_below_current",
        "cadence": "monitor_wait",
        "rrule": "FREQ=MINUTELY;INTERVAL=29",
        "proof": True,
        "expected": {"ok": False},
    },
    {
        "id": "monitor_stale_hint_outside_tolerance",
        "cadence": "monitor_wait",
        "rrule": "FREQ=MINUTELY;INTERVAL=33",
        "proof": True,
        "expected": {"ok": False},
    },
    {
        "id": "monitor_stale_hint_without_identity_proof",
        "cadence": "monitor_wait",
        "rrule": STALE_WITHIN,
        "expected": {"ok": False},
    },
    {
        "id": "non_monitor_never_accepts_stale_hint",
        "rrule": STALE_WITHIN,
        "proof": True,
        "expected": {"ok": False},
    },
    {
        "id": "missing_rrule_while_ack_required",
        "rrule": None,
        "expected": {"ok": False},
    },
    {
        "id": "steady_state_needs_no_ack",
        "rrule": None,
        "apply": False,
        "expected": {"ok": True, "already_applied": True},
    },
]


@pytest.mark.parametrize(
    "case",
    ACK_DECISION_CASES,
    ids=[case["id"] for case in ACK_DECISION_CASES],
)
def test_scheduler_ack_decision_table(case: dict) -> None:
    decision = _decision(cadence_class=case.get("cadence", "active_work"))
    stateful_backoff = decision["scheduler_hint"]["codex_app"]["stateful_backoff"]
    stateful_backoff["apply_needed"] = case.get("apply", True)
    stateful_backoff["ack_needed"] = case.get("ack", False)

    result = build_scheduler_ack_plan(
        decision,
        agent_id=AGENT_ID,
        applied_rrule=case["rrule"],
        reset_token=RESET_TOKEN if case.get("proof") else None,
        identity_signature=IDENTITY_SIGNATURE if case.get("proof") else None,
    )

    expected = case["expected"]
    assert {key: result.get(key) for key in expected} == expected


@pytest.mark.parametrize(
    ("mutation", "expected_reason_fragment"),
    [
        ("missing_agent", "--agent-id"),
        ("wrong_state_key", "--state-key"),
        ("wrong_reset_token", "--reset-token"),
        ("wrong_identity_signature", "--identity-signature"),
    ],
)
def test_scheduler_ack_scope_proof_rejects_mutations(
    mutation: str,
    expected_reason_fragment: str,
) -> None:
    decision = _decision()
    kwargs = {
        "agent_id": AGENT_ID,
        "state_key": CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
        "applied_rrule": EXPECTED_RRULE,
        "reset_token": RESET_TOKEN,
        "identity_signature": IDENTITY_SIGNATURE,
    }
    if mutation == "missing_agent":
        kwargs["agent_id"] = None
    elif mutation == "wrong_state_key":
        kwargs["state_key"] = "scheduler.wrong.state"
    elif mutation == "wrong_reset_token":
        kwargs["reset_token"] = "wrong-reset"
    elif mutation == "wrong_identity_signature":
        kwargs["identity_signature"] = "wrong-identity"

    result = build_scheduler_ack_plan(decision, **kwargs)

    assert result["ok"] is False
    assert expected_reason_fragment in result["reason"]


def test_monitor_stale_ack_event_persists_the_observed_rrule() -> None:
    decision = _decision(cadence_class="monitor_wait")

    event = build_codex_app_scheduler_ack_event(
        decision,
        agent_id=AGENT_ID,
        applied_rrule=STALE_WITHIN,
        reset_token=RESET_TOKEN,
        identity_signature=IDENTITY_SIGNATURE,
        generated_at="2026-01-01T12:00:00+00:00",
    )["scheduler_ack_event"]

    assert event["applied_rrule"] == STALE_WITHIN
    assert event["expected_rrule"] == EXPECTED_RRULE
    assert event["stale_hint_accepted"] is True
    assert event["scheduler_state"]["last_applied_rrule"] == STALE_WITHIN


STATE_SCOPE_MUTATIONS = [
    ("schema_version", "scheduler_state_v999"),
    ("goal_id", "wrong-goal"),
    ("agent_id", "wrong-agent"),
    ("surface", "wrong-surface"),
    ("state_key", "scheduler.wrong.state"),
]


@pytest.mark.parametrize(
    ("field", "mutated_value"),
    STATE_SCOPE_MUTATIONS,
    ids=[field for field, _ in STATE_SCOPE_MUTATIONS],
)
def test_scheduler_state_scope_mutations_fail_closed(
    tmp_path,
    field: str,
    mutated_value: str,
) -> None:
    valid_state = {
        "schema_version": SCHEDULER_STATE_SCHEMA_VERSION,
        "goal_id": "goal-ack-decision-table",
        "agent_id": AGENT_ID,
        "surface": CODEX_APP_SURFACE,
        "state_key": CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
        "reset_token": RESET_TOKEN,
        "identity_signature": IDENTITY_SIGNATURE,
        "progression_index": 0,
        "progression_minutes": [30],
        "last_applied_rrule": EXPECTED_RRULE,
        "updated_at": "2026-01-01T12:00:00+00:00",
    }
    state_path = write_scheduler_state(
        tmp_path,
        valid_state,
        goal_id=valid_state["goal_id"],
        agent_id=valid_state["agent_id"],
    )
    mutated_state = {**valid_state, field: mutated_value}
    state_path.write_text(
        json.dumps(mutated_state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert (
        load_scheduler_state(
            tmp_path,
            goal_id=valid_state["goal_id"],
            agent_id=valid_state["agent_id"],
        )
        is None
    )
    with pytest.raises(ValueError, match="target scope or schema"):
        write_scheduler_state(
            tmp_path,
            mutated_state,
            goal_id=valid_state["goal_id"],
            agent_id=valid_state["agent_id"],
        )


def test_scheduler_ack_hint_preserves_public_contract_and_runtime_capabilities() -> None:
    hint = build_codex_app_scheduler_ack_hint(
        goal_id="goal-ack-contract",
        agent_id=AGENT_ID,
        applied_rrule=EXPECTED_RRULE,
        reset_token=RESET_TOKEN,
        identity_signature=IDENTITY_SIGNATURE,
        available_capabilities=["shell", "network", "benchmark_runner"],
        host_match_observed=True,
    )

    assert {
        "schema_version": hint["schema_version"],
        "command": hint["command"],
        "execute": hint["execute"],
        "uses_current_hint": hint["uses_current_hint"],
        "no_spend": hint["no_spend"],
    } == {
        "schema_version": "codex_app_scheduler_ack_hint_v0",
        "command": "quota scheduler-ack-current",
        "execute": True,
        "uses_current_hint": True,
        "no_spend": True,
    }
    assert hint["args"]["available_capabilities"] == [
        "network",
        "benchmark_runner",
    ]
    assert hint["args"]["host_match_observed"] is True
    assert hint["cli_args"] == [
        "quota",
        "scheduler-ack-current",
        "--goal-id",
        "goal-ack-contract",
        "--agent-id",
        AGENT_ID,
        "-A",
        "--available-capability",
        "network",
        "--available-capability",
        "benchmark_runner",
        "--applied-rrule",
        EXPECTED_RRULE,
        "--host-match-observed",
        "--reset-token",
        RESET_TOKEN,
        "--identity-signature",
        IDENTITY_SIGNATURE,
        "--execute",
    ]
