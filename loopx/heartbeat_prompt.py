from __future__ import annotations

import re
import shlex
from typing import Any

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
from .control_plane.agents.runtime_model import (
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


def build_heartbeat_prompt(**kwargs):
    from .control_plane.heartbeat.builder import build_heartbeat_prompt as _impl
    return _impl(**kwargs)


def build_heartbeat_prompt_error_payload(**kwargs):
    from .control_plane.heartbeat.builder import build_heartbeat_prompt_error_payload as _impl
    return _impl(**kwargs)


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
