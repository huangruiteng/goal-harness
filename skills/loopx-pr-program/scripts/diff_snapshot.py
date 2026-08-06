#!/usr/bin/env python3
"""Compare provider-neutral LoopX PR-program snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SNAPSHOT_SCHEMA = "loopx_pr_program_snapshot_v0"
DELTA_SCHEMA = "loopx_pr_program_delta_v0"
MATERIAL_FIELDS = (
    "title",
    "state",
    "draft",
    "target_branch",
    "head_sha",
    "checks",
    "review",
    "work_item",
    "theme",
    "priority",
    "requirement_ids",
    "depends_on",
    "supersedes",
    "description_digest",
    "review_digest",
)
REQUIREMENT_FIELDS = ("title", "priority", "coverage")
SCOPE_FIELDS = ("repositories", "states", "authors", "time_window")


def _normalized_scope_value(value: Any, *, path: str) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_scope_value(item, path=f"{path}.{key}")
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        normalized = [
            _normalized_scope_value(item, path=f"{path}[]") for item in value
        ]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{path} must not contain an empty string")
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"{path} contains an unsupported value")


def _scope_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    completeness = payload.get("result_completeness")
    if not isinstance(completeness, Mapping):
        raise TypeError("result_completeness must be an object")
    scope = completeness.get("scope")
    if not isinstance(scope, Mapping):
        raise TypeError("result_completeness.scope must be an object")
    missing = [field for field in SCOPE_FIELDS if field not in scope]
    if missing:
        raise ValueError(
            "result_completeness.scope is missing " + ", ".join(missing)
        )
    for field in ("repositories", "states", "authors"):
        if not isinstance(scope.get(field), list):
            raise TypeError(f"result_completeness.scope.{field} must be an array")
    if not scope["repositories"]:
        raise ValueError("result_completeness.scope.repositories must not be empty")
    if not scope["states"]:
        raise ValueError("result_completeness.scope.states must not be empty")
    time_window = scope.get("time_window")
    if not isinstance(time_window, Mapping):
        raise TypeError("result_completeness.scope.time_window must be an object")
    for field in ("since", "until"):
        if field not in time_window:
            raise ValueError(
                f"result_completeness.scope.time_window is missing {field}"
            )
        if time_window[field] is not None and not isinstance(time_window[field], str):
            raise TypeError(
                f"result_completeness.scope.time_window.{field} must be a string or null"
            )
    normalized = _normalized_scope_value(scope, path="result_completeness.scope")
    json.dumps(normalized, allow_nan=False)
    return normalized


def _scope_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _scope_projection(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"snapshot must be an object: {path}")
    if payload.get("schema_version") != SNAPSHOT_SCHEMA:
        raise ValueError(f"unsupported snapshot schema in {path}")
    for field in (
        "program_id",
        "generated_at",
        "result_completeness",
        "requirements",
        "change_requests",
    ):
        if field not in payload:
            raise ValueError(f"snapshot is missing {field}: {path}")
    _scope_projection(payload)
    return payload


def _rows(
    payload: Mapping[str, Any], field: str, key: str
) -> dict[str, dict[str, Any]]:
    raw_rows = payload.get(field)
    if not isinstance(raw_rows, list):
        raise TypeError(f"{field} must be an array")
    result: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            raise TypeError(f"{field}[{index}] must be an object")
        identity = str(row.get(key) or "").strip()
        if not identity:
            raise ValueError(f"{field}[{index}] is missing {key}")
        if identity in result:
            raise ValueError(f"duplicate {field} identity: {identity}")
        result[identity] = row
    return result


def _changed_fields(
    before: Mapping[str, Any], after: Mapping[str, Any], fields: tuple[str, ...]
) -> list[str]:
    return [field for field in fields if before.get(field) != after.get(field)]


def _project(row: Mapping[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: row.get(field) for field in fields}


def _material_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    requirements = _rows(payload, "requirements", "id")
    changes = _rows(payload, "change_requests", "ref")
    return {
        "program_id": payload.get("program_id"),
        "scope": _scope_projection(payload),
        "requirements": {
            key: _project(row, REQUIREMENT_FIELDS)
            for key, row in sorted(requirements.items())
        },
        "change_requests": {
            key: _project(row, MATERIAL_FIELDS) for key, row in sorted(changes.items())
        },
    }


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        _material_projection(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_delta(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> dict[str, Any]:
    current_changes = _rows(current, "change_requests", "ref")
    current_requirements = _rows(current, "requirements", "id")
    previous_changes = (
        _rows(previous, "change_requests", "ref") if previous is not None else {}
    )
    previous_requirements = (
        _rows(previous, "requirements", "id") if previous is not None else {}
    )
    current_scope_fingerprint = _scope_fingerprint(current)
    previous_scope_fingerprint = (
        _scope_fingerprint(previous) if previous is not None else None
    )
    scope_matches_previous = (
        previous_scope_fingerprint is None
        or previous_scope_fingerprint == current_scope_fingerprint
    )
    current_complete = bool(
        isinstance(current.get("result_completeness"), Mapping)
        and current["result_completeness"].get("complete") is True
    )
    complete = current_complete and scope_matches_previous
    baseline_block_reason = (
        None
        if complete
        else "scope_mismatch"
        if not scope_matches_previous
        else "incomplete_result"
    )

    added = sorted(set(current_changes) - set(previous_changes))
    absent = sorted(set(previous_changes) - set(current_changes))
    removed = absent if complete else []
    omitted_previous = [] if complete else absent
    changed: list[dict[str, Any]] = []
    observation_only: list[str] = []
    for ref in sorted(set(previous_changes) & set(current_changes)):
        before = previous_changes[ref]
        after = current_changes[ref]
        fields = _changed_fields(before, after, MATERIAL_FIELDS)
        if fields:
            changed.append(
                {
                    "ref": ref,
                    "changed_fields": fields,
                    "before": _project(before, tuple(fields)),
                    "after": _project(after, tuple(fields)),
                }
            )
        elif before.get("updated_at") != after.get("updated_at"):
            observation_only.append(ref)

    requirement_changes: list[dict[str, Any]] = []
    omitted_previous_requirements: list[str] = []
    for requirement_id in sorted(
        set(previous_requirements) | set(current_requirements)
    ):
        before = previous_requirements.get(requirement_id)
        after = current_requirements.get(requirement_id)
        if before is None:
            requirement_changes.append(
                {
                    "id": requirement_id,
                    "change": "added",
                }
            )
            continue
        if after is None:
            if complete:
                requirement_changes.append(
                    {
                        "id": requirement_id,
                        "change": "removed",
                    }
                )
            else:
                omitted_previous_requirements.append(requirement_id)
            continue
        fields = _changed_fields(before, after, REQUIREMENT_FIELDS)
        if fields:
            requirement_changes.append(
                {
                    "id": requirement_id,
                    "change": "updated",
                    "changed_fields": fields,
                    "before": _project(before, tuple(fields)),
                    "after": _project(after, tuple(fields)),
                }
            )

    material_change = bool(added or removed or changed or requirement_changes)
    observed_result_hash = _digest(current)
    return {
        "schema_version": DELTA_SCHEMA,
        "program_id": current.get("program_id"),
        "generated_at": current.get("generated_at"),
        "baseline": previous is None,
        "baseline_advance_allowed": complete,
        "baseline_block_reason": baseline_block_reason,
        "result_completeness": current.get("result_completeness"),
        "scope_fingerprint": current_scope_fingerprint,
        "previous_scope_fingerprint": previous_scope_fingerprint,
        "scope_matches_previous": scope_matches_previous,
        "result_hash": observed_result_hash if complete else None,
        "observed_result_hash": observed_result_hash,
        "material_change": material_change,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "requirement_changed": len(requirement_changes),
            "observation_only": len(observation_only),
            "omitted_previous": len(omitted_previous),
            "omitted_previous_requirements": len(omitted_previous_requirements),
            "unchanged": len(current_changes)
            - len(added)
            - len(changed)
            - len(observation_only),
        },
        "added": added,
        "removed": removed,
        "changed": changed,
        "requirement_changes": requirement_changes,
        "observation_only": observation_only,
        "omitted_previous": omitted_previous,
        "omitted_previous_requirements": omitted_previous_requirements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare provider-neutral LoopX PR-program snapshots."
    )
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    previous = _load(args.previous) if args.previous else None
    current = _load(args.current)
    if previous and previous.get("program_id") != current.get("program_id"):
        raise ValueError(
            "previous and current snapshots use different program_id values"
        )
    rendered = json.dumps(build_delta(previous, current), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
