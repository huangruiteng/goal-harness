from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from loopx.file_lock import (
    LOCK_ACQUIRE_TIMEOUT_ERROR_CODE,
    LockAcquireTimeoutError,
    exclusive_file_lock,
    fcntl,
    lock_incident_path,
    try_exclusive_file_lock,
)
from loopx.presentation.markdown import append_operator_action_markdown


pytestmark = pytest.mark.skipif(fcntl is None, reason="POSIX flock is required")


def _start_stalled_holder(target: Path) -> subprocess.Popen[str]:
    script = """
import sys
import time
from pathlib import Path
from loopx.file_lock import exclusive_file_lock

with exclusive_file_lock(
    Path(sys.argv[1]),
    timeout_seconds=1.0,
    agent_id="holder-agent",
    operation="stalled-holder",
):
    print("ready", flush=True)
    time.sleep(30)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(target)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    return process


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def test_exclusive_lock_persists_public_safe_holder_metadata(tmp_path: Path) -> None:
    target = tmp_path / "state.json"

    with exclusive_file_lock(
        target,
        agent_id="agent-a",
        operation="todo-update",
    ) as lock_path:
        holder = json.loads(lock_path.read_text(encoding="utf-8"))
        assert holder["pid"] > 0
        assert holder["agent_id"] == "agent-a"
        assert holder["operation"] == "todo-update"
        assert holder["acquired_at"].endswith("Z")
        assert "released_at" not in holder

    released = json.loads(lock_path.read_text(encoding="utf-8"))
    assert released["released_at"].endswith("Z")
    assert lock_path.exists()


def test_stalled_holder_times_out_and_records_independent_incident(tmp_path: Path) -> None:
    target = tmp_path / "todos.md"
    process = _start_stalled_holder(target)
    try:
        with pytest.raises(LockAcquireTimeoutError) as raised:
            with exclusive_file_lock(
                target,
                timeout_seconds=0.15,
                poll_interval_seconds=0.02,
                agent_id="waiter-agent",
                operation="todo-add",
            ):
                pytest.fail("waiter unexpectedly acquired the stalled lock")

        error = raised.value
        payload = error.to_payload()
        assert payload["error_code"] == LOCK_ACQUIRE_TIMEOUT_ERROR_CODE
        assert payload["incident_recorded"] is True
        incident = payload["lock_timeout"]
        assert incident["holder"]["pid"] == process.pid
        assert incident["holder"]["agent_id"] == "holder-agent"
        assert incident["waiter"]["agent_id"] == "waiter-agent"
        assert incident["waiter"]["waited_seconds"] >= 0.1
        assert incident["operator_action"]["retry_mode"] == (
            "manual_after_holder_inspection"
        )
        markdown_lines: list[str] = []
        append_operator_action_markdown(markdown_lines, payload)
        markdown = "\n".join(markdown_lines)
        assert "error_code: `lock_acquire_timeout`" in markdown
        assert f"holder_pid={process.pid}" in markdown
        assert "Do not delete the lock file" in markdown

        rows = lock_incident_path(target).read_text(encoding="utf-8").splitlines()
        recorded = json.loads(rows[-1])
        assert recorded["error_code"] == LOCK_ACQUIRE_TIMEOUT_ERROR_CODE
        assert recorded["lock_id"] == incident["lock_id"]
        assert str(target) not in rows[-1]
    finally:
        _stop(process)

    assert target.with_name(f"{target.name}.lock").exists()


def test_single_flight_returns_none_without_timeout_incident(tmp_path: Path) -> None:
    target = tmp_path / "sync.json"
    process = _start_stalled_holder(target)
    try:
        with try_exclusive_file_lock(target, operation="duplicate-sync") as lock_path:
            assert lock_path is None
        assert not lock_incident_path(target).exists()
    finally:
        _stop(process)
