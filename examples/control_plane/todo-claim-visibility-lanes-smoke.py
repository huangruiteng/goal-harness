#!/usr/bin/env python3
"""Smoke-test todo claim visibility lane projection helpers."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.todos.claim_visibility import (  # noqa: E402
    TODO_AGENT_CLAIM_SCOPE_SCHEMA_VERSION,
    build_agent_claim_scoped_open_items,
    build_todo_claim_visibility_lanes,
)
from loopx.quota import build_quota_should_run  # noqa: E402
from work_lane_contract_fixtures import GOAL_ID, status_payload  # noqa: E402


CURRENT_AGENT = "codex-product-capability"
OTHER_AGENT = "codex-main-control"


def todo(
    todo_id: str,
    *,
    index: int,
    text: str,
    task_class: str,
    claimed_by: str | None = None,
    continuation_policy: str | None = None,
    blocks_agent: str | None = None,
) -> dict:
    item = {
        "index": index,
        "todo_id": todo_id,
        "text": text,
        "status": "open",
        "task_class": task_class,
        "claimed_by": claimed_by,
        "continuation_policy": continuation_policy,
        "blocks_agent": blocks_agent,
        "required_write_scopes": [" loopx/** ", "loopx/**"],
        "decision_scope": "direction:action:claim",
    }
    return {key: value for key, value in item.items() if value is not None}


def assert_agent_claim_scope_prefers_current_then_unclaimed() -> None:
    current_p2 = todo(
        "todo_current_p2",
        index=4,
        text="[P2] Current agent lower priority.",
        task_class="advancement_task",
        claimed_by=CURRENT_AGENT,
    )
    current_p0 = todo(
        "todo_current_p0",
        index=5,
        text="[P0] Current agent higher priority.",
        task_class="advancement_task",
        claimed_by=CURRENT_AGENT,
    )
    unclaimed_p0 = todo(
        "todo_unclaimed_p0",
        index=1,
        text="[P0] Unclaimed high priority.",
        task_class="advancement_task",
    )
    other_p0 = todo(
        "todo_other_p0",
        index=2,
        text="[P0] Other agent work.",
        task_class="advancement_task",
        claimed_by=OTHER_AGENT,
    )
    open_items = [unclaimed_p0, other_p0, current_p2, current_p0]

    selectable, claim_scope = build_agent_claim_scoped_open_items(
        open_items,
        agent_identity={
            "agent_id": CURRENT_AGENT,
            "agent_model": "peer_v1",
        },
        diagnostic_item_limit=3,
    )
    assert [item["todo_id"] for item in selectable] == [
        "todo_current_p0",
        "todo_current_p2",
        "todo_unclaimed_p0",
    ], selectable
    assert claim_scope is not None, claim_scope
    assert claim_scope["schema_version"] == TODO_AGENT_CLAIM_SCOPE_SCHEMA_VERSION
    assert claim_scope["agent_id"] == CURRENT_AGENT
    assert claim_scope["agent_model"] == "peer_v1"
    assert "primary_agent" not in claim_scope
    assert claim_scope["selection_order"] == "current_agent_claimed_then_unclaimed"
    assert claim_scope["selectable_open_count"] == 3
    assert claim_scope["current_agent_claimed_open_count"] == 2
    assert claim_scope["unclaimed_open_count"] == 1
    assert claim_scope["other_agent_claimed_open_count"] == 1
    assert claim_scope["other_agent_claimed_weight"] == "diagnostic_only"
    assert claim_scope["other_agent_claimed_items"][0]["todo_id"] == "todo_other_p0"
    assert claim_scope["blocked_claimed_items"][0]["todo_id"] == "todo_other_p0"


def assert_review_handoff_excludes_only_the_blocked_peer() -> None:
    review = todo(
        "todo_review",
        index=1,
        text="[P0] Review the peer implementation.",
        task_class="advancement_task",
        continuation_policy="review_handoff",
        blocks_agent=CURRENT_AGENT,
    )
    fallback = todo(
        "todo_fallback",
        index=2,
        text="[P1] Continue the current peer lane.",
        task_class="advancement_task",
    )

    blocked_selectable, blocked_scope = build_agent_claim_scoped_open_items(
        [review, fallback],
        agent_identity={"agent_id": CURRENT_AGENT, "agent_model": "peer_v1"},
        diagnostic_item_limit=3,
    )
    assert [item["todo_id"] for item in blocked_selectable] == ["todo_fallback"]
    assert blocked_scope is not None
    assert blocked_scope["review_handoff_blocked_self_count"] == 1
    assert blocked_scope["review_handoff_blocked_self_items"][0]["todo_id"] == (
        "todo_review"
    )
    assert blocked_scope["review_handoff_eligibility_policy"] == (
        "blocks_agent_cannot_review"
    )

    reviewer_selectable, reviewer_scope = build_agent_claim_scoped_open_items(
        [review, fallback],
        agent_identity={"agent_id": OTHER_AGENT, "agent_model": "peer_v1"},
        diagnostic_item_limit=3,
    )
    assert [item["todo_id"] for item in reviewer_selectable] == [
        "todo_review",
        "todo_fallback",
    ]
    assert reviewer_scope is not None
    assert reviewer_scope["review_handoff_blocked_self_count"] == 0

    invalid_claim = dict(review, claimed_by=CURRENT_AGENT)
    invalid_selectable, invalid_scope = build_agent_claim_scoped_open_items(
        [invalid_claim],
        agent_identity={"agent_id": CURRENT_AGENT, "agent_model": "peer_v1"},
        diagnostic_item_limit=3,
    )
    assert invalid_selectable == []
    assert invalid_scope is not None
    assert invalid_scope["review_handoff_blocked_self_count"] == 1


def assert_quota_routes_unclaimed_review_to_an_eligible_peer() -> None:
    review = todo(
        "todo_unclaimed_review",
        index=1,
        text="[P0] Review the peer implementation before delivery.",
        task_class="advancement_task",
        continuation_policy="review_handoff",
        blocks_agent=CURRENT_AGENT,
    )
    fallback = todo(
        "todo_side_fallback",
        index=2,
        text="[P1] Continue the blocked peer's independent fallback.",
        task_class="advancement_task",
        claimed_by=CURRENT_AGENT,
    )
    for item in (review, fallback):
        item["role"] = "agent"
        item["required_capabilities"] = ["shell"]
    coordination = {
        "agent_model": "peer_v1",
        "registered_agents": [OTHER_AGENT, CURRENT_AGENT],
    }

    def guard(agent_id: str) -> dict:
        return build_quota_should_run(
            status_payload(
                status="review_handoff_eligibility_frontier",
                next_action=review["text"],
                coordination=coordination,
                agent_todo_items=[review, fallback],
            ),
            goal_id=GOAL_ID,
            agent_id=agent_id,
        )

    blocked_guard = guard(CURRENT_AGENT)
    assert blocked_guard["agent_lane_next_action"]["todo_id"] == (
        "todo_side_fallback"
    ), blocked_guard
    assert [
        item["todo_id"]
        for item in blocked_guard["capability_gate"]["runnable_candidates"]
    ] == ["todo_side_fallback"], blocked_guard

    reviewer_guard = guard(OTHER_AGENT)
    assert reviewer_guard["agent_lane_next_action"]["todo_id"] == (
        "todo_unclaimed_review"
    ), reviewer_guard
    assert reviewer_guard["recommended_action"] == review["text"], reviewer_guard


def assert_claim_visibility_lanes_split_current_other_and_task_class() -> None:
    open_items = [
        todo(
            "todo_unclaimed_p0",
            index=1,
            text="[P0] Unclaimed high priority.",
            task_class="advancement_task",
        ),
        todo(
            "todo_current_advancement",
            index=2,
            text="[P1] Current advancement.",
            task_class="advancement_task",
            claimed_by=CURRENT_AGENT,
        ),
        todo(
            "todo_current_monitor",
            index=3,
            text="[P1 monitor] Current monitor.",
            task_class="continuous_monitor",
            claimed_by=CURRENT_AGENT,
        ),
        todo(
            "todo_other_advancement",
            index=4,
            text="[P1] Other advancement.",
            task_class="advancement_task",
            claimed_by=OTHER_AGENT,
        ),
    ]

    lanes = build_todo_claim_visibility_lanes(
        open_items,
        agent_identity={"agent_id": CURRENT_AGENT},
        backlog_item_limit=8,
        visibility_lane_limit=16,
    )
    assert lanes["unclaimed_priority_open_items"][0]["todo_id"] == "todo_unclaimed_p0"
    assert [item["todo_id"] for item in lanes["claimed_open_items"]] == [
        "todo_current_advancement",
        "todo_current_monitor",
        "todo_other_advancement",
    ], lanes
    assert lanes["claimed_advancement_open_count"] == 2, lanes
    assert lanes["claimed_monitor_open_count"] == 1, lanes
    assert lanes["current_agent_claimed_open_count"] == 2, lanes
    assert lanes["current_agent_claimed_advancement_count"] == 1, lanes
    assert lanes["current_agent_claimed_monitor_count"] == 1, lanes
    assert lanes["claimed_by_others_count"] == 1, lanes
    current = lanes["current_agent_claimed_advancement_items"][0]
    assert current["required_write_scopes"] == ["loopx/**"], current
    assert current["decision_scope"]["scope_key"] == "claim", current
    assert lanes["claimed_by_others_items"][0]["todo_id"] == "todo_other_advancement"


def main() -> int:
    assert_agent_claim_scope_prefers_current_then_unclaimed()
    assert_review_handoff_excludes_only_the_blocked_peer()
    assert_quota_routes_unclaimed_review_to_an_eligible_peer()
    assert_claim_visibility_lanes_split_current_other_and_task_class()
    print("todo-claim-visibility-lanes-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
