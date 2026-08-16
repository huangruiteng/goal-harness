"""Minimal transport-neutral Codex app-server Goal transaction.

The benchmark runner owns process supervision, environment bridging, timeout,
and independent scoring. This module owns only request order, identity checks,
event correlation, and a compact receipt that excludes raw content.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol


class NativeGoalProtocolError(RuntimeError):
    """The app-server response did not prove the required Goal transaction."""


class NativeGoalTransport(Protocol):
    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def notify(self, method: str, params: Mapping[str, Any]) -> None: ...


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _nested(value: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    nested = value.get(key)
    return nested if isinstance(nested, Mapping) else {}


@dataclass(frozen=True)
class NativeGoalConfig:
    cwd: str
    objective: str
    task_instruction: str
    model: str | None = None
    effort: str | None = None
    token_budget: int | None = None
    approval_policy: str = "never"
    sandbox: str = "workspace-write"

    def validate(self) -> None:
        if not self.cwd.strip():
            raise ValueError("cwd must be non-empty")
        if not self.objective.strip():
            raise ValueError("objective must be non-empty")
        if not self.task_instruction.strip():
            raise ValueError("task_instruction must be non-empty")
        if self.token_budget is not None and (
            isinstance(self.token_budget, bool)
            or not isinstance(self.token_budget, int)
            or self.token_budget <= 0
        ):
            raise ValueError("token_budget must be a positive integer when provided")


@dataclass
class NativeGoalTurn:
    thread_id: str
    turn_id: str
    response_turn_id: str
    goal_status: str
    objective_sha256: str
    objective_chars: int
    task_instruction_sha256: str
    task_instruction_chars: int
    token_budget_present: bool
    methods: list[str] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    event_turn_id_observed: bool = False
    terminal_event_observed: bool = False
    turn_status: str = "accepted"
    item_event_count: int = 0
    error_event_count: int = 0


def start_native_goal_turn(
    transport: NativeGoalTransport,
    config: NativeGoalConfig,
) -> NativeGoalTurn:
    """Attach an active Goal to a new thread and start one task turn."""

    config.validate()
    methods: list[str] = []

    transport.request(
        "initialize",
        {
            "clientInfo": {
                "name": "loopx_benchmark_research",
                "title": "LoopX Benchmark Research",
                "version": "0.1.0",
            },
            "capabilities": {"experimentalApi": True},
        },
    )
    methods.append("initialize")
    transport.notify("initialized", {})
    methods.append("initialized")

    thread_result = transport.request(
        "thread/start",
        {
            "cwd": config.cwd,
            "sandbox": config.sandbox,
            "approvalPolicy": config.approval_policy,
        },
    )
    methods.append("thread/start")
    thread = _nested(thread_result, "thread")
    thread_id = str(thread.get("id") or thread_result.get("threadId") or "")
    if not thread_id:
        raise NativeGoalProtocolError("thread_start_id_missing")

    goal_set: dict[str, Any] = {
        "threadId": thread_id,
        "objective": config.objective,
        "status": "active",
    }
    if config.token_budget is not None:
        goal_set["tokenBudget"] = config.token_budget
    transport.request("thread/goal/set", goal_set)
    methods.append("thread/goal/set")

    goal_result = transport.request("thread/goal/get", {"threadId": thread_id})
    methods.append("thread/goal/get")
    goal = _nested(goal_result, "goal")
    if str(goal.get("status") or "") != "active":
        raise NativeGoalProtocolError("goal_not_active")
    if str(goal.get("threadId") or "") != thread_id:
        raise NativeGoalProtocolError("goal_thread_mismatch")
    if str(goal.get("objective") or "") != config.objective:
        raise NativeGoalProtocolError("goal_objective_mismatch")

    turn_params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": config.task_instruction}],
        "cwd": config.cwd,
        "approvalPolicy": config.approval_policy,
    }
    if config.model:
        turn_params["model"] = config.model
    if config.effort:
        turn_params["effort"] = config.effort
    turn_result = transport.request("turn/start", turn_params)
    methods.append("turn/start")
    turn = _nested(turn_result, "turn")
    turn_id = str(turn.get("id") or turn_result.get("turnId") or "")
    if not turn_id:
        raise NativeGoalProtocolError("turn_start_id_missing")

    return NativeGoalTurn(
        thread_id=thread_id,
        turn_id=turn_id,
        response_turn_id=turn_id,
        goal_status="active",
        objective_sha256=_digest(config.objective),
        objective_chars=len(config.objective),
        task_instruction_sha256=_digest(config.task_instruction),
        task_instruction_chars=len(config.task_instruction),
        token_budget_present=config.token_budget is not None,
        methods=methods,
        turn_status=str(turn.get("status") or "accepted"),
    )


def observe_native_goal_event(
    turn: NativeGoalTurn,
    event: Mapping[str, Any],
) -> bool:
    """Apply one app-server notification and return terminal observation state."""

    method = str(event.get("method") or "")
    params = _nested(event, "params")
    if not method:
        event_type = str(event.get("type") or "")
        payload = _nested(event, "payload")
        payload_type = str(payload.get("type") or "")
        method = f"{event_type}:{payload_type}" if event_type and payload_type else event_type
        params = payload
    if not method:
        return turn.terminal_event_observed

    turn.notifications.append(method)
    event_thread_id = str(params.get("threadId") or "")
    if event_thread_id and event_thread_id != turn.thread_id:
        return turn.terminal_event_observed
    event_turn = _nested(params, "turn")
    event_turn_id = str(event_turn.get("id") or params.get("turnId") or "")

    if method == "turn/started" and event_turn_id:
        turn.turn_id = event_turn_id
        turn.event_turn_id_observed = True
        turn.turn_status = str(event_turn.get("status") or "inProgress")
        return False
    if event_turn_id and event_turn_id != turn.turn_id:
        return turn.terminal_event_observed
    if method.startswith(("item/", "response_item:")):
        turn.item_event_count += 1
    if method == "error":
        turn.error_event_count += 1
        turn.turn_status = "error"
    if method == "turn/completed" or method in {
        "event_msg:task_complete",
        "event_msg:task_completed",
        "event_msg:turn_completed",
    }:
        turn.terminal_event_observed = True
        turn.turn_status = str(event_turn.get("status") or "completed")
    return turn.terminal_event_observed


def compact_native_goal_receipt(turn: NativeGoalTurn) -> dict[str, Any]:
    """Return public-safe transaction evidence without task or response content."""

    return {
        "schema_version": "native_codex_goal_turn_receipt_v0",
        "thread_id_present": bool(turn.thread_id),
        "turn_id_present": bool(turn.turn_id),
        "response_turn_id_present": bool(turn.response_turn_id),
        "event_turn_id_observed": turn.event_turn_id_observed,
        "goal_status": turn.goal_status,
        "token_budget_present": turn.token_budget_present,
        "objective_sha256": turn.objective_sha256,
        "objective_chars": turn.objective_chars,
        "task_instruction_sha256": turn.task_instruction_sha256,
        "task_instruction_chars": turn.task_instruction_chars,
        "methods": list(turn.methods),
        "notifications": sorted(set(turn.notifications)),
        "turn_status": turn.turn_status,
        "terminal_event_observed": turn.terminal_event_observed,
        "item_event_count": turn.item_event_count,
        "error_event_count": turn.error_event_count,
        "public_boundary": {
            "raw_objective_recorded": False,
            "raw_task_instruction_recorded": False,
            "raw_assistant_message_recorded": False,
            "raw_tool_events_recorded": False,
            "credentials_recorded": False,
            "local_paths_recorded": False,
        },
    }
