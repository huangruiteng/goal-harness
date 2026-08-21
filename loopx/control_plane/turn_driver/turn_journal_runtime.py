from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
from typing import Any

from ..effect_runtime import effect_runtime_result


TURN_JOURNAL_INTERPRETATION_REQUEST_SCHEMA_VERSION = (
    "loopx_turn_journal_interpretation_request_v0"
)
TURN_JOURNAL_INSPECTION_SCHEMA_VERSION = "loopx_turn_journal_inspection_v0"
_PROJECTION_KEYS = {
    "ok",
    "schema_version",
    "decision",
    "journal_status",
    "replay_legal",
    "goal_matches",
    "owner_matches",
    "turn_key_matches",
    "phases_form_ordered_prefix",
    "completed_phases",
    "tombstone_retained",
    "violations",
    "effects",
}
_BOOLEAN_PROJECTION_KEYS = {
    "replay_legal",
    "goal_matches",
    "owner_matches",
    "turn_key_matches",
    "phases_form_ordered_prefix",
    "tombstone_retained",
}


def interpret_turn_journal_projection(
    journal: Mapping[str, Any],
    *,
    goal_id: str,
    agent_id: str,
    turn_key: str,
) -> dict[str, object]:
    """Run the TS-owned journal rule through the managed Effect runtime."""

    request = {
        "schema_version": TURN_JOURNAL_INTERPRETATION_REQUEST_SCHEMA_VERSION,
        "journal": journal,
        "goal_id": goal_id,
        "agent_id": agent_id,
        "turn_key": turn_key,
    }
    payload = effect_runtime_result("turn_journal.inspect", request)
    if not isinstance(payload, dict) or set(payload) != _PROJECTION_KEYS:
        raise RuntimeError(
            "TypeScript Turn-journal inspection projection shape mismatch"
        )
    if payload.get("schema_version") != TURN_JOURNAL_INSPECTION_SCHEMA_VERSION:
        raise RuntimeError(
            "TypeScript Turn-journal inspection projection schema mismatch"
        )
    if (
        payload.get("ok") is not True
        or payload.get("decision") not in {"replay_legal", "replay_blocked"}
        or not isinstance(payload.get("journal_status"), str)
        or any(
            not isinstance(payload.get(key), bool) for key in _BOOLEAN_PROJECTION_KEYS
        )
        or not isinstance(payload.get("completed_phases"), list)
        or not all(isinstance(phase, str) for phase in payload["completed_phases"])
        or not isinstance(payload.get("violations"), list)
        or not all(isinstance(violation, str) for violation in payload["violations"])
    ):
        raise RuntimeError(
            "TypeScript Turn-journal inspection projection type mismatch"
        )
    if payload.get("effects") != []:
        raise RuntimeError("Turn-journal inspection must remain effect-free")
    return payload


def write_turn_journal(
    path: str,
    journal: Mapping[str, Any],
    *,
    expected_effect_id: str | None = None,
) -> dict[str, object]:
    """Atomically checkpoint a Turn journal in the TS Effect runtime."""

    journal_path = Path(path)
    try:
        expected_previous_sha256: str | None = hashlib.sha256(
            journal_path.read_bytes()
        ).hexdigest()
    except FileNotFoundError:
        expected_previous_sha256 = None

    payload = effect_runtime_result(
        "turn_journal.write",
        {
            "path": path,
            "journal": dict(journal),
            "expected_effect_id": expected_effect_id,
            "expected_previous_sha256": expected_previous_sha256,
        },
        retry_safe=True,
    )
    if (
        not isinstance(payload, dict)
        or payload.get("ok") is not True
        or not isinstance(payload.get("appended"), bool)
        or not isinstance(payload.get("replayed"), bool)
        or not isinstance(payload.get("operation_id"), str)
    ):
        raise RuntimeError("TypeScript Effect runtime did not commit the journal")
    return payload
