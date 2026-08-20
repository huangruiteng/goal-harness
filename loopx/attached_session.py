"""Provider-neutral broker contract for already-running Agent sessions."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .chat_store import CHAT_SESSION_MODE_ATTACHED, ChatSessionStore
from .control_plane.todos.contract import normalize_todo_claimed_by
from .file_lock import exclusive_file_lock
from .registry import find_registry_goal
from .thread_agent_binding import resolve_thread_agent_binding

ATTACHED_SESSION_BROKER_SCHEMA_VERSION = "loopx_attached_agent_session_broker_v0"
ATTACHED_SESSION_ADAPTER_KIND = "attached_host_session"
ATTACHED_SESSION_UPSTREAM_MODE = "host_broker"
MAX_ATTACHED_SESSION_CLAIM_WAIT_SECONDS = 1_800.0
ATTACHED_SESSION_CLAIM_POLL_INTERVAL_SECONDS = 0.1


def _binding_lock_path(
    store: ChatSessionStore,
    *,
    goal_id: str,
    agent_id: str,
    channel_id: str,
) -> Path:
    material = f"{goal_id}\0{agent_id}\0{channel_id}".encode()
    digest = hashlib.sha256(material).hexdigest()
    return store.root / "attached-bindings" / f"{digest}.json"


def _registered_agent(goal: dict[str, Any], agent_id: str) -> str:
    normalized = normalize_todo_claimed_by(agent_id)
    if not normalized:
        raise ValueError("agent_id must be a public-safe registered Agent id")
    coordination = goal.get("coordination")
    coordination = coordination if isinstance(coordination, dict) else {}
    registered = coordination.get("registered_agents")
    registered_ids = {
        normalize_todo_claimed_by(item)
        for item in (registered if isinstance(registered, list) else [])
    }
    if normalized not in registered_ids:
        raise ValueError(f"agent_id={normalized!r} is not registered for this Goal")
    return normalized


def _require_bound_host(
    *,
    goal: dict[str, Any],
    agent_id: str,
    host_surface: str,
    host_session_id: str,
) -> None:
    binding = resolve_thread_agent_binding(
        goal,
        host_surface=host_surface,
        thread_id=host_session_id,
    )
    if binding.get("status") != "bound" or binding.get("agent_id") != agent_id:
        raise ValueError(
            "the host session must already be bound to the exact registered Agent"
        )


def bind_attached_agent_session(
    *,
    store: ChatSessionStore,
    registry: dict[str, Any],
    goal_id: str,
    agent_id: str,
    host_surface: str,
    host_session_id: str,
    executor_endpoint_id: str,
    channel_id: str | None = None,
    execute: bool,
) -> dict[str, Any]:
    """Bind one existing host session without starting or resuming an adapter."""

    goal = find_registry_goal(registry, goal_id)
    if goal is None:
        raise ValueError(f"goal_id not found in registry: {goal_id}")
    normalized_agent = _registered_agent(goal, agent_id)
    _require_bound_host(
        goal=goal,
        agent_id=normalized_agent,
        host_surface=host_surface,
        host_session_id=host_session_id,
    )
    selected_channel = channel_id or f"goal.{goal_id}"
    lock_path = _binding_lock_path(
        store,
        goal_id=goal_id,
        agent_id=normalized_agent,
        channel_id=selected_channel,
    )
    with exclusive_file_lock(
        lock_path,
        agent_id="loopx-chat",
        operation="bind_attached_agent_session",
    ):
        latest = store.latest_session(
            goal_id=goal_id,
            agent_id=normalized_agent,
            channel_id=selected_channel,
        )
        if latest is not None:
            exact_match = (
                latest.get("session_mode") == CHAT_SESSION_MODE_ATTACHED
                and latest.get("host_surface") == host_surface
                and latest.get("upstream_thread_id") == host_session_id
                and latest.get("executor_endpoint_id") == executor_endpoint_id
            )
            if not exact_match:
                raise ValueError(
                    "an active working Session already exists for this Goal, Agent, and channel"
                )
            return {
                "ok": True,
                "schema_version": ATTACHED_SESSION_BROKER_SCHEMA_VERSION,
                "action": "bind",
                "execute": execute,
                "changed": False,
                "created": False,
                "session": store.public_session(latest),
            }
        if not execute:
            return {
                "ok": True,
                "schema_version": ATTACHED_SESSION_BROKER_SCHEMA_VERSION,
                "action": "bind",
                "execute": False,
                "changed": True,
                "created": False,
                "binding": {
                    "goal_id": goal_id,
                    "agent_id": normalized_agent,
                    "executor_endpoint_id": executor_endpoint_id,
                    "host_surface": host_surface,
                    "channel_id": selected_channel,
                    "session_mode": CHAT_SESSION_MODE_ATTACHED,
                },
            }
        session = store.create_session(
            goal_id=goal_id,
            agent_id=normalized_agent,
            executor_endpoint_id=executor_endpoint_id,
            adapter_kind=ATTACHED_SESSION_ADAPTER_KIND,
            upstream_thread_id=host_session_id,
            upstream_mode=ATTACHED_SESSION_UPSTREAM_MODE,
            channel_id=selected_channel,
            session_mode=CHAT_SESSION_MODE_ATTACHED,
            host_surface=host_surface,
            attached_capabilities={
                "live_steering": False,
                "session_queue": True,
                "claim_wait": True,
                "reply_readback": True,
            },
        )
    return {
        "ok": True,
        "schema_version": ATTACHED_SESSION_BROKER_SCHEMA_VERSION,
        "action": "bind",
        "execute": True,
        "changed": True,
        "created": True,
        "session": store.public_session(session),
    }


def _require_attached_host(
    *,
    store: ChatSessionStore,
    session_id: str,
    host_surface: str,
    host_session_id: str,
) -> dict[str, Any]:
    session = store.load_session(session_id)
    if session is None or session.get("status") == "closed":
        raise KeyError("attached Agent session was not found")
    if session.get("session_mode") != CHAT_SESSION_MODE_ATTACHED:
        raise ValueError("the selected Session is not an attached host session")
    if (
        session.get("host_surface") != host_surface
        or session.get("upstream_thread_id") != host_session_id
    ):
        raise ValueError("attached host identity does not match the Session binding")
    return session


def claim_attached_agent_turn(
    *,
    store: ChatSessionStore,
    session_id: str,
    host_surface: str,
    host_session_id: str,
    claim_id: str,
    wait_seconds: float = 0.0,
) -> dict[str, Any]:
    """Claim or bounded-wait for the oldest queued message for the exact host."""

    _require_attached_host(
        store=store,
        session_id=session_id,
        host_surface=host_surface,
        host_session_id=host_session_id,
    )
    normalized_wait = float(wait_seconds)
    if (
        not math.isfinite(normalized_wait)
        or normalized_wait < 0
        or normalized_wait > MAX_ATTACHED_SESSION_CLAIM_WAIT_SECONDS
    ):
        raise ValueError(
            "wait_seconds must be between 0 and "
            f"{int(MAX_ATTACHED_SESSION_CLAIM_WAIT_SECONDS)}"
        )
    deadline = time.monotonic() + normalized_wait
    turn = None
    while turn is None:
        turn = store.claim_next_queued_turn(session_id, host_claim_id=claim_id)
        if turn is not None or normalized_wait == 0:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(ATTACHED_SESSION_CLAIM_POLL_INTERVAL_SECONDS, remaining))
    return {
        "ok": True,
        "schema_version": ATTACHED_SESSION_BROKER_SCHEMA_VERSION,
        "action": "claim",
        "claimed": turn is not None,
        "waited": normalized_wait > 0,
        "turn": (
            {
                "session_id": session_id,
                "turn_id": str(turn.get("turn_id") or ""),
                "client_turn_id": str(turn.get("client_turn_id") or ""),
                "claim_id": str(turn.get("host_claim_id") or ""),
                "origin": str(turn.get("origin") or "external"),
                "message": str(turn.get("message") or ""),
                "created_at": turn.get("created_at"),
                "expires_at": turn.get("expires_at"),
            }
            if turn is not None
            else None
        ),
    }


def complete_attached_agent_turn(
    *,
    store: ChatSessionStore,
    session_id: str,
    turn_id: str,
    host_surface: str,
    host_session_id: str,
    claim_id: str,
    completion_id: str,
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Write back one attached-host response with duplicate-safe receipts."""

    _require_attached_host(
        store=store,
        session_id=session_id,
        host_surface=host_surface,
        host_session_id=host_session_id,
    )
    message = str(response.get("message") or "").strip()
    if not message:
        raise ValueError("response.message is required")
    if len(message) > 200_000:
        raise ValueError("response.message is too large")
    normalized_response = {
        "schema_version": "loopx_chat_agent_response_v0",
        "message": message,
        "proposals": list(response.get("proposals") or [])[:5],
        "gate": response.get("gate") if isinstance(response.get("gate"), Mapping) else None,
    }
    _turn, created = store.complete_attached_turn(
        session_id,
        turn_id,
        claim_id=claim_id,
        completion_id=completion_id,
        response=normalized_response,
        agent_message=message,
    )
    return {
        "ok": True,
        "schema_version": ATTACHED_SESSION_BROKER_SCHEMA_VERSION,
        "action": "complete",
        "completed": True,
        "created": created,
        "session_id": session_id,
        "turn_id": turn_id,
        "completion_id": completion_id,
    }


def render_attached_session_broker_markdown(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "attached-session")
    if not payload.get("ok"):
        return f"# Attached Agent Session\n\n- Action: `{action}`\n- Error: {payload.get('error')}"
    if action == "claim":
        turn = payload.get("turn")
        if not isinstance(turn, dict):
            return "# Attached Agent Session\n\nNo queued message is available."
        return (
            "# Attached Agent Session\n\n"
            f"- Turn: `{turn.get('turn_id')}`\n"
            f"- Origin: `{turn.get('origin')}`\n\n"
            f"{turn.get('message')}"
        )
    session = payload.get("session")
    session_id = session.get("session_id") if isinstance(session, dict) else payload.get("session_id")
    return (
        "# Attached Agent Session\n\n"
        f"- Action: `{action}`\n"
        f"- Session: `{session_id or 'preview'}`\n"
        f"- Changed: `{bool(payload.get('changed') or payload.get('created'))}`"
    )
