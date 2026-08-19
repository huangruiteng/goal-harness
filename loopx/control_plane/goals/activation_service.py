from __future__ import annotations

from pathlib import Path
from typing import Any

from ...file_lock import exclusive_file_lock
from ...global_registry import sync_project_registry_to_global
from ...history import load_registry
from ...registry import atomic_write_json, registry_goals
from ...registry_writability import probe_registry_write_path
from ..runtime.time import now_local_iso
from .activation import (
    GoalActivationState,
    build_goal_activation,
    goal_activation_state,
    normalize_goal_activation_state,
)
from .configure_goal_service import resolve_configure_goal_sync_target


GOAL_ACTIVATION_TRANSITION_SCHEMA_VERSION = "loopx_goal_activation_transition_v1"
GOAL_ACTIVATION_READBACK_SCHEMA_VERSION = "loopx_goal_activation_readback_v1"


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.expanduser().resolve() == right.expanduser().resolve()
    except OSError:
        return str(left.expanduser()) == str(right.expanduser())


def _goal(payload: dict[str, Any], goal_id: str) -> dict[str, Any]:
    goal = next(
        (
            item
            for item in registry_goals(payload)
            if str(item.get("id") or "") == goal_id
        ),
        None,
    )
    if goal is None:
        raise ValueError(f"goal id not found in registry: {goal_id}")
    return goal


def _source_and_target(
    *,
    registry_path: Path,
    goal_id: str,
    runtime_root_override: str | None,
) -> tuple[Path, Path, str | None]:
    requested_registry = registry_path.expanduser().resolve()
    requested_goal = _goal(load_registry(requested_registry), goal_id)
    source_ref = str(requested_goal.get("source_registry") or "").strip()
    if source_ref:
        source_registry = Path(source_ref).expanduser().resolve()
        _goal(load_registry(source_registry), goal_id)
        return source_registry, requested_registry, str(requested_registry.parent)

    resolution = resolve_configure_goal_sync_target(
        registry_path=requested_registry,
        goal_id=goal_id,
        runtime_root_override=runtime_root_override,
    )
    target_registry = Path(str(resolution["target_global_registry"])).expanduser().resolve()
    return (
        requested_registry,
        target_registry,
        str(resolution["target_runtime_root"]),
    )


def _readback(
    *,
    source_registry: Path,
    target_registry: Path,
    goal_id: str,
    expected_state: GoalActivationState,
) -> dict[str, Any]:
    source_state = goal_activation_state(
        _goal(load_registry(source_registry), goal_id)
    )
    target_state = goal_activation_state(
        _goal(load_registry(target_registry), goal_id)
    )
    verified = source_state is expected_state and target_state is expected_state
    return {
        "schema_version": GOAL_ACTIVATION_READBACK_SCHEMA_VERSION,
        "status": "verified" if verified else "mismatch",
        "verified": verified,
        "goal_id": goal_id,
        "expected_state": expected_state.value,
        "source_state": source_state.value,
        "target_state": target_state.value,
    }


def set_goal_activation_state(
    *,
    registry_path: Path,
    goal_id: str,
    state: GoalActivationState | str,
    reason: str | None = None,
    runtime_root_override: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or apply one reversible Goal activation transition."""

    normalized_goal_id = str(goal_id or "").strip()
    if not normalized_goal_id:
        raise ValueError("goal id is required")
    target_state = normalize_goal_activation_state(state)
    source_registry, target_registry, sync_runtime_root = _source_and_target(
        registry_path=registry_path,
        goal_id=normalized_goal_id,
        runtime_root_override=runtime_root_override,
    )
    source_goal = _goal(load_registry(source_registry), normalized_goal_id)
    before_state = goal_activation_state(source_goal)
    changed = before_state is not target_state
    default_reason = (
        "Stopped by owner"
        if target_state is GoalActivationState.STOPPED
        else "Resumed by owner"
    )
    reason_text = " ".join(str(reason or default_reason).split()).strip()
    proposed_activation = build_goal_activation(
        state=target_state,
        updated_at=now_local_iso(),
        reason=reason_text,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "schema_version": GOAL_ACTIVATION_TRANSITION_SCHEMA_VERSION,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": normalized_goal_id,
        "before_state": before_state.value,
        "after_state": target_state.value,
        "changed": changed,
        "written": False,
        "partial_write": False,
        "source_registry": str(source_registry),
        "target_global_registry": str(target_registry),
        "activation": proposed_activation,
        "readback": {
            "schema_version": GOAL_ACTIVATION_READBACK_SCHEMA_VERSION,
            "status": "not_executed" if changed else "not_required",
            "verified": not changed,
        },
    }
    if not execute:
        return payload

    if changed and not _same_path(source_registry, target_registry):
        writability = probe_registry_write_path(target_registry, create_parent=True)
        payload["global_registry_writability"] = writability
        if not writability.get("ok"):
            payload.update(
                {
                    "ok": False,
                    "error_kind": "global_registry_write_denied",
                    "error": str(
                        writability.get("error")
                        or "authoritative shared registry is not writable"
                    ),
                    "recommended_action": writability.get("recommended_action"),
                }
            )
            return payload

    if changed:
        with exclusive_file_lock(
            source_registry,
            operation="set_goal_activation_state",
        ):
            source_payload = load_registry(source_registry)
            locked_goal = _goal(source_payload, normalized_goal_id)
            locked_state = goal_activation_state(locked_goal)
            if locked_state is not before_state:
                payload.update(
                    {
                        "ok": False,
                        "error_kind": "goal_activation_state_changed",
                        "error": (
                            "goal activation changed after preview; regenerate the transition"
                        ),
                        "observed_state": locked_state.value,
                    }
                )
                return payload
            locked_goal.pop("activation_state", None)
            locked_goal["activation"] = proposed_activation
            atomic_write_json(source_registry, source_payload, preserve_mode=True)
            payload["written"] = True

    sync_payload: dict[str, Any] | None = None
    if changed and not _same_path(source_registry, target_registry):
        sync_payload = sync_project_registry_to_global(
            registry_path=source_registry,
            runtime_root_override=sync_runtime_root,
            goal_id=normalized_goal_id,
            dry_run=False,
        )
        payload["global_sync"] = sync_payload

    readback = (
        _readback(
            source_registry=source_registry,
            target_registry=target_registry,
            goal_id=normalized_goal_id,
            expected_state=target_state,
        )
        if sync_payload is None or sync_payload.get("ok")
        else {
            "schema_version": GOAL_ACTIVATION_READBACK_SCHEMA_VERSION,
            "status": "not_run",
            "verified": False,
        }
    )
    payload["readback"] = readback
    sync_ok = sync_payload is None or bool(sync_payload.get("ok"))
    payload["ok"] = bool(sync_ok and readback.get("verified"))
    payload["partial_write"] = bool(payload["written"] and not payload["ok"])
    if not payload["ok"]:
        payload["error"] = "goal activation shared registry readback did not verify"
        payload["recommended_action"] = (
            (sync_payload or {}).get("recommended_action")
            or f"rerun loopx sync-global --goal-id {normalized_goal_id} after repairing the shared registry route"
        )
    return payload


def render_goal_activation_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Goal Activation",
        "",
        f"- ok: `{str(payload.get('ok')).lower()}`",
        f"- goal: `{payload.get('goal_id')}`",
        f"- transition: `{payload.get('before_state')}` → `{payload.get('after_state')}`",
        f"- dry_run: `{str(payload.get('dry_run')).lower()}`",
        f"- changed: `{str(payload.get('changed')).lower()}`",
        f"- written: `{str(payload.get('written')).lower()}`",
    ]
    readback = payload.get("readback")
    if isinstance(readback, dict):
        lines.append(f"- readback: `{readback.get('status')}`")
    if payload.get("error"):
        lines.extend(["", f"Error: {payload.get('error')}"])
    return "\n".join(lines).rstrip() + "\n"
