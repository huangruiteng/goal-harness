from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...file_lock import exclusive_file_lock
from ...global_registry import preserve_attention_override, sanitize_goal_for_global
from ...registry import atomic_write_json, read_json, registry_goals
from ..machine_configuration.builtins import (
    build_builtin_machine_configuration_registry,
)
from ..machine_configuration.store import read_machine_configuration
from .machine_defaults import (
    materialize_goal_periodic_report_subscription,
    normalize_loopx_machine_defaults,
)


GOAL_MATERIALIZATION_PLAN_SCHEMA = "periodic_report_goal_materialization_plan_v0"
GOAL_MATERIALIZATION_TRANSACTION_SCHEMA = (
    "periodic_report_goal_materialization_transaction_v0"
)
GOAL_MATERIALIZATION_BACKUP_SCHEMA = "periodic_report_goal_materialization_backup_v0"
GOAL_MATERIALIZATION_ROLLBACK_PLAN_SCHEMA = (
    "periodic_report_goal_materialization_rollback_plan_v0"
)
GOAL_MATERIALIZATION_ROLLBACK_RECEIPT_SCHEMA = (
    "periodic_report_goal_materialization_rollback_receipt_v0"
)

_TRANSACTION_ID_RE = re.compile(r"^goal_materialization_[0-9a-f]{24}$")
_TERMINAL_GOAL_STATUSES = {
    "archived",
    "canceled",
    "cancelled",
    "completed",
    "disconnected",
    "retired",
    "stopped",
}
JsonWriter = Callable[[Path, dict[str, Any]], None]


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def _is_global_registry(path: Path, payload: Mapping[str, Any]) -> bool:
    role = str(payload.get("registry_role") or payload.get("role") or "")
    return role == "global-local" or path.name == "registry.global.json"


def _state_path(goal: Mapping[str, Any]) -> Path | None:
    repo = str(goal.get("repo") or "").strip()
    state_file = str(goal.get("state_file") or "").strip()
    if not repo or not state_file:
        return None
    path = Path(state_file).expanduser()
    return path if path.is_absolute() else Path(repo).expanduser() / path


def _goal(payload: Mapping[str, Any], goal_id: str) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in registry_goals(dict(payload))
            if str(item.get("id") or "") == goal_id
        ),
        None,
    )


def _periodic(goal: Mapping[str, Any]) -> dict[str, Any] | None:
    control_plane = goal.get("control_plane")
    if not isinstance(control_plane, Mapping):
        return None
    periodic = control_plane.get("periodic_report")
    return dict(periodic) if isinstance(periodic, Mapping) else None


def _transaction_id(value: str) -> str:
    normalized = str(value or "").strip()
    if not _TRANSACTION_ID_RE.fullmatch(normalized):
        raise ValueError("transaction_id is invalid")
    return normalized


def _transaction_dir(runtime_root: Path, transaction_id: str) -> Path:
    return (
        runtime_root.expanduser().resolve()
        / "machine"
        / "periodic-report"
        / "goal-materializations"
        / transaction_id
    )


def _transaction_ref(transaction_id: str, name: str) -> str:
    return f"machine/periodic-report/goal-materializations/{transaction_id}/{name}.json"


def _registry_key(path: Path) -> str:
    return "registry_" + hashlib.sha256(
        str(path.expanduser().resolve()).encode("utf-8")
    ).hexdigest()[:16]


def _known_registry_paths(registry_path: Path) -> dict[str, Path]:
    root_path = registry_path.expanduser().resolve()
    root_payload = read_json(root_path)
    paths = {root_path}
    if _is_global_registry(root_path, root_payload):
        for goal in registry_goals(root_payload):
            source_path = _source_path(
                root_path=root_path,
                root_is_global=True,
                projected_goal=goal,
            )
            if source_path is not None:
                paths.add(source_path)
    return {_registry_key(path): path for path in paths}


def _secure_write(path: Path, payload: dict[str, Any], *, writer: JsonWriter) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    writer(path, payload)
    path.chmod(0o600)


def _source_path(
    *, root_path: Path, root_is_global: bool, projected_goal: Mapping[str, Any]
) -> Path | None:
    if not root_is_global:
        return root_path
    source = str(projected_goal.get("source_registry") or "").strip()
    return Path(source).expanduser().resolve() if source else None


def _load_source_goal(
    *,
    projected_goal: Mapping[str, Any],
    root_path: Path,
    root_is_global: bool,
    payloads: dict[Path, dict[str, Any]],
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    status = str(projected_goal.get("status") or "active").strip().lower()
    if status in _TERMINAL_GOAL_STATUSES:
        return None, None, "goal_not_active"
    source_path = _source_path(
        root_path=root_path,
        root_is_global=root_is_global,
        projected_goal=projected_goal,
    )
    if source_path is None or not source_path.is_file():
        return source_path, None, "authoritative_registry_unavailable"
    try:
        if source_path not in payloads:
            payloads[source_path] = read_json(source_path)
    except (OSError, ValueError):
        return source_path, None, "authoritative_registry_unavailable"
    goal_id = str(projected_goal.get("id") or "").strip()
    source_goal = _goal(payloads[source_path], goal_id)
    if source_goal is None:
        return source_path, None, "authoritative_goal_unavailable"
    return source_path, source_goal, None


def _materialization_outcome(
    source_goal: Mapping[str, Any],
    machine_defaults: Mapping[str, Any],
) -> tuple[str, str, dict[str, Any] | None]:
    status = str(source_goal.get("status") or "active").strip().lower()
    if status in _TERMINAL_GOAL_STATUSES:
        return "excluded", "goal_not_active", None
    state_path = _state_path(source_goal)
    if state_path is None or not state_path.is_file():
        return "excluded", "authoritative_state_unavailable", None
    existing = _periodic(source_goal)
    if existing is not None and existing.get("source") != "machine_default":
        return "preserve", "goal_override", None
    updated_goal = materialize_goal_periodic_report_subscription(
        source_goal,
        machine_defaults,
        update_inherited=True,
    )
    if updated_goal == source_goal:
        return "unchanged", "already_materialized", None
    if existing is None:
        return "materialize", "machine_default_missing", updated_goal
    return "update", "inherited_default_revision_changed", updated_goal


def _build_snapshot(
    *, registry_path: Path, runtime_root: Path, synced_at: str | None = None
) -> dict[str, Any]:
    root_path = registry_path.expanduser().resolve()
    root_payload = read_json(root_path)
    machine_defaults = read_machine_configuration(
        runtime_root, registry=build_builtin_machine_configuration_registry()
    )
    if machine_defaults is None:
        raise ValueError("periodic-report machine defaults are not configured")
    normalized_defaults = normalize_loopx_machine_defaults(machine_defaults)
    root_is_global = _is_global_registry(root_path, root_payload)
    payloads: dict[Path, dict[str, Any]] = {root_path: root_payload}
    rows: list[dict[str, Any]] = []
    changes: list[tuple[str, Path, dict[str, Any]]] = []

    for projected_goal in registry_goals(root_payload):
        goal_id = str(projected_goal.get("id") or "").strip()
        source_path, source_goal, exclusion = _load_source_goal(
            projected_goal=projected_goal,
            root_path=root_path,
            root_is_global=root_is_global,
            payloads=payloads,
        )
        if exclusion is not None:
            action, reason = "excluded", exclusion
        else:
            assert source_goal is not None and source_path is not None
            action, reason, updated_goal = _materialization_outcome(
                source_goal, normalized_defaults
            )
            if updated_goal is not None:
                changes.append((goal_id, source_path, updated_goal))
        rows.append({"goal_id": goal_id, "action": action, "reason": reason})

    updated_payloads = {
        path: copy.deepcopy(payload) for path, payload in payloads.items()
    }
    sync_timestamp = synced_at or "<apply-time>"
    for goal_id, source_path, updated_goal in changes:
        source_payload = updated_payloads[source_path]
        source_payload["goals"] = [
            updated_goal if str(item.get("id") or "") == goal_id else item
            for item in registry_goals(source_payload)
        ]
        if root_is_global and not _same_path(source_path, root_path):
            incoming = sanitize_goal_for_global(
                updated_goal,
                source_registry=source_path,
                synced_at=sync_timestamp,
            )
            updated_payloads[root_path]["goals"] = [
                preserve_attention_override(item, incoming)
                if str(item.get("id") or "") == goal_id
                else item
                for item in registry_goals(updated_payloads[root_path])
            ]

    counts = {
        action: sum(row["action"] == action for row in rows)
        for action in ("materialize", "update", "unchanged", "preserve", "excluded")
    }
    registry_revisions = [
        {
            "registry_key": _registry_key(path),
            "before_revision": _digest(payloads[path]),
        }
        for path in sorted(payloads, key=str)
    ]
    identity = {
        "machine_defaults_revision": _digest(normalized_defaults),
        "root_registry_revision": _digest(root_payload),
        "registry_revisions": registry_revisions,
        "rows": rows,
    }
    plan = {
        "ok": True,
        "schema_version": GOAL_MATERIALIZATION_PLAN_SCHEMA,
        "status": "preview",
        **identity,
        "counts": counts,
        "writes_required": counts["materialize"] + counts["update"],
        "registries_write_required": sum(
            updated_payloads[path] != payloads[path] for path in payloads
        ),
        "plan_revision": _digest(identity),
    }
    return {
        "plan": plan,
        "paths": sorted(payloads, key=str),
        "before": payloads,
        "after": updated_payloads,
        "machine_defaults": normalized_defaults,
    }


def plan_periodic_report_goal_materialization(
    *, registry_path: Path, runtime_root: Path
) -> dict[str, Any]:
    return dict(
        _build_snapshot(registry_path=registry_path, runtime_root=runtime_root)["plan"]
    )


def _restore(entries: Sequence[Mapping[str, Any]], *, writer: JsonWriter) -> None:
    for entry in reversed(entries):
        path = entry["path"]
        if not isinstance(path, Path):
            raise TypeError("validated registry path is required")
        writer(path, dict(entry["payload"]))


def _apply_transaction(
    *,
    snapshot: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    backup_path: Path,
    receipt_path: Path,
    backup: dict[str, Any],
    transaction_id: str,
    applied_at: str,
    writer: JsonWriter,
) -> dict[str, Any]:
    written: list[Mapping[str, Any]] = []
    try:
        _secure_write(backup_path, backup, writer=writer)
        for entry, path in zip(entries, snapshot["paths"], strict=True):
            if snapshot["after"][path] == snapshot["before"][path]:
                continue
            written.append({"path": path, "payload": entry["payload"]})
            writer(path, snapshot["after"][path])
        for path in snapshot["paths"]:
            if read_json(path) != snapshot["after"][path]:
                raise RuntimeError("goal-materialization registry readback mismatch")
        plan = snapshot["plan"]
        receipt = {
            "ok": True,
            "schema_version": GOAL_MATERIALIZATION_TRANSACTION_SCHEMA,
            "status": "applied",
            "transaction_id": transaction_id,
            "transaction_ref": _transaction_ref(transaction_id, "transaction"),
            "backup_ref": _transaction_ref(transaction_id, "backup"),
            "backup_revision": _digest(backup),
            "plan_revision": plan["plan_revision"],
            "applied_at": applied_at,
            "counts": plan["counts"],
            "writes_required": plan["writes_required"],
            "registries_written": len(written),
            "readback_verified": True,
            "rollback_available": True,
        }
        receipt["receipt_revision"] = _digest(receipt)
        _secure_write(receipt_path, receipt, writer=writer)
        return receipt
    except Exception as exc:
        try:
            _restore(written, writer=writer)
        except Exception as rollback_exc:
            raise RuntimeError(
                "goal materialization failed and automatic restoration also failed"
            ) from rollback_exc
        raise RuntimeError(
            "goal materialization failed; prior registries were restored"
        ) from exc


def migrate_periodic_report_goal_materializations(
    *,
    registry_path: Path,
    runtime_root: Path,
    execute: bool = False,
    expected_plan_revision: str | None = None,
    now: datetime | None = None,
    writer: JsonWriter = atomic_write_json,
) -> dict[str, Any]:
    preview = plan_periodic_report_goal_materialization(
        registry_path=registry_path, runtime_root=runtime_root
    )
    if not execute:
        return preview
    expected = str(expected_plan_revision or "").strip()
    if not expected:
        raise ValueError("expected_plan_revision is required when execute is true")

    initial = _build_snapshot(registry_path=registry_path, runtime_root=runtime_root)
    lock_paths = list(initial["paths"])
    with ExitStack() as locks:
        for path in lock_paths:
            locks.enter_context(
                exclusive_file_lock(
                    path, operation="periodic_report_goal_materialization"
                )
            )
        applied_at = _now_iso(now)
        snapshot = _build_snapshot(
            registry_path=registry_path,
            runtime_root=runtime_root,
            synced_at=applied_at,
        )
        plan = snapshot["plan"]
        if plan["plan_revision"] != expected:
            raise ValueError(
                "goal-materialization plan revision changed; preview again"
            )
        if plan["writes_required"] == 0:
            return {
                **plan,
                "schema_version": GOAL_MATERIALIZATION_TRANSACTION_SCHEMA,
                "status": "unchanged",
                "transaction_id": None,
                "transaction_ref": None,
                "backup_ref": None,
                "readback_verified": True,
                "rollback_available": False,
            }

        transaction_id = f"goal_materialization_{uuid4().hex[:24]}"
        directory = _transaction_dir(runtime_root, transaction_id)
        backup_path = directory / "backup.json"
        receipt_path = directory / "transaction.json"
        entries = [
            {
                "registry_key": _registry_key(path),
                "path": str(path),
                "before_revision": _digest(snapshot["before"][path]),
                "after_revision": _digest(snapshot["after"][path]),
                "payload": snapshot["before"][path],
            }
            for path in snapshot["paths"]
        ]
        backup = {
            "schema_version": GOAL_MATERIALIZATION_BACKUP_SCHEMA,
            "transaction_id": transaction_id,
            "plan_revision": plan["plan_revision"],
            "registries": entries,
        }
        return _apply_transaction(
            snapshot=snapshot,
            entries=entries,
            backup_path=backup_path,
            receipt_path=receipt_path,
            backup=backup,
            transaction_id=transaction_id,
            applied_at=applied_at,
            writer=writer,
        )


def _read_transaction(
    *, registry_path: Path, runtime_root: Path, transaction_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    safe_id = _transaction_id(transaction_id)
    directory = _transaction_dir(runtime_root, safe_id)
    receipt = read_json(directory / "transaction.json")
    backup = read_json(directory / "backup.json")
    receipt_revision = receipt.get("receipt_revision")
    unsigned_receipt = {
        key: value for key, value in receipt.items() if key != "receipt_revision"
    }
    if (
        receipt.get("schema_version") != GOAL_MATERIALIZATION_TRANSACTION_SCHEMA
        or receipt.get("status") != "applied"
        or receipt.get("transaction_id") != safe_id
        or _digest(unsigned_receipt) != receipt_revision
        or backup.get("schema_version") != GOAL_MATERIALIZATION_BACKUP_SCHEMA
        or backup.get("transaction_id") != safe_id
        or backup.get("plan_revision") != receipt.get("plan_revision")
        or _digest(backup) != receipt.get("backup_revision")
    ):
        raise ValueError("goal-materialization transaction is invalid")
    entries = backup.get("registries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("goal-materialization backup is invalid")
    known_paths = _known_registry_paths(registry_path)
    seen_keys: set[str] = set()
    validated_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("goal-materialization backup registry entry is invalid")
        registry_key = str(entry.get("registry_key") or "")
        path = known_paths.get(registry_key)
        payload = entry.get("payload")
        if (
            path is None
            or registry_key in seen_keys
            or str(path) != entry.get("path")
            or not isinstance(payload, Mapping)
            or _digest(payload) != entry.get("before_revision")
            or not str(entry.get("after_revision") or "").startswith("sha256:")
        ):
            raise ValueError("goal-materialization backup registry entry is invalid")
        seen_keys.add(registry_key)
        validated_entries.append({**entry, "path": path, "payload": dict(payload)})
    return receipt, validated_entries


def _revision_state(
    *, current_revision: str, before_revision: str, after_revision: str
) -> str:
    if current_revision == before_revision:
        return "before"
    if current_revision == after_revision:
        return "after"
    return "changed"


def _rollback_plan(
    *, transaction_id: str, entries: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    states: list[str] = []
    revisions: list[dict[str, str]] = []
    for entry in entries:
        path = entry["path"]
        if not isinstance(path, Path):
            raise TypeError("validated registry path is required")
        current_revision = _digest(read_json(path)) if path.is_file() else "absent"
        before_revision = str(entry.get("before_revision") or "")
        after_revision = str(entry.get("after_revision") or "")
        state = _revision_state(
            current_revision=current_revision,
            before_revision=before_revision,
            after_revision=after_revision,
        )
        states.append(state)
        revisions.append(
            {
                "registry_key": str(entry.get("registry_key") or ""),
                "current_revision": current_revision,
                "before_revision": before_revision,
                "after_revision": after_revision,
            }
        )
    if all(state == "before" for state in states):
        action, allowed, reason = "unchanged", True, "already_rolled_back"
    elif all(state in {"before", "after"} for state in states) and any(
        state == "after" for state in states
    ):
        action, allowed, reason = "restore", True, "exact_applied_revisions_match"
    else:
        action, allowed, reason = "blocked", False, "registry_revision_changed"
    identity = {
        "transaction_id": transaction_id,
        "registry_revisions": revisions,
        "action": action,
    }
    return {
        "ok": True,
        "schema_version": GOAL_MATERIALIZATION_ROLLBACK_PLAN_SCHEMA,
        "status": "preview",
        **identity,
        "reason": reason,
        "rollback_allowed": allowed,
        "writes_required": sum(state == "after" for state in states),
        "plan_revision": _digest(identity),
    }


def plan_periodic_report_goal_materialization_rollback(
    *, registry_path: Path, runtime_root: Path, transaction_id: str
) -> dict[str, Any]:
    _, entries = _read_transaction(
        registry_path=registry_path,
        runtime_root=runtime_root,
        transaction_id=transaction_id,
    )
    return _rollback_plan(
        transaction_id=_transaction_id(transaction_id),
        entries=entries,
    )


def _execute_rollback(
    entries: Sequence[Mapping[str, Any]], *, writer: JsonWriter
) -> None:
    applied_entries: list[dict[str, Any]] = []
    for entry in entries:
        path = entry["path"]
        current_payload = read_json(path)
        if _digest(current_payload) == str(entry["after_revision"]):
            applied_entries.append({"path": path, "payload": current_payload})
    try:
        for entry in entries:
            path = entry["path"]
            if _digest(read_json(path)) == str(entry["after_revision"]):
                writer(path, dict(entry["payload"]))
        if any(
            _digest(read_json(entry["path"])) != str(entry["before_revision"])
            for entry in entries
        ):
            raise RuntimeError("goal-materialization rollback readback mismatch")
    except Exception as exc:
        try:
            _restore(applied_entries, writer=writer)
        except Exception as restore_exc:
            raise RuntimeError(
                "goal-materialization rollback failed and applied state could not be restored"
            ) from restore_exc
        raise RuntimeError(
            "goal-materialization rollback failed; applied state was restored"
        ) from exc


def rollback_periodic_report_goal_materializations(
    *,
    registry_path: Path,
    runtime_root: Path,
    transaction_id: str,
    execute: bool = False,
    expected_plan_revision: str | None = None,
    now: datetime | None = None,
    writer: JsonWriter = atomic_write_json,
) -> dict[str, Any]:
    preview = plan_periodic_report_goal_materialization_rollback(
        registry_path=registry_path,
        runtime_root=runtime_root,
        transaction_id=transaction_id,
    )
    if not execute:
        return preview
    expected = str(expected_plan_revision or "").strip()
    if not expected:
        raise ValueError("expected_plan_revision is required when execute is true")
    safe_id = _transaction_id(transaction_id)
    _, entries = _read_transaction(
        registry_path=registry_path,
        runtime_root=runtime_root,
        transaction_id=safe_id,
    )
    lock_paths = sorted((entry["path"] for entry in entries), key=str)
    with ExitStack() as locks:
        for path in lock_paths:
            locks.enter_context(
                exclusive_file_lock(path, operation="rollback_goal_materialization")
            )
        plan = _rollback_plan(transaction_id=safe_id, entries=entries)
        if plan["plan_revision"] != expected:
            raise ValueError(
                "goal-materialization rollback plan changed; preview again"
            )
        if not plan["rollback_allowed"]:
            raise ValueError(
                "goal-materialization rollback is blocked by a newer revision"
            )
        if plan["action"] == "unchanged":
            return {
                **plan,
                "schema_version": GOAL_MATERIALIZATION_ROLLBACK_RECEIPT_SCHEMA,
                "status": "unchanged",
                "rollback_id": None,
                "readback_verified": True,
            }
        _execute_rollback(entries, writer=writer)
        rollback_id = f"goal_materialization_rollback_{uuid4().hex[:24]}"
        receipt = {
            "ok": True,
            "schema_version": GOAL_MATERIALIZATION_ROLLBACK_RECEIPT_SCHEMA,
            "status": "rolled_back",
            "rollback_id": rollback_id,
            "transaction_id": safe_id,
            "plan_revision": plan["plan_revision"],
            "registries_restored": plan["writes_required"],
            "rolled_back_at": _now_iso(now),
            "readback_verified": True,
        }
        _secure_write(
            _transaction_dir(runtime_root, safe_id) / f"{rollback_id}.json",
            receipt,
            writer=writer,
        )
        return receipt


__all__ = [
    "GOAL_MATERIALIZATION_BACKUP_SCHEMA",
    "GOAL_MATERIALIZATION_PLAN_SCHEMA",
    "GOAL_MATERIALIZATION_ROLLBACK_PLAN_SCHEMA",
    "GOAL_MATERIALIZATION_ROLLBACK_RECEIPT_SCHEMA",
    "GOAL_MATERIALIZATION_TRANSACTION_SCHEMA",
    "migrate_periodic_report_goal_materializations",
    "plan_periodic_report_goal_materialization",
    "plan_periodic_report_goal_materialization_rollback",
    "rollback_periodic_report_goal_materializations",
]
