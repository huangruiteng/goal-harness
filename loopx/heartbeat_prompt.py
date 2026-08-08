from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from .ark_managed_agent_host import build_ark_managed_agent_host_contract
from .agent_registry import normalize_registered_agents
from .project_prompt import (
    render_accountable_progress_refresh_command,
    render_available_capability_args,
    render_cli_preflight,
    render_quota_guard_command,
    render_quota_spend_command,
    render_refresh_state_command,
    render_scheduler_execution_args,
)
from .control_plane.scheduler.execution_context import (
    ExecutionMode,
    HostSurface,
    NATIVE_GOAL_RUNTIME_PROFILES,
    SchedulerOwner,
    SchedulerRuntimeProfile,
    resolve_scheduler_execution_context,
)
from .control_plane.agents.capability_gate import (
    runtime_capabilities_for_cli_projection,
)
from .control_plane.quota.spend_sources import (
    DEFAULT_SLOT_SPEND_SOURCE,
    VISIBLE_GOAL_SLOT_SPEND_SOURCE,
)
from .control_plane.todos.contract import (
    normalize_required_capabilities,
    normalize_todo_claimed_by,
)
from .control_plane.agents.runtime_model import (
    AgentRuntimeModel,
    PEER_AGENT_PROFILE_SCHEMA_VERSION,
)
from .control_plane.work_items.runtime_capability_reentry import (
    RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
)


DEFAULT_MATERIAL_QUEUE_RULE = "Do not consume the learning material queue unless the user explicitly asks."
DEFAULT_PERMISSION_RULE = "Do not ask for permissions when the current Codex session is already trusted."
USER_TODO_FINAL_MESSAGE_RULE = (
    "`interaction_contract.user_channel.notify` controls output: `NOTIFY` -> concrete "
    "action; otherwise quiet. `should_run`/due monitor and other-agent scoped todos "
    "are not user prompts. Only inside `NOTIFY`, `action_required` without an action -> "
    '"具体 user todo 未投影，需修复 LoopX 状态投影"; with `DONT_NOTIFY`, repair '
    "the projection internally and stay quiet."
)
HEARTBEAT_NOTIFICATION_RULE_SHORT = (
    "`user_channel.notify`: NOTIFY=Chinese action; DONT_NOTIFY=quiet. "
    "Due/peer gate != prompt; missing NOTIFY action->"
    "具体user todo未投影，需修复LoopX状态投影."
)
HEARTBEAT_VISION_WRITEBACK_RULE_SHORT = (
    "writeback: no-change=`surface_only`/no spend; "
    "unchanged->`--vision-unchanged-reason`; material->actual outcome."
)
SCHEDULER_HINT_APPLICATION_RULE = (
    "`scheduler_hint` no-spend. host_action=pause_or_delete_current_heartbeat -> "
    "automation_update stop once, verify, end; else apply_needed -> RRULE then "
    "ack/failure_hint; ack_needed -> ack."
)
SCHEDULER_HINT_COMPACT_RULE = (
    "host_action=pause_or_delete_current_heartbeat: automation_update stop; "
    "else RRULE apply/ack/fail. No spend."
)
SCHEDULER_HINT_THIN_RULE = (
    "host_action=pause_or_delete_current_heartbeat->automation_update stop(no-spend); "
    "else RRULE/ack/fail."
)
RUNTIME_CAPABILITY_PROJECTION_THIN_RULE = (
    "Observed capabilities -> `--available-capability`; never user gates."
)
RUNTIME_EXECUTION_ROUTING_RULE = (
    "Normal turns use CLI `interaction_contract`; use `loopx-project` for "
    "lifecycle/registry and `loopx-self-repair` for runtime/projection drift."
)
CODEX_NATIVE_GOAL_UNCHANGED_WAIT_RULE = """

Native Codex `/goal` owns its blocked state. At the matching
`scheduler_hint.unchanged_poll` limit, rerun quota once. If the same blocking
condition remains for the third consecutive Goal turn and no meaningful progress
is possible, call `update_goal` with `status=blocked`. This stops native Goal
continuation without spending or completing LoopX. Only user `/goal resume`
reactivates it; rerun quota after resume."""
INTERFACE_BUDGET_CHARS = {
    "full": 12_000,
    "compact": 6_200,
    "brief": 3_500,
    "thin": 1_750,
    "visible_goal": 4_000,
}
NATIVE_GOAL_HOST_MAX_CHARS = INTERFACE_BUDGET_CHARS["visible_goal"]
VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_PROJECTION_SCHEMA_VERSION = (
    "visible_goal_initial_runtime_capability_projection_v0"
)
VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT = 8
VISIBLE_GOAL_HOST_CONTROL_CAPABILITIES = frozenset(
    {
        "automation_update",
        "current_time",
        "first_turn_receipt",
        "heartbeat_prequota",
        "loop",
        "loopx_turn",
        "rrule",
        "scheduler_execution_context",
        "turn_instance_id",
    }
)
VISIBLE_GOAL_HEARTBEAT_ONLY_POLICY_PATTERNS = (
    re.compile(r"(?<![a-z0-9_/])/loop(?![a-z0-9_-])", re.IGNORECASE),
    re.compile(r"\bautomation(?:[\s_-]+update)?\b", re.IGNORECASE),
    re.compile(r"\bheartbeat(?:[\s_-]+prequota)?\b", re.IGNORECASE),
    re.compile(r"\brrule\b", re.IGNORECASE),
    re.compile(r"\breceipt\b|\bfirst[\s_-]*turn[\s_-]*receipt\b", re.IGNORECASE),
    re.compile(r"\bcurrent[\s_-]*time(?:[\s_-]*iso)?\b", re.IGNORECASE),
    re.compile(r"\bloopx[\s_-]*turn\b", re.IGNORECASE),
    re.compile(r"\bturn[\s_-]*instance[\s_-]*id\b", re.IGNORECASE),
    re.compile(r"\bscheduler(?:[\s_-]*execution[\s_-]*context)?\b", re.IGNORECASE),
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


def heartbeat_prompt_mode(
    *,
    full: bool = False,
    compact: bool = False,
    brief: bool = False,
    thin: bool = False,
) -> str:
    if full:
        return "full"
    if thin:
        return "thin"
    if brief:
        return "brief"
    if compact:
        return "compact"
    return "thin"


def prompt_budget_text(text: str, *, goal_id: str, active_state: str) -> str:
    return text.replace(goal_id, "<GOAL_ID>").replace(active_state, "<ACTIVE_STATE>")


def normalize_agent_scope(value: Any) -> str | None:
    candidate = " ".join(str(value or "").strip().split())
    if not candidate:
        return None
    if len(candidate) > 180 or any(char in candidate for char in "<>"):
        raise ValueError("agent scope must be compact text without angle brackets")
    return candidate


def normalize_agent_scopes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    scopes: list[str] = []
    for value in values or []:
        scope = normalize_agent_scope(value)
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def build_visible_goal_initial_runtime_capability_projection(
    available_capabilities: Any,
) -> dict[str, Any] | None:
    capabilities = [
        capability
        for capability in runtime_capabilities_for_cli_projection(
            available_capabilities
        )
        if capability not in VISIBLE_GOAL_HOST_CONTROL_CAPABILITIES
    ]
    if not capabilities:
        return None
    if len(capabilities) > VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT:
        raise ValueError(
            "visible Goal initial runtime capabilities exceed the limit of "
            f"{VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT}"
        )
    return {
        "schema_version": (
            VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_PROJECTION_SCHEMA_VERSION
        ),
        "source": "activation_available_capabilities",
        "scope": "visible_goal_session",
        "capabilities": capabilities,
        "capability_count": len(capabilities),
        "max_capabilities": VISIBLE_GOAL_INITIAL_RUNTIME_CAPABILITY_LIMIT,
        "first_quota_path": "task_body.quota_guard_command",
        "user_gate": False,
        "durable_grant_written": False,
        "dynamic_reentry_schema_version": RUNTIME_CAPABILITY_REENTRY_SCHEMA_VERSION,
    }


def validate_visible_goal_policy_rule(*, field: str, value: str) -> None:
    if any(
        pattern.search(value)
        for pattern in VISIBLE_GOAL_HEARTBEAT_ONLY_POLICY_PATTERNS
    ):
        raise ValueError(
            f"visible Goal {field} contains heartbeat-only control vocabulary"
        )


def agent_profile_scopes(profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(profile, dict):
        return []
    raw_scopes: list[Any] = []
    for key in ("scope_summary", "default_scope", "scope"):
        value = profile.get(key)
        if isinstance(value, list):
            raw_scopes.extend(value)
        elif value:
            raw_scopes.append(value)
    for key in ("scope_summaries", "default_scopes", "scopes"):
        value = profile.get(key)
        if isinstance(value, list):
            raw_scopes.extend(value)
    return normalize_agent_scopes(raw_scopes)


def agent_profile_prompt_projection(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return None
    public_keys = {
        "schema_version",
        "agent_id",
        "profile_role",
        "scope_summary",
        "default_scope",
        "scope",
        "scope_summaries",
        "default_scopes",
        "scopes",
        "default_task_classes",
        "vision_requirement",
        "preferred_action_kinds",
        "avoid_action_kinds",
    }
    projection = {key: value for key, value in profile.items() if key in public_keys}
    projection["schema_version"] = PEER_AGENT_PROFILE_SCHEMA_VERSION
    return projection or None


def agent_prompt_command_args(*, agent_id: str | None, agent_scopes: list[str]) -> str:
    parts: list[str] = []
    if agent_id:
        parts.extend(["--agent-id", agent_id])
    for scope in agent_scopes:
        parts.extend(["--agent-scope", scope])
    return "".join(f" {shlex.quote(part)}" for part in parts)


def build_peer_identity_required_error(
    *,
    goal_id: str,
    cli_bin: str,
    active_state_arg: str,
    full: bool,
    compact: bool,
    brief: bool,
    thin: bool,
    registered_agents: list[str],
) -> str:
    mode_arg = (
        " --thin"
        if thin
        else " --brief"
        if brief
        else " --compact"
        if compact
        else " --full"
        if full
        else ""
    )
    base = (
        f"{cli_bin} heartbeat-prompt{mode_arg} "
        f"--goal-id {shlex.quote(goal_id)}{active_state_arg}"
    )
    examples = "; ".join(
        f"`{base} --agent-id {shlex.quote(agent)} "
        "--agent-scope 'peer task claims and leases'`"
        for agent in registered_agents[:2]
    )
    return (
        "identity-aware peer heartbeat prompt required: "
        f"coordination.registered_agents is configured for goal_id={goal_id!r}, "
        "so automation prompts without --agent-id are not accepted. Regenerate each "
        f"installed automation with its registered identity. Examples: {examples}."
    )


def render_peer_agent_scope_instruction(
    *,
    goal_id: str,
    agent_id: str | None,
    agent_scopes: list[str],
    cli_bin: str,
    compact: bool = False,
    thin: bool = False,
) -> str:
    if not agent_id and not agent_scopes:
        return ""
    identity = agent_id or "<registered-agent-id>"
    scope_text = "; ".join(agent_scopes) if agent_scopes else "registered peer lane"
    scope_text = scope_text.rstrip(".!?")
    claim_command = (
        f"{cli_bin} todo claim --goal-id {goal_id} --todo-id <todo_id> "
        f"--claimed-by {agent_id} --agent-id {agent_id}"
        if agent_id
        else f"{cli_bin} todo claim --goal-id {goal_id} --todo-id <todo_id> "
        "--claimed-by <agent_id> --agent-id <agent_id>"
    )
    peer_rule = (
        "You are an equal peer agent: claim or lease in-scope work; use an independent worktree "
        "for repository writes; follow todo continuation policy. PR review is "
        "user_action with a runnable successor; gate only exact merge/release/launch "
        "authority. Task-scoped coordination grants no authority over other agents."
    )
    if thin:
        return (
            f"Equal peer `{identity}` (peer_v1); scope: {scope_text}. Claim/lease first; "
            "independent repo worktree; todo continuation; no cross-agent authority; "
            "no scope in todo metadata."
        )
    if compact:
        return (
            f"Agent identity and scope: agent_id `{identity}`; model: peer_v1; "
            f"scope: {scope_text}. {peer_rule} Claim: `{claim_command}`. "
            "Do not write scope into todo metadata."
        )
    return f"""Agent identity and scope:

- agent_id: `{identity}`
- agent_model: `peer_v1`
- scope: {scope_text}

{peer_rule}

Before delivery, claim an in-scope open todo:

```bash
{claim_command}
```

If a todo is claimed or leased by another peer, choose another in-scope item or
record no in-scope work internally. Only `NOTIFY` reports it; `DONT_NOTIFY` stays quiet.
Scope belongs in the heartbeat prompt, not todo metadata.
"""


def build_interface_budget(
    *,
    task_body: str,
    goal_id: str,
    active_state: str,
    full: bool = False,
    compact: bool = False,
    brief: bool = False,
    thin: bool = False,
    native_goal_host: bool = False,
) -> dict[str, Any]:
    mode = (
        "visible_goal"
        if native_goal_host
        else heartbeat_prompt_mode(full=full, compact=compact, brief=brief, thin=thin)
    )
    budget_text = prompt_budget_text(task_body, goal_id=goal_id, active_state=active_state)
    budget_chars = len(budget_text)
    max_chars = INTERFACE_BUDGET_CHARS[mode]
    return {
        "mode": mode,
        "char_count": len(task_body),
        "line_count": len(task_body.splitlines()),
        "budget_char_count": budget_chars,
        "max_chars": max_chars,
        "within_budget": budget_chars <= max_chars,
    }


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
    if traex_visible_goal:
        task_body_renderer = render_traex_visible_goal_task_body
    elif ark_managed_agent_goal:
        task_body_renderer = render_ark_managed_agent_goal_task_body
    elif native_goal_host:
        task_body_renderer = render_visible_goal_task_body
    elif thin:
        task_body_renderer = render_thin_heartbeat_task_body
    elif brief:
        task_body_renderer = render_brief_heartbeat_task_body
    elif compact:
        task_body_renderer = render_compact_heartbeat_task_body
    else:
        task_body_renderer = render_heartbeat_task_body
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


def render_heartbeat_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    scope_block = f"\n{agent_scope_instruction}\n" if agent_scope_instruction else ""
    pr_review_pre_quota_block = (
        f"{pr_review_pre_quota_command}\n" if pr_review_pre_quota_command else ""
    )
    return f"""Advance `{goal_id}` using `{active_state}`.

Generic LoopX lifecycle. Keep project-specific branching out of the
automation prompt. Put local policy in registry, active-state sections, adapter
output, `quota should-run.goal_boundary`, or boundary rules; if a lifecycle
rule is needed, update `{cli_bin} heartbeat-prompt` so all projects inherit it.
{scope_block}

Before spending delivery compute, make the CLI reachable; set
`LOOPX_TURN=<current_time_iso>` per trigger, reuse it on retries, and run guard:

```bash
{cli_preflight}
{pr_review_pre_quota_block}{quota_guard_command}
```

If that preflight still fails: no work/spend; quiet `DONT_NOTIFY`.

`lark_event_inbox`: `reply_due`: drain -> effect/reply/readback/ACK.

{USER_TODO_FINAL_MESSAGE_RULE}
{HEARTBEAT_VISION_WRITEBACK_RULE_SHORT}

If the result says `should_run=false`:

- Only if `user_channel.notify=NOTIFY`, interpret `state=operator_gate` or
  `notify_user_on_open_todo=true` as a user prompt. Read `gate_prompt`,
  `operator_question`, `user_todo_summary`, and `open_todo_notify_reason`;
  ask one concise Chinese action/question with reply format. If
  `user_todo_summary.open_count > 0`, include up to three `first_open_items`;
  never say "no new user action". Honor
  `open_todo_notification_policy=repeat_until_resolved`; when
  `user_gate_notification_cooldown.notification_suppressed=true`, keep the gate
  pending and quiet until its reminder window/change. No gated delivery/spend.
  No delivery/spend on the gated path.
- If the payload also says `safe_bypass_allowed=true` and the same gate has
  already been surfaced, the gate blocks only the gated delivery path. You may
  do exactly one bounded safe-bypass step from the Priority Stack that does not
  depend on that gate; validate, write back, refresh accountable progress, spend
  once. Only if `user_channel.notify=NOTIFY`: report the result compactly; if
  `user_todo_summary.open_count > 0`, include those todos; if none exists, report
  the gate. Under `DONT_NOTIFY`, stay quiet after the safe-bypass work.
- If `effective_action=monitor_quiet_skip`, receipt/stall is written; quiet
  unless replan. On receipt write failure, retry same id. No edits/spend;
  receipts do not self-stop.
- If `waiting_on=external_evidence` or `state=waiting`, and this automation is
  explicitly a monitor, run at most one bounded read-only observation poll using
  project-approved status/log/metric/marker surfaces named in active state,
  `recommended_action`, or `goal_boundary.next_probe`. Unchanged evidence:
  quiet `DONT_NOTIFY`, no edits, no spend. New eval/fail/complete/blocker/
  approval/CI/deploy/data evidence: write back only allowed canonical
  state/board/ledger, add todos if needed, then spend once after validation.
  Only if `user_channel.notify=NOTIFY`: report the new evidence. Under
  `DONT_NOTIFY`, stay quiet.
  Still do not launch/stop/restart/sync/design code or mutate production unless
  `should_run=true` or the user explicitly authorizes it.
- Otherwise, do not do implementation work, adapter work, file edits, research,
  or project exploration in this turn. Return a quiet heartbeat `DONT_NOTIFY`
  response with the skip reason.
  {SCHEDULER_HINT_APPLICATION_RULE} Codex App cadence changes are host
  scheduling updates only; they never consume quota or authorize delivery work.

If the result says `should_run=true`:

1. Read the active state, Priority Stack, recent progress, and critic.
   When you inspect current LoopX routing, use the current status queue:
   `attention_queue.items` and each item's `project_asset` are authoritative
   for owner, gate, waiting party, and next action. If `project_asset` is absent
   or legacy/raw fallback, raw queue fields are not owner/gate/stop authority. Treat
   `run_history.latest_runs` as evidence and drill-down only; it may be limited
   by status command limits or filters, so do not decide whether a gate is
   pending or approved from latest runs alone. Also inspect `goal_boundary` and
   guard `user_todo_summary`. Stop for an open user/owner todo only when it
   belongs to this goal's guard payload or current project asset and blocks the
   selected path; then use the blocker-push pattern above. Dependency or
   sibling-goal todos found in `attention_queue.items` should be recorded as
   dependency blockers; they must not consume the whole eligible turn. Choose a
   gate-independent P0/P1/P2 candidate for this goal when one exists.
   If `effective_action=outcome_floor_recovery` or
   `recovery_delivery_allowed=true` or
   `safe_bypass_kind=outcome_floor_recovery`, produce the required
   ranker/cross-domain evidence artifact named by `must_advance`, or write back
   the concrete blocker. Do not fall through to ordinary delivery,
   surface propagation, or synthetic-only chains.
   Read `execution_obligation`: `notify` is not an execution gate;
   `must_attempt_work=true` means one bounded segment even with
   `notify=DONT_NOTIFY`; quiet no-op needs `must_attempt_work=false` and
   `user_channel.notify=DONT_NOTIFY`. Use
   `scheduler_hint` for wakeup and unchanged-loop limits. For Codex App:
   `apply_needed=true` -> update `recommended_rrule` once; on success run
   `ack_hint.cli_args`; on failure/timeout do not retry or ack, run
   `failure_hint.cli_args` once. LoopX suppresses that target/host pair until
   either changes; continue under the observed host cadence. Else
   `ack_needed=true` -> run that bound ack directly; else skip.
   LoopX owns reset/progression state. It is scheduling only, not delivery
   permission. Then use
   `heartbeat_recommendation`: `recommended_mode=run_first_read_only_map` means
   run its `command` as a real read-only map, then
   validate/save the `read_only_project_map` result, refresh accountable
   progress, append exactly one heartbeat spend, sync state if needed; notify
   only under `NOTIFY`. If it says
   `recommended_mode=mapped_noop_if_unchanged` with `stop_if_unchanged=true`,
   and you find no new user instruction, owner evidence, agent todo, stale
   source, or safe handoff, return quiet `DONT_NOTIFY`: do not run, edit, or
   spend.
   Check `delivery_batch_scale`, `delivery_outcome`,
   `post_handoff_outcome_gap_streak`, and `handoff_delivery_contract`; for
   repeated-small or surface-only loops, obey the contract.
2. Run a short steering audit before choosing work: list at least three
   plausible next-action candidates across different P0/P1/P2 lanes when
   useful; if the same topic has consumed several recent delivery slices, apply
   a continuation check and state why continuing still wins; keep compute quota
   separate from focus quota; record any losing high-value candidate that should
   not be forgotten. Include a product bottleneck lens: ask whether the core
   goal is currently bottlenecked by user experience, agent capability,
   evidence quality, adapter readiness, or priority-rule gaps, and promote one
   concrete bottleneck candidate when it should outrank the nearest local TODO.
   Plan/top todo/route changes need todo/Next Action writeback or no-writeback rationale.
3. Run the no-progress self-repair check before choosing delivery work. Obey
   any machine-readable `autonomous_replan_obligation` or
   `execution_obligation.must_attempt_work=true` from `quota should-run`; that
   hard contract overrides a quiet no-op. Count a turn as no-progress only when
   it produced no substantive artifact, adapter/implementation progress,
   gate/user decision, or validation signal. If 2 consecutive eligible
   heartbeats are no-progress loops, run one bounded self-repair/replan segment
   before another quiet no-op. Delete/pause only when that repair path is stuck
   for 2 more eligible turns; no spend for the self-cancel turn.
4. Choose one bounded, verifiable progress segment from that audit. It may be a
   coherent batch across related implementation, test, doc, and state-writeback
   files when the write scope is clear and validation is explicit; it should not
   be forced into a tiny single-file step.
5. Do that segment only. Stay inside `goal_boundary` when present and keep
   public/private boundaries intact. Public-safe repo publication is not an
   operator gate by itself: for routine public project work, commit, push, and
   PR creation may proceed autonomously after validation and a clean
   public/private boundary scan. Stop and surface a user/controller gate only
   for private or company-internal material, credentials, destructive git
   operations, production actions, or repository rules that explicitly require
   review.
6. Run the smallest useful validation.
7. Write back changed files, validation, critic, and next action to the active
   state. If a user/owner todo appears, do not hide it in prose: use
   `{cli_bin} todo add --goal-id {goal_id} --role user --task-class user_gate --blocks-agent <agent-id>`
   or `{cli_bin} todo add --goal-id {goal_id} --role user --task-class user_action`.
   Use `--role agent` for project-agent follow-up work.
   For non-trivial feature slices, complete the current todo only after adding
   a successor todo, or include a compact no-follow-up rationale.
   For the full field contract, see `docs/project-agent-todo-contract.md` in
   the LoopX checkout.
8. After validation/writeback, use actual class/scale/outcome; never default or
   upgrade to `multi_surface` / `outcome_progress`. Record accountable delivery:

   ```bash
   {progress_refresh_state_command}
   ```

   Spend consumes this causal record; plain state-only refresh cannot replace
   it. Then spend once:

   ```bash
   {quota_spend_command}
   ```

   Do not append spend for quiet `should_run=false` skips, preflight failures,
   pure dry-run previews, or duplicate accounting attempts. If
   `should_run=false` but `safe_bypass_allowed=true` and you actually completed
   a bounded safe-bypass step, append this same spend event once after
   validation/writeback.

9. After spend, optionally refresh state-only:

   ```bash
   {refresh_state_command}
   ```

   Never emit accountable progress after spend; it creates an unspent record.

10. Return compactly under `interaction_contract.user_channel.notify`:
    `NOTIFY` only for concrete artifact/gate/blocker/self-stop when the
    authority is `NOTIFY`; otherwise stay quiet `DONT_NOTIFY`.

{material_queue_rule}
{permission_rule}"""


def render_brief_heartbeat_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    scope_block = f"\n{agent_scope_instruction}\n" if agent_scope_instruction else ""
    pr_review_pre_quota_block = (
        f"{pr_review_pre_quota_command}\n" if pr_review_pre_quota_command else ""
    )
    return f"""Advance `{goal_id}` using `{active_state}`.

Brief installed LoopX heartbeat. Thin dispatcher; detail:
`{compact_prompt_command}`.
{scope_block}

Guard/retry; `LOOPX_TURN=<current_time_iso>`:

```bash
{cli_preflight}
{pr_review_pre_quota_block}{quota_guard_command}
```

Fail:quiet.

{HEARTBEAT_NOTIFICATION_RULE_SHORT}
{HEARTBEAT_VISION_WRITEBACK_RULE_SHORT}

If `should_run=false`: follow user channel. `monitor_quiet_skip`: receipt/stall
done; quiet unless replan; write failure: retry same id. External/wait monitor:
one read-only poll; new evidence -> writeback/spend. Safe bypass if allowed.
{SCHEDULER_HINT_THIN_RULE}
`lark_event_inbox`: reply_due: drain_command -> effect/reply/readback/ACK.

If `should_run=true`: fetch compact; use `status --limit 3` and
`review-packet --handoff-only`. Obey
`execution_obligation`, `effective_action`, `recovery_delivery_allowed`,
`heartbeat_recommendation`, `safe_bypass_kind=outcome_floor_recovery`,
`goal_boundary`, `delivery_batch_scale`, `delivery_outcome`, outcome streaks,
`handoff_delivery_contract`; do 1 bounded segment/batch when
`execution_obligation.must_attempt_work=true`; if recovery, run
ranker/cross-domain evidence recovery or blocker writeback;
validate/writeback/todos; done->successor/rationale. Progress(actual,no upgrade):
`{progress_refresh_state_command}`
Spend:
`{quota_spend_command}`
Post-spend state:
`{refresh_state_command}`

No spend for quiet skips, preflight failures, blocker-push asks, dry-runs, or
duplicate accounting. Return only under `user_channel.notify=NOTIFY`; else quiet.

{material_queue_rule}
{permission_rule}"""


def render_compact_heartbeat_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    scope_block = f"\n{agent_scope_instruction}\n" if agent_scope_instruction else ""
    pr_review_pre_quota_block = (
        f"{pr_review_pre_quota_command}\n" if pr_review_pre_quota_command else ""
    )
    return f"""Advance `{goal_id}` using `{active_state}`.

This compact LoopX heartbeat body; policy:
registry/state/adapter/`goal_boundary`.
Expanded lifecycle contract: `{expanded_prompt_command}`.
{scope_block}

Preflight/guard; `LOOPX_TURN=<current_time_iso>`; reuse:

```bash
{cli_preflight}
{pr_review_pre_quota_block}{quota_guard_command}
```

Preflight fail: quiet; no work/spend.

{SCHEDULER_HINT_COMPACT_RULE}
{HEARTBEAT_VISION_WRITEBACK_RULE_SHORT}

`lark_event_inbox`: reply_due: drain_command -> effect/reply/readback/ACK.

Output policy: authority=`interaction_contract.user_channel.notify`;
external=`NOTIFY`; quiet=`DONT_NOTIFY`; quiet_missing_action=`internal_repair`.

If `should_run=false`: `monitor_quiet_skip` -> receipt/stall; quiet unless
replan; failed write -> retry id; no edits/spend; receipts do not self-stop.
Only under `NOTIFY`, `state=operator_gate`/`notify_user_on_open_todo=true`
permit concrete blocker-push; else quiet.
Honor repeat/cooldown. `safe_bypass_allowed=true`: one validated step. Wait
monitor: one read-only poll; unchanged quiet, new evidence writeback/spend.

If `should_run=true`:
1. Read active state, Priority Stack, progress/critic, `goal_boundary`,
   `attention_queue.items` / `project_asset`, and guard `user_todo_summary`.
   Legacy/raw fallback is not owner/gate/stop authority. Treat
   `run_history.latest_runs` as drill-down only.
2. Goal-owned blocker: stop its path. Under `NOTIFY`, send a concrete Chinese
   blocker-push; under `DONT_NOTIFY`, repair internally and stay quiet.
   Dependency/sibling todos: record; continue audit.
3. If `effective_action=outcome_floor_recovery` or
   `recovery_delivery_allowed=true` or
   `safe_bypass_kind=outcome_floor_recovery`, run only ranker/cross-domain
   evidence artifact or blocker recovery; no ordinary delivery or
   surface/synthetic-only work.
4. Follow `execution_obligation`: `notify` is not an execution gate.
   `must_attempt_work=true` means one bounded segment even with
   `notify=DONT_NOTIFY`; quiet no-op needs `must_attempt_work=false` and
   `user_channel.notify=DONT_NOTIFY`.
   Then follow `heartbeat_recommendation`:
   `run_first_read_only_map`: exact real-map, validate/save/refresh/spend;
   notify only under `NOTIFY`;
   `mapped_noop_if_unchanged` plus
   `stop_if_unchanged=true` means quiet no-op if no new instruction/evidence/
   todo/stale source/safe handoff.
   `task_orchestration_contract`: spawn admitted child lanes or resume peers;
   the coordinator alone accepts evidence and writes/spends once.
   Check `delivery_batch_scale`, `delivery_outcome`,
   `post_handoff_outcome_gap_streak`, `handoff_delivery_contract`; obey
   repeated-small/surface-loop contracts.
5. Run steering audit: compare P0/P1/P2, continuation checks,
   compute/focus quota, bottleneck lens.
6. no-progress self-repair: obey `autonomous_replan_obligation` or
   `execution_obligation.must_attempt_work=true`; after 2 eligible stall
   heartbeats with only status/brief checks, replan before quiet no-op.
   Pause/delete only if repair stays stuck 2 more turns.
7. Choose one bounded segment; coherent batch is OK with clear validation.
   Public-safe commit/push/PR may proceed after validation/clean scan. Stop for
   private/company material, credentials, destructive git, production, or review rules.
8. Validate; write files/validation/critic/next action to active state;
   use `{cli_bin} todo add --goal-id {goal_id} --role user --task-class user_gate|user_action`
   for owner todos and `--role agent` for agent todos, not prose. Nontrivial done ->
   successor todo or no-follow-up rationale.
9. Account actual validated class/scale/outcome; never default/upgrade. Then
   refresh and spend:

```bash
{progress_refresh_state_command}
{quota_spend_command}
```

10. Optional state-only post-spend: `{refresh_state_command}`; never accountable.

No spend for quiet skips, preflight failures, blocker-push asks, dry-runs,
self-cancel turns, or duplicate accounting.

Return only under `user_channel.notify=NOTIFY`; otherwise stay quiet.

{material_queue_rule}
{permission_rule}"""


def render_visible_goal_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    del (
        cli_preflight,
        expanded_prompt_command,
        compact_prompt_command,
        brief_prompt_command,
        thin_prompt_command,
    )
    return _render_goal_task_body(
        goal_id=goal_id,
        active_state=active_state,
        host_preamble=(
            "in this visible\nCodex `/goal` task. This is an interactive goal "
            "loop, not a heartbeat automation:\ndo not create/update an "
            "automation, apply RRULE cadence, or invent `LOOPX_TURN`."
        ),
        completion_subject="visible\nGoal",
        pr_review_pre_quota_command=pr_review_pre_quota_command,
        quota_guard_command=quota_guard_command,
        quota_spend_command=quota_spend_command,
        progress_refresh_state_command=progress_refresh_state_command,
        material_queue_rule=material_queue_rule,
        permission_rule=permission_rule,
        agent_scope_instruction=agent_scope_instruction,
        host_wait_rule=CODEX_NATIVE_GOAL_UNCHANGED_WAIT_RULE,
    )


def render_traex_visible_goal_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    del (
        cli_preflight,
        refresh_state_command,
        cli_bin,
        expanded_prompt_command,
        compact_prompt_command,
        brief_prompt_command,
        thin_prompt_command,
    )
    return _render_goal_task_body(
        goal_id=goal_id,
        active_state=active_state,
        host_preamble=(
            "in this visible\nTraeX `/goal` task. The visible TraeX Goal owns "
            "interactive continuation."
        ),
        completion_subject="visible\nGoal",
        pr_review_pre_quota_command=pr_review_pre_quota_command,
        quota_guard_command=quota_guard_command,
        quota_spend_command=quota_spend_command,
        progress_refresh_state_command=progress_refresh_state_command,
        material_queue_rule=material_queue_rule,
        permission_rule=permission_rule,
        agent_scope_instruction=agent_scope_instruction,
        host_wait_rule="",
    )


def _render_goal_task_body(
    *,
    goal_id: str,
    active_state: str,
    host_preamble: str,
    completion_subject: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    agent_scope_instruction: str,
    host_wait_rule: str,
) -> str:
    scope_block = f"\n{agent_scope_instruction}\n" if agent_scope_instruction else ""
    prequota_block = (
        f"Run `{pr_review_pre_quota_command}` first.\n"
        if pr_review_pre_quota_command
        else ""
    )
    return f"""Advance LoopX goal `{goal_id}` from `{active_state}` {host_preamble}
{scope_block}

{RUNTIME_EXECUTION_ROUTING_RULE}

At every continuation, inspect LoopX state/status and the repository. {prequota_block}Run
`{quota_guard_command}` and follow its `interaction_contract`.

If `should_run=false`, do no delivery work and do not spend quota. Surface only a
concrete user action/gate in Chinese when the contract requires `NOTIFY`; otherwise
wait quietly.{host_wait_rule}

If `should_run=true`, choose the highest-priority in-scope unblocked agent todo.
Honor claims/leases, blocker-push and recovery obligations. Before dependent work,
persist material scope/acceptance/non-goal changes in current evidence and the next
todo. Complete one bounded segment inside this same Goal; a segment is progress, not
a new Goal boundary. Keep this activation across phases, steers, and code revisions
until terminal; do not create a successor host Goal merely to continue the
registered objective. Validate the segment; write public-safe evidence, critic, and
next action back to LoopX. A non-trivial completion needs a successor todo or an
explicit no-follow-up rationale. After validated writeback, replace all three
accountable-refresh placeholders with this turn's actual classification, batch
scale, and outcome; never default or upgrade them to
`multi_surface` / `outcome_progress`. Then refresh the accountable progress
record before spending:
`{progress_refresh_state_command}`. Then spend exactly once against that refresh:
`{quota_spend_command}`.

Do not spend for gates, waits, dry runs, failed preflight, no-op inspection, or
duplicate accounting. Stop for private/company material, credentials, destructive
git, unauthorized production, or repository review rules. Complete this {completion_subject} only when LoopX reports terminal success with no follow-up; otherwise keep the
current gate or next safe action explicit.

{material_queue_rule}
{permission_rule}"""


def render_ark_managed_agent_goal_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    del (
        cli_preflight,
        refresh_state_command,
        cli_bin,
        expanded_prompt_command,
        compact_prompt_command,
        brief_prompt_command,
        thin_prompt_command,
    )
    return _render_goal_task_body(
        goal_id=goal_id,
        active_state=active_state,
        host_preamble=(
            "in one Goal\nactivation. The Goal runtime owns continuation and "
            "inner iterations. This is a\ngoal loop, not automation; do not "
            "invoke LoopX Turn."
        ),
        completion_subject="Goal",
        pr_review_pre_quota_command=pr_review_pre_quota_command,
        quota_guard_command=quota_guard_command,
        quota_spend_command=quota_spend_command,
        progress_refresh_state_command=progress_refresh_state_command,
        material_queue_rule=material_queue_rule,
        permission_rule=permission_rule,
        agent_scope_instruction=agent_scope_instruction,
        host_wait_rule="",
    )


def render_thin_heartbeat_task_body(
    *,
    goal_id: str,
    active_state: str,
    cli_preflight: str,
    pr_review_pre_quota_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    refresh_state_command: str,
    progress_refresh_state_command: str,
    material_queue_rule: str,
    permission_rule: str,
    cli_bin: str,
    agent_scope_instruction: str,
    expanded_prompt_command: str,
    compact_prompt_command: str,
    brief_prompt_command: str,
    thin_prompt_command: str,
) -> str:
    permission_tail = "" if permission_rule == DEFAULT_PERMISSION_RULE else f" {permission_rule}"
    material_sentence = (
        "Do not consume learning queue unless asked."
        if material_queue_rule == DEFAULT_MATERIAL_QUEUE_RULE
        else material_queue_rule
    )
    scope_sentence = f"\n{agent_scope_instruction}" if agent_scope_instruction else ""
    quota_guard_instruction = (
        f"`{quota_guard_command}`"
        if any(
            marker in quota_guard_command
            for marker in (
                "--available-capability",
                "--runtime-profile",
                "--codex-app",
                "--host-surface",
                " -H ",
            )
        )
        else "`quota should-run`"
    )
    pr_review_pre_quota_instruction = (
        f"`{pr_review_pre_quota_command}`\n"
        if pr_review_pre_quota_command
        else ""
    )
    return f"""Advance `{goal_id}` from {active_state}.

{RUNTIME_EXECUTION_ROUTING_RULE}
{scope_sentence}

Inspect state/status/repo.
`LOOPX_TURN=<current_time_iso>`; reuse.
{pr_review_pre_quota_instruction}{quota_guard_instruction}.
{HEARTBEAT_NOTIFICATION_RULE_SHORT}
{RUNTIME_CAPABILITY_PROJECTION_THIN_RULE}
{SCHEDULER_HINT_THIN_RULE}
{HEARTBEAT_VISION_WRITEBACK_RULE_SHORT}
Done->todo/rationale; guard receipt; 2 stalls->replan.
`lark_event_inbox`: reply_due; drain_command/reply-readback/ACK.

P0 blocked: safe P1/P2; monitor quiet/no-spend.

No project branches; {material_sentence} Stop: private material, credentials,
destructive git, unauthorized prod{permission_tail}"""


def render_heartbeat_generator_inputs_markdown(payload: dict[str, Any]) -> str:
    interface_budget = payload.get("interface_budget") if isinstance(payload.get("interface_budget"), dict) else {}
    lines = [
        "## Generator Inputs",
        "",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- active_state: `{payload.get('active_state')}`",
        f"- active_state_source: `{payload.get('active_state_source')}`",
        f"- resolved_active_state: `{payload.get('resolved_active_state')}`",
        f"- compact: `{payload.get('compact')}`",
        f"- brief: `{payload.get('brief')}`",
        f"- thin: `{payload.get('thin')}`",
        f"- cli_bin: `{payload.get('cli_bin')}`",
        f"- agent_id: `{payload.get('agent_id')}`",
        f"- agent_model: `{payload.get('agent_model')}`",
        f"- agent_role: `{payload.get('agent_role')}`",
    ]
    lines.extend(
        [
            f"- agent_scopes: `{payload.get('agent_scopes')}`",
            f"- expanded_prompt_command: `{payload.get('expanded_prompt_command')}`",
            f"- compact_prompt_command: `{payload.get('compact_prompt_command')}`",
            f"- brief_prompt_command: `{payload.get('brief_prompt_command')}`",
            f"- thin_prompt_command: `{payload.get('thin_prompt_command')}`",
            "- pr_review_pre_quota_command: "
            f"`{payload.get('pr_review_pre_quota_command')}`",
            f"- quota_guard_command: `{payload.get('quota_guard_command')}`",
            f"- quota_spend_command: `{payload.get('quota_spend_command')}`",
            f"- cli_preflight: `{payload.get('cli_preflight')}`",
            "- interface_budget: "
            f"mode=`{interface_budget.get('mode')}` "
            f"budget_chars=`{interface_budget.get('budget_char_count')}` "
            f"max_chars=`{interface_budget.get('max_chars')}` "
            f"within_budget=`{interface_budget.get('within_budget')}`",
            "",
        ]
    )
    return "\n".join(lines)


def render_heartbeat_prompt_error_markdown(payload: dict[str, Any]) -> str:
    return f"""# Heartbeat Automation Prompt Error

No heartbeat task body was generated.

## Error

```text
{payload.get("error") or "unknown heartbeat-prompt generation error"}
```

{render_heartbeat_generator_inputs_markdown(payload)}"""


def render_heartbeat_prompt_markdown(payload: dict[str, Any]) -> str:
    if payload.get("ok") is False:
        return render_heartbeat_prompt_error_markdown(payload)
    if payload.get("visible_goal_host") == "traex-cli":
        return f"""# Visible TraeX Goal Prompt

Paste this task body into the visible TraeX `/goal` task.

````text
{payload.get("task_body", "")}
````

{render_heartbeat_generator_inputs_markdown(payload)}"""
    if payload.get("thin"):
        style = "thin "
    elif payload.get("brief"):
        style = "brief "
    elif payload.get("compact"):
        style = "compact "
    else:
        style = ""
    return f"""# Heartbeat Automation Prompt

Copy this {style}task body into a Codex App heartbeat automation.

````text
{payload.get("task_body", "")}
````

{render_heartbeat_generator_inputs_markdown(payload)}"""
