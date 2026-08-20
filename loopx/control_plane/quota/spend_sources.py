from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..scheduler.execution_context import (
    NATIVE_GOAL_RUNTIME_PROFILES,
    SchedulerExecutionContextResolution,
    scheduler_runtime_profile_for_execution_context,
)
from ..todos.contract import normalize_todo_id
from .effect_program import SettlementStepKind, settlement_step_command


DEFAULT_SLOT_SPEND_SOURCE = "heartbeat"
VISIBLE_GOAL_SLOT_SPEND_SOURCE = "visible-goal"
VALID_SLOT_SPEND_SOURCES = {
    "heartbeat",
    "controller",
    "adapter",
    VISIBLE_GOAL_SLOT_SPEND_SOURCE,
}


def quota_spend_source_for_execution_context(
    value: Mapping[str, Any] | SchedulerExecutionContextResolution | None,
) -> str:
    profile = scheduler_runtime_profile_for_execution_context(value)
    if profile in NATIVE_GOAL_RUNTIME_PROFILES:
        return VISIBLE_GOAL_SLOT_SPEND_SOURCE
    return DEFAULT_SLOT_SPEND_SOURCE


def build_quota_spend_action(
    goal_id: str,
    *,
    scoped_cli_args: str,
    payload: Mapping[str, Any],
    settlement_plan: Mapping[str, Any] | None,
    scheduler_execution_context: (
        Mapping[str, Any] | SchedulerExecutionContextResolution | None
    ) = None,
) -> str:
    typed_command = settlement_step_command(
        settlement_plan,
        SettlementStepKind.QUOTA_SPEND,
    )
    if typed_command:
        return typed_command
    selected_value = payload.get("selected_todo")
    selected = selected_value if isinstance(selected_value, Mapping) else {}
    todo_id = normalize_todo_id(selected.get("todo_id"))
    source = quota_spend_source_for_execution_context(scheduler_execution_context)
    todo_arg = (
        f" --todo-id {todo_id}"
        if todo_id and source == DEFAULT_SLOT_SPEND_SOURCE
        else ""
    )
    return (
        f"loopx quota spend-slot --goal-id {goal_id} --slots 1 "
        f"--source {source} --execute{todo_arg}{scoped_cli_args}"
    )
