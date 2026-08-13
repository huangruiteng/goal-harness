from __future__ import annotations

import pytest

from loopx.control_plane.goals.goal_frontier import (
    acceptance_gaps_from_agent_vision,
    derive_goal_frontier_replan_obligation_from_summaries,
)
from loopx.control_plane.goals.goal_frontier.outcome_continuity import (
    acceptance_gaps_from_outcome_checkpoint,
    acceptance_gaps_from_todo_completion_checkpoint,
    latest_outcome_vision_checkpoint_from_status_payload,
)
from loopx.control_plane.todos.quota_summary import (
    compact_quota_todo_summary_for_payload,
    summarize_user_todos_for_quota,
)
from loopx.control_plane.todos.todo_summary import compact_todo_group

AGENT_ID = "fixture-agent"


def vision(state: str) -> dict[str, object]:
    return {
        "schema_version": "goal_vision_replan_contract_v0",
        "agent_id": AGENT_ID,
        "state": state,
        "vision_patch": {
            "vision_summary": "Complete one bounded stage.",
            "acceptance_summary": "Stage evidence is complete.",
        },
        "generated_at": "2026-07-12T00:00:00Z",
    }


@pytest.mark.parametrize("state", ["vision_closed", "closed", "satisfied"])
@pytest.mark.parametrize("goal_status", ["active", "active-read-only"])
def test_active_goal_closed_stage_requires_successor_vision(
    state: str,
    goal_status: str,
) -> None:
    gaps = acceptance_gaps_from_agent_vision(vision(state), goal_status=goal_status)

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_successor_required"
    assert gaps[0]["advancement_policy"] == "repeat_until_closed"


@pytest.mark.parametrize(
    ("state", "goal_status"),
    [
        ("vision_closed", "completed"),
        ("retired", "active"),
        ("retired_or_superseded", "active"),
        ("superseded", "active"),
        ("no_followup", "active"),
    ],
)
def test_terminal_goal_or_lane_closure_does_not_require_successor(
    state: str,
    goal_status: str,
) -> None:
    assert (
        acceptance_gaps_from_agent_vision(
            vision(state),
            goal_status=goal_status,
        )
        == []
    )


@pytest.mark.parametrize("ready_deferred_count", [0, 2])
def test_successor_vision_replan_precedes_existing_work(
    ready_deferred_count: int,
) -> None:
    gaps = acceptance_gaps_from_agent_vision(
        vision("vision_closed"),
        goal_status="active",
    )
    todo = {
        "todo_id": "todo_successor123",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": AGENT_ID,
    }
    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 0},
        agent_todo_summary={
            "open_count": 1,
            "current_agent_claimed_open_count": 1,
            "current_agent_claimed_advancement_count": 1,
            "current_agent_deferred_resume_count": ready_deferred_count,
            "unclaimed_open_count": 0,
            "executable_backlog_items": [todo],
        },
        work_lane_contract={
            "lane": "advancement_task",
            "must_attempt_work": True,
        },
        agent_id=AGENT_ID,
        existing_replan_obligation=None,
        acceptance_gaps=gaps,
    )

    assert obligation is not None
    assert obligation["required"] is True
    assert obligation["triggers"][0]["kind"] == "vision_successor_required"


def test_user_gate_still_precedes_successor_vision_replan() -> None:
    gaps = acceptance_gaps_from_agent_vision(
        vision("vision_closed"),
        goal_status="active",
    )
    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 1},
        agent_todo_summary={"open_count": 0},
        work_lane_contract={"lane": "advancement_task", "must_attempt_work": True},
        agent_id=AGENT_ID,
        existing_replan_obligation=None,
        acceptance_gaps=gaps,
    )

    assert obligation is None


def test_other_agent_work_does_not_satisfy_scoped_repeat_vision() -> None:
    active_vision = vision("vision_active")
    active_vision["vision_patch"]["advancement_policy"] = "repeat_until_closed"
    gaps = acceptance_gaps_from_agent_vision(active_vision, goal_status="active")
    other_agent_todo = {
        "todo_id": "todo_other_agent",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": "fixture-other-agent",
    }

    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 0},
        agent_todo_summary={
            "open_count": 1,
            "claimed_advancement_open_count": 1,
            "current_agent_claimed_advancement_count": 0,
            "unclaimed_priority_open_items": [],
            "executable_backlog_items": [],
            "claim_scope": {"other_agent_claimed_items": [other_agent_todo]},
        },
        work_lane_contract=None,
        agent_id=AGENT_ID,
        existing_replan_obligation=None,
        acceptance_gaps=gaps,
    )

    assert obligation is not None
    assert obligation["agent_id"] == AGENT_ID
    assert obligation["triggers"][0]["kind"] == "vision_acceptance_gap"
    assert obligation["todo_actions"][0]["action"] == "add"


def test_open_vision_projects_only_active_todo_delta_lineage() -> None:
    active_vision = vision("vision_active")
    active_vision["todo_delta"] = [
        "complete:todo_previous",
        "activate:todo_current",
        "create:todo_successor",
        "supersede:todo_obsolete",
    ]

    gaps = acceptance_gaps_from_agent_vision(
        active_vision,
        goal_status="active",
    )

    assert gaps[0]["vision_todo_ids"] == [
        "todo_current",
        "todo_successor",
    ]


def _outcome_vision(
    *,
    generated_at: str = "2026-07-12T00:01:00Z",
    outcome: str = "continue",
    evidence_refs: list[str] | None = None,
) -> dict[str, object]:
    packet = vision("vision_active")
    packet["generated_at"] = generated_at
    packet["path_delta"] = {
        "schema_version": "goal_path_delta_v0",
        "outcome": outcome,
        "evidence_refs": evidence_refs or [],
    }
    return packet


def _material_checkpoint(
    *,
    generated_at: str = "2026-07-12T00:01:00Z",
    decision: str = "patched",
) -> dict[str, object]:
    triggers: list[dict[str, object]] = [
        {
            "kind": "material_delivery_outcome",
            "delivery_outcome": "outcome_progress",
        }
    ]
    return {
        "schema_version": "vision_checkpoint_v0",
        "agent_id": AGENT_ID,
        "required": True,
        "satisfied": True,
        "decision": decision,
        "triggers": triggers,
        "generated_at": generated_at,
    }


def test_material_unchanged_checkpoint_rejects_stale_planning_evidence() -> None:
    active_vision = _outcome_vision(
        generated_at="2026-07-12T00:00:00Z",
        evidence_refs=["todo:planned-stage"],
    )
    checkpoint = _material_checkpoint(decision="unchanged_with_reason")

    gaps = acceptance_gaps_from_outcome_checkpoint(active_vision, checkpoint)

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_outcome_checkpoint_required"
    assert gaps[0]["fresh_vision_patch"] is False


def test_fresh_evidence_linked_continue_checkpoint_preserves_frontier() -> None:
    active_vision = _outcome_vision(evidence_refs=["result:final-outcome-receipt"])
    checkpoint = _material_checkpoint()

    assert acceptance_gaps_from_outcome_checkpoint(active_vision, checkpoint) == []


def test_unsatisfied_material_checkpoint_cannot_preserve_frontier() -> None:
    active_vision = _outcome_vision(evidence_refs=["result:final-outcome-receipt"])
    checkpoint = {**_material_checkpoint(), "satisfied": False}

    gaps = acceptance_gaps_from_outcome_checkpoint(active_vision, checkpoint)

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_outcome_checkpoint_required"


def test_fresh_evidence_linked_replan_checkpoint_preserves_frontier() -> None:
    active_vision = _outcome_vision(
        outcome="replan",
        evidence_refs=["result:outcome-conflict"],
    )
    checkpoint = _material_checkpoint()

    assert acceptance_gaps_from_outcome_checkpoint(active_vision, checkpoint) == []


@pytest.mark.parametrize(
    ("checkpoint_generated_at", "expects_gap"),
    [
        ("2026-07-12T00:01:00Z", True),
        ("2026-07-12T00:03:00Z", False),
    ],
)
def test_completed_todo_chain_requires_a_later_outcome_checkpoint(
    checkpoint_generated_at: str,
    expects_gap: bool,
) -> None:
    active_vision = _outcome_vision(
        generated_at=checkpoint_generated_at,
        evidence_refs=["result:completed-milestone"],
    )
    checkpoint = _material_checkpoint(generated_at=checkpoint_generated_at)
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_milestone_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": f"2026-07-12T00:02:0{index}Z",
            }
            for index in range(5)
        ]
    }

    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        active_vision,
        checkpoint,
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
    )

    assert bool(gaps) is expects_gap
    if expects_gap:
        assert gaps[0]["completed_todo_count"] == 5
        assert gaps[0]["completed_todo_threshold"] == 5


def test_completed_todo_chain_without_vision_baseline_still_requires_checkpoint() -> None:
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_no_vision_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": f"2026-07-12T00:02:0{index}Z",
            }
            for index in range(5)
        ]
    }

    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        None,
        None,
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
    )

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_outcome_checkpoint_required"
    assert gaps[0]["completed_todo_count"] == 5
    assert gaps[0]["completed_todo_threshold"] == 5
    assert "Write a bounded agent vision patch" in gaps[0]["acceptance_summary"]


def test_legacy_replan_checkpoint_does_not_cover_completed_chain() -> None:
    active_vision = _outcome_vision(
        generated_at="2026-07-12T00:03:00Z",
        outcome="replan",
        evidence_refs=["todo:bounded-watch"],
    )
    checkpoint = {
        "schema_version": "vision_checkpoint_v0",
        "agent_id": AGENT_ID,
        "required": True,
        "satisfied": True,
        "decision": "patched",
        "triggers": [{"kind": "autonomous_replan_recorded"}],
        "repair_delta_kinds": ["goal_vision_patch", "watch_lane_continuation"],
        "generated_at": "2026-07-12T00:03:00Z",
        "qualification_agent_vision": active_vision,
    }
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_milestone_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": f"2026-07-12T00:02:0{index}Z",
            }
            for index in range(5)
        ]
    }

    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        active_vision,
        checkpoint,
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
    )

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_outcome_checkpoint_required"


def test_four_completed_todos_do_not_force_a_chain_checkpoint() -> None:
    active_vision = _outcome_vision(
        generated_at="2026-07-12T00:01:00Z",
        evidence_refs=["result:bounded-progress"],
    )
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_slice_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": f"2026-07-12T00:02:0{index}Z",
            }
            for index in range(4)
        ]
    }

    assert (
        acceptance_gaps_from_todo_completion_checkpoint(
            active_vision,
            _material_checkpoint(generated_at="2026-07-12T00:01:00Z"),
            agent_todo_summary=summary,
            agent_id=AGENT_ID,
        )
        == []
    )


def test_qualified_checkpoint_resets_the_completed_todo_chain() -> None:
    active_vision = _outcome_vision(
        generated_at="2026-07-12T00:02:00Z",
        evidence_refs=["result:checkpointed-milestone"],
    )
    checkpoint = _material_checkpoint(generated_at="2026-07-12T00:02:00Z")
    completed_at = [
        "2026-07-12T00:01:00Z",
        "2026-07-12T00:03:00Z",
        "2026-07-12T00:04:00Z",
        "2026-07-12T00:05:00Z",
        "2026-07-12T00:06:00Z",
    ]
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_slice_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": timestamp,
            }
            for index, timestamp in enumerate(completed_at)
        ]
    }

    assert (
        acceptance_gaps_from_todo_completion_checkpoint(
            active_vision,
            checkpoint,
            agent_todo_summary=summary,
            agent_id=AGENT_ID,
        )
        == []
    )


def test_completed_chain_replan_precedes_runnable_advancement() -> None:
    active_vision = _outcome_vision(
        generated_at="2026-07-12T00:01:00Z",
        evidence_refs=["result:bounded-progress"],
    )
    completed_items = [
        {
            "todo_id": f"todo_completed_slice_{index}",
            "claimed_by": AGENT_ID,
            "completed_at": f"2026-07-12T00:02:0{index}Z",
        }
        for index in range(5)
    ]
    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        active_vision,
        _material_checkpoint(generated_at="2026-07-12T00:01:00Z"),
        agent_todo_summary={
            "recent_completed_advancement_items": completed_items,
        },
        agent_id=AGENT_ID,
    )
    runnable = {
        "todo_id": "todo_next_slice",
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": AGENT_ID,
    }

    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 0},
        agent_todo_summary={
            "open_count": 1,
            "current_agent_claimed_open_count": 1,
            "current_agent_claimed_advancement_count": 1,
            "unclaimed_open_count": 0,
            "executable_backlog_items": [runnable],
        },
        work_lane_contract={"lane": "advancement_task", "must_attempt_work": True},
        agent_id=AGENT_ID,
        existing_replan_obligation=None,
        acceptance_gaps=gaps,
    )

    assert obligation is not None
    trigger = obligation["triggers"][0]
    assert trigger["kind"] == "vision_outcome_checkpoint_required"
    assert trigger["completed_todo_count"] == 5
    assert trigger["completed_todo_threshold"] == 5


def test_plain_refresh_after_completed_todo_does_not_clear_checkpoint_gap() -> None:
    active_vision = _outcome_vision(generated_at="2026-07-12T00:00:00Z")
    checkpoint = {
        **_material_checkpoint(generated_at="2026-07-12T00:03:00Z"),
        "triggers": [{"kind": "heartbeat_refresh"}],
    }
    summary = {
        "recent_completed_advancement_items": [
            {
                "todo_id": f"todo_completed_milestone_{index}",
                "claimed_by": AGENT_ID,
                "completed_at": f"2026-07-12T00:02:0{index}Z",
            }
            for index in range(5)
        ]
    }

    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        active_vision,
        checkpoint,
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
    )

    assert len(gaps) == 1
    assert gaps[0]["kind"] == "vision_outcome_checkpoint_required"


def test_plain_refresh_does_not_supersede_older_material_checkpoint() -> None:
    status = {
        "run_history": {
            "goals": [
                {
                    "id": "goal-outcome",
                    "latest_runs": [
                        {
                            "agent_id": AGENT_ID,
                            "generated_at": "2026-07-12T00:03:00Z",
                            "vision_checkpoint": {
                                "agent_id": AGENT_ID,
                                "satisfied": True,
                                "decision": "not_required",
                                "triggers": [{"kind": "heartbeat_refresh"}],
                            },
                        },
                        {
                            "agent_id": AGENT_ID,
                            "generated_at": "2026-07-12T00:02:00Z",
                            "vision_checkpoint": _material_checkpoint(
                                generated_at="2026-07-12T00:02:00Z",
                                decision="unchanged_with_reason",
                            ),
                        },
                    ],
                }
            ]
        }
    }

    checkpoint = latest_outcome_vision_checkpoint_from_status_payload(
        status,
        goal_id="goal-outcome",
        agent_id=AGENT_ID,
    )

    assert checkpoint is not None
    assert checkpoint["generated_at"] == "2026-07-12T00:02:00Z"


def test_later_vision_patch_does_not_invalidate_qualified_checkpoint() -> None:
    qualified_vision = _outcome_vision(
        generated_at="2026-07-12T00:02:00Z",
        evidence_refs=["result:qualified-milestone"],
    )
    status = {
        "run_history": {
            "goals": [
                {
                    "id": "goal-outcome",
                    "latest_runs": [
                        {
                            "agent_id": AGENT_ID,
                            "generated_at": "2026-07-12T00:03:00Z",
                            "agent_vision": _outcome_vision(
                                generated_at="2026-07-12T00:03:00Z",
                                outcome="replan",
                                evidence_refs=["result:new-planning-evidence"],
                            ),
                        },
                        {
                            "agent_id": AGENT_ID,
                            "generated_at": "2026-07-12T00:02:00Z",
                            "agent_vision": qualified_vision,
                            "vision_checkpoint": _material_checkpoint(
                                generated_at="2026-07-12T00:02:00Z",
                            ),
                        },
                    ],
                }
            ]
        }
    }
    checkpoint = latest_outcome_vision_checkpoint_from_status_payload(
        status,
        goal_id="goal-outcome",
        agent_id=AGENT_ID,
    )

    assert checkpoint is not None
    assert (
        acceptance_gaps_from_outcome_checkpoint(
            _outcome_vision(generated_at="2026-07-12T00:03:00Z"),
            checkpoint,
        )
        == []
    )


def test_recent_completed_advancement_projection_is_agent_scoped() -> None:
    source = compact_todo_group(
        [
            *[
                {
                    "todo_id": f"todo_current_completed_{minute}",
                    "role": "agent",
                    "status": "done",
                    "done": True,
                    "text": "Complete a current-agent milestone.",
                    "task_class": "advancement_task",
                    "claimed_by": AGENT_ID,
                    "completed_at": f"2026-07-12T00:0{minute}:00Z",
                }
                for minute in range(1, 8)
            ],
            {
                "todo_id": "todo_other_completed",
                "role": "agent",
                "status": "done",
                "done": True,
                "text": "Complete another agent milestone.",
                "task_class": "advancement_task",
                "claimed_by": "other-agent",
                "completed_at": "2026-07-12T00:08:00Z",
            },
        ],
        source_section="Agent Todo",
        role="agent",
        include_empty_source=True,
        item_limit=None,
    )

    summary = summarize_user_todos_for_quota(
        source,
        agent_identity={"agent_id": AGENT_ID},
    )

    assert summary is not None
    assert len(summary["recent_completed_advancement_items"]) == 7
    payload = compact_quota_todo_summary_for_payload(summary)
    assert [
        item["todo_id"]
        for item in payload["recent_completed_advancement_items"]
    ] == [
        "todo_current_completed_7",
        "todo_current_completed_6",
        "todo_current_completed_5",
        "todo_current_completed_4",
        "todo_current_completed_3",
    ]
    gaps = acceptance_gaps_from_todo_completion_checkpoint(
        _outcome_vision(
            generated_at="2026-07-12T00:02:00Z",
            evidence_refs=["result:checkpointed-milestone"],
        ),
        _material_checkpoint(generated_at="2026-07-12T00:02:00Z"),
        agent_todo_summary=summary,
        agent_id=AGENT_ID,
    )
    assert gaps[0]["completed_todo_count"] == 5
    assert gaps[0]["completed_todo_threshold"] == 5
