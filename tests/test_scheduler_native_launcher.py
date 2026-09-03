from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from examples.control_plane.quota_plan_fixtures import (
    SCOPED_AGENT_ID,
    write_cli_fixture,
)
from loopx.control_plane.testing.canary_harness import run_json_cli_result

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_unix_launcher_process_replaces_python_for_exact_native_followup(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_node = fake_bin / "node"
    fake_node.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
        "LOOPX_PYTHON": str(tmp_path / "python-must-not-run"),
    }
    args = [
        "--format",
        "json",
        "--runtime-root",
        str(tmp_path / "runtime"),
        "quota",
        "scheduler-ack-current",
        "--goal-id",
        "goal-native-launcher",
        "--agent-id",
        "agent-native-launcher",
        "--scheduler-host-facts-chunk",
        "facts",
        "--turn-instance-id",
        "turn-native-launcher",
        "--execute",
    ]

    completed = subprocess.run(
        [str(REPO_ROOT / "scripts" / "loopx"), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[:3] == [
        "--no-warnings",
        "--experimental-strip-types",
        str(
            REPO_ROOT
            / "loopx"
            / "control_plane"
            / "scheduler"
            / "heartbeat_followup_cli.ts"
        ),
    ]
    assert lines[-len(args) :] == args


def test_unix_launcher_keeps_unbound_calls_on_the_python_compatibility_route(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "quota",
            "scheduler-ack-current",
            "--scheduler-host-facts-chunk",
            "facts",
            "--execute",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOOPX_PYTHON": str(tmp_path / "missing-python")},
    )

    assert completed.returncode == 2
    assert "configured Python executable not found" in completed.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_receipt_bound_should_run_hint_executes_native_without_python(
    tmp_path: Path,
) -> None:
    registry_path, runtime_root, project = write_cli_fixture(
        tmp_path / "fixture",
        scoped_agents=True,
    )
    goal_id = "needs-operator"
    turn_id = "turn-native-transaction"
    returncode, guard = run_json_cli_result(
        "quota",
        "should-run",
        "--goal-id",
        goal_id,
        "--agent-id",
        SCOPED_AGENT_ID,
        "--codex-app",
        "--turn-instance-id",
        turn_id,
        registry_path=registry_path,
        runtime_root=runtime_root,
        cwd=project,
    )
    assert returncode == 0, guard
    hint = guard["scheduler_hint"]["codex_app"]["ack_hint"]
    assert "--scheduler-host-facts-chunk" in hint["cli_args"]
    assert hint["args"]["turn_instance_id"] == turn_id

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "--format",
            "json",
            *hint["cli_args"],
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "LOOPX_PYTHON": str(tmp_path / "python-must-not-run"),
        },
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["scheduler_commit"]["status"] == "written"
    assert (
        result["scheduler_ack_event"]["scheduler_state"]["last_applied_rrule"]
        == guard["scheduler_hint"]["codex_app"]["recommended_rrule"]
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required")
def test_receipt_bound_failure_hint_executes_native_without_python(
    tmp_path: Path,
) -> None:
    registry_path, runtime_root, project = write_cli_fixture(
        tmp_path / "fixture-failure",
        scoped_agents=True,
    )
    turn_id = "turn-native-failure"
    returncode, guard = run_json_cli_result(
        "quota",
        "should-run",
        "--goal-id",
        "needs-operator",
        "--agent-id",
        SCOPED_AGENT_ID,
        "--codex-app",
        "--turn-instance-id",
        turn_id,
        registry_path=registry_path,
        runtime_root=runtime_root,
        cwd=project,
    )
    assert returncode == 0, guard
    hint = guard["scheduler_hint"]["codex_app"]["failure_hint"]
    assert "--scheduler-host-facts-chunk" in hint["cli_args"]

    completed = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "loopx"),
            "--format",
            "json",
            *hint["cli_args"],
        ],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "LOOPX_PYTHON": str(tmp_path / "python-must-not-run"),
        },
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["ok"] is True
    assert result["mode"] == "scheduler-fail-current"
    assert result["scheduler_commit"]["status"] == "written"
    assert result["failure_count"] == 1


def test_windows_launcher_contains_the_same_exact_native_dispatch_gate() -> None:
    source = (REPO_ROOT / "scripts" / "loopx.ps1").read_text(encoding="utf-8")

    assert '"--scheduler-host-facts-chunk"' in source
    assert '"--turn-instance-id"' in source
    assert "heartbeat_followup_cli.ts" in source
    assert "Get-Command node" in source
