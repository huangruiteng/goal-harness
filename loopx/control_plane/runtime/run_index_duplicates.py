from __future__ import annotations

import json
from typing import Any


REWARD_OVERLAY_IDENTITY_KEYS = (
    "generated_at",
    "goal_id",
    "classification",
    "json_path",
    "markdown_path",
)


def index_identity(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("generated_at") or ""),
        str(record.get("json_path") or ""),
        str(record.get("markdown_path") or ""),
    )


def _normalized_index_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "human_reward"}


def _normalized_key(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def is_reward_overlay_bundle(records: list[dict[str, Any]]) -> bool:
    """Return true when compact reward rows are projections of one base run."""

    base_rows = [
        record for record in records if not isinstance(record.get("human_reward"), dict)
    ]
    reward_rows = [
        record for record in records if isinstance(record.get("human_reward"), dict)
    ]
    if len(base_rows) != 1 or not reward_rows:
        return False

    base = base_rows[0]
    for overlay in reward_rows:
        projected = _normalized_index_record(overlay)
        if not all(key in projected for key in REWARD_OVERLAY_IDENTITY_KEYS):
            return False
        if any(
            key not in base or base[key] != value for key, value in projected.items()
        ):
            return False
    return True


def classify_index_duplicate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_keys = {
        _normalized_key(_normalized_index_record(record)) for record in records
    }
    reward_records = sum(
        1 for record in records if isinstance(record.get("human_reward"), dict)
    )
    if is_reward_overlay_bundle(records):
        return {
            "duplicate_kind": "reward_overlay",
            "severity": "info",
            "repair_hint": "no index repair needed; reward overlay rows merge into the base run",
            "action": "preserve_reward_overlay",
            "repairable": False,
            "reason": "reward overlay rows are intentionally merged by status checks",
        }

    if not reward_records and len(normalized_keys) == 1:
        return {
            "duplicate_kind": "plain_duplicate",
            "severity": "warning",
            "repair_hint": "append-only ledger repair can archive or supersede the extra identical index row",
            "action": "drop_plain_duplicate_rows",
            "repairable": True,
            "reason": "duplicate rows are byte-equivalent after reward fields are ignored",
        }

    return {
        "duplicate_kind": "artifact_identity_collision",
        "severity": "warning",
        "repair_hint": (
            "do not delete blindly; inspect artifacts and append an explicit repair/supersede event "
            "or rebuild a reviewed index copy"
        ),
        "action": "blocked_artifact_identity_collision",
        "repairable": False,
        "reason": "artifact identity collision is not auto-repairable without reviewed merge semantics",
    }


def duplicate_repair_decision(
    records: list[tuple[int, dict[str, Any]]],
) -> dict[str, Any]:
    line_numbers = [line_number for line_number, _ in records]
    payload = classify_index_duplicate_records([record for _, record in records])
    action = payload.get("action")
    kept_line_numbers = line_numbers
    removed_line_numbers: list[int] = []
    if action == "drop_plain_duplicate_rows":
        kept_line_numbers = [line_numbers[0]]
        removed_line_numbers = line_numbers[1:]
    return {
        "action": action,
        "repairable": payload.get("repairable"),
        "line_numbers": line_numbers,
        "kept_line_numbers": kept_line_numbers,
        "removed_line_numbers": removed_line_numbers,
        "reason": payload.get("reason"),
    }
