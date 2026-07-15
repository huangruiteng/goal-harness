from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any


AGENT_LOOP_SHADOW_TICK_SCHEMA_VERSION = "agent_loop_shadow_tick_v0"
TURN_ENVELOPE_SCHEMA_VERSION = "loopx_turn_envelope_v0"
SUPPORTED_HOSTS = {"codex-cli", "claude-code", "generic-cli"}
SUPPORTED_EXECUTION_MODES = {"interactive-visible", "isolated-headless"}
REPLAN_ACTIONS = {
    "autonomous_replan",
    "autonomous_replan_required",
    "successor_replan_required",
}
REPAIR_ACTIONS = {
    "capability_repair",
    "projection_repair",
    "self_repair",
    "state_projection_repair",
    "workspace_repair",
}


class AgentLoopRoute(str, Enum):
    READY_FOR_HOST = "ready_for_host"
    REPAIR_REQUIRED = "repair_required"
    REPLAN_REQUIRED = "replan_required"
    USER_ACTION_REQUIRED = "user_action_required"
    WAIT = "wait"
    BLOCKED = "blocked"
    CONTRACT_ERROR = "contract_error"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _typed_route(envelope: Mapping[str, Any]) -> AgentLoopRoute:
    if envelope.get("schema_version") != TURN_ENVELOPE_SCHEMA_VERSION:
        return AgentLoopRoute.CONTRACT_ERROR
    signature = _mapping(envelope.get("action_signature"))
    source_hash = str(signature.get("source_hash") or "")
    envelope_hash = str(signature.get("envelope_hash") or "")
    if (
        signature.get("matches") is not True
        or not source_hash
        or source_hash != envelope_hash
    ):
        return AgentLoopRoute.CONTRACT_ERROR
    compaction = _mapping(envelope.get("compaction"))
    if compaction.get("within_budget") is not True:
        return AgentLoopRoute.CONTRACT_ERROR

    action = _mapping(envelope.get("action"))
    user = _mapping(envelope.get("user"))
    should_run = envelope.get("should_run") is True
    effective_action = str(envelope.get("effective_action") or "")
    delivery_allowed = action.get("delivery_allowed") is True
    must_attempt = action.get("must_attempt") is True

    if should_run:
        if not delivery_allowed or not must_attempt:
            return AgentLoopRoute.BLOCKED
        if effective_action in REPLAN_ACTIONS:
            return AgentLoopRoute.REPLAN_REQUIRED
        if effective_action in REPAIR_ACTIONS or effective_action.endswith(
            ("_repair", "_repair_required")
        ):
            return AgentLoopRoute.REPAIR_REQUIRED
        return AgentLoopRoute.READY_FOR_HOST
    if user.get("action_required") is True:
        return AgentLoopRoute.USER_ACTION_REQUIRED
    if action.get("quiet_noop_allowed") is True:
        return AgentLoopRoute.WAIT
    return AgentLoopRoute.BLOCKED


def build_agent_loop_shadow_tick(
    turn_envelope: Mapping[str, Any],
    *,
    host: str,
    execution_mode: str,
) -> dict[str, Any]:
    """Project a TurnEnvelope into a typed, side-effect-free host decision."""

    if host not in SUPPORTED_HOSTS:
        raise ValueError(f"unsupported agent-loop host: {host}")
    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        raise ValueError(f"unsupported agent-loop execution mode: {execution_mode}")

    envelope = dict(turn_envelope)
    route = _typed_route(envelope)
    action = _mapping(envelope.get("action"))
    selected_todo = _mapping(action.get("selected_todo"))
    would_invoke_host = route in {
        AgentLoopRoute.READY_FOR_HOST,
        AgentLoopRoute.REPAIR_REQUIRED,
        AgentLoopRoute.REPLAN_REQUIRED,
    }
    return {
        "ok": route is not AgentLoopRoute.CONTRACT_ERROR,
        "schema_version": AGENT_LOOP_SHADOW_TICK_SCHEMA_VERSION,
        "mode": "shadow",
        "host": {
            "kind": host,
            "execution_mode": execution_mode,
            "explicit_isolation": execution_mode == "isolated-headless",
        },
        "route": {
            "schema_version": "agent_loop_typed_route_v0",
            "kind": route.value,
            "effective_action": envelope.get("effective_action"),
            "would_invoke_host": would_invoke_host,
            "host_invocation_allowed": False,
            "selected_todo": selected_todo or None,
        },
        "turn_envelope": envelope,
        "effects": {
            "host_invoked": False,
            "state_written": False,
            "scheduler_acknowledged": False,
            "quota_spent": False,
        },
        "boundary": {
            "shadow_only": True,
            "requires_explicit_execute_surface": True,
            "preserves_turn_envelope": True,
        },
    }
