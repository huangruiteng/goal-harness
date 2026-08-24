from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ...quota import build_quota_should_run
from ..capability_hooks import (
    InteractionProjectionHookRegistration,
    dispatch_interaction_projection_hooks,
)
from .settlement import (
    receipt_bound_monitor_settlement_phase,
    receipt_bound_terminal_settlement_phase,
)
from ..scheduler.execution_context import (
    SchedulerExecutionContextResolution,
    resolve_scheduler_execution_context,
)


HostObservationResolver = Callable[..., Mapping[str, Any]]
BoundedResearchFrontierProjector = Callable[..., Mapping[str, Any] | None]


def bind_scheduler_followup_cli_routes(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
    source: str = "quota_cli_invocation",
) -> None:
    """Bind scheduler follow-ups to the registry/runtime that built the hint."""

    scheduler_hint = payload.get("scheduler_hint")
    if not isinstance(scheduler_hint, dict):
        return
    codex_app = scheduler_hint.get("codex_app")
    if not isinstance(codex_app, dict):
        return
    for hint_name in ("ack_hint", "failure_hint", "fallback_hint"):
        followup_hint = codex_app.get(hint_name)
        if not isinstance(followup_hint, dict):
            continue
        cli_args = followup_hint.get("cli_args")
        if not isinstance(cli_args, list) or not cli_args:
            continue
        if hint_name == "fallback_hint":
            if cli_args[0] != "loopx-apply-rrule" or "--registry" in cli_args:
                continue
            followup_hint["cli_args"] = [
                cli_args[0],
                "--registry",
                str(registry_path.expanduser().resolve()),
                *cli_args[1:],
            ]
            followup_hint["route_binding"] = {
                "schema_version": "codex_app_scheduler_fallback_route_v0",
                "source": source,
                "registry_bound": True,
                "runtime_root_bound": False,
            }
            continue
        if cli_args[0] == "--registry":
            continue
        followup_hint["cli_args"] = [
            "--registry",
            str(registry_path.expanduser().resolve()),
            "--runtime-root",
            str(runtime_root.expanduser().resolve()),
            *cli_args,
        ]
        followup_hint["route_binding"] = {
            "schema_version": (
                "scheduler_ack_cli_route_v0"
                if hint_name == "ack_hint"
                else "scheduler_failure_cli_route_v0"
            ),
            "source": source,
            "registry_bound": True,
            "runtime_root_bound": True,
        }


def bind_action_selection_cli_routes(
    payload: dict[str, Any],
    *,
    registry_path: Path,
    runtime_root: Path,
) -> None:
    """Bind two-phase action-selection commands to this live CLI source."""

    interaction_value = payload.get("interaction_contract")
    interaction: Mapping[str, Any] = (
        interaction_value
        if isinstance(interaction_value, Mapping)
        else {}
    )
    cli_channel_value = interaction.get("cli_channel")
    if not isinstance(cli_channel_value, dict):
        return
    cli_channel: dict[str, Any] = cli_channel_value
    if cli_channel.get("selection_required") is not True:
        return
    selection_command = cli_channel.get("selection_command")
    if not isinstance(selection_command, dict):
        return
    route_prefix = selection_command.get("route_prefix")
    if not isinstance(route_prefix, str):
        return
    try:
        tokens = shlex.split(route_prefix)
    except ValueError:
        return
    if tokens == ["loopx", "--format", "json"]:
        selection_command["route_prefix"] = shlex.join(
            [
                "loopx",
                "--registry",
                str(registry_path.expanduser().resolve()),
                "--runtime-root",
                str(runtime_root.expanduser().resolve()),
                "--format",
                "json",
            ]
        )


def build_live_quota_should_run_decision(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    agent_id: str | None,
    available_capabilities: list[str] | None,
    include_scheduler_detail: bool,
    codex_app_current_rrule: str | None,
    registry_path: Path,
    runtime_root: Path,
    host_observation_resolver: HostObservationResolver | None = None,
    route_source: str = "quota_cli_invocation",
    scheduler_execution_context: Mapping[str, Any] | SchedulerExecutionContextResolution | None = None,
    operator_inbox_urgency_projector: Callable[..., dict[str, Any]] | None = None,
    bounded_research_frontier_projector: BoundedResearchFrontierProjector | None = None,
    receipt_bound_todo_id: str | None = None,
    requested_action_todo_id: str | None = None,
    receipt_bound_replan_obligation_id: str | None = None,
    turn_instance_id: str | None = None,
    interaction_projection_hooks: Sequence[
        InteractionProjectionHookRegistration
    ]
    | None = None,
) -> dict[str, Any]:
    """Build one live CLI decision while keeping host observation injectable."""

    resolved_context = resolve_scheduler_execution_context(scheduler_execution_context)
    codex_app_applicable = (
        resolved_context.ok
        and resolved_context.context is not None
        and resolved_context.context.codex_app_applicable
    )
    observed_rrule = str(codex_app_current_rrule or "").strip()
    observed_automation_id = ""
    if (
        codex_app_applicable
        and not observed_rrule
        and host_observation_resolver is not None
    ):
        observation = host_observation_resolver(goal_id=goal_id, agent_id=agent_id)
        if observation.get("available") is True:
            observed_rrule = str(observation.get("rrule") or "")
            observed_automation_id = str(observation.get("automation_id") or "").strip()
    decision_status_payload = status_payload
    if bounded_research_frontier_projector is not None:
        frontier = bounded_research_frontier_projector(
            runtime_root=runtime_root,
            goal_id=goal_id,
            agent_id=agent_id,
            status_payload=status_payload,
        )
        if isinstance(frontier, Mapping):
            decision_status_payload = {
                **status_payload,
                "bounded_research_frontier": dict(frontier),
            }
    receipt_bound_monitor_phase = receipt_bound_monitor_settlement_phase(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=receipt_bound_todo_id,
        turn_instance_id=turn_instance_id,
    )
    receipt_bound_terminal_phase = receipt_bound_terminal_settlement_phase(
        runtime_root,
        goal_id=goal_id,
        agent_id=agent_id,
        todo_id=receipt_bound_todo_id,
        replan_obligation_id=receipt_bound_replan_obligation_id,
        turn_instance_id=turn_instance_id,
    )
    payload = build_quota_should_run(
        decision_status_payload,
        goal_id=goal_id,
        agent_id=agent_id,
        available_capabilities=available_capabilities,
        include_scheduler_detail=include_scheduler_detail,
        codex_app_current_rrule=observed_rrule,
        codex_app_automation_id=observed_automation_id or None,
        scheduler_execution_context=resolved_context,
        operator_inbox_urgency_projector=operator_inbox_urgency_projector,
        receipt_bound_todo_id=receipt_bound_todo_id,
        requested_action_todo_id=requested_action_todo_id,
        receipt_bound_monitor_phase=receipt_bound_monitor_phase,
        receipt_bound_terminal_phase=receipt_bound_terminal_phase,
        receipt_bound_replan_obligation_id=receipt_bound_replan_obligation_id,
        turn_instance_id=turn_instance_id,
    )
    hook_dispatch = dispatch_interaction_projection_hooks(
        interaction_projection_hooks
    )
    interaction = payload.get("interaction_contract")
    if isinstance(interaction, dict):
        projections = hook_dispatch["projections"]
        if isinstance(projections, Mapping):
            interaction.update(projections)
    if hook_dispatch["failures"]:
        payload["capability_hook_dispatch"] = {
            key: value
            for key, value in hook_dispatch.items()
            if key != "projections"
        }
    bind_scheduler_followup_cli_routes(
        payload,
        registry_path=registry_path,
        runtime_root=runtime_root,
        source=route_source,
    )
    bind_action_selection_cli_routes(
        payload,
        registry_path=registry_path,
        runtime_root=runtime_root,
    )
    return payload
