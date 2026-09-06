from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..file_lock import exclusive_file_lock
from ..history import validate_goal_id_path_segment


POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION = (
    "loopx_post_writeback_composition_retry_receipt_v0"
)
POST_WRITEBACK_COMPOSITION_RETRY_LOG_NAME = "composition-retry-receipts.jsonl"
POST_WRITEBACK_COMPOSITION_RETRY_REF_PREFIX = "post-writeback-composition:"
POST_WRITEBACK_COMPOSITION_RETRY_ERROR_CODES = (
    "source_projection_failed",
    "dispatch_failed",
)
_COMPOSITION_RETRY_JOURNAL_ROW_LIMIT = 512


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def composition_retry_receipt_log_path(runtime_root: Path, goal_id: str) -> Path:
    """Resolve the per-goal append-only journal for composition retry receipts."""

    return (
        runtime_root.expanduser()
        / "goals"
        / validate_goal_id_path_segment(goal_id)
        / "post_writeback_hooks"
        / POST_WRITEBACK_COMPOSITION_RETRY_LOG_NAME
    )


def composition_retry_receipt_id(
    *,
    goal_id: str,
    event_kind: str,
    identity: Mapping[str, Any],
    state_version: str,
) -> str:
    """Bind one receipt to the exact primary writeback it observes."""

    stable = {
        "goal_id": str(goal_id or ""),
        "event_kind": str(event_kind or ""),
        "agent_id": str(identity.get("agent_id") or ""),
        "todo_id": str(identity.get("todo_id") or ""),
        "turn_instance_id": str(identity.get("turn_instance_id") or ""),
        "effect_id": str(identity.get("effect_id") or ""),
        "state_version": str(state_version or ""),
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return "pwcr_" + hashlib.sha256(encoded).hexdigest()[:16]


def composition_retry_receipt_ref(receipt_id: str) -> str:
    return f"{POST_WRITEBACK_COMPOSITION_RETRY_REF_PREFIX}{receipt_id}"


def build_composition_retry_receipt(
    *,
    goal_id: str,
    event_kind: str,
    identity: Mapping[str, Any],
    state_version: str,
    committed_at: str,
    hook_identities: Sequence[Mapping[str, str]],
    error_code: str | None = None,
    status: str = "retryable",
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Build one public-safe retry receipt bound to a committed primary writeback.

    The receipt records lifecycle identity only: no projection payload, task
    text, local paths, or provider output is ever embedded.
    """

    if status not in {"retryable", "settled"}:
        raise ValueError("composition retry receipt status is invalid")
    if status == "retryable" and error_code not in (
        POST_WRITEBACK_COMPOSITION_RETRY_ERROR_CODES
    ):
        raise ValueError("composition retry receipt error_code is invalid")
    bounded_identities: list[dict[str, str]] = []
    seen_hook_ids: set[str] = set()
    for raw_identity in hook_identities:
        hook_id = str(raw_identity.get("hook_id") or "")[:200]
        capability_id = str(raw_identity.get("capability_id") or "")[:200]
        if not hook_id or hook_id in seen_hook_ids:
            continue
        seen_hook_ids.add(hook_id)
        bounded_identities.append(
            {"hook_id": hook_id, "capability_id": capability_id}
        )
    return {
        "schema_version": POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION,
        "receipt_id": composition_retry_receipt_id(
            goal_id=goal_id,
            event_kind=event_kind,
            identity=identity,
            state_version=state_version,
        ),
        "status": status,
        "error_code": error_code,
        "event_kind": str(event_kind or ""),
        "identity": {
            "goal_id": str(goal_id or ""),
            "agent_id": str(identity.get("agent_id") or ""),
            "todo_id": str(identity.get("todo_id") or ""),
            "turn_instance_id": str(identity.get("turn_instance_id") or ""),
            "effect_id": str(identity.get("effect_id") or ""),
        },
        "state_version": str(state_version or ""),
        "committed_at": str(committed_at or ""),
        "hooks": bounded_identities,
        "primary_writeback_preserved": True,
        "external_writes_performed": False,
        "recorded_at": recorded_at or _now_iso(),
    }


def _iter_composition_retry_rows(
    log_path: Path, *, row_limit: int = _COMPOSITION_RETRY_JOURNAL_ROW_LIMIT
) -> list[dict[str, Any]]:
    """Read a bounded suffix of valid journal rows, oldest first."""

    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(0, row_limit) :]:
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if (
            row.get("schema_version")
            != POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION
            or not isinstance(row.get("receipt_id"), str)
            or row.get("status") not in {"retryable", "settled"}
        ):
            continue
        rows.append(row)
    return rows


def _current_composition_retry_row(
    handle: Any, receipt_id: str
) -> dict[str, Any] | None:
    handle.seek(0)
    current: dict[str, Any] | None = None
    for line in handle:
        text = line.strip()
        if not text or receipt_id not in text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(row, dict)
            and row.get("schema_version")
            == POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION
            and row.get("receipt_id") == receipt_id
            and row.get("status") in {"retryable", "settled"}
        ):
            current = row
    return current


def append_composition_retry_receipt(
    log_path: Path, receipt: Mapping[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Append one receipt row once, never regressing a settled receipt.

    Returns the durable row and whether this call appended it. Re-recording a
    still-retryable receipt appends the newest observation; a settled receipt
    is terminal and is returned unchanged.
    """

    payload = dict(receipt)
    if (
        payload.get("schema_version")
        != POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION
    ):
        raise ValueError("unsupported composition retry receipt schema")
    receipt_id = str(payload.get("receipt_id") or "")
    if not receipt_id:
        raise ValueError("composition retry receipt_id is required")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(log_path):
        with log_path.open("a+", encoding="utf-8") as handle:
            current = _current_composition_retry_row(handle, receipt_id)
            if current is not None and current.get("status") == "settled":
                return current, False
            handle.write(
                json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n"
            )
    return payload, True


def settle_composition_retry_receipt(
    log_path: Path,
    *,
    goal_id: str,
    event_kind: str,
    identity: Mapping[str, Any],
    state_version: str,
    committed_at: str,
    hook_identities: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], bool]:
    """Supersede one retryable receipt after its projection composed cleanly."""

    settled = build_composition_retry_receipt(
        goal_id=goal_id,
        event_kind=event_kind,
        identity=identity,
        state_version=state_version,
        committed_at=committed_at,
        hook_identities=hook_identities,
        error_code=None,
        status="settled",
    )
    receipt_id = str(settled["receipt_id"])
    if not log_path.is_file():
        return {}, False
    with exclusive_file_lock(log_path):
        with log_path.open("r+", encoding="utf-8") as handle:
            current = _current_composition_retry_row(handle, receipt_id)
            if current is not None and current.get("status") == "settled":
                return current, False
            if current is None:
                return {}, False
            handle.seek(0, 2)
            handle.write(
                json.dumps(settled, sort_keys=True, ensure_ascii=False) + "\n"
            )
    return settled, True


def pending_composition_retry_receipts(
    runtime_root: Path, goal_id: str
) -> list[dict[str, Any]]:
    """Read unconsumed retryable receipts for one goal, newest row per receipt."""

    rows = _iter_composition_retry_rows(
        composition_retry_receipt_log_path(runtime_root, goal_id)
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[str(row.get("receipt_id"))] = row
    return sorted(
        (
            dict(row)
            for row in latest.values()
            if row.get("status") == "retryable"
        ),
        key=lambda row: str(row.get("receipt_id") or ""),
    )


__all__ = [
    "POST_WRITEBACK_COMPOSITION_RETRY_ERROR_CODES",
    "POST_WRITEBACK_COMPOSITION_RETRY_LOG_NAME",
    "POST_WRITEBACK_COMPOSITION_RETRY_RECEIPT_SCHEMA_VERSION",
    "POST_WRITEBACK_COMPOSITION_RETRY_REF_PREFIX",
    "append_composition_retry_receipt",
    "build_composition_retry_receipt",
    "composition_retry_receipt_id",
    "composition_retry_receipt_log_path",
    "composition_retry_receipt_ref",
    "pending_composition_retry_receipts",
    "settle_composition_retry_receipt",
]
