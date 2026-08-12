from __future__ import annotations

from loopx.control_plane import compact_control_plane_policy
from loopx.control_plane.goals.goal_frontier import (
    autonomous_replan_ack_satisfies_obligation,
)
from loopx.control_plane.runtime.agent_scoped_evidence_log import (
    build_agent_scoped_evidence_log_command,
    project_evidence_log_read_receipts,
)
from loopx.control_plane.scheduler.execution_context import (
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.control_plane.work_items.autonomous_replan_ack import (
    validate_replan_required_read_receipt,
)
from loopx.control_plane.work_items.autonomous_replan_obligation import (
    build_autonomous_replan_obligation_payload,
)
from loopx.quota import build_quota_should_run
from loopx.rollout_event_log import build_rollout_event

GOAL_ID = "replan-read-receipt-goal"
AGENT_ID = "codex-replan"
TRIGGERED_AT = "2026-08-12T01:00:00Z"
ACKED_AT = "2026-08-12T01:10:00Z"
COMMAND = (
    "loopx --format json evidence-log --goal-id replan-read-receipt-goal "
    "--agent-id codex-replan --thin --limit 24"
)


def _obligation(*, triggered_at: str = TRIGGERED_AT) -> dict[str, object]:
    return {
        "required": True,
        "triggers": [
            {
                "kind": "run_history_no_progress_repeat",
                "latest_generated_at": triggered_at,
            }
        ],
        "replan_novelty_policy": {
            "evidence_source": "agent_scoped_evidence_log",
            "writeback": "repair_delta",
        },
    }


def _ack() -> dict[str, object]:
    return {
        "recorded": True,
        "agent_id": AGENT_ID,
        "generated_at": ACKED_AT,
        "delta_contract": {
            "delta_present": True,
            "delta_kinds": ["runnable_todo_set"],
        },
    }


def _receipt(
    recorded_at: str,
    *,
    required_read_id: str | None = None,
    limit: int = 24,
) -> dict[str, object]:
    return {
        "schema_version": "evidence_log_read_receipt_v0",
        "event_id": f"receipt-{recorded_at}",
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "recorded_at": recorded_at,
        "command": build_agent_scoped_evidence_log_command(
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            limit=limit,
            required_read_id=required_read_id,
        ),
        "read_window": {
            "mode": "thin",
            "limit": limit,
        },
    }


def test_evidence_log_rollout_event_projects_a_machine_readable_receipt() -> None:
    event = build_rollout_event(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        event_kind="evidence_log_read",
        status="completed",
        recorded_at="2026-08-12T01:05:00Z",
        details={
            "command": COMMAND,
            "mode": "thin",
            "limit": 24,
            "history_limit": 80,
            "rollout_limit": 400,
        },
    )

    receipts = project_evidence_log_read_receipts([event])

    assert receipts == [
        {
            "schema_version": "evidence_log_read_receipt_v0",
            "event_id": event["event_id"],
            "goal_id": GOAL_ID,
            "agent_id": AGENT_ID,
            "recorded_at": "2026-08-12T01:05:00Z",
            "command": COMMAND,
            "read_window": {
                "mode": "thin",
                "limit": 24,
                "history_limit": 80,
                "rollout_limit": 400,
            },
        }
    ]


def test_soft_mode_accepts_ack_but_warns_when_required_read_is_missing() -> None:
    validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=_obligation(),
        receipts=[],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="soft",
    )

    assert validation is not None
    assert validation["accepted"] is True
    assert validation["required_read_satisfied"] is False
    assert validation["warnings"][0]["kind"] == "required_read_not_executed"
    assert COMMAND in validation["warnings"][0]["reason"]
    assert autonomous_replan_ack_satisfies_obligation(
        _ack(),
        replan_obligation=_obligation(),
        acceptance_gaps=None,
        required_read_validation=validation,
    )


def test_hard_mode_rejects_ack_when_required_read_is_missing() -> None:
    validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=_obligation(),
        receipts=[],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="hard",
    )

    assert validation is not None
    assert validation["accepted"] is False
    assert validation["required_read_satisfied"] is False
    assert validation["rejected_claims"][0]["kind"] == ("required_read_not_executed")
    assert not autonomous_replan_ack_satisfies_obligation(
        _ack(),
        replan_obligation=_obligation(),
        acceptance_gaps=None,
        required_read_validation=validation,
    )


def test_receipt_must_be_after_trigger_and_no_later_than_ack() -> None:
    stale = _receipt("2026-08-12T00:59:59Z")
    after_ack = _receipt("2026-08-12T01:10:01Z")
    fresh = _receipt("2026-08-12T01:05:00Z")

    stale_validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=_obligation(),
        receipts=[stale, after_ack],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="hard",
    )
    fresh_validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=_obligation(),
        receipts=[stale, fresh, after_ack],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="hard",
    )

    assert stale_validation is not None
    assert stale_validation["accepted"] is False
    assert stale_validation["rejected_claims"][0]["kind"] == (
        "required_read_not_executed"
    )
    assert fresh_validation is not None
    assert fresh_validation["accepted"] is True
    assert fresh_validation["required_read_satisfied"] is True
    assert fresh_validation["matched_receipt"]["event_id"] == fresh["event_id"]


def test_repeated_obligation_requires_a_receipt_after_its_new_trigger() -> None:
    first_receipt = _receipt("2026-08-12T01:05:00Z")
    repeated_obligation = _obligation(triggered_at="2026-08-12T01:06:00Z")

    repeated_validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=repeated_obligation,
        receipts=[first_receipt],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="hard",
    )

    assert repeated_validation is not None
    assert repeated_validation["accepted"] is False
    assert repeated_validation["triggered_at"] == "2026-08-12T01:06:00Z"


def test_receipt_must_match_the_projected_read_window() -> None:
    narrow_receipt = _receipt("2026-08-12T01:05:00Z", limit=0)

    validation = validate_replan_required_read_receipt(
        _ack(),
        replan_obligation=_obligation(),
        receipts=[narrow_receipt],
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        enforcement="hard",
    )

    assert validation is not None
    assert validation["accepted"] is False
    assert validation["required_read_satisfied"] is False


def test_control_plane_policy_defaults_soft_and_preserves_hard_opt_in() -> None:
    assert compact_control_plane_policy(
        {"replan_required_reads": {"enforcement": "soft"}}
    )["replan_required_reads"] == {"enforcement": "soft"}
    assert compact_control_plane_policy(
        {"replan_required_reads": {"enforcement": "hard"}}
    )["replan_required_reads"] == {"enforcement": "hard"}
    assert compact_control_plane_policy(
        {"replan_required_reads": {"enforcement": "unexpected"}}
    )["replan_required_reads"] == {"enforcement": "soft"}


def _quota_obligation() -> dict[str, object]:
    return build_autonomous_replan_obligation_payload(
        schema_version="autonomous_replan_obligation_v0",
        stall_threshold=2,
        trigger_count=1,
        triggers=[
            {
                "kind": "run_history_no_progress_repeat",
                "latest_generated_at": TRIGGERED_AT,
            }
        ],
        guidance_actions=["create_successor"],
        todo_actions=[],
        stop_condition="stop on owner-only authority",
        recommended_action="run a bounded replan",
        agent_id=AGENT_ID,
        include_agent_id=True,
    )


def _quota_payload(
    *,
    enforcement: str,
    receipts: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    obligation = _quota_obligation()
    status_payload = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        recommended_action="run a bounded replan",
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID],
        },
        latest_runs=[
            {
                "goal_id": GOAL_ID,
                "generated_at": ACKED_AT,
                "agent_id": AGENT_ID,
                "classification": "autonomous_replan_ack",
                "autonomous_replan_ack": {
                    "schema_version": "autonomous_replan_ack_v0",
                    "recorded": True,
                    "source": "refresh-state",
                    "delta_contract": {
                        "schema_version": "repair_delta_contract_v0",
                        "delta_present": True,
                        "delta_kinds": ["runnable_todo_set"],
                    },
                },
            }
        ],
        item_extra={
            "autonomous_replan_obligation": obligation,
            "evidence_log_read_receipts": receipts or [],
            "control_plane": {"replan_required_reads": {"enforcement": enforcement}},
        },
        project_asset_extra={
            "autonomous_replan_obligation": obligation,
        },
        goal_extra={
            "control_plane": {"replan_required_reads": {"enforcement": enforcement}}
        },
    )
    return build_quota_should_run(
        status_payload,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        scheduler_execution_context=(GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT),
    )


def test_quota_hard_mode_keeps_obligation_and_projects_actionable_feedback() -> None:
    payload = _quota_payload(enforcement="hard")

    assert payload["decision"] == "autonomous_replan_required"
    feedback = payload["replan_ack_feedback"]
    assert feedback["accepted"] is False
    assert feedback["rejected_claims"][0]["kind"] == ("required_read_not_executed")
    assert "--required-read-id" in feedback["required_read"]["command"]
    assert payload["autonomous_replan_obligation"]["replan_ack_feedback"] == (feedback)


def test_quota_hard_mode_accepts_matching_obligation_receipt() -> None:
    obligation = _quota_obligation()
    receipt = _receipt(
        "2026-08-12T01:05:00Z",
        required_read_id=str(obligation["obligation_id"]),
    )
    receipt["required_read_id"] = obligation["obligation_id"]
    payload = _quota_payload(enforcement="hard", receipts=[receipt])

    assert payload.get("autonomous_replan_obligation") is None
    assert payload.get("replan_ack_feedback") is None


def test_quota_soft_mode_closes_ack_but_keeps_warning_feedback() -> None:
    payload = _quota_payload(enforcement="soft")

    assert payload.get("autonomous_replan_obligation") is None
    assert payload["replan_ack_feedback"]["accepted"] is True
    assert payload["replan_ack_feedback"]["warnings"][0]["kind"] == (
        "required_read_not_executed"
    )
