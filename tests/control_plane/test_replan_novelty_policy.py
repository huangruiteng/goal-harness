from __future__ import annotations

from loopx.control_plane.goals.goal_frontier import (
    align_autonomous_replan_guidance_with_acceptance_policy,
    autonomous_replan_scope_decision,
    compact_replan_obligation,
)
from loopx.control_plane.work_items.autonomous_replan_obligation import (
    build_autonomous_replan_obligation_payload,
)
from loopx.control_plane.quota.should_run_packet import _quota_required_reads
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
    assert policy["evidence_source"] == "agent_scoped_evidence_log"
    assert policy["writeback"] == "repair_delta"

    action = obligation["recommended_action"]
    assert "required_reads[0] (evidence-log)" in action
    assert "untried direction" in action
    assert "Reject repeats" in action
    assert "exploration_exhausted" in action


def test_dead_monitor_obligation_reuses_the_same_repair_delta_contract() -> None:
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
    assert policy["evidence_source"] == "agent_scoped_evidence_log"
    assert policy["writeback"] == "repair_delta"
    action = obligation["recommended_action"]
    assert "resolve a dead monitor loop" in action
    assert "required_reads[0] (evidence-log)" in action


def test_periodic_review_obligation_reuses_the_same_preflight_contract() -> None:
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
    assert policy["evidence_source"] == "agent_scoped_evidence_log"
    action = obligation["recommended_action"]
    assert "bounded autonomous periodic review" in action
    assert "required_reads[0] (evidence-log)" in action


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
    assert (
        "watch-lane continuation alone does not satisfy"
        in aligned["recommended_action"]
    )
    assert "required_reads[0] (evidence-log)" in aligned["recommended_action"]
    assert aligned["replan_novelty_policy"]["writeback"] == "repair_delta"


def test_compact_replan_obligation_keeps_only_authoritative_seam_refs() -> None:
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
    assert compact["replan_novelty_policy"] == {
        "evidence": "agent_scoped_evidence_log",
    }


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

    assert "required_reads[0] (evidence-log)" in payload["recommended_action"]
    assert "untried direction" in payload["recommended_action"]
    policy = payload["replan_novelty_policy"]
    assert policy["evidence_source"] == "agent_scoped_evidence_log"
    assert policy["writeback"] == "repair_delta"


def test_payload_builder_normalizes_legacy_policy_extra_fields() -> None:
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

    assert payload["replan_novelty_policy"] == {
        "schema_version": "replan_novelty_policy_v0",
        "evidence_source": "agent_scoped_evidence_log",
        "writeback": "repair_delta",
    }


def test_novelty_policy_materializes_the_evidence_log_provider() -> None:
    reads = _quota_required_reads(
        {
            "goal_id": "replan-goal",
            "agent_identity": {"agent_id": "codex-replan"},
            "autonomous_replan_obligation": {
                "replan_novelty_policy": {
                    "evidence": "agent_scoped_evidence_log",
                    "writeback": "repair_delta",
                }
            },
        }
    )

    assert reads[0]["kind"] == "agent_scoped_evidence_log"
    assert "evidence-log --goal-id replan-goal" in reads[0]["command"]
    assert "--agent-id codex-replan" in reads[0]["command"]
    assert "novelty policy evidence source" in reads[0]["reason"]


def test_generic_replan_without_novelty_policy_does_not_restore_the_old_hint() -> None:
    reads = _quota_required_reads(
        {
            "goal_id": "replan-goal",
            "effective_action": "autonomous_replan",
            "agent_identity": {"agent_id": "codex-replan"},
            "autonomous_replan_obligation": {},
        }
    )

    assert reads == []


def test_policy_normalization_precedes_deterministic_peer_scope_selection() -> None:
    obligation = _obligation([{"kind": "periodic_review_due", "source": "fixture"}])
    registered_agents = ["codex-primary", "codex-reviewer"]

    selected = {
        scope["selected_peer_agent"]
        for agent_id in registered_agents
        if (
            scope := autonomous_replan_scope_decision(
                obligation,
                agent_id=agent_id,
                registered_agent_ids=registered_agents,
            )
        )["applies"]
    }

    assert len(selected) == 1
    assert selected <= set(registered_agents)
