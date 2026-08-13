from __future__ import annotations

from dataclasses import replace

import pytest

from loopx.control_plane.goals.goal_frontier import (
    derive_goal_frontier_replan_obligation_from_summaries,
)
from loopx.control_plane.goals.goal_frontier.ack_policy import (
    replan_successor_transition_ack,
)
from loopx.control_plane.goals.goal_frontier.replan_rules import (
    GOAL_FRONTIER_REPLAN_RULE_ORDER,
    GoalFrontierReplanFacts,
    GoalFrontierReplanRule,
    select_goal_frontier_replan_rule,
)
from loopx.control_plane.todos.summary_item import compact_todo_summary_item


@pytest.mark.parametrize(
    ("overrides", "expected_rule", "derives_obligation"),
    [
        (
            {"existing_replan_required": True, "blocking_handoff_gate_count": 1},
            GoalFrontierReplanRule.EXISTING_OBLIGATION,
            False,
        ),
        (
            {"blocking_handoff_gate_count": 1, "acceptance_gap_count": 1},
            GoalFrontierReplanRule.BLOCKING_HANDOFF_GATE,
            False,
        ),
        (
            {"ready_deferred_successor_count": 1},
            GoalFrontierReplanRule.READY_DEFERRED_SUCCESSOR,
            False,
        ),
        (
            {"blocking_user_open_count": 1, "acceptance_gap_count": 1},
            GoalFrontierReplanRule.OPEN_USER_TODO,
            False,
        ),
        (
            {"succession_gap_count": 1, "acceptance_gap_count": 1},
            GoalFrontierReplanRule.TODO_SUCCESSION_GAP,
            True,
        ),
        (
            {"acceptance_gap_count": 1},
            GoalFrontierReplanRule.VISION_ACCEPTANCE_GAP,
            True,
        ),
        (
            {
                "acceptance_gap_count": 1,
                "selectable_frontier_advancement": 1,
                "outcome_checkpoint_replan_required": True,
            },
            GoalFrontierReplanRule.VISION_ACCEPTANCE_GAP,
            True,
        ),
        (
            {
                "long_todo_chain_triggered": True,
                "selectable_frontier_advancement": 15,
            },
            GoalFrontierReplanRule.LONG_TODO_CHAIN,
            True,
        ),
        (
            {
                "current_agent_blocker_count": 1,
                "monitor_no_change_streak_triggered": True,
                "monitor_only_lane": True,
                "monitor_count": 1,
            },
            GoalFrontierReplanRule.CURRENT_AGENT_BLOCKER,
            False,
        ),
        (
            {
                "monitor_no_change_streak_triggered": True,
                "monitor_only_lane": True,
                "monitor_count": 1,
                "total_frontier_advancement": 1,
            },
            GoalFrontierReplanRule.MONITOR_NO_CHANGE_STREAK,
            True,
        ),
        ({}, GoalFrontierReplanRule.NOT_MONITOR_ONLY, False),
        (
            {"monitor_only_lane": True},
            GoalFrontierReplanRule.NO_OPEN_MONITOR,
            False,
        ),
        (
            {
                "monitor_only_lane": True,
                "monitor_count": 1,
                "agent_advancement_count": 1,
                "total_frontier_advancement": 1,
            },
            GoalFrontierReplanRule.ADVANCEMENT_REMAINS,
            False,
        ),
        (
            {"monitor_only_lane": True, "monitor_count": 1},
            GoalFrontierReplanRule.MONITOR_FRONTIER_EXHAUSTED,
            True,
        ),
    ],
)
def test_goal_frontier_replan_decision_table(
    overrides: dict[str, object],
    expected_rule: GoalFrontierReplanRule,
    derives_obligation: bool,
) -> None:
    facts = replace(GoalFrontierReplanFacts(), **overrides)

    decision = select_goal_frontier_replan_rule(facts)

    assert decision.rule is expected_rule
    assert decision.derives_obligation is derives_obligation
    assert decision.to_payload()["rule_index"] == GOAL_FRONTIER_REPLAN_RULE_ORDER.index(
        expected_rule
    )


def _repeat_vision_gap() -> list[dict[str, object]]:
    return [
        {
            "kind": "vision_acceptance_gap",
            "acceptance_summary": "This agent must keep advancing its own stage.",
            "replan_trigger_summary": "No runnable work satisfies this agent's stage.",
            "advancement_policy": "repeat_until_closed",
        }
    ]


def _advancement(todo_id: str, claimed_by: str) -> dict[str, object]:
    return {
        "todo_id": todo_id,
        "status": "open",
        "task_class": "advancement_task",
        "claimed_by": claimed_by,
    }


@pytest.mark.parametrize("other_agent_count", [1, 2, 8])
def test_other_agent_backlog_size_cannot_satisfy_scoped_vision_gap(
    other_agent_count: int,
) -> None:
    other_items = [
        _advancement(f"todo_peer_{index}", f"peer-{index}")
        for index in range(other_agent_count)
    ]

    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 0},
        agent_todo_summary={
            "open_count": other_agent_count,
            "claimed_advancement_open_count": other_agent_count,
            "current_agent_claimed_advancement_count": 0,
            "unclaimed_priority_open_items": [],
            "executable_backlog_items": [],
            "claim_scope": {"other_agent_claimed_items": other_items},
        },
        work_lane_contract=None,
        agent_id="current-agent",
        existing_replan_obligation=None,
        acceptance_gaps=_repeat_vision_gap(),
    )

    assert obligation is not None
    assert obligation["agent_id"] == "current-agent"
    assert obligation["triggers"][0]["kind"] == "vision_acceptance_gap"


def test_current_agent_advancement_satisfies_scoped_vision_frontier() -> None:
    current_item = _advancement("todo_current", "current-agent")

    obligation = derive_goal_frontier_replan_obligation_from_summaries(
        user_todo_summary={"open_count": 0},
        agent_todo_summary={
            "open_count": 1,
            "claimed_advancement_open_count": 1,
            "current_agent_claimed_advancement_count": 1,
            "unclaimed_priority_open_items": [],
            "executable_backlog_items": [current_item],
            "claim_scope": {"other_agent_claimed_items": []},
        },
        work_lane_contract={"lane": "advancement_task", "must_attempt_work": True},
        agent_id="current-agent",
        existing_replan_obligation=None,
        acceptance_gaps=_repeat_vision_gap(),
    )

    assert obligation is None


def test_exact_replan_successor_uses_authoritative_todo_source() -> None:
    obligation_id = "replan-0123456789abcdef"
    frontier_identity = "progress:abcdef0123456789"
    successor = compact_todo_summary_item(
        {
            "todo_id": "todo_0123456789ab",
            "text": "Run the selected bounded experiment.",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": "current-agent",
            "replan_obligation_id": obligation_id,
        }
    )
    unrelated_display_items = [
        _advancement(f"todo_{index:012x}", "current-agent") for index in range(3)
    ]

    ack = replan_successor_transition_ack(
        {"first_executable_items": unrelated_display_items},
        agent_id="current-agent",
        replan_obligation={
            "obligation_id": obligation_id,
            "frontier_identity": frontier_identity,
            "satisfying_semantic_outcomes": ["new_runnable_successor"],
        },
        agent_todo_items=[*unrelated_display_items, successor],
    )

    assert successor["replan_obligation_id"] == obligation_id
    assert ack is not None
    assert ack["frontier_identity"] == frontier_identity
    assert ack["semantic_delta"]["successor_todo_id"] == successor["todo_id"]
    assert ack["semantic_delta"]["outcomes"] == ["new_runnable_successor"]


def test_unrelated_actionable_todo_cannot_close_replan() -> None:
    obligation_id = "replan-0123456789abcdef"

    ack = replan_successor_transition_ack(
        {"first_executable_items": []},
        agent_id="current-agent",
        replan_obligation={
            "obligation_id": obligation_id,
            "satisfying_semantic_outcomes": ["new_runnable_successor"],
        },
        agent_todo_items=[
            {
                **_advancement("todo_0123456789ab", "current-agent"),
                "replan_obligation_id": "replan-fedcba9876543210",
            }
        ],
    )

    assert ack is None


def test_empty_authoritative_todo_source_does_not_use_stale_display_item() -> None:
    obligation_id = "replan-0123456789abcdef"
    stale_display_item = {
        **_advancement("todo_0123456789ab", "current-agent"),
        "replan_obligation_id": obligation_id,
    }

    ack = replan_successor_transition_ack(
        {"first_executable_items": [stale_display_item]},
        agent_id="current-agent",
        replan_obligation={
            "obligation_id": obligation_id,
            "satisfying_semantic_outcomes": ["new_runnable_successor"],
        },
        agent_todo_items=[],
    )

    assert ack is None
