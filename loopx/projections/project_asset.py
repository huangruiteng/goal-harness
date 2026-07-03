from __future__ import annotations

from typing import Any


DEFAULT_MAX_ACTIVE_DONE_TODOS_BEFORE_ARCHIVE = 12
DEFAULT_MONITOR_SIGNAL_WAITING_ON = "monitor_signal"


def completed_todo_archive_warning(
    agent_todos: dict[str, Any] | None,
    *,
    max_active_done_todos: int = DEFAULT_MAX_ACTIVE_DONE_TODOS_BEFORE_ARCHIVE,
) -> dict[str, Any] | None:
    if not isinstance(agent_todos, dict):
        return None
    try:
        done_count = int(agent_todos.get("done_count") or 0)
    except (TypeError, ValueError):
        done_count = 0
    if done_count <= max_active_done_todos:
        return None
    try:
        open_count = int(agent_todos.get("open_count") or 0)
    except (TypeError, ValueError):
        open_count = 0
    return {
        "kind": "completed_agent_todo_archive_required",
        "requires_archive": True,
        "archive_section": "Completed Work Archive",
        "active_done_count": done_count,
        "active_open_count": open_count,
        "max_active_done_count": max_active_done_todos,
        "recommended_action": (
            "move older completed Agent Todo entries into a dedicated Completed Work Archive "
            "until the active Agent Todo section keeps only current open work and a small recent-done tail"
        ),
    }


def project_asset_owner(
    waiting_on: str,
    *,
    monitor_signal_waiting_on: str = DEFAULT_MONITOR_SIGNAL_WAITING_ON,
) -> str:
    if waiting_on == "codex":
        return "codex"
    if waiting_on == "external_evidence":
        return "external_evidence"
    if waiting_on == monitor_signal_waiting_on:
        return monitor_signal_waiting_on
    if waiting_on == "controller":
        return "controller"
    if waiting_on == "user_or_controller":
        return "user_or_controller"
    return waiting_on or "unknown"


def project_asset_gate(
    *,
    waiting_on: str,
    operator_question: str | None,
    missing_gates: list[str] | None,
    status: str,
    monitor_signal_waiting_on: str = DEFAULT_MONITOR_SIGNAL_WAITING_ON,
) -> str:
    if operator_question:
        return "operator_question"
    if missing_gates:
        return str(missing_gates[0])
    if waiting_on in {"user_or_controller", "controller"}:
        return status or waiting_on
    if waiting_on == "external_evidence":
        return "external_evidence"
    if waiting_on == monitor_signal_waiting_on:
        return "none"
    return "none"
