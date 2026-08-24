from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from ..todos.contract import normalize_todo_id


def action_portfolio_requires_explicit_selection(
    payload: Mapping[str, Any],
) -> bool:
    portfolio = payload.get("action_portfolio")
    if not isinstance(portfolio, Mapping):
        return False
    policy = portfolio.get("selection_policy")
    return bool(
        isinstance(policy, Mapping)
        and policy.get("requires_explicit_turn_binding") is True
    )


def action_portfolio_selection_actions(
    payload: Mapping[str, Any],
    *,
    scoped_cli_args: str,
    scheduler_args: str,
    turn_instance_id: str | None,
) -> list[str]:
    if not action_portfolio_requires_explicit_selection(payload):
        return []
    portfolio = payload.get("action_portfolio")
    if not isinstance(portfolio, Mapping):
        return []
    suggested_actions = portfolio.get("suggested_actions")
    if not isinstance(suggested_actions, list):
        return []
    goal_id = str(payload.get("goal_id") or "").strip()
    if not goal_id:
        return []
    turn_arg = (
        f" --turn-instance-id {shlex.quote(turn_instance_id)}"
        if turn_instance_id
        else ""
    )
    commands: list[str] = []
    for item in suggested_actions:
        if not isinstance(item, Mapping):
            continue
        todo_id = normalize_todo_id(item.get("todo_id"))
        if todo_id:
            commands.append(
                "loopx --format json quota should-run"
                f" --goal-id {shlex.quote(goal_id)}"
                f" --todo-id {shlex.quote(todo_id)}"
                f"{scoped_cli_args}{scheduler_args}{turn_arg}"
            )
    return commands


def apply_action_selection_agent_gate(
    channel: dict[str, Any],
    payload: Mapping[str, Any],
) -> None:
    if not action_portfolio_requires_explicit_selection(payload):
        return
    portfolio = payload.get("action_portfolio")
    suggested_actions = (
        portfolio.get("suggested_actions")
        if isinstance(portfolio, Mapping)
        else None
    )
    channel.update(
        {
            "selection_required": True,
            "delivery_allowed": False,
            "primary_action": (
                "choose one currently eligible action after a bounded steering "
                "audit; the recommendation and suggestions are not bindings"
            ),
            "suggested_action_count": (
                len(suggested_actions)
                if isinstance(suggested_actions, list)
                else 0
            ),
        }
    )


def apply_action_selection_cli_gate(
    channel: dict[str, Any],
    payload: Mapping[str, Any],
) -> None:
    if not action_portfolio_requires_explicit_selection(payload):
        return
    channel.update(
        {
            "selection_required": True,
            "selection_policy_ref": "$.action_portfolio.selection_policy",
            "spend_policy": (
                "no delivery or quota spend until one eligible action is "
                "explicitly bound by rerunning quota in this turn"
            ),
        }
    )


def delivery_spend_allowed(
    payload: Mapping[str, Any],
    spend_after_validation: bool,
) -> bool:
    return spend_after_validation and not action_portfolio_requires_explicit_selection(
        payload
    )
