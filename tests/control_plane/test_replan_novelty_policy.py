from __future__ import annotations

from loopx.control_plane.goals.goal_frontier import (
    align_autonomous_replan_guidance_with_acceptance_policy,
    compact_replan_obligation,
)
from loopx.control_plane.work_items.autonomous_replan_obligation import (
    build_autonomous_replan_obligation_payload,
)
from loopx.status import (
    DEAD_MONITOR_REPEAT_THRESHOLD,
    build_autonomous_replan_obligation,
)


def _obligation(evidence: list[dict[str, object]]) -> dict:
    obligation = build_autonomous_replan_obligation(evidence, agent_todos=None)
    assert obligation is not None, obligation
    return obligation


def test_generic_stall_obligation_carries_novelty_guidance() -> None:
    obligation = _obligation(
        [
            {
                "kind": "run_history_no_progress_repeat",
                "section": "run_history",
                "text": "two stalled turns repeated the same action",
            }
        ]
    )

    policy = obligation["replan_novelty_policy"]
    assert policy["schema_version"] == "replan_novelty_policy_v0"
    assert policy["review_evidence_log"] is True
    assert policy["prefer_unattempted_direction"] is True
    assert policy["repeated_blocker_restatement_rejected"] is True
    assert "exploration_exhausted_with_coverage_evidence" in policy[
        "no_new_direction_closure"
    ]

    action = obligation["recommended_action"]
    assert "evidence log" in action
    assert "not already covered" in action
    assert "Do not repeat an already-tried action" in action
    assert "exploration_exhausted" in action


def test_dead_monitor_obligation_policy_adds_watch_expiry_closure() -> None:
    obligation = _obligation(
        [
            {
                "kind": "dead_monitor_repeat",
                "monitor_target_id": "stable-monitor-target",
                "run_count": DEAD_MONITOR_REPEAT_THRESHOLD,
                "threshold": DEAD_MONITOR_REPEAT_THRESHOLD,
            }
        ]
    )

    policy = obligation["replan_novelty_policy"]
    assert policy["repeated_blocker_restatement_rejected"] is True
    assert policy["no_new_direction_closure"] == [
        "watch_lane_expiry",
        "exploration_exhausted_with_coverage_evidence",
    ]
    action = obligation["recommended_action"]
    assert "resolve a dead monitor loop" in action
    assert "evidence log" in action


def test_periodic_review_obligation_policy_is_not_repeated_stall() -> None:
    obligation = _obligation(
        [
            {
                "kind": "periodic_review_due",
                "section": "run_history",
                "text": "periodic review threshold reached",
            }
        ]
    )

    policy = obligation["replan_novelty_policy"]
    assert policy["repeated_blocker_restatement_rejected"] is False
    assert policy["review_evidence_log"] is True
    action = obligation["recommended_action"]
    assert "bounded autonomous periodic review" in action
    assert "evidence log" in action


def test_aligned_repeat_until_closed_guidance_keeps_novelty_hint() -> None:
    obligation = _obligation(
        [
            {
                "kind": "blocked_successor_no_progress_repeat",
                "section": "run_history",
                "text": "exact blocked successor waits repeated",
                "frontier_identity": "stable-frontier",
            }
        ]
    )
    aligned = align_autonomous_replan_guidance_with_acceptance_policy(
        obligation,
        acceptance_gaps=[
            {
                "kind": "vision_acceptance_gap",
                "advancement_policy": "repeat_until_closed",
            }
        ],
    )
    assert aligned is not None
    assert "watch-lane continuation alone does not satisfy" in aligned[
        "recommended_action"
    ]
    assert "evidence log" in aligned["recommended_action"]
    assert aligned["replan_novelty_policy"]["repeated_blocker_restatement_rejected"]


def test_compact_replan_obligation_preserves_novelty_policy() -> None:
    obligation = _obligation(
        [
            {
                "kind": "run_history_no_progress_repeat",
                "section": "run_history",
                "text": "two stalled turns repeated the same action",
            }
        ]
    )
    compact = compact_replan_obligation(obligation)
    assert compact["replan_novelty_policy"] == obligation["replan_novelty_policy"]


def test_payload_builder_defaults_to_novelty_guidance_and_policy() -> None:
    payload = build_autonomous_replan_obligation_payload(
        schema_version="autonomous_replan_obligation_v0",
        stall_threshold=1,
        trigger_count=1,
        triggers=[],
        guidance_actions=["create_successor"],
        todo_actions=[],
        stop_condition="stop on owner-only authority",
        recommended_action="run a bounded frontier replan",
    )

    assert "evidence log" in payload["recommended_action"]
    assert "prefer a direction not already covered" in payload["recommended_action"]
    policy = payload["replan_novelty_policy"]
    assert policy["review_evidence_log"] is True
    assert policy["repeated_blocker_restatement_rejected"] is False


def test_payload_builder_extra_fields_override_novelty_policy() -> None:
    payload = build_autonomous_replan_obligation_payload(
        schema_version="autonomous_replan_obligation_v0",
        stall_threshold=1,
        trigger_count=1,
        triggers=[],
        guidance_actions=[],
        todo_actions=[],
        stop_condition="stop on owner-only authority",
        recommended_action="run a bounded replan",
        extra_fields={
            "replan_novelty_policy": {
                "schema_version": "replan_novelty_policy_v0",
                "review_evidence_log": True,
                "prefer_unattempted_direction": True,
                "repeated_blocker_restatement_rejected": True,
                "no_new_direction_closure": ["watch_lane_expiry"],
            }
        },
    )

    assert payload["replan_novelty_policy"]["repeated_blocker_restatement_rejected"]
    assert payload["replan_novelty_policy"]["no_new_direction_closure"] == [
        "watch_lane_expiry"
    ]
