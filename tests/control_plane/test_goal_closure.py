"""Tests for the Goal Closure Evaluator + Controller (elegant, event-driven).

Covers the design from `plan/new_plan.md` + user feedback: Goal closure is a
*distinct lifecycle* from Todo completion. A goal is closable purely from state
(no ready work, no pending deps, no replan, no external follow-up) — WITHOUT
requiring every todo to carry an explicit ``no_followup`` intent.
"""

from __future__ import annotations

from pathlib import Path

from loopx.control_plane.goals.goal_closure import (
    GOAL_CLOSE,
    GOAL_RUN,
    GOAL_WAIT,
    build_goal_closure_state,
    classify_goal_continuation,
    emit_goal_closed,
    emit_goal_closure_ready,
    evaluate_goal_closure,
    goal_closure_reason,
    is_goal_closable,
    maybe_close_goal,
)
from loopx.rollout_event_log import load_rollout_events, rollout_event_log_path


def test_goal_closable_when_no_work_no_deps_no_replan() -> None:
    state = build_goal_closure_state()
    assert is_goal_closable(state) is True
    assert goal_closure_reason(state) is None
    assert classify_goal_continuation(state) == GOAL_CLOSE


def test_goal_not_closable_when_ready_work() -> None:
    state = build_goal_closure_state(ready_todo_ids=["todo_a"])
    assert is_goal_closable(state) is False
    assert goal_closure_reason(state) == "ready_work_remaining"
    assert classify_goal_continuation(state) == GOAL_RUN


def test_goal_not_closable_when_pending_dependency() -> None:
    state = build_goal_closure_state(pending_dependency_ids=["todo_b"])
    assert is_goal_closable(state) is False
    assert goal_closure_reason(state) == "pending_dependencies"
    assert classify_goal_continuation(state) == GOAL_WAIT


def test_goal_not_closable_when_replan_required() -> None:
    state = build_goal_closure_state(replan_required=True)
    assert is_goal_closable(state) is False
    assert goal_closure_reason(state) == "replan_required"


def test_goal_not_closable_when_external_followup_required() -> None:
    state = build_goal_closure_state(external_followup_required=True)
    assert is_goal_closable(state) is False
    assert goal_closure_reason(state) == "external_followup_required"


def test_goal_not_closable_when_open_or_claimed_count() -> None:
    open_state = build_goal_closure_state(open_todo_count=1)
    assert is_goal_closable(open_state) is False
    claimed_state = build_goal_closure_state(claimed_advancement_count=1)
    assert is_goal_closable(claimed_state) is False


def test_goal_closable_with_blocked_but_no_open_work() -> None:
    # Blocked work is future work -> WAIT, not CLOSE. Deferred + blocked keeps it open.
    state = build_goal_closure_state(blocked_todo_ids=["todo_c"])
    assert is_goal_closable(state) is False
    assert classify_goal_continuation(state) == GOAL_WAIT


def test_evaluate_goal_closure_returns_evidence() -> None:
    state = build_goal_closure_state(
        ready_todo_ids=[],
        blocked_todo_ids=["todo_x"],
        deferred_todo_ids=["todo_y"],
        replan_required=False,
    )
    evaluation = evaluate_goal_closure(state)
    assert evaluation["ready"] is False
    assert evaluation["tri_state"] == GOAL_WAIT
    assert evaluation["evidence"]["blocked_todo_ids"] == ["todo_x"]
    assert evaluation["evidence"]["deferred_todo_ids"] == ["todo_y"]
    assert evaluation["evidence"]["replan_required"] is False


def test_maybe_close_goal_emits_events_when_ready(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    result = maybe_close_goal(
        log_path=log_path,
        goal_id="g1",
        state=build_goal_closure_state(),
    )
    assert result["ready"] is True
    assert result.get("closed") is True
    kinds = [e["event_kind"] for e in load_rollout_events(log_path, limit=10)]
    assert kinds == ["goal_closure_ready", "goal_closed"]


def test_maybe_close_goal_does_nothing_when_not_ready(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    result = maybe_close_goal(
        log_path=log_path,
        goal_id="g1",
        state=build_goal_closure_state(ready_todo_ids=["todo_a"]),
    )
    assert result["ready"] is False
    assert result.get("closed") is not True
    assert load_rollout_events(log_path, limit=10) == []


def test_emit_events_idempotent(tmp_path: Path) -> None:
    log_path = rollout_event_log_path(tmp_path, goal_id="g1")
    emit_goal_closure_ready(log_path=log_path, goal_id="g1", reason="no_followup_work")
    emit_goal_closure_ready(log_path=log_path, goal_id="g1", reason="no_followup_work")
    emit_goal_closed(log_path=log_path, goal_id="g1", kind="derived")
    emit_goal_closed(log_path=log_path, goal_id="g1", kind="derived")
    events = load_rollout_events(log_path, limit=10)
    kinds = [e["event_kind"] for e in events]
    assert kinds.count("goal_closure_ready") == 1
    assert kinds.count("goal_closed") == 1
