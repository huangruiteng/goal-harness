from __future__ import annotations

import json
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loopx.control_plane import effect_runtime
from loopx.control_plane.scheduler.state import (
    CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
    CODEX_APP_SURFACE,
    SCHEDULER_STATE_STORE_REQUEST_SCHEMA,
    build_scheduler_state,
    load_scheduler_state,
    normalize_scheduler_host_update_failures,
    scheduler_state_path,
    write_scheduler_state,
)


GOAL_ID = "scheduler-runtime-goal"
AGENT_ID = "scheduler-runtime-agent"


def _state(rrule: str = "FREQ=MINUTELY;INTERVAL=3") -> dict[str, object]:
    return build_scheduler_state(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        reset_token="reset",
        identity_signature="identity",
        progression_index=0,
        progression_minutes=[3, 15, 30],
        last_applied_rrule=rrule,
        updated_at="2026-01-01T12:00:00Z",
    )


def _store_request(runtime_root: Path, state: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": SCHEDULER_STATE_STORE_REQUEST_SCHEMA,
        "runtime_root": str(runtime_root),
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "surface": CODEX_APP_SURFACE,
        "state_key": CODEX_APP_STATEFUL_BACKOFF_STATE_KEY,
        "state": state,
    }


def _shutdown_runtime() -> None:
    effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)


def test_scheduler_state_facade_reuses_runtime_and_replays_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "effect-runtime"
    state_root = tmp_path / "state"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")

    first_runtime = effect_runtime.effect_runtime_result("runtime.ping", {})
    state = _state()
    path = write_scheduler_state(
        state_root,
        state,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    assert effect_runtime.effect_runtime_result("runtime.ping", {})["pid"] == (
        first_runtime["pid"]
    )
    assert load_scheduler_state(
        state_root,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    ) == state

    _shutdown_runtime()
    deadline = time.monotonic() + 2
    while list(runtime_dir.glob("runtime-*.json")) and time.monotonic() < deadline:
        time.sleep(0.025)

    replay = effect_runtime.effect_runtime_result(
        "scheduler.state.write",
        _store_request(state_root, state),
    )
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})
    assert replay["written"] is False
    assert replay["replayed"] is True
    assert replacement["pid"] != first_runtime["pid"]
    assert json.loads(path.read_text(encoding="utf-8")) == state
    _shutdown_runtime()


def test_scheduler_state_same_key_writes_remain_atomic_across_python_callers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "effect-runtime"
    state_root = tmp_path / "state"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    states = [
        _state("FREQ=MINUTELY;INTERVAL=15"),
        _state("FREQ=MINUTELY;INTERVAL=30"),
    ]

    def write(state: dict[str, object]) -> Path:
        return write_scheduler_state(
            state_root,
            state,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(write, states))

    assert paths[0] == paths[1]
    persisted = load_scheduler_state(
        state_root,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    )
    assert persisted in states
    siblings = [item.name for item in paths[0].parent.iterdir()]
    assert not any(".tmp" in name or ".lock" in name for name in siblings)
    _shutdown_runtime()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process termination probe")
def test_scheduler_state_retry_recovers_after_runtime_crash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "effect-runtime"
    state_root = tmp_path / "state"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    state = _state()
    first = effect_runtime.effect_runtime_result(
        "scheduler.state.write",
        _store_request(state_root, state),
    )
    original = effect_runtime.effect_runtime_result("runtime.ping", {})
    os.kill(int(original["pid"]), signal.SIGTERM)
    time.sleep(0.1)

    replay = effect_runtime.effect_runtime_result(
        "scheduler.state.write",
        _store_request(state_root, state),
        retry_safe=True,
    )
    replacement = effect_runtime.effect_runtime_result("runtime.ping", {})

    assert first["written"] is True
    assert replay["written"] is False
    assert replay["replayed"] is True
    assert replacement["pid"] != original["pid"]
    assert load_scheduler_state(
        state_root,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    ) == state
    _shutdown_runtime()


def test_failure_normalization_returns_independent_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "effect-runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    failure = {
        "schema_version": "scheduler_host_update_failure_v0",
        "target_rrule": "FREQ=MINUTELY;INTERVAL=3",
        "observed_host_rrule": "FREQ=MINUTELY;INTERVAL=30",
        "failure_kind": "timeout",
        "failure_count": 1,
        "failed_at": "2026-01-01T12:00:00Z",
    }

    first = normalize_scheduler_host_update_failures([failure])
    first[0]["failure_count"] = 99
    second = normalize_scheduler_host_update_failures([failure])

    assert second[0]["failure_count"] == 1
    _shutdown_runtime()


def test_scheduler_state_scope_mismatch_is_rejected_before_disk_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_dir = tmp_path / "effect-runtime"
    monkeypatch.setattr(effect_runtime, "_runtime_dir", lambda: runtime_dir)
    monkeypatch.setenv("LOOPX_EFFECT_RUNTIME_IDLE_MS", "1000")
    state = {**_state(), "goal_id": "different-goal"}

    with pytest.raises(ValueError, match="does not match target scope"):
        write_scheduler_state(
            tmp_path / "state",
            state,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
        )

    assert not scheduler_state_path(
        tmp_path / "state",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
    ).exists()
    _shutdown_runtime()
