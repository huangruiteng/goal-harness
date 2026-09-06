"""Pure projection rules shared by the local authority shadow capture and parity.

Everything here is a deterministic function of its inputs: no file, lock,
registry, or effect-runtime access. The same complete record contracts and canonical
bytes define the source digest, the outbox partition digest, and the candidate
readback comparison, so no two code paths can disagree about what "the same
coordination state" means.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from ..todos.todo_summary import canonical_todo_read_record
from .coordination_state_contract import TODO_CANONICAL_READ_RECORD_FIELDS
from .coordination_state_contract_generated import LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA


LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V0 = LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA
TODO_PARTITION = "todos"
LEASE_PARTITION = "leases"
PARTITIONS: tuple[str, ...] = (TODO_PARTITION, LEASE_PARTITION)

TODO_FIELDS: tuple[str, ...] = TODO_CANONICAL_READ_RECORD_FIELDS


class ProjectionValueError(ValueError):
    """A value cannot be part of a canonical shadow projection."""


def _reject_floats(value: object, path: str) -> None:
    # Python `1.0` and JavaScript `1` would canonicalize differently, so a
    # float anywhere in a compared projection would manufacture a false
    # divergence between the Python source digest and the TypeScript head.
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        raise ProjectionValueError(f"float values are not allowed in shadow projections ({path})")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProjectionValueError(f"non-string key in shadow projection ({path})")
            _reject_floats(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")
        return
    raise ProjectionValueError(
        f"unsupported value type {type(value).__name__} in shadow projection ({path})"
    )


def canonical_bytes(value: object) -> bytes:
    """Sorted-key, minimal-separator UTF-8 JSON; floats and NaN are rejected."""

    _reject_floats(value, "$")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_value(value: object) -> Any:
    """Round-trip a value through canonical JSON so key order is normalized."""

    return json.loads(canonical_bytes(value))


def sha256_digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def compact_todo(raw: object) -> dict[str, Any] | None:
    """Retain the complete versioned Todo consumer record."""

    if not isinstance(raw, Mapping):
        return None
    todo_id = str(raw.get("todo_id") or "").strip()
    if not todo_id:
        return None
    try:
        return dict(
            canonical_value(
                canonical_todo_read_record(dict(raw), reject_unknown=True)
            )
        )
    except ValueError as error:
        raise ProjectionValueError(str(error)) from error


def compact_lease(raw: object, *, goal_id: str, file_stem: str) -> dict[str, Any]:
    """Retain the complete versioned lease record after binding its identity."""

    if not isinstance(raw, Mapping):
        raise ProjectionValueError("task lease must contain an object")
    if raw.get("goal_id") != goal_id or raw.get("todo_id") != file_stem:
        raise ProjectionValueError("task lease identity does not match its shadow source")
    return dict(canonical_value(dict(raw)))


def todo_partition_projection(
    *,
    handoff_mode: str,
    todos: Iterable[object],
) -> dict[str, Any]:
    """The state guarded by the goal's active-state file lock."""

    compact = [item for item in (compact_todo(raw) for raw in todos) if item is not None]
    compact.sort(key=lambda item: str(item["todo_id"]))
    return {"handoff_mode": handoff_mode, "todos": compact}


def lease_partition_projection(
    records: Iterable[tuple[str, object]],
    *,
    goal_id: str,
) -> dict[str, Any]:
    """The state guarded by the goal's task-lease lock.

    ``records`` pairs each lease file stem with its decoded JSON object.
    """

    leases = [
        compact_lease(raw, goal_id=goal_id, file_stem=stem)
        for stem, raw in sorted(records, key=lambda pair: pair[0])
    ]
    return {"leases": leases}


def partition_digest(projection: Mapping[str, Any]) -> str:
    return sha256_digest(dict(projection))


def head_comparison_view(head: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a candidate head that parity compares against the source."""

    return {
        "handoff_mode": head.get("handoff_mode"),
        "todos": head.get("todos"),
        "leases": head.get("leases"),
    }


def head_digest(head: Mapping[str, Any]) -> str:
    return sha256_digest(head_comparison_view(head))


__all__ = [
    "LEASE_PARTITION",
    "LOCAL_AUTHORITY_SHADOW_PROJECTION_SCHEMA_V0",
    "PARTITIONS",
    "TODO_FIELDS",
    "TODO_PARTITION",
    "ProjectionValueError",
    "canonical_bytes",
    "canonical_value",
    "compact_lease",
    "compact_todo",
    "head_comparison_view",
    "head_digest",
    "lease_partition_projection",
    "partition_digest",
    "sha256_digest",
    "text_digest",
    "todo_partition_projection",
]
