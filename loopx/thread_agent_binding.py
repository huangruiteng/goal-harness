"""Validated, project-local bindings between host threads and agent lanes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .control_plane.todos.contract import normalize_todo_claimed_by
from .file_lock import exclusive_file_lock
from .history import load_registry
from .registry import atomic_write_json, find_registry_goal

THREAD_ID_MAX_LENGTH = 128
THREAD_BINDING_SCHEMA_VERSION = "loopx_thread_agent_binding_v0"


def normalize_thread_id(value: Any) -> str | None:
    """Return a bounded opaque host token, or None for an omitted token."""

    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    if len(token) > THREAD_ID_MAX_LENGTH:
        raise ValueError(f"thread_id must be at most {THREAD_ID_MAX_LENGTH} characters")
    if any(char.isspace() or ord(char) < 32 for char in token):
        raise ValueError(
            "thread_id must be a public-safe opaque token without whitespace"
        )
    if any(char in token for char in ("/", "\\", '"', "'")):
        raise ValueError("thread_id must not contain path or quoting characters")
    return token


def _normalized_host_surface(value: Any) -> str:
    surface = str(value or "").strip()
    if not surface:
        raise ValueError("host_surface is required for a thread binding")
    if len(surface) > 64 or any(char.isspace() for char in surface):
        raise ValueError("host_surface must be a compact public-safe token")
    return surface


def _bindings_for_goal(goal: dict[str, Any]) -> list[dict[str, str]]:
    coordination = goal.get("coordination")
    if not isinstance(coordination, dict):
        return []
    raw = coordination.get("thread_agent_bindings")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            thread_id = normalize_thread_id(item.get("thread_id"))
            host_surface = _normalized_host_surface(item.get("host_surface"))
            agent_id = normalize_todo_claimed_by(item.get("agent_id"))
        except ValueError:
            continue
        if thread_id and agent_id:
            result.append(
                {
                    "thread_id": thread_id,
                    "host_surface": host_surface,
                    "agent_id": agent_id,
                }
            )
    return result


def resolve_thread_agent_binding(
    goal: dict[str, Any] | None,
    *,
    host_surface: str,
    thread_id: str | None,
) -> dict[str, Any]:
    """Resolve a thread binding without guessing from registry order."""

    normalized_thread_id = normalize_thread_id(thread_id)
    normalized_surface = _normalized_host_surface(host_surface)
    base: dict[str, Any] = {
        "schema_version": THREAD_BINDING_SCHEMA_VERSION,
        "host_surface": normalized_surface,
        "thread_id": normalized_thread_id,
        "status": "unavailable" if not normalized_thread_id else "missing",
        "agent_id": None,
        "matches": [],
    }
    if not normalized_thread_id:
        return base
    matches = [
        item
        for item in _bindings_for_goal(goal or {})
        if item["host_surface"] == normalized_surface
        and item["thread_id"] == normalized_thread_id
    ]
    base["matches"] = matches
    agent_ids = sorted({item["agent_id"] for item in matches})
    if len(agent_ids) == 1:
        base["status"] = "bound"
        base["agent_id"] = agent_ids[0]
    elif len(agent_ids) > 1:
        base["status"] = "conflict"
        base["reason"] = "one thread is bound to multiple agent lanes"
    return base


def _merge_thread_binding_entries(
    current: list[dict[str, str]], entry: dict[str, str]
) -> list[dict[str, str]]:
    merged = [
        item
        for item in current
        if not (
            item["thread_id"] == entry["thread_id"]
            and item["host_surface"] == entry["host_surface"]
        )
    ]
    merged.append(entry)
    merged.sort(
        key=lambda item: (item["host_surface"], item["thread_id"], item["agent_id"])
    )
    return merged


def _prepare_binding(
    payload: dict[str, Any],
    *,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    goal = find_registry_goal(payload, goal_id)
    if goal is None:
        raise ValueError(f"goal_id not found in registry: {goal_id}")
    coordination = goal.get("coordination")
    coordination = coordination if isinstance(coordination, dict) else {}
    registered = coordination.get("registered_agents")
    registered_ids = {
        normalize_todo_claimed_by(item)
        for item in (registered if isinstance(registered, list) else [])
    }
    if agent_id not in registered_ids:
        raise ValueError(
            f"agent_id={agent_id!r} is not registered for goal {goal_id!r}"
        )

    current = _bindings_for_goal(goal)
    existing = resolve_thread_agent_binding(
        goal,
        host_surface=host_surface,
        thread_id=thread_id,
    )
    if existing["status"] == "conflict":
        return (
            {
                "ok": False,
                "changed": False,
                "written": False,
                "error_kind": "thread_agent_binding_conflict",
                "binding": existing,
            },
            goal,
            current,
        )
    if existing["status"] == "bound" and existing["agent_id"] != agent_id:
        return (
            {
                "ok": False,
                "changed": False,
                "written": False,
                "error_kind": "thread_agent_binding_conflict",
                "error": "thread is already bound to a different agent; explicit unbind is required",
                "binding": existing,
            },
            goal,
            current,
        )

    entry = {"thread_id": thread_id, "host_surface": host_surface, "agent_id": agent_id}
    merged = _merge_thread_binding_entries(current, entry)
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": goal_id,
        "registry": "",
        "thread_id": thread_id,
        "host_surface": host_surface,
        "agent_id": agent_id,
        "changed": merged != current,
        "written": False,
        "binding": {
            "schema_version": THREAD_BINDING_SCHEMA_VERSION,
            **entry,
            "status": "bound",
        },
    }
    return result, goal, merged


def bind_thread_agent_in_registry(
    *,
    registry_path: Path,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> dict[str, Any]:
    """Preview or atomically bind an already registered agent to a host thread."""

    normalized_thread_id = normalize_thread_id(thread_id)
    if normalized_thread_id is None:
        raise ValueError("thread_id is required")
    normalized_surface = _normalized_host_surface(host_surface)
    normalized_agent = normalize_todo_claimed_by(agent_id)
    if not normalized_agent:
        raise ValueError("agent_id must be a public-safe registered agent id")

    if execute:
        with exclusive_file_lock(
            registry_path,
            agent_id=normalized_agent,
            operation="bind_agent_thread",
        ):
            latest = load_registry(registry_path)
            result, latest_goal, merged = _prepare_binding(
                latest,
                goal_id=goal_id,
                host_surface=normalized_surface,
                thread_id=normalized_thread_id,
                agent_id=normalized_agent,
                execute=True,
            )
            result["registry"] = str(registry_path)
            if not result["ok"] or not result["changed"]:
                return result
            coordination = latest_goal.get("coordination")
            coordination = coordination if isinstance(coordination, dict) else {}
            coordination["thread_agent_bindings"] = merged
            latest_goal["coordination"] = coordination
            atomic_write_json(registry_path, latest, preserve_mode=True)
            result["written"] = True
            return result

    payload = load_registry(registry_path)
    result, _goal, _merged = _prepare_binding(
        payload,
        goal_id=goal_id,
        host_surface=normalized_surface,
        thread_id=normalized_thread_id,
        agent_id=normalized_agent,
        execute=False,
    )
    result["registry"] = str(registry_path)
    return result
