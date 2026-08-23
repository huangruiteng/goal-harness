from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ...agent_registry import require_registered_agent_id
from ...file_lock import exclusive_file_lock
from ...history import load_registry
from ...paths import resolve_runtime_root
from ...state_refresh import now_local, resolve_goal_state
from ..runtime.local_state_write_correctness import (
    build_todo_write_correctness_dry_run_packet,
)
from ..work_items.task_lease import (
    acquire_task_lease,
    lease_is_active,
    read_lease,
    task_lease_dir,
)
from .active_state_editing import find_todo_block, replace_updated_at
from .active_state_todo_parser import parse_active_state_todos
from .claim_visibility import build_agent_claim_scoped_open_items
from .contract import (
    TODO_TASK_CLASS_ADVANCEMENT,
    normalize_todo_claimed_by,
    normalize_todo_id,
)
from .handoff_mode import enter_todo_ownership_handoff_gate
from .line_update import apply_todo_update_to_lines
from .mutation_authority import authorize_todo_lifecycle_mutation
from .projection import (
    todo_item_is_actionable_open,
    todo_item_task_class,
)


CLAIM_NEXT_SCHEMA_VERSION = "todo_claim_next_v0"
CLAIM_NEXT_EMPTY_REASON = "no_claimable_todo"
CLAIM_NEXT_LEASE_IDEMPOTENCY_PREFIX = "claim-next"


def active_leased_todo_ids(*, runtime_root: Path, goal_id: str) -> set[str]:
    """Return todo ids that currently hold a time-active task lease."""

    lease_dir = task_lease_dir(runtime_root=runtime_root, goal_id=goal_id)
    if not lease_dir.is_dir():
        return set()
    leased: set[str] = set()
    for path in lease_dir.glob("todo_*.json"):
        lease = read_lease(path)
        if not lease_is_active(lease):
            continue
        todo_id = normalize_todo_id((lease or {}).get("todo_id") or path.stem)
        if todo_id:
            leased.add(todo_id)
    return leased


def todo_is_claimable(
    item: dict[str, Any],
    *,
    leased_todo_ids: set[str],
) -> bool:
    """Return True when the item is still free to pick-and-claim.

    Already claimed or actively leased items stay out of claim-next so
    concurrent callers cannot collide on the same todo.
    """

    todo_id = normalize_todo_id(item.get("todo_id"))
    if not todo_id:
        return False
    if normalize_todo_claimed_by(item.get("claimed_by")):
        return False
    if todo_id in leased_todo_ids:
        return False
    return True


def select_claimable_todo(
    items: list[dict[str, Any]],
    *,
    agent_id: str,
    task_class: str | None,
    leased_todo_ids: set[str],
) -> dict[str, Any] | None:
    """Pick the next claimable todo using the existing selected-todo order."""

    requested_task_class = str(task_class or TODO_TASK_CLASS_ADVANCEMENT).strip()
    open_items = [
        item
        for item in items
        if isinstance(item, dict)
        if todo_item_is_actionable_open(item)
        if todo_item_task_class(item) == requested_task_class
    ]
    selectable, _claim_scope = build_agent_claim_scoped_open_items(
        open_items,
        agent_identity={"agent_id": agent_id},
        diagnostic_item_limit=0,
    )
    for item in selectable:
        if todo_is_claimable(item, leased_todo_ids=leased_todo_ids):
            return item
    return None


def _empty_claim_next_payload(
    *,
    goal_id: str,
    agent_id: str,
    task_class: str,
    dry_run: bool,
    state_file: Path,
    project: Path | None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "schema_version": CLAIM_NEXT_SCHEMA_VERSION,
        "command": "claim-next",
        "claimed": False,
        "changed": False,
        "dry_run": dry_run,
        "empty_reason": CLAIM_NEXT_EMPTY_REASON,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "task_class": task_class,
        "todo_id": None,
        "claimed_by": None,
        "state_file": str(state_file),
        "project": str(project) if project else None,
    }


def claim_next_goal_todo(
    *,
    registry_path: Path,
    goal_id: str,
    agent_id: str,
    claimed_by: str | None = None,
    task_class: str | None = None,
    acquire_lease: bool = False,
    project: Path | None = None,
    state_file: Path | None = None,
    runtime_root_arg: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Select the next runnable todo and claim it under the goal file lock."""

    normalized_agent_id = normalize_todo_claimed_by(agent_id)
    if not normalized_agent_id:
        raise ValueError(
            "todo claim-next requires --agent-id as a public-safe agent token "
            "such as codex-main-control"
        )
    normalized_claimed_by = (
        normalize_todo_claimed_by(claimed_by) if claimed_by else None
    )
    if claimed_by and not normalized_claimed_by:
        raise ValueError(
            "claimed_by must be a public-safe agent token such as codex-main-control"
        )
    if normalized_claimed_by and normalized_claimed_by != normalized_agent_id:
        raise ValueError(
            "todo claim-next uses --agent-id as the claimant; --claimed-by must "
            "match --agent-id when both are provided"
        )
    requested_task_class = str(task_class or TODO_TASK_CLASS_ADVANCEMENT).strip()
    registry = load_registry(registry_path)
    goal, resolved_project, resolved_state_file = resolve_goal_state(
        registry=registry,
        goal_id=goal_id,
        project_override=project,
        state_file_override=state_file,
    )
    if goal is None:
        raise ValueError(f"goal {goal_id!r} is not present in the registry")
    if not resolved_state_file.exists():
        raise ValueError(f"active state file does not exist: {resolved_state_file}")
    runtime_root = resolve_runtime_root(registry, runtime_root_arg)
    effective_agent_id = require_registered_agent_id(
        registry_path=registry_path,
        goal_id=goal_id,
        agent_id=normalized_agent_id,
        field="agent_id",
    )

    with exclusive_file_lock(
        resolved_state_file,
        agent_id=effective_agent_id,
        operation="todo_claim_next",
    ), ExitStack() as handoff_gate_stack:
        original = resolved_state_file.read_text(encoding="utf-8")
        lines = original.splitlines()
        fields = parse_active_state_todos(original, item_limit=None)
        agent_items = list((fields.get("agent_todos") or {}).get("items") or [])
        leased_todo_ids = active_leased_todo_ids(
            runtime_root=runtime_root,
            goal_id=goal_id,
        )
        selected = select_claimable_todo(
            agent_items,
            agent_id=effective_agent_id,
            task_class=requested_task_class,
            leased_todo_ids=leased_todo_ids,
        )
        if selected is None:
            return _empty_claim_next_payload(
                goal_id=goal_id,
                agent_id=effective_agent_id,
                task_class=requested_task_class,
                dry_run=dry_run,
                state_file=resolved_state_file,
                project=resolved_project,
            )
        selected_todo_id = normalize_todo_id(selected.get("todo_id"))
        if not selected_todo_id:
            return _empty_claim_next_payload(
                goal_id=goal_id,
                agent_id=effective_agent_id,
                task_class=requested_task_class,
                dry_run=dry_run,
                state_file=resolved_state_file,
                project=resolved_project,
            )
        existing_block_match = find_todo_block(
            lines,
            todo_id=selected_todo_id,
            role="agent",
        )
        if not existing_block_match:
            raise ValueError(
                f"todo_id {selected_todo_id!r} was not found in active agent todos"
            )
        _existing_role, _section, _start, _end, existing_block = existing_block_match
        authority_todo = dict(existing_block)
        authority_todo["role"] = "agent"
        mutation_authority = authorize_todo_lifecycle_mutation(
            registry_path=registry_path,
            goal_id=goal_id,
            command="claim",
            todo=authority_todo,
            actor_agent_id=effective_agent_id,
            authority_action=None,
            requested_claimed_by=effective_agent_id,
        )
        handoff_gate = enter_todo_ownership_handoff_gate(
            handoff_gate_stack,
            state_text=original,
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=selected_todo_id,
            mutation_authority=mutation_authority,
            actor_agent_id=effective_agent_id,
            ownership_mutation=True,
        )
        updated_at = now_local()
        update_result = apply_todo_update_to_lines(
            lines,
            todo_id=selected_todo_id,
            role="agent",
            claimed_by=effective_agent_id,
            claim_only=True,
            updated_at=updated_at,
        )
        changed = bool(update_result["changed"])
        new_text = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
        if changed:
            new_text = replace_updated_at(new_text, updated_at)
        if changed and not dry_run:
            resolved_state_file.write_text(new_text, encoding="utf-8")
        payload: dict[str, Any] = {
            "ok": True,
            "schema_version": CLAIM_NEXT_SCHEMA_VERSION,
            "command": "claim-next",
            "claimed": True,
            "dry_run": dry_run,
            "changed": changed,
            "goal_id": goal_id,
            "agent_id": effective_agent_id,
            "mutation_authority": mutation_authority,
            **handoff_gate,
            **update_result,
            "state_file": str(resolved_state_file),
            "project": str(resolved_project) if resolved_project else None,
            "updated_at": updated_at if changed else None,
        }
        if acquire_lease:
            if dry_run:
                payload["task_lease"] = {
                    "ok": True,
                    "dry_run": True,
                    "would_acquire": True,
                    "todo_id": selected_todo_id,
                    "owner": effective_agent_id,
                }
            else:
                payload["task_lease"] = acquire_task_lease(
                    registry_path=registry_path,
                    runtime_root=runtime_root,
                    goal_id=goal_id,
                    todo_id=selected_todo_id,
                    owner=effective_agent_id,
                    idempotency_key=(
                        f"{CLAIM_NEXT_LEASE_IDEMPOTENCY_PREFIX}:"
                        f"{selected_todo_id}:{effective_agent_id}"
                    ),
                )
        if dry_run:
            payload["local_state_write_correctness"] = (
                build_todo_write_correctness_dry_run_packet(
                    goal_id=goal_id,
                    write_class="todo_claim",
                    state_text=original,
                    todo_id=selected_todo_id,
                    role="agent",
                    section=str(update_result.get("section") or ""),
                    claimed_by=effective_agent_id,
                    changed=changed,
                )
            )
        return payload
