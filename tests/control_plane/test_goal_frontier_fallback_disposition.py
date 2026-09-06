from __future__ import annotations

from typing import Any

import pytest

from loopx.control_plane.goals.goal_frontier import (
    VISION_FRONTIER_TODO_DELTA_ACTIONS,
    agent_scoped_selectable_advancement_todo_ids,
    build_goal_frontier_projection_context_from_status,
)
from loopx.control_plane.scheduler.execution_context import (
    GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT,
)
from loopx.control_plane.testing.quota_fixtures import (
    quota_status_payload,
    quota_todo_item,
    quota_todo_summary,
)
from loopx.control_plane.todos.projection import todo_advancement_frontier_counts
from loopx.quota import build_quota_should_run

GOAL_ID = "vision-fallback-disposition-fixture"
AGENT_ID = "codex-fallback-agent"
PRIMARY_AGENT = "codex-primary-agent"
PREREQ_ID = "todo_primary_prereq"
PRIMARY_WAIT_ID = "todo_primary_successor"
FALLBACK_ID = "todo_declared_fallback"
DECLARED_FALLBACK_ACCEPTANCE = (
    "Deliver the primary successor; if the primary stays blocked, "
    "deliver the declared fallback direction instead."
)


def _fallback_vision_run(
    *,
    state: str = "vision_drift_detected",
    todo_delta: list[str] | None = None,
    acceptance_summary: str = DECLARED_FALLBACK_ACCEPTANCE,
    path_outcome: str | None = None,
    fallback_declarations: list[Any] | None = None,
) -> dict:
    agent_vision: dict = {
        "schema_version": "goal_vision_replan_contract_v0",
        "agent_id": AGENT_ID,
        "state": state,
        "todo_delta": todo_delta
        if todo_delta is not None
        else [f"retain:{PRIMARY_WAIT_ID}"],
        "vision_patch": {
            "acceptance_summary": acceptance_summary,
            "replan_trigger_summary": "The primary acceptance remains open.",
            "advancement_policy": "repeat_until_closed",
        },
    }
    if fallback_declarations is not None:
        agent_vision["fallback_declarations"] = fallback_declarations
    elif acceptance_summary == DECLARED_FALLBACK_ACCEPTANCE:
        agent_vision["fallback_declarations"] = [
            {
                "declaration_id": "declared_fallback_direction",
                "target_todo_id": FALLBACK_ID,
                "successor_todo_id": FALLBACK_ID,
            }
        ]
    if path_outcome is not None:
        agent_vision["path_delta"] = {"outcome": path_outcome}
    return {
        "classification": "vision_fallback_disposition_fixture",
        "generated_at": "2026-09-05T00:00:00+00:00",
        "agent_id": AGENT_ID,
        "progress_scope": "agent_lane",
        "agent_vision": agent_vision,
    }


def _agent_todos(*, fallback_runnable: bool) -> dict:
    prereq = quota_todo_item(
        todo_id=PREREQ_ID,
        index=1,
        text="[P0] Complete the primary prerequisite.",
        claimed_by=PRIMARY_AGENT,
    )
    waiting = quota_todo_item(
        todo_id=PRIMARY_WAIT_ID,
        index=2,
        text="[P0] Resume the primary successor.",
        status="deferred",
        claimed_by=AGENT_ID,
        resume_when=f"todo_done:{PREREQ_ID}",
    )
    items = [prereq, waiting]
    if fallback_runnable:
        items.append(
            quota_todo_item(
                todo_id=FALLBACK_ID,
                index=3,
                text="[P1] Deliver the declared fallback direction.",
                claimed_by=AGENT_ID,
            )
        )
    return quota_todo_summary(items, role="agent")


def _status_payload(
    *,
    fallback_runnable: bool,
    latest_runs: list[dict],
) -> dict:
    return quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        recommended_action="Resolve the declared fallback direction.",
        agent_todos=_agent_todos(fallback_runnable=fallback_runnable),
        coordination={
            "agent_model": "peer_v1",
            "registered_agents": [PRIMARY_AGENT, AGENT_ID],
        },
        latest_runs=latest_runs,
    )


def _frontier_projection(payload: dict) -> dict:
    item = payload["attention_queue"]["items"][0]
    context = build_goal_frontier_projection_context_from_status(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        status_payload=payload,
        item=item,
        project_asset=item["project_asset"],
        user_todo_summary=item["user_todos"],
        agent_todo_summary=item["agent_todos"],
        work_lane_contract=None,
        neutral_replan_ack_classifications=set(),
        registered_agent_ids=[PRIMARY_AGENT, AGENT_ID],
        goal_status="active",
    )
    return context["goal_frontier_projection"]


def test_blocked_primary_with_runnable_fallback_projects_todo_selectable() -> None:
    payload = _status_payload(
        fallback_runnable=True,
        latest_runs=[_fallback_vision_run(todo_delta=[f"retain:{FALLBACK_ID}"])],
    )

    frontier = _frontier_projection(payload)
    assert "fallback_gaps" not in frontier
    assert "vision_wait_state" not in frontier
    remaining = frontier["remaining_advancement_frontier"]
    assert remaining["current_agent_claimed_advancement_count"] == 1
    assert remaining["unclaimed_advancement_count"] == 0

    decision = build_quota_should_run(
        payload,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        scheduler_execution_context=(GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT),
    )
    assert decision["decision"] == "run"
    assert decision["should_run"] is True
    assert decision["selected_todo"]["todo_id"] == FALLBACK_ID
    assert "fallback_gaps" not in decision["goal_frontier_projection"]


def test_declared_fallback_without_resolution_projects_single_gap() -> None:
    # The structured declaration links the fallback direction to a Todo id,
    # but no runnable Todo with that id exists on this agent's frontier.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}", f"retain:{FALLBACK_ID}"]
            )
        ],
    )

    frontier = _frontier_projection(payload)

    # The blocked-successor wait state clears ordinary acceptance gaps; the
    # declared fallback would disappear silently without the dedicated field.
    assert frontier["acceptance_gaps"] == []
    wait = frontier["vision_wait_state"]
    assert wait["reason_code"] == "exact_blocked_successor"
    assert wait["selected_todo_id"] == PRIMARY_WAIT_ID
    gaps = frontier["fallback_gaps"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["kind"] == "vision_fallback_unresolved"
    assert gap["reason_code"] == "declared_fallback_without_runnable_or_terminal"
    assert gap["agent_id"] == AGENT_ID
    assert gap["unresolved_todo_ids"] == [FALLBACK_ID]
    assert "fallback" in gap["recommended_action"]
    assert "do not invent a user gate" in gap["recommended_action"]
    assert frontier["replan_required"] is False


def test_retaining_only_the_blocked_primary_successor_is_no_declaration() -> None:
    # The primary successor is the wait state's own object; retaining it does
    # not declare a fallback direction, so no gap is invented.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}"],
                fallback_declarations=[],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


@pytest.mark.parametrize(
    "acceptance_summary",
    [
        # Owner probe 1: explicit negation must not project a fallback gap.
        "No fallback is authorized; wait for the primary prerequisite.",
        # Owner probe 2: a non-English prose declaration has no structured
        # declaration channel, so the conservative projection yields no gap.
        "主路径阻塞时，执行已声明的备用方案。",
        # English prose mentioning a fallback is equally non-declarative.
        "Deliver the primary successor after its prerequisite clears; "
        "the fallback wording lives in prose only.",
    ],
    ids=["negated-english", "chinese-prose", "english-prose"],
)
def test_prose_text_alone_never_declares_a_fallback(
    acceptance_summary: str,
) -> None:
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                acceptance_summary=acceptance_summary,
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}"],
                fallback_declarations=[],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


def test_other_agent_primary_todo_without_fallback_declaration_generates_no_gap() -> (
    None
):
    # Maintainer blocker 2: generic primary-path retain (e.g. peer-held prerequisite)
    # is not a fallback declaration; without a structured declaration, no gap is invented.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}", f"retain:{PREREQ_ID}"],
                fallback_declarations=[],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


def test_other_agent_primary_todo_does_not_resolve_the_gap() -> None:
    # A peer-claimed prerequisite retained on the primary path is not on this
    # agent's selectable frontier and is not linked to the declared fallback,
    # so the declared fallback gap survives for the declared fallback Todo.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}", f"retain:{PREREQ_ID}"],
                fallback_declarations=[
                    {
                        "declaration_id": "declared_fallback_direction",
                        "target_todo_id": FALLBACK_ID,
                        "successor_todo_id": FALLBACK_ID,
                    }
                ],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert frontier["acceptance_gaps"] == []
    gaps = frontier["fallback_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["unresolved_todo_ids"] == [FALLBACK_ID]


def test_declared_fallback_linked_to_monitor_todo_keeps_the_gap() -> None:
    # A linked Todo that is not advancement work is not a runnable fallback
    # successor, so the declaration stays unresolved.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[_fallback_vision_run(todo_delta=[f"retain:{FALLBACK_ID}"])],
    )
    item = payload["attention_queue"]["items"][0]
    monitor = quota_todo_item(
        todo_id=FALLBACK_ID,
        index=3,
        text="[P2] Watch the declared fallback direction.",
        claimed_by=AGENT_ID,
    )
    monitor["task_class"] = "continuous_monitor"
    summary = _agent_todos(fallback_runnable=False)
    for slot in ("executable_backlog_items", "backlog_items"):
        summary[slot] = list(summary.get(slot) or []) + [monitor]
    item["agent_todos"] = summary

    frontier = _frontier_projection(payload)

    gaps = frontier["fallback_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["unresolved_todo_ids"] == [FALLBACK_ID]


@pytest.mark.parametrize(
    ("state", "path_outcome"),
    [
        ("no_followup", None),
        ("vision_drift_detected", "stop"),
    ],
    ids=["closed-state", "terminal-path-outcome"],
)
def test_terminal_disposition_closes_fallback_gap_without_regenerating(
    state: str,
    path_outcome: str | None,
) -> None:
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[_fallback_vision_run(state=state, path_outcome=path_outcome)],
    )

    first = _frontier_projection(payload)
    assert "fallback_gaps" not in first
    assert first["acceptance_gaps"] == []

    second = _frontier_projection(payload)
    assert "fallback_gaps" not in second
    assert second["acceptance_gaps"] == []


def test_declared_bounded_successor_delta_resolves_the_gap() -> None:
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[_fallback_vision_run(todo_delta=[f"create:{FALLBACK_ID}"])],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


def test_unrelated_create_does_not_resolve_fallback_gap() -> None:
    # Maintainer blocker 1: An unrelated create/reopen action must not
    # resolve the declared fallback direction.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[
                    f"retain:{PRIMARY_WAIT_ID}",
                    "create:todo_unrelated_maintenance",
                ],
                fallback_declarations=[
                    {
                        "declaration_id": "fallback_direction",
                        "target_todo_id": FALLBACK_ID,
                        "successor_todo_id": FALLBACK_ID,
                    }
                ],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    gaps = frontier["fallback_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["unresolved_todo_ids"] == [FALLBACK_ID]


def test_fallback_declared_via_todo_linkage_contract_projects_gap() -> None:
    # A fallback declared on a blocked successor item via the task linkage
    # contract projects an advisory gap when unresolved.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}"],
                fallback_declarations=[],
            )
        ],
    )
    item = payload["attention_queue"]["items"][0]
    agent_todos = item["agent_todos"]
    for deferred in agent_todos.get("deferred_items") or []:
        if isinstance(deferred, dict):
            deferred["fallback_todo_id"] = FALLBACK_ID

    frontier = _frontier_projection(payload)

    gaps = frontier["fallback_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["unresolved_todo_ids"] == [FALLBACK_ID]


def test_typed_declaration_successor_relation_resolves_gap() -> None:
    # A typed declaration-to-successor relation resolves when its declared
    # bounded successor is created in todo_delta.
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                todo_delta=[f"retain:{PRIMARY_WAIT_ID}", "create:todo_typed_successor"],
                fallback_declarations=[
                    {
                        "declaration_id": "fallback_direction",
                        "successor_todo_id": "todo_typed_successor",
                    }
                ],
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


def test_selectable_frontier_ids_mirror_the_authoritative_counts() -> None:
    # The completion-evidence id set must be the same agent-scoped frontier
    # the authoritative advancement counter projects.
    summary = _agent_todos(fallback_runnable=True)
    peer_only = quota_todo_item(
        todo_id="todo_peer_owned_direction",
        index=4,
        text="[P1] Advance the peer-owned direction.",
        claimed_by=PRIMARY_AGENT,
    )
    for slot in ("executable_backlog_items", "backlog_items"):
        summary[slot] = list(summary.get(slot) or []) + [peer_only]

    selectable_ids = agent_scoped_selectable_advancement_todo_ids(
        summary,
        agent_id=AGENT_ID,
    )
    counts = todo_advancement_frontier_counts(summary, agent_id=AGENT_ID)

    assert selectable_ids == {FALLBACK_ID}
    assert counts["current_agent_claimed_advancement_count"] == 1
    assert counts["unclaimed_advancement_count"] == 0
    assert counts["other_agent_claimed_advancement_count"] == 2
    assert PREREQ_ID not in selectable_ids
    assert PRIMARY_WAIT_ID not in selectable_ids


def test_vision_todo_delta_actions_contract_stays_the_shared_owner() -> None:
    # Both the acceptance-gap projection and the fallback disposition must
    # consume one action contract; create/reopen stay the successor subset.
    assert VISION_FRONTIER_TODO_DELTA_ACTIONS == frozenset(
        {"activate", "create", "reopen", "resume", "retain"}
    )
