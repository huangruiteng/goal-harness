from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from benchmark.native_codex_goal import (
    NativeGoalConfig,
    NativeGoalProtocolError,
    compact_native_goal_receipt,
    observe_native_goal_event,
    probe_native_goal_process,
    run_native_goal_process,
    run_native_goal_process_until_terminal,
    run_native_goal_until_terminal,
    start_native_goal_turn,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeTransport:
    def __init__(self, *, goal_objective: str = "Finish the task.") -> None:
        self.goal_objective = goal_objective
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append((method, dict(params)))
        if method == "initialize":
            return {"serverInfo": {"name": "fake"}}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "thread/goal/set":
            return {"goal": {"threadId": "thread-1", **dict(params)}}
        if method == "thread/goal/get":
            return {
                "goal": {
                    "threadId": "thread-1",
                    "objective": self.goal_objective,
                    "status": "active",
                }
            }
        if method == "turn/start":
            return {"turn": {"id": "response-turn", "status": "inProgress"}}
        raise AssertionError(method)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        self.calls.append((method, dict(params)))


class ContinuationTransport(FakeTransport):
    def __init__(self, *, terminal_after_second_turn: bool = True) -> None:
        super().__init__()
        self.goal_reads = 0
        self.terminal_after_second_turn = terminal_after_second_turn
        self.events: list[dict[str, Any]] = [
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn-1", "status": "inProgress"},
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn-1", "status": "completed"},
                },
            },
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn-2", "status": "inProgress"},
                },
            },
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn-2", "status": "completed"},
                },
            },
        ]

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if method != "thread/goal/get":
            return super().request(method, params)
        self.calls.append((method, dict(params)))
        self.goal_reads += 1
        status = (
            "complete"
            if self.terminal_after_second_turn and self.goal_reads >= 3
            else "active"
        )
        return {
            "goal": {
                "threadId": "thread-1",
                "objective": self.goal_objective,
                "status": status,
            }
        }

    def next_event(self, *, timeout_sec: float) -> Mapping[str, Any] | None:
        del timeout_sec
        return self.events.pop(0) if self.events else None


def _config(**overrides: Any) -> NativeGoalConfig:
    values = {
        "cwd": "/workspace/case",
        "objective": "Finish the task.",
        "task_instruction": "Implement the requested behavior and validate it.",
        "model": "model-route",
        "effort": "high",
        "token_budget": 120000,
    }
    values.update(overrides)
    return NativeGoalConfig(**values)


def test_goal_transaction_order_and_compact_receipt() -> None:
    transport = FakeTransport()
    turn = start_native_goal_turn(transport, _config())

    assert [method for method, _ in transport.calls] == [
        "initialize",
        "initialized",
        "thread/start",
        "thread/goal/set",
        "thread/goal/get",
        "turn/start",
    ]
    initialize = transport.calls[0][1]
    assert initialize["capabilities"] == {"experimentalApi": True}
    goal_set = transport.calls[3][1]
    assert goal_set["tokenBudget"] == 120000
    assert transport.calls[5][1]["effort"] == "high"

    assert (
        observe_native_goal_event(
            turn,
            {
                "method": "turn/started",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn", "status": "inProgress"},
                },
            },
        )
        is False
    )
    assert turn.turn_id == "event-turn"
    assert (
        observe_native_goal_event(
            turn,
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "event-turn", "status": "completed"},
                },
            },
        )
        is True
    )

    receipt = compact_native_goal_receipt(turn)
    rendered = json.dumps(receipt, sort_keys=True)
    assert receipt["event_turn_id_observed"] is True
    assert receipt["terminal_event_observed"] is True
    assert receipt["turn_started_count"] == 1
    assert receipt["turn_completed_count"] == 1
    assert receipt["goal_continuation_turn_completed_count"] == 0
    assert receipt["token_budget_present"] is True
    assert "Finish the task." not in rendered
    assert "Implement the requested behavior" not in rendered
    assert "/workspace/case" not in rendered


@pytest.mark.parametrize("token_budget", [0, -1, True, 1.5])
def test_non_positive_or_boolean_token_budget_fails_before_transport(
    token_budget: object,
) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError, match="positive integer"):
        start_native_goal_turn(transport, _config(token_budget=token_budget))
    assert transport.calls == []


def test_goal_identity_mismatch_fails_closed() -> None:
    with pytest.raises(NativeGoalProtocolError, match="goal_objective_mismatch"):
        start_native_goal_turn(FakeTransport(goal_objective="Different"), _config())


def test_terminal_event_preserves_failed_turn_status() -> None:
    turn = start_native_goal_turn(FakeTransport(), _config())
    assert (
        observe_native_goal_event(
            turn,
            {
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {"id": "response-turn", "status": "failed"},
                },
            },
        )
        is True
    )
    assert turn.turn_status == "failed"


def test_goal_runtime_waits_for_automatic_continuation_until_terminal() -> None:
    transport = ContinuationTransport()

    turn = run_native_goal_until_terminal(transport, _config(), timeout_sec=1)

    methods = [method for method, _ in transport.calls]
    assert methods.count("turn/start") == 1
    assert methods.count("thread/goal/get") == 3
    assert turn.post_goal_status == "complete"
    assert turn.turn_started_count == 2
    assert turn.turn_completed_count == 2
    assert turn.goal_status_poll_count == 2
    assert turn.turn_id == "event-turn-2"
    assert (
        compact_native_goal_receipt(turn)["goal_continuation_turn_completed_count"] == 1
    )


def test_goal_runtime_fails_closed_when_active_goal_never_continues() -> None:
    transport = ContinuationTransport(terminal_after_second_turn=False)
    transport.events = transport.events[:2]

    with pytest.raises(NativeGoalProtocolError, match="goal_timeout_before_terminal"):
        run_native_goal_until_terminal(transport, _config(), timeout_sec=0.01)


def _write_fake_app_server(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            r"""
            #!/usr/bin/env python3
            import json
            import os
            import sys

            expected_process_cwd = os.environ.get("EXPECTED_PROCESS_CWD")
            if expected_process_cwd:
                assert os.getcwd() == expected_process_cwd
            objective = ""
            goal_reads = 0
            continuation_enabled = os.environ.get("FAKE_GOAL_CONTINUATION") == "1"
            for line in sys.stdin:
                request = json.loads(line)
                method = request.get("method")
                request_id = request.get("id")
                params = request.get("params") or {}
                if method == "initialized":
                    continue
                if method == "initialize":
                    result = {"serverInfo": {"name": "fixture"}}
                elif method == "thread/start":
                    assert params["model"] == "model-route"
                    expected_goal_cwd = os.environ.get("EXPECTED_GOAL_CWD")
                    if expected_goal_cwd:
                        assert params["cwd"] == expected_goal_cwd
                    result = {"thread": {"id": "thread-1"}}
                elif method == "thread/goal/set":
                    objective = params["objective"]
                    result = {"goal": {"threadId": "thread-1"}}
                elif method == "thread/goal/get":
                    goal_reads += 1
                    result = {
                        "goal": {
                            "threadId": "thread-1",
                            "objective": objective,
                            "status": (
                                "complete"
                                if continuation_enabled and goal_reads >= 3
                                else "active"
                            ),
                        }
                    }
                elif method == "turn/start":
                    assert params["sandboxPolicy"]["networkAccess"] is False
                    result = {"turn": {"id": "response-turn", "status": "inProgress"}}
                else:
                    raise AssertionError(method)
                print(json.dumps({"id": request_id, "result": result}), flush=True)
                if method == "turn/start":
                    print(json.dumps({
                        "method": "turn/started",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "event-turn", "status": "inProgress"},
                        },
                    }), flush=True)
                    print(json.dumps({
                        "method": "item/agentMessage/delta",
                        "params": {"threadId": "thread-1", "turnId": "event-turn"},
                    }), flush=True)
                    print(json.dumps({
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "event-turn", "status": "completed"},
                        },
                    }), flush=True)
                elif (
                    method == "thread/goal/get"
                    and continuation_enabled
                    and goal_reads == 2
                ):
                    for event_method, turn_id in (
                        ("turn/started", "event-turn-2"),
                        ("turn/completed", "event-turn-2"),
                    ):
                        print(json.dumps({
                            "method": event_method,
                            "params": {
                                "threadId": "thread-1",
                                "turn": {"id": turn_id, "status": "completed"},
                            },
                        }), flush=True)
            """
        ).lstrip(),
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_real_stdio_process_runs_complete_native_goal_transaction(
    tmp_path: Path,
) -> None:
    fake_server = tmp_path / "fake-codex"
    _write_fake_app_server(fake_server)
    config = _config(
        cwd=str(tmp_path),
        sandbox_policy={
            "type": "workspaceWrite",
            "writableRoots": [str(tmp_path)],
            "networkAccess": False,
        },
    )

    turn = run_native_goal_process(
        config,
        process_command=[sys.executable, str(fake_server)],
        response_timeout_sec=2,
        goal_timeout_sec=2,
    )

    assert turn.response_turn_id == "response-turn"
    assert turn.turn_id == "event-turn"
    assert turn.event_turn_id_observed is True
    assert turn.terminal_event_observed is True
    assert turn.post_goal_status == "active"
    assert turn.notification_counts == {
        "item/agentMessage/delta": 1,
        "turn/completed": 1,
        "turn/started": 1,
    }


def test_process_cwd_can_differ_from_goal_thread_cwd(tmp_path: Path) -> None:
    fake_server = tmp_path / "fake-codex"
    _write_fake_app_server(fake_server)
    process_cwd = tmp_path / "process"
    goal_cwd = tmp_path / "goal"
    process_cwd.mkdir()
    goal_cwd.mkdir()
    process_env = dict(os.environ)
    process_env.update(
        {
            "EXPECTED_PROCESS_CWD": str(process_cwd),
            "EXPECTED_GOAL_CWD": str(goal_cwd),
        }
    )

    turn = run_native_goal_process(
        _config(
            cwd=str(goal_cwd),
            sandbox_policy={
                "type": "workspaceWrite",
                "writableRoots": [str(goal_cwd)],
                "networkAccess": False,
            },
        ),
        process_command=[sys.executable, str(fake_server)],
        process_env=process_env,
        process_cwd=str(process_cwd),
        response_timeout_sec=2,
        goal_timeout_sec=2,
    )

    assert turn.terminal_event_observed is True


def test_real_stdio_process_waits_until_native_goal_is_terminal(
    tmp_path: Path,
) -> None:
    fake_server = tmp_path / "fake-continuing-codex"
    _write_fake_app_server(fake_server)
    process_env = dict(os.environ)
    process_env["FAKE_GOAL_CONTINUATION"] = "1"

    turn = run_native_goal_process_until_terminal(
        _config(
            cwd=str(tmp_path),
            sandbox_policy={
                "type": "workspaceWrite",
                "writableRoots": [str(tmp_path)],
                "networkAccess": False,
            },
        ),
        process_command=[sys.executable, str(fake_server)],
        process_env=process_env,
        response_timeout_sec=2,
        goal_timeout_sec=2,
    )

    assert turn.post_goal_status == "complete"
    assert turn.turn_started_count == 2
    assert turn.turn_completed_count == 2
    assert turn.goal_status_poll_count == 2


def test_real_stdio_preflight_attaches_goal_without_starting_turn(
    tmp_path: Path,
) -> None:
    fake_server = tmp_path / "fake-codex"
    _write_fake_app_server(fake_server)

    turn = probe_native_goal_process(
        _config(cwd=str(tmp_path)),
        process_command=[sys.executable, str(fake_server)],
        response_timeout_sec=2,
    )

    assert turn.goal_status == "active"
    assert turn.turn_id == ""
    assert turn.methods[-1] == "thread/goal/get"


def test_runnable_example_connects_to_stdio_app_server(tmp_path: Path) -> None:
    fake_server = tmp_path / "fake-codex"
    _write_fake_app_server(fake_server)
    objective = tmp_path / "objective.txt"
    task = tmp_path / "task.txt"
    objective.write_text("\nFinish the task.\n", encoding="utf-8")
    task.write_text("\nImplement the requested behavior.\n", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "benchmark" / "deepswe" / "run_native_codex_goal.py"),
            "--cwd",
            str(tmp_path),
            "--objective-file",
            str(objective),
            "--task-file",
            str(task),
            "--codex-bin",
            str(fake_server),
            "--model",
            "model-route",
            "--preflight-only",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    receipt = json.loads(completed.stdout)
    assert receipt["execution_mode"] == "goal_attachment_preflight"
    assert receipt["goal_status"] == "active"
    assert receipt["turn_id_present"] is False
    assert str(tmp_path) not in completed.stdout
