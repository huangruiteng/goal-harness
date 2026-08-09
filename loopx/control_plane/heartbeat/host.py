"""Heartbeat host detection helpers inside the heartbeat bounded context."""

from __future__ import annotations

from typing import Any

from ..scheduler.execution_context import (
    ExecutionMode,
    HostSurface,
    NATIVE_GOAL_RUNTIME_PROFILES,
    SchedulerOwner,
    SchedulerRuntimeProfile,
    resolve_scheduler_execution_context,
)


def uses_native_goal_host_loop(
    *,
    runtime_profile: str | None,
    scheduler_execution_context: dict[str, Any] | None,
) -> bool:
    if runtime_profile:
        try:
            profile = SchedulerRuntimeProfile(runtime_profile)
        except ValueError:
            return False
        return profile in NATIVE_GOAL_RUNTIME_PROFILES
    if scheduler_execution_context is None:
        return False
    resolution = resolve_scheduler_execution_context(scheduler_execution_context)
    if not resolution.ok or resolution.context is None:
        return False
    context = resolution.context
    if context.execution_mode is not ExecutionMode.INTERACTIVE:
        return False
    if context.host_surface is HostSurface.ARK_MANAGED_AGENT:
        return context.scheduler_owner is SchedulerOwner.GOAL_RUNTIME
    return (
        context.host_surface in {HostSurface.CODEX_APP_SSH, HostSurface.CODEX_CLI}
        and context.scheduler_owner is SchedulerOwner.AGENT_CLI_LOOP
    )


def uses_ark_managed_agent_goal_host(
    *,
    runtime_profile: str | None,
    scheduler_execution_context: dict[str, Any] | None,
) -> bool:
    if runtime_profile:
        try:
            return (
                SchedulerRuntimeProfile(runtime_profile)
                is SchedulerRuntimeProfile.ARK_MANAGED_AGENT_GOAL
            )
        except ValueError:
            return False
    if scheduler_execution_context is None:
        return False
    resolution = resolve_scheduler_execution_context(scheduler_execution_context)
    return bool(
        resolution.ok
        and resolution.context is not None
        and resolution.context.host_surface is HostSurface.ARK_MANAGED_AGENT
    )
