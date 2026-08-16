from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from benchmark.native_codex_goal import (
    NativeGoalConfig,
    NativeGoalProtocolError,
    compact_native_goal_receipt,
    observe_native_goal_event,
    start_native_goal_turn,
)


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

    assert observe_native_goal_event(
        turn,
        {
            "method": "turn/started",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "event-turn", "status": "inProgress"},
            },
        },
    ) is False
    assert turn.turn_id == "event-turn"
    assert observe_native_goal_event(
        turn,
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "event-turn", "status": "completed"},
            },
        },
    ) is True

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
    assert observe_native_goal_event(
        turn,
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "response-turn", "status": "failed"},
            },
        },
    ) is True
    assert turn.turn_status == "failed"
