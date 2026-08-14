from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.policy import (
    POLICY_DECISION_EVENT_KIND,
    Decision,
    PolicyDecisionRecorder,
    compute_decision_fingerprint,
    policy_decision_events,
    record_policy_decision,
)


def _wait_decision() -> Decision:
    return Decision(outcome="wait", reason="quota_backoff", source="quota")


def _run_decision() -> Decision:
    return Decision(outcome="run", reason="normal_delivery", source="quota")


def _read_events(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Fingerprint determinism
# ---------------------------------------------------------------------------


def test_fingerprint_deterministic_and_stable() -> None:
    first = compute_decision_fingerprint(
        _wait_decision(), goal_id="g1", todo_id="t1", agent_id="a1"
    )
    second = compute_decision_fingerprint(
        _wait_decision(), goal_id="g1", todo_id="t1", agent_id="a1"
    )
    assert first == second
    assert len(first) == 16


def test_fingerprint_changes_with_decision_semantics() -> None:
    wait = compute_decision_fingerprint(_wait_decision(), goal_id="g1", todo_id="t1")
    run = compute_decision_fingerprint(_run_decision(), goal_id="g1", todo_id="t1")
    assert wait != run


def test_fingerprint_excludes_timestamps() -> None:
    decision = _wait_decision()
    stable = compute_decision_fingerprint(decision, goal_id="g1", todo_id="t1")
    unstable = Decision(
        outcome=decision.outcome,
        reason=decision.reason,
        source=decision.source,
        retry_at="2026-08-13T12:30:00Z",
    )
    assert compute_decision_fingerprint(unstable, goal_id="g1", todo_id="t1") == stable


# ---------------------------------------------------------------------------
# Idempotent recording + deduplication (RFC §8.4)
# ---------------------------------------------------------------------------


def test_record_appends_once(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    event, was_new = record_policy_decision(
        _wait_decision(),
        goal_id="g1",
        todo_id="t1",
        agent_id="a1",
        log_path=log_path,
        state_dir=tmp_path / "state",
    )
    assert was_new is True
    assert event["event_kind"] == POLICY_DECISION_EVENT_KIND
    assert event["goal_id"] == "g1"
    assert event["todo_id"] == "t1"
    assert event["status"] == "wait"
    assert event["classification"] == "quota_backoff"
    assert event["details"]["decision_source"] == "quota"
    assert event["details"]["decision_outcome"] == "wait"
    assert event["decision_fingerprint"]


def test_transition_only_suppresses_repeated_identical_decision(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    recorder = PolicyDecisionRecorder(log_path=log_path, state_dir=tmp_path / "state")
    _, first_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    _, second_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    assert first_new is True
    assert second_new is False
    assert len(_read_events(log_path)) == 1


def test_transition_only_records_transition(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    recorder = PolicyDecisionRecorder(log_path=log_path, state_dir=tmp_path / "state")
    recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    _, transition_new = recorder.record(_run_decision(), goal_id="g1", todo_id="t1")
    assert transition_new is True
    events = _read_events(log_path)
    assert len(events) == 2
    assert [event["status"] for event in events] == ["wait", "run"]


def test_transition_only_scopes_by_todo(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    recorder = PolicyDecisionRecorder(log_path=log_path, state_dir=tmp_path / "state")
    _, first_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    _, other_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t2")
    assert first_new is True
    assert other_new is True
    assert len(_read_events(log_path)) == 2


def test_opt_out_transition_only_relies_on_identity_dedup(tmp_path: Path) -> None:
    # Without transition tracking, idempotency still prevents exact duplicates
    # because the fingerprint is part of the identity fields.
    log_path = tmp_path / "events.jsonl"
    recorder = PolicyDecisionRecorder(
        log_path=log_path, state_dir=tmp_path / "state", transition_only=False
    )
    _, first_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    _, second_new = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1")
    assert first_new is True
    assert second_new is False
    assert len(_read_events(log_path)) == 1


def test_record_persists_public_safe_boundary(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    event, _ = record_policy_decision(
        _wait_decision(),
        goal_id="g1",
        todo_id="t1",
        log_path=log_path,
        state_dir=tmp_path / "state",
    )
    boundary = event["boundary"]
    assert boundary["raw_task_text_recorded"] is False
    assert boundary["credential_values_recorded"] is False
    assert boundary["absolute_paths_recorded"] is False


def test_policy_decision_events_projection(tmp_path: Path) -> None:
    log_path = tmp_path / "events.jsonl"
    record_policy_decision(_wait_decision(), goal_id="g1", todo_id="t1", log_path=log_path, state_dir=tmp_path / "state")
    # Inject a non-decision event by appending a raw line.
    from loopx.rollout_event_log import build_rollout_event, append_rollout_event_once

    other = build_rollout_event(
        goal_id="g1",
        event_kind="quota_monitor_poll",
        summary="poll",
        details={"n": 1},
    )
    append_rollout_event_once(log_path, other, identity_fields=["goal_id", "event_kind"])
    decisions = policy_decision_events(_read_events(log_path))
    assert len(decisions) == 1
    assert decisions[0]["event_kind"] == POLICY_DECISION_EVENT_KIND


def test_replay_identity_shape(tmp_path: Path) -> None:
    recorder = PolicyDecisionRecorder(log_path=tmp_path / "e.jsonl", state_dir=tmp_path / "s")
    event, _ = recorder.record(_wait_decision(), goal_id="g1", todo_id="t1", agent_id="a1")
    goal_id, todo_id, agent_id, fingerprint = recorder.replay_identity(event)
    assert goal_id == "g1"
    assert todo_id == "t1"
    assert agent_id == "a1"
    assert fingerprint == event["decision_fingerprint"]
