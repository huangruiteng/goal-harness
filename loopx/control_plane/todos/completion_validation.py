from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from ...event_sourced_state import (
    AppendOnlyStateEventStore,
    StateEventError,
    build_state_projection,
)
from ...history import load_registry
from ...materials import find_registry_goal, goal_repo
from ..goals.active_state_event_projection import state_event_log_candidates
from ..goals.path_resolution import resolve_goal_local_path
from ..runtime.validation_command import (
    CALLER_VALIDATION_RECEIPT_SCHEMA_VERSION,
    run_caller_validation,
)
from .active_state_editing import find_todo_block
from .contract import TODO_STATUS_DONE, normalize_todo_id

# Kept safely under the 30s outer CLI/MCP subprocess budget so a timed-out
# validation still produces a typed receipt before the outer call is killed.
_COMPLETION_VALIDATION_TIMEOUT_SECONDS = 20
# Per-todo overrides (declared on `todo add`) must also stay under that outer
# budget for the same reason; the writer-side range check enforces this.
COMPLETION_VALIDATION_TIMEOUT_MAX_SECONDS = 29


def _resolve_goal_repo_workspace(registry_path: Path, goal_id: str) -> Path | None:
    """Resolve the goal's repository directory to use as the validation workspace."""
    goal = find_registry_goal(load_registry(registry_path), goal_id)
    if goal is None:
        return None
    repo = goal_repo(goal)
    if repo is None or not repo.is_dir():
        return None
    return repo


def _declaration_from_mapping(
    block: dict[str, Any],
) -> tuple[str | None, list[str] | None, str | None, int | None, bool]:
    """Parse a stored validation declaration from markdown or event projection."""
    try:
        timeout_seconds: int | None = (
            int(block["validation_timeout_seconds"])
            if block.get("validation_timeout_seconds")
            else None
        )
    except (TypeError, ValueError):
        timeout_seconds = None
    validation_argv: list[str] | None = None
    raw_argv = block.get("validation_command_argv")
    if raw_argv is not None and raw_argv != "":
        if isinstance(raw_argv, list):
            parsed_argv: Any = raw_argv
        else:
            try:
                parsed_argv = json.loads(raw_argv)
            except ValueError:
                parsed_argv = None
        if (
            isinstance(parsed_argv, list)
            and parsed_argv
            and all(isinstance(item, str) and item for item in parsed_argv)
        ):
            validation_argv = parsed_argv
        else:
            validation_argv = []
    already_completed = (
        block.get("status") == TODO_STATUS_DONE or block.get("done") is True
    )
    return (
        block.get("validation_command") or None,
        validation_argv,
        block.get("validation_label") or None,
        timeout_seconds,
        already_completed,
    )


def _event_projected_todo_item(
    *,
    state_file: Path,
    todo_id: str,
    role: str | None,
    registry_path: Path,
    goal_id: str,
) -> dict[str, Any] | None:
    """Read one todo from the append-only event log without holding the lock.

    Do not reuse ``event_projection_todo_context`` here. That helper renders
    Markdown and runs the public status projector, which strips
    ``validation_command`` / argv down to ``completion_validation_required``.
    The completion gate needs the actual declared command, so it must read the
    raw event-sourced projection. When multiple logs contain the same todo,
    a later log that still carries a validation declaration wins over an
    earlier log that only has the todo identity; otherwise an older undeclared
    snapshot would skip the gate.
    """
    goal = find_registry_goal(load_registry(registry_path), goal_id)
    if goal is None:
        log_paths = [state_file.with_name("events.jsonl")]
    else:
        log_paths = state_event_log_candidates(
            goal,
            state_path=state_file,
            resolve_goal_local_path=resolve_goal_local_path,
        )
    normalized_todo_id = normalize_todo_id(todo_id) or todo_id
    roles = [role] if role in {"user", "agent"} else ["user", "agent"]
    undeclared_item: dict[str, Any] | None = None
    for log_path in log_paths:
        if not log_path.exists():
            continue
        try:
            events = AppendOnlyStateEventStore(log_path).load()
            if not events:
                continue
            projection = build_state_projection(events, goal_id=goal_id or None)
        except (OSError, StateEventError):
            continue
        for item_role in roles:
            summary = projection.get(f"{item_role}_todos") or {}
            items = summary.get("items") if isinstance(summary, dict) else []
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                if (normalize_todo_id(item.get("todo_id")) or "") != normalized_todo_id:
                    continue
                command, argv, _label, _timeout, _done = _declaration_from_mapping(item)
                if command or argv is not None:
                    return item
                if undeclared_item is None:
                    undeclared_item = item
    return undeclared_item


def _read_declared_validation(
    *,
    state_file: Path,
    todo_id: str,
    role: str | None,
    registry_path: Path,
    goal_id: str,
) -> tuple[str | None, list[str] | None, str | None, int | None, bool]:
    """Pre-read a todo's declared validation command without the mutation lock.

    Returns ``(validation_command, validation_argv, validation_label,
    validation_timeout_seconds, already_completed)`` from the markdown state
    file, or from the event-sourced projection when the todo exists only in
    the append-only log. Missing todos return
    ``(None, None, None, None, False)``. Read-only; safe to call before
    acquiring the state-file lock so a slow validation command does not block
    concurrent todo operations on the same goal (the MUTATION lock deadline
    is 5s). ``validation_command``, ``validation_command_argv`` and
    ``validation_timeout_seconds`` are set only at ``todo add`` and have no
    update path, so the values cannot drift between this pre-read and the
    in-lock commit. A stored timeout that fails to parse as an int falls back
    to ``None`` (the default), matching the writer-side range check that
    guarantees a well-formed value. A stored argv that fails to parse as a
    non-empty string list collapses to ``[]`` — never to ``None`` — so a
    corrupted declaration still runs the gate and fails closed as a malformed
    command instead of silently skipping validation. Markdown remains
    authoritative when the todo is materialized there.
    """
    try:
        lines = state_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    match = find_todo_block(lines, todo_id=todo_id, role=role) if lines else None
    if match:
        _role, _section, _start, _end, block = match
        return _declaration_from_mapping(block)
    item = _event_projected_todo_item(
        state_file=state_file,
        todo_id=todo_id,
        role=role,
        registry_path=registry_path,
        goal_id=goal_id,
    )
    if item is None:
        return None, None, None, None, False
    return _declaration_from_mapping(item)


def _run_declared_completion_validation(
    *,
    validation_command: str | None,
    validation_argv: list[str] | None,
    validation_label: str | None,
    validation_timeout_seconds: int | None,
    registry_path: Path,
    goal_id: str,
) -> dict[str, Any] | None:
    """Run a todo's declared caller-approved validation command.

    Returns ``None`` when no command form is declared (the unchanged fast
    path). ``validation_argv`` (the JSON argv form declared on ``todo add``)
    takes the run-once no-shell path; ``validation_command`` keeps the
    legacy shlex form. ``validation_timeout_seconds`` overrides the module
    default when declared on ``todo add``; ``None`` keeps the default.
    Otherwise always returns a privacy-safe receipt whose ``passed`` is True
    only when the command ran and exited zero; setup failures (no repository
    workspace), timeouts, missing executables, and malformed commands are all
    reported as ``passed=False`` receipts rather than raised, so completion
    can surface a typed failure without committing.
    """
    if not validation_command and validation_argv is None:
        return None
    timeout_seconds = (
        validation_timeout_seconds
        if validation_timeout_seconds is not None
        else _COMPLETION_VALIDATION_TIMEOUT_SECONDS
    )
    label = validation_label or "todo completion validation"
    workspace = _resolve_goal_repo_workspace(registry_path, goal_id)
    if workspace is None:
        return {
            "schema_version": CALLER_VALIDATION_RECEIPT_SCHEMA_VERSION,
            "command_label": label,
            "exit_code": None,
            "passed": False,
            "status": "workspace_unavailable",
            "summary": (
                "validation_command is declared but the goal has no "
                "repository workspace to run it in"
            ),
            "stdout_captured": False,
            "stderr_captured": False,
            "local_path_captured": False,
        }
    try:
        if validation_argv is not None:
            return run_caller_validation(
                workspace,
                validation_argv=validation_argv,
                validation_label=label,
                timeout_seconds=timeout_seconds,
            )
        return run_caller_validation(
            workspace,
            validation_command=str(validation_command),
            validation_label=label,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "schema_version": CALLER_VALIDATION_RECEIPT_SCHEMA_VERSION,
            "command_label": label,
            "exit_code": None,
            "passed": False,
            "status": "timeout",
            "summary": (
                f"validation command timed out after {timeout_seconds}s"
            ),
            "stdout_captured": False,
            "stderr_captured": False,
            "local_path_captured": False,
        }
    except (FileNotFoundError, PermissionError) as exc:
        return {
            "schema_version": CALLER_VALIDATION_RECEIPT_SCHEMA_VERSION,
            "command_label": label,
            "exit_code": None,
            "passed": False,
            "status": "command_not_run",
            "summary": f"validation command could not be launched: {exc}",
            "stdout_captured": False,
            "stderr_captured": False,
            "local_path_captured": False,
        }
    except ValueError as exc:
        # shlex.split rejects malformed (e.g. unbalanced-quote) commands, and
        # an argv form that collapsed to [] (corrupted stored declaration)
        # fails the runner's own empty-command check.
        return {
            "schema_version": CALLER_VALIDATION_RECEIPT_SCHEMA_VERSION,
            "command_label": label,
            "exit_code": None,
            "passed": False,
            "status": "command_malformed",
            "summary": f"validation command could not be parsed: {exc}",
            "stdout_captured": False,
            "stderr_captured": False,
            "local_path_captured": False,
        }


def run_completion_validation_gate(
    *,
    state_file: Path,
    todo_id: str,
    role: str | None,
    registry_path: Path,
    goal_id: str,
    dry_run: bool,
) -> dict[str, Any] | None:
    """Run the caller-approved completion validation gate, OUTSIDE the mutation lock.

    Returns a ``validation_blocked_completion`` failure payload when a declared
    validation command does not pass (the caller returns it unchanged so the
    durable writeback and quota spend are both skipped), or ``None`` when there
    is no declared command, the command passes, or the completion is a dry_run
    or a terminal replay (no gate). Read-only w.r.t. the state file; safe to
    call before acquiring the mutation lock so a multi-second validation command
    does not block concurrent todo operations on the same goal.
    """
    (
        validation_command,
        validation_argv,
        validation_label,
        validation_timeout_seconds,
        already_completed,
    ) = _read_declared_validation(
        state_file=state_file,
        todo_id=todo_id,
        role=role,
        registry_path=registry_path,
        goal_id=goal_id,
    )
    completion_validation = (
        _run_declared_completion_validation(
            validation_command=validation_command,
            validation_argv=validation_argv,
            validation_label=validation_label,
            validation_timeout_seconds=validation_timeout_seconds,
            registry_path=registry_path,
            goal_id=goal_id,
        )
        if not dry_run and not already_completed
        else None
    )
    if completion_validation is None or completion_validation.get("passed") is True:
        return None
    return {
        "ok": False,
        "dry_run": dry_run,
        "completed": False,
        "goal_id": goal_id,
        "todo_id": todo_id,
        "changed": False,
        "validation": completion_validation,
        "validation_blocked_completion": True,
    }
