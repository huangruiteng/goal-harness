from __future__ import annotations

import pytest

from loopx.control_plane.goals.goal_frontier import (
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
        latest_runs=[
            _fallback_vision_run(todo_delta=[f"retain:{FALLBACK_ID}"])
        ],
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
        scheduler_execution_context=(
            GENERIC_CLI_OUTER_CONTROLLER_SCHEDULER_CONTEXT
        ),
    )
    assert decision["decision"] == "run"
    assert decision["should_run"] is True
    assert decision["selected_todo"]["todo_id"] == FALLBACK_ID
    assert "fallback_gaps" not in decision["goal_frontier_projection"]


def test_declared_fallback_without_resolution_projects_single_gap() -> None:
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[_fallback_vision_run()],
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
    assert gap["unresolved_todo_ids"] == [PRIMARY_WAIT_ID]
    assert "fallback" in gap["recommended_action"]
    assert "do not invent a user gate" in gap["recommended_action"]
    assert frontier["replan_required"] is False


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
        latest_runs=[
            _fallback_vision_run(state=state, path_outcome=path_outcome)
        ],
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
        latest_runs=[
            _fallback_vision_run(todo_delta=[f"create:{FALLBACK_ID}"])
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier


def test_vision_without_declared_fallback_word_projects_no_gap() -> None:
    payload = _status_payload(
        fallback_runnable=False,
        latest_runs=[
            _fallback_vision_run(
                acceptance_summary=(
                    "Deliver the primary successor after its prerequisite clears."
                )
            )
        ],
    )

    frontier = _frontier_projection(payload)

    assert "fallback_gaps" not in frontier
