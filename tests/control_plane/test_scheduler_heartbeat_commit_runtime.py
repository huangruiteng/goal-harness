from __future__ import annotations

from pathlib import Path

import pytest

from loopx.control_plane.scheduler.heartbeat_commit import (
    commit_scheduler_heartbeat,
    scheduler_state_digest,
)


GOAL_ID = "scheduler-heartbeat-commit-runtime"
AGENT_ID = "codex-main-control"
SURFACE = "codex_app"
STATE_KEY = "scheduler_hint.codex_app.stateful_backoff"
RRULE_15 = "FREQ=MINUTELY;INTERVAL=15"
RRULE_30 = "FREQ=MINUTELY;INTERVAL=30"


def _state(*, progression_index: int, updated_at: str) -> dict[str, object]:
    return {
        "schema_version": "loopx_scheduler_state_v0",
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "surface": SURFACE,
        "state_key": STATE_KEY,
        "reset_token": "reset-runtime",
        "identity_signature": "identity-runtime",
        "progression_index": progression_index,
        "progression_minutes": [15, 30],
        "last_applied_rrule": RRULE_15,
        "updated_at": updated_at,
    }


def _commit(
    runtime_root: Path,
    *,
    outcome: str,
    state: dict[str, object],
    operation_id: str,
    expected_state_digest: str | None,
    ack: dict[str, object] | None = None,
    failure: dict[str, object] | None = None,
) -> dict[str, object]:
    return dict(
        commit_scheduler_heartbeat(
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            surface=SURFACE,
            state_key=STATE_KEY,
            outcome=outcome,
            state=state,
            ack=ack,
            failure=failure,
            operation_id=operation_id,
            expected_state_digest=expected_state_digest,
        )
    )


def test_python_facade_commits_replays_and_enforces_scheduler_cas(
    tmp_path: Path,
) -> None:
    initial_state = _state(
        progression_index=0,
        updated_at="2026-08-24T08:00:00Z",
    )
    ack = {
        "expected_rrule": RRULE_15,
        "applied_rrule": RRULE_15,
        "cadence_class": "active_work",
    }
    written = _commit(
        tmp_path,
        outcome="ack",
        state=initial_state,
        ack=ack,
        operation_id="ack-runtime-1",
        expected_state_digest=None,
    )
    assert written["status"] == "written"
    assert written["written"] is True
    assert written["state"]["last_applied_rrule"] == RRULE_15
    assert scheduler_state_digest(written["state"]) == written["state_digest"]

    replayed = _commit(
        tmp_path,
        outcome="ack",
        state=initial_state,
        ack=ack,
        operation_id="ack-runtime-1",
        expected_state_digest=None,
    )
    assert replayed["status"] == "replayed"
    assert replayed["replayed"] is True
    assert replayed["state_digest"] == written["state_digest"]

    failure_state = _state(
        progression_index=1,
        updated_at="2026-08-24T08:01:00Z",
    )
    failure = {
        "target_rrule": RRULE_30,
        "observed_host_rrule": RRULE_15,
        "failure_kind": "timeout",
    }
    failed_once = _commit(
        tmp_path,
        outcome="failure",
        state=failure_state,
        failure=failure,
        operation_id="failure-runtime-1",
        expected_state_digest=written["state_digest"],
    )
    assert failed_once["status"] == "written"
    assert failed_once["failure_count"] == 1

    next_failure_state = _state(
        progression_index=1,
        updated_at="2026-08-24T08:02:00Z",
    )
    failed_twice = _commit(
        tmp_path,
        outcome="failure",
        state=next_failure_state,
        failure=failure,
        operation_id="failure-runtime-2",
        expected_state_digest=failed_once["state_digest"],
    )
    assert failed_twice["status"] == "written"
    assert failed_twice["failure_count"] == 2

    stale = _commit(
        tmp_path,
        outcome="failure",
        state=next_failure_state,
        failure=failure,
        operation_id="failure-runtime-stale",
        expected_state_digest=written["state_digest"],
    )
    assert stale["status"] == "conflict"
    assert stale["reason_code"] == "state_digest_conflict"
    assert stale["state_digest"] == failed_twice["state_digest"]


def test_python_adapter_rejects_malformed_compact_facts_before_runtime(
    tmp_path: Path,
) -> None:
    state = _state(progression_index=0, updated_at="2026-08-24T08:00:00Z")
    with pytest.raises(ValueError, match="execute must be a boolean"):
        commit_scheduler_heartbeat(
            runtime_root=tmp_path,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            surface=SURFACE,
            state_key=STATE_KEY,
            outcome="ack",
            state=state,
            facts={"execute": "false"},
            ack={"applied_rrule": RRULE_15, "expected_rrule": RRULE_15},
            expected_state_digest=None,
        )
    with pytest.raises(ValueError, match="prior failure cache must be a list"):
        commit_scheduler_heartbeat(
            runtime_root=tmp_path,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            surface=SURFACE,
            state_key=STATE_KEY,
            state=state,
            outcome="ack",
            facts={"prior_host_update_failures": "not-a-list"},
            ack={"applied_rrule": RRULE_15, "expected_rrule": RRULE_15},
            expected_state_digest=None,
        )
    with pytest.raises(
        ValueError, match=r"prior_host_update_failures\[0\] is malformed"
    ):
        commit_scheduler_heartbeat(
            runtime_root=tmp_path,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            surface=SURFACE,
            state_key=STATE_KEY,
            outcome="ack",
            state=state,
            facts={"prior_host_update_failures": [{"failure_kind": "timeout"}]},
            ack={"applied_rrule": RRULE_15, "expected_rrule": RRULE_15},
            expected_state_digest=None,
        )
