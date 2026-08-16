from __future__ import annotations

import json
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


def _write_fake_app_server(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            r"""
            #!/usr/bin/env python3
            import json
            import sys

            objective = ""
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
                    result = {"thread": {"id": "thread-1"}}
                elif method == "thread/goal/set":
                    objective = params["objective"]
                    result = {"goal": {"threadId": "thread-1"}}
                elif method == "thread/goal/get":
                    result = {
                        "goal": {
                            "threadId": "thread-1",
                            "objective": objective,
                            "status": "active",
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
    objective.write_text("Finish the task.", encoding="utf-8")
    task.write_text("Implement the requested behavior.", encoding="utf-8")

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
