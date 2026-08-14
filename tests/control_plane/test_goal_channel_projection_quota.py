from __future__ import annotations

from loopx.control_plane.goals.goal_channel_projection import (
    _compact_quota,
    _compact_policy_decision,
    _compact_scheduler_hint,
)


def _scheduler_hint_payload() -> dict:
    return {
        "schema_version": "scheduler_hint_v0",
        "source": "quota.should-run",
        "action": "backoff",
        "cadence_class": "agent_monitor_only",
        "reason_code": "agent_monitor_only_quiet_poll",
        "reason": "Agent is in monitor-only quiet poll; hold cadence.",
        "spend_policy": "no quota spend for monitor-only wait",
        "codex_app": {
            "applicability": "applies",
            "apply": "reschedule",
            "host_action": "reschedule_heartbeat",
        },
        "heartbeat_recommendation": {
            "recommended_mode": "resume",
            "cadence_class": "agent_monitor_only",
            "recommended_interval_seconds": 900,
        },
    }


def _policy_decision_payload() -> dict:
    return {
        "outcome": "wait",
        "source": "quota",
        "reason": "Quota slot exhausted; back off before next poll.",
        "retry_after_seconds": 300,
        "manual_approval_required": False,
    }


def test_compact_quota_passes_through_scheduler_hint_and_policy_decision() -> None:
    quota = {
        "state": "paused",
        "reason": "agent monitor-only",
        "spend_policy": "pause",
        "scheduler_hint": _scheduler_hint_payload(),
        "policy_decision": _policy_decision_payload(),
        "scheduler_rrule": "FREQ=HOURLY;INTERVAL=1",
        "scheduler_reset_token": "tok-123",
        "cadence_class": "agent_monitor_only",
    }
    compact = _compact_quota({"quota": quota}, {})

    # Legacy scalar fields preserved.
    assert compact["state"] == "paused"
    assert compact["reason"] == "agent monitor-only"
    assert compact["spend_policy"] == "pause"

    # New-architecture scheduler hint surfaced (whitelisted public fields only).
    hint = compact["scheduler_hint"]
    assert hint["action"] == "backoff"
    assert hint["cadence_class"] == "agent_monitor_only"
    assert hint["heartbeat_recommendation"]["recommended_interval_seconds"] == "900"
    # Raw/private nested structures (codex_app) are not copied.
    assert "codex_app" not in hint

    # Unified policy decision surfaced.
    policy = compact["policy_decision"]
    assert policy["outcome"] == "wait"
    assert policy["retry_after_seconds"] == "300"

    # Top-level cadence scalars surfaced for frontstage direct reads.
    assert compact["scheduler_rrule"] == "FREQ=HOURLY;INTERVAL=1"
    assert compact["scheduler_reset_token"] == "tok-123"
    assert compact["cadence_class"] == "agent_monitor_only"


def test_compact_quota_unchanged_when_no_new_architecture_fields() -> None:
    quota = {
        "state": "ok",
        "reason": "quota available",
        "spend_policy": "proceed",
        "spent_slots": 1,
        "allowed_slots": 5,
    }
    compact = _compact_quota({"quota": quota}, {})

    # Byte-identical to the pre-Phase-5 shape: only the five legacy scalars.
    assert compact == {
        "state": "ok",
        "reason": "quota available",
        "spend_policy": "proceed",
        "spent_slots": "1",
        "allowed_slots": "5",
    }


def test_compact_scheduler_hint_returns_none_for_empty_or_non_mapping() -> None:
    assert _compact_scheduler_hint(None) is None
    assert _compact_scheduler_hint({}) is None
    assert _compact_scheduler_hint("not-a-mapping") is None


def test_compact_policy_decision_returns_none_for_empty_or_non_mapping() -> None:
    assert _compact_policy_decision(None) is None
    assert _compact_policy_decision({}) is None
    assert _compact_policy_decision("not-a-mapping") is None


def test_compact_quota_falls_back_to_project_asset_source() -> None:
    project_asset = {
        "quota": {
            "state": "ok",
            "spend_policy": "proceed",
            "policy_decision": {"outcome": "run", "source": "quota", "reason": "go"},
        }
    }
    compact = _compact_quota({}, project_asset)
    assert compact["state"] == "ok"
    assert compact["policy_decision"]["outcome"] == "run"
