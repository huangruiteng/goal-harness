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
    complete = bool(
        isinstance(current.get("result_completeness"), Mapping)
        and current["result_completeness"].get("complete") is True
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
        "result_completeness": current.get("result_completeness"),
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
