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


def render_heartbeat_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_heartbeat_task_body as _impl
    return _impl(**kwargs)


def render_brief_heartbeat_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_brief_heartbeat_task_body as _impl
    return _impl(**kwargs)


def render_compact_heartbeat_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_compact_heartbeat_task_body as _impl
    return _impl(**kwargs)


def render_visible_goal_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_visible_goal_task_body as _impl
    return _impl(**kwargs)


def render_traex_visible_goal_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_traex_visible_goal_task_body as _impl
    return _impl(**kwargs)


def _render_goal_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import _render_goal_task_body as _impl
    return _impl(**kwargs)


def render_ark_managed_agent_goal_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_ark_managed_agent_goal_task_body as _impl
    return _impl(**kwargs)


def render_thin_heartbeat_task_body(**kwargs):
    from .control_plane.heartbeat.task_body import render_thin_heartbeat_task_body as _impl
    return _impl(**kwargs)


def render_heartbeat_generator_inputs_markdown(payload: dict[str, Any]):
    from .control_plane.heartbeat.task_body import render_heartbeat_generator_inputs_markdown as _impl
    return _impl(payload)


def render_heartbeat_prompt_error_markdown(payload: dict[str, Any]):
    from .control_plane.heartbeat.task_body import render_heartbeat_prompt_error_markdown as _impl
    return _impl(payload)


def render_heartbeat_prompt_markdown(payload: dict[str, Any]):
    from .control_plane.heartbeat.task_body import render_heartbeat_prompt_markdown as _impl
    return _impl(payload)
