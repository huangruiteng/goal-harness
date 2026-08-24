from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any


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


def action_portfolio_selection_command_template(
    payload: Mapping[str, Any],
    *,
    scoped_cli_args: str,
    scheduler_args: str,
    turn_instance_id: str | None,
) -> str | None:
    if not action_portfolio_requires_explicit_selection(payload):
        return None
    goal_id = str(payload.get("goal_id") or "").strip()
    if not goal_id:
        return None
    turn_arg = (
        f" --turn-instance-id {shlex.quote(turn_instance_id)}"
        if turn_instance_id
        else ""
    )
    return (
        "loopx --format json quota should-run"
        f" --goal-id {shlex.quote(goal_id)}"
        " --todo-id {todo_id}"
        f"{scoped_cli_args}{scheduler_args}{turn_arg}"
    )


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
                "choose any current eligible Todo; recommendations are non-binding"
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
    actions = channel.get("next_cli_actions")
    command_template = (
        actions[0]
        if isinstance(actions, list)
        and len(actions) == 1
        and isinstance(actions[0], str)
        else None
    )
    channel["next_cli_actions"] = []
    goal_id = str(payload.get("goal_id") or "").strip()
    command_args_template: str | None = None
    if command_template:
        try:
            command_tokens = shlex.split(command_template)
        except ValueError:
            command_tokens = []
        if command_tokens[:3] == ["loopx", "--format", "json"]:
            command_args_template = shlex.join(command_tokens[3:])
    if command_args_template is None:
        raise RuntimeError(
            "explicit action selection requires one typed quota command template"
        )
    channel.update(
        {
            "selection_required": True,
            "selection_policy_ref": "$.action_portfolio.selection_policy",
            "spend_policy": (
                "no delivery or quota spend until one eligible action is "
                "explicitly bound by rerunning quota in this turn"
            ),
            "selection_command": {
                "schema_version": "action_selection_cli_command_v1",
                "route_prefix": "loopx --format json",
                "command_args_template": command_args_template,
                "candidate_discovery_args": (
                    "todo list"
                    f" --goal-id {shlex.quote(goal_id)}"
                    " --role agent --status open --limit 50"
                ),
            },
        }
    )


def delivery_spend_allowed(
    payload: Mapping[str, Any],
    spend_after_validation: bool,
) -> bool:
    return spend_after_validation and not action_portfolio_requires_explicit_selection(
        payload
    )
