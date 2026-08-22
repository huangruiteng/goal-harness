from __future__ import annotations

from loopx.control_plane.quota.should_run import build_quota_should_run
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
)


GOAL_ID = "delivery-continuity-fixture"
AGENT_ID = "codex-main"
CURRENT_TODO_ID = "todo_current001"
QUEUE_HEAD_TODO_ID = "todo_queuehead001"


def _status(
    *, delivery_outcome: str = "outcome_progress", current_status: str = "open"
):
    queue_head = quota_todo_item(
        todo_id=QUEUE_HEAD_TODO_ID,
        index=1,
        priority="P1",
        title="Start the newly queued sibling slice.",
        claimed_by=AGENT_ID,
    )
    current = quota_todo_item(
        todo_id=CURRENT_TODO_ID,
        index=2,
        priority="P1",
        status=current_status,
        title="Continue the already validated implementation slice.",
        claimed_by=AGENT_ID,
    )
    return quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[queue_head, current],
        recommended_action=queue_head["text"],
        next_action=queue_head["text"],
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [AGENT_ID],
        },
        claim_scope_agent_id=AGENT_ID,
        latest_runs=[
            {
                "generated_at": "2026-08-22T10:00:00Z",
                "classification": "bounded_implementation_progress",
                "progress_scope": "agent_lane",
                "agent_id": AGENT_ID,
                "todo_id": CURRENT_TODO_ID,
                "delivery_outcome": delivery_outcome,
                "recommended_action": current["text"],
            }
        ],
    )


def test_same_open_todo_survives_cross_heartbeat_queue_reordering() -> None:
    packet = build_quota_should_run(
        _status(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert packet["selected_todo"]["todo_id"] == CURRENT_TODO_ID
    assert packet["agent_lane_next_action"]["selected_by"] == "in_flight_todo"
    assert packet["agent_lane_next_action"]["selection_reason"] == (
        "same_open_todo_after_progress"
    )
    assert packet["delivery_continuity"] == {
        "schema_version": "loopx_delivery_continuity_result_v0",
        "decision": "resume_in_flight",
        "reason": "same_open_todo_after_progress",
        "todo_id": CURRENT_TODO_ID,
        "delivery_boundary": "in_flight_continuation",
    }


def test_outcome_gap_releases_normal_queue_selection() -> None:
    packet = build_quota_should_run(
        _status(delivery_outcome="outcome_gap"),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert packet["selected_todo"]["todo_id"] == QUEUE_HEAD_TODO_ID
    assert packet["delivery_continuity"]["decision"] == "release_for_reselection"
    assert packet["delivery_continuity"]["reason"] == ("previous_delivery_not_progress")


def test_closed_or_blocked_todo_releases_normal_queue_selection() -> None:
    packet = build_quota_should_run(
        _status(current_status="blocked"),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )

    assert packet["selected_todo"]["todo_id"] == QUEUE_HEAD_TODO_ID
    assert packet["delivery_continuity"]["reason"] in {
        "todo_not_open",
        "todo_not_actionable",
    }


def test_same_turn_receipt_still_outranks_cross_heartbeat_continuity() -> None:
    packet = build_quota_should_run(
        _status(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        receipt_bound_todo_id=QUEUE_HEAD_TODO_ID,
    )

    assert packet["selected_todo"]["todo_id"] == QUEUE_HEAD_TODO_ID
    assert packet["agent_lane_next_action"]["selection_binding"] == (
        "heartbeat_receipt"
    )
    assert packet["delivery_continuity"]["decision"] == "preempt"
    assert packet["delivery_continuity"]["reason"] == "heartbeat_receipt"
