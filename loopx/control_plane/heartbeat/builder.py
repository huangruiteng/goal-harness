"""Heartbeat prompt builder inside the heartbeat bounded context."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from ...agent_registry import normalize_registered_agents
from ...ark_managed_agent_host import build_ark_managed_agent_host_contract
from ..agents.runtime_model import AgentRuntimeModel
from ..quota.spend_sources import (
    DEFAULT_SLOT_SPEND_SOURCE,
    VISIBLE_GOAL_SLOT_SPEND_SOURCE,
)
from ..scheduler.execution_context import (
    SchedulerRuntimeProfile,
    render_scheduler_execution_args,
)
from ..todos.contract import (
    normalize_required_capabilities,
    normalize_todo_claimed_by,
)
from .agent import (
    agent_prompt_command_args,
    agent_profile_prompt_projection,
    agent_profile_scopes,
    build_peer_identity_required_error,
    normalize_agent_scopes,
    render_peer_agent_scope_instruction,
)
from .budget import (
    NATIVE_GOAL_HOST_MAX_CHARS,
    build_interface_budget,
)
from .host import (
    uses_ark_managed_agent_goal_host,
    uses_native_goal_host_loop,
)
from .rules import (
    DEFAULT_MATERIAL_QUEUE_RULE,
    DEFAULT_PERMISSION_RULE,
)
from .task_body import (
    render_ark_managed_agent_goal_task_body,
    render_brief_heartbeat_task_body,
    render_compact_heartbeat_task_body,
    render_heartbeat_task_body,
    render_thin_heartbeat_task_body,
    render_traex_visible_goal_task_body,
    render_visible_goal_task_body,
)
from .visible_goal import (
    build_visible_goal_initial_runtime_capability_projection,
    validate_visible_goal_policy_rule,
)
from ...project_prompt import (
    render_accountable_progress_refresh_command,
    render_available_capability_args,
    render_cli_preflight,
    render_quota_guard_command,
    render_quota_spend_command,
    render_refresh_state_command,
)


def _select_task_body_renderer(
    *,
    traex_visible_goal: bool,
    ark_managed_agent_goal: bool,
    native_goal_host: bool,
    thin: bool,
    brief: bool,
    compact: bool,
) -> Any:
    if traex_visible_goal:
        return render_traex_visible_goal_task_body
    if ark_managed_agent_goal:
        return render_ark_managed_agent_goal_task_body
    if native_goal_host:
        return render_visible_goal_task_body
    if thin:
        return render_thin_heartbeat_task_body
    if brief:
        return render_brief_heartbeat_task_body
    if compact:
        return render_compact_heartbeat_task_body
    return render_heartbeat_task_body


def build_heartbeat_prompt(
    *,
    goal_id: str,
    active_state: Path | None = None,
    active_state_source: str = "explicit",
    resolved_active_state: Path | None = None,
    material_queue_rule: str | None = None,
    permission_rule: str | None = None,
    full: bool = False,
    compact: bool = False,
    brief: bool = False,
    thin: bool = False,
    cli_bin: str = "loopx",
    agent_id: str | None = None,
    agent_scopes: list[str] | tuple[str, ...] | None = None,
    agent_profile: dict[str, Any] | None = None,
    registered_agents: list[str] | tuple[str, ...] | None = None,
    available_capabilities: list[str] | tuple[str, ...] | None = None,
    runtime_profile: str | None = None,
    scheduler_execution_context: dict[str, Any] | None = None,
    visible_goal_host: str | None = None,
) -> dict[str, Any]:
    if not (full or compact or brief or thin):
        thin = True
    if visible_goal_host not in {None, "traex-cli"}:
        raise ValueError(f"unsupported visible goal host: {visible_goal_host}")
    if visible_goal_host == "traex-cli" and (
        runtime_profile != SchedulerRuntimeProfile.GENERIC_CLI_AGENT_LOOP.value
        or scheduler_execution_context is not None
    ):
        raise ValueError(
            "visible_goal_host='traex-cli' requires runtime_profile='generic_cli' "
            "without scheduler_execution_context"
        )
    traex_visible_goal = visible_goal_host == "traex-cli"
    native_goal_host = uses_native_goal_host_loop(
        runtime_profile=runtime_profile,
        scheduler_execution_context=scheduler_execution_context,
    ) or traex_visible_goal
    ark_managed_agent_goal = uses_ark_managed_agent_goal_host(
        runtime_profile=runtime_profile,
        scheduler_execution_context=scheduler_execution_context,
    )
    effective_resolved_active_state = resolved_active_state or active_state
    active_state_text = str(active_state.expanduser()) if active_state else "the registry-declared active state"
    if active_state:
        resolved_active_state_source = active_state_source
    else:
        resolved_active_state_source = "registry" if active_state_source == "explicit" else active_state_source
    active_state_arg = f" --active-state {active_state_text}" if active_state else ""
    resolved_material_rule = material_queue_rule or DEFAULT_MATERIAL_QUEUE_RULE
    resolved_permission_rule = permission_rule or DEFAULT_PERMISSION_RULE
    if traex_visible_goal:
        validate_visible_goal_policy_rule(
            field="material_queue_rule",
            value=resolved_material_rule,
        )
        validate_visible_goal_policy_rule(
            field="permission_rule",
            value=resolved_permission_rule,
        )
    normalized_agent_id = normalize_todo_claimed_by(agent_id) if agent_id else None
    if agent_id and not normalized_agent_id:
        raise ValueError("agent_id must be a public-safe token such as codex-main-control")
    explicit_agent_scopes = normalize_agent_scopes(agent_scopes)
    profile_agent_scopes = agent_profile_scopes(agent_profile)
    normalized_agent_scopes = explicit_agent_scopes or profile_agent_scopes
    if traex_visible_goal:
        for scope in normalized_agent_scopes:
            validate_visible_goal_policy_rule(field="agent_scope", value=scope)
    agent_scope_source = "argument" if explicit_agent_scopes else "agent_profile_v1" if profile_agent_scopes else None
    if normalized_agent_scopes and not normalized_agent_id:
        raise ValueError("--agent-scope requires --agent-id so claimed_by uses a registered agent")
    normalized_registered_agents = normalize_registered_agents(registered_agents)
    if normalized_registered_agents and not normalized_agent_id:
        raise ValueError(
            build_peer_identity_required_error(
                goal_id=goal_id,
                cli_bin=cli_bin,
                active_state_arg=active_state_arg,
                full=full,
                compact=compact,
                brief=brief,
                thin=thin,
                registered_agents=normalized_registered_agents,
            )
        )
    if normalized_agent_id:
        if registered_agents is not None and not normalized_registered_agents:
            raise ValueError("agent_id cannot be used until registered_agents are configured")
        if normalized_registered_agents and normalized_agent_id not in normalized_registered_agents:
            raise ValueError(
                f"agent_id={normalized_agent_id!r} is not registered; "
                f"registered_agents={', '.join(normalized_registered_agents)}"
            )
    agent_role = "peer-agent" if normalized_agent_id else None
    command_agent_scopes = explicit_agent_scopes
    agent_args = agent_prompt_command_args(
        agent_id=normalized_agent_id,
        agent_scopes=command_agent_scopes,
    )
    normalized_available_capabilities = normalize_required_capabilities(
        available_capabilities
    )
    initial_runtime_capability_projection = (
        build_visible_goal_initial_runtime_capability_projection(
            normalized_available_capabilities
        )
        if traex_visible_goal
        else None
    )
    if initial_runtime_capability_projection:
        task_body_available_capabilities = initial_runtime_capability_projection[
            "capabilities"
        ]
    elif traex_visible_goal:
        task_body_available_capabilities = []
    else:
        task_body_available_capabilities = normalized_available_capabilities
    capability_args = render_available_capability_args(
        normalized_available_capabilities
    )
    agent_scope_instruction = render_peer_agent_scope_instruction(
        goal_id=goal_id,
        agent_id=normalized_agent_id,
        agent_scopes=normalized_agent_scopes,
        cli_bin=cli_bin,
        compact=compact or brief,
        thin=thin,
    )
    quota_guard_command = render_quota_guard_command(
        goal_id,
        cli_bin=cli_bin,
        agent_id=normalized_agent_id,
        available_capabilities=normalized_available_capabilities,
        runtime_profile=runtime_profile,
        scheduler_execution_context=scheduler_execution_context,
        heartbeat_turn_receipt=not native_goal_host,
    )
    quota_spend_command = render_quota_spend_command(
        goal_id,
        source=(
            VISIBLE_GOAL_SLOT_SPEND_SOURCE
            if native_goal_host
            else DEFAULT_SLOT_SPEND_SOURCE
        ),
        cli_bin=cli_bin,
        agent_id=normalized_agent_id,
        available_capabilities=normalized_available_capabilities,
    )
    task_body_quota_guard_command = quota_guard_command
    task_body_quota_spend_command = quota_spend_command
    if traex_visible_goal:
        task_body_quota_guard_command = render_quota_guard_command(
            goal_id,
            cli_bin=cli_bin,
            agent_id=normalized_agent_id,
            available_capabilities=task_body_available_capabilities,
            runtime_profile=runtime_profile,
            scheduler_execution_context=scheduler_execution_context,
        )
        task_body_quota_spend_command = render_quota_spend_command(
            goal_id,
            source=VISIBLE_GOAL_SLOT_SPEND_SOURCE,
            cli_bin=cli_bin,
            agent_id=normalized_agent_id,
        )
    refresh_state_command = render_refresh_state_command(
        goal_id,
        cli_bin=cli_bin,
        agent_id=normalized_agent_id,
    )
    progress_refresh_state_command = render_accountable_progress_refresh_command(
        goal_id,
        cli_bin=cli_bin,
        agent_id=normalized_agent_id,
    )
    cli_preflight = render_cli_preflight(cli_bin=cli_bin)
    pr_review_pre_quota_command = (
        f"{cli_bin} heartbeat-prequota -g {shlex.quote(goal_id)} "
        f"-a {shlex.quote(normalized_agent_id)}"
        if normalized_agent_id
        and "external_evidence_poll" in normalized_available_capabilities
        else ""
    )
    scheduler_args = render_scheduler_execution_args(
        runtime_profile=runtime_profile,
        scheduler_execution_context=scheduler_execution_context,
    )
    expanded_prompt_command = f"{cli_bin} heartbeat-prompt --full --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}{scheduler_args}"
    compact_prompt_command = f"{cli_bin} heartbeat-prompt --compact --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}{scheduler_args}"
    brief_prompt_command = f"{cli_bin} heartbeat-prompt --brief --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}{scheduler_args}"
    thin_prompt_command = f"{cli_bin} heartbeat-prompt --thin --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}{scheduler_args}"
    task_body_renderer = _select_task_body_renderer(
        traex_visible_goal=traex_visible_goal,
        ark_managed_agent_goal=ark_managed_agent_goal,
        native_goal_host=native_goal_host,
        thin=thin,
        brief=brief,
        compact=compact,
    )
    task_body = task_body_renderer(
        goal_id=goal_id,
        active_state=active_state_text,
        cli_preflight=cli_preflight,
        pr_review_pre_quota_command=(
            "" if traex_visible_goal else pr_review_pre_quota_command
        ),
        quota_guard_command=task_body_quota_guard_command,
        quota_spend_command=task_body_quota_spend_command,
        refresh_state_command=refresh_state_command,
        progress_refresh_state_command=progress_refresh_state_command,
        material_queue_rule=resolved_material_rule,
        permission_rule=resolved_permission_rule,
        cli_bin=cli_bin,
        agent_scope_instruction=agent_scope_instruction,
        expanded_prompt_command=expanded_prompt_command,
        compact_prompt_command=compact_prompt_command,
        brief_prompt_command=brief_prompt_command,
        thin_prompt_command=thin_prompt_command,
    )
    if native_goal_host and len(task_body) > NATIVE_GOAL_HOST_MAX_CHARS:
        host_limit = (
            "Ark Managed Agent goal prompt"
            if ark_managed_agent_goal
            else "visible TraeX /goal task body"
            if traex_visible_goal
            else "visible Codex /goal task body"
        )
        raise ValueError(
            f"generated {host_limit} exceeds the 4000-character host budget; "
            "shorten agent scopes or project-specific prompt rules"
        )
    payload = {
        "ok": True,
        "goal_id": goal_id,
        "active_state": active_state_text,
        "active_state_source": resolved_active_state_source,
        "resolved_active_state": str(effective_resolved_active_state.expanduser())
        if effective_resolved_active_state
        else None,
        "compact": compact,
        "brief": brief,
        "thin": thin,
        "cli_bin": cli_bin,
        "agent_id": normalized_agent_id,
        "agent_role": agent_role,
        "agent_scopes": normalized_agent_scopes,
        "agent_scope_source": agent_scope_source,
        "agent_profile": agent_profile_prompt_projection(agent_profile),
        "registered_agents": normalized_registered_agents,
        "runtime_profile": runtime_profile,
        "scheduler_execution_context": scheduler_execution_context,
        **(
            {"visible_goal_host": visible_goal_host}
            if visible_goal_host
            else {}
        ),
        **(
            {
                "initial_runtime_capability_projection": (
                    initial_runtime_capability_projection
                )
            }
            if initial_runtime_capability_projection
            else {}
        ),
        **(
            {"host_contract": build_ark_managed_agent_host_contract()}
            if ark_managed_agent_goal
            else {}
        ),
        "expanded_prompt_command": expanded_prompt_command,
        "compact_prompt_command": compact_prompt_command,
        "brief_prompt_command": brief_prompt_command,
        "thin_prompt_command": thin_prompt_command,
        "pr_review_pre_quota_command": pr_review_pre_quota_command or None,
        "quota_guard_command": quota_guard_command,
        "quota_spend_command": quota_spend_command,
        "refresh_state_command": refresh_state_command,
        "progress_refresh_state_command": progress_refresh_state_command,
        "cli_preflight": cli_preflight,
        "material_queue_rule": resolved_material_rule,
        "permission_rule": resolved_permission_rule,
        "interface_budget": build_interface_budget(
            task_body=task_body,
            goal_id=goal_id,
            active_state=active_state_text,
            full=full,
            compact=compact,
            brief=brief,
            thin=thin,
            native_goal_host=native_goal_host,
        ),
        "task_body": task_body,
    }
    payload["agent_model"] = AgentRuntimeModel.PEER_V1.value
    if thin:
        payload.pop("compact_prompt_command", None)
        payload.pop("brief_prompt_command", None)
    return payload
def build_heartbeat_prompt_error_payload(
    *,
    goal_id: str,
    error: str,
    active_state: Path | None = None,
    active_state_source: str | None = None,
    resolved_active_state: Path | None = None,
    full: bool = False,
    compact: bool = False,
    brief: bool = False,
    thin: bool = False,
    cli_bin: str = "loopx",
    agent_id: str | None = None,
    agent_scopes: list[str] | tuple[str, ...] | None = None,
    registered_agents: list[str] | tuple[str, ...] | None = None,
    available_capabilities: list[str] | tuple[str, ...] | None = None,
    material_queue_rule: str | None = None,
    permission_rule: str | None = None,
) -> dict[str, Any]:
    if not (full or compact or brief or thin):
        thin = True
    active_state_text = str(active_state.expanduser()) if active_state else "the registry-declared active state"
    source = active_state_source or ("explicit" if active_state else "registry")
    active_state_arg = f" --active-state {active_state_text}" if active_state else ""
    projected_agent_scopes = []
    for value in agent_scopes or []:
        scope = " ".join(str(value or "").strip().split())
        if scope and scope not in projected_agent_scopes:
            projected_agent_scopes.append(scope)
    agent_args = agent_prompt_command_args(
        agent_id=str(agent_id).strip() if agent_id else None,
        agent_scopes=projected_agent_scopes,
    )
    projected_available_capabilities = normalize_required_capabilities(
        available_capabilities
    )
    capability_args = render_available_capability_args(
        projected_available_capabilities
    )
    expanded_prompt_command = f"{cli_bin} heartbeat-prompt --full --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}"
    compact_prompt_command = f"{cli_bin} heartbeat-prompt --compact --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}"
    brief_prompt_command = f"{cli_bin} heartbeat-prompt --brief --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}"
    thin_prompt_command = f"{cli_bin} heartbeat-prompt --thin --goal-id {goal_id}{active_state_arg}{agent_args}{capability_args}"
    normalized_registered_agents = normalize_registered_agents(registered_agents)
    payload = {
        "ok": False,
        "goal_id": goal_id,
        "error": error,
        "active_state": active_state_text,
        "active_state_source": source,
        "resolved_active_state": str(resolved_active_state.expanduser()) if resolved_active_state else None,
        "compact": compact,
        "brief": brief,
        "thin": thin,
        "cli_bin": cli_bin,
        "agent_id": str(agent_id).strip() if agent_id else None,
        "agent_role": None,
        "agent_scopes": projected_agent_scopes,
        "agent_scope_source": "argument" if projected_agent_scopes else None,
        "agent_profile": None,
        "registered_agents": normalized_registered_agents,
        "expanded_prompt_command": expanded_prompt_command,
        "compact_prompt_command": compact_prompt_command,
        "brief_prompt_command": brief_prompt_command,
        "thin_prompt_command": thin_prompt_command,
        "quota_guard_command": None,
        "quota_spend_command": None,
        "cli_preflight": None,
        "material_queue_rule": material_queue_rule,
        "permission_rule": permission_rule,
        "interface_budget": None,
        "task_body": None,
    }
    payload["agent_model"] = AgentRuntimeModel.PEER_V1.value
    return payload
