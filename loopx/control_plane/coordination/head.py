"""The ``loopx_coordination_head_v0`` aggregate for the shared-goal RFC.

One goal's coordination facts, its replayable receipt index, and the
``retain_all_v0`` retention declaration form one document; a coordination
provider stores it behind an opaque generation CAS and never interprets it.
This module owns the document's shape: fail-closed validation, deterministic
canonical bytes, the adapters that project aggregate facts into the Stage 1
core's snapshot types, and the explicit bootstrap constructors (RFC section 8).

It performs no I/O and makes no domain decisions: transitions belong to
``authority_core.decide`` and the execution layer in ``executor``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, cast

from ..todos.contract import normalize_todo_claimed_by, normalize_todo_id
from ..todos.handoff_mode import goal_handoff_mode
from .authority_core import (
    CoordinationSnapshot,
    HandoffMode,
    LeaseSnapshot,
    TodoSnapshot,
)

HEAD_SCHEMA_VERSION = "loopx_coordination_head_v0"
RECEIPT_SCHEMA_VERSION = "loopx_authority_receipt_v0"
RETAIN_ALL = {"mode": "retain_all_v0"}

_HEAD_FIELDS = {
    "schema_version",
    "goal_id",
    "handoff_mode",
    "authority_revision",
    "coordination",
    "receipt_index",
    "receipt_retention",
}
_TODO_FIELDS = {
    "todo_revision",
    "status",
    "claimed_by",
    "eligibility",
    "repository",
    "code_revision",
    "last_lease_epoch",
}
_ELIGIBILITY_FIELDS = {
    "authorization_projection_revision",
    "authorization_projection_digest",
    "allowed_agent_ids",
    "dependencies_satisfied",
    "dependency_revision",
    "gates_open",
    "gate_revision",
}
_ELIGIBILITY_REVISION_FIELDS = (
    "authorization_projection_revision",
    "dependency_revision",
    "gate_revision",
)
_LEASE_FIELDS = {"lease_id", "owner", "lease_epoch", "expires_at", "write_scopes"}
_REPOSITORY_PATTERN = re.compile(r"git:[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+")
_CODE_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")


class HeadValidationError(ValueError):
    """The aggregate document violates the reviewed v0 contract."""


def canonical_head_bytes(head: dict[str, Any]) -> bytes:
    """Deterministic canonical serialization of one head document.

    This is the one canonical encoding (sorted keys, minimal separators,
    UTF-8 without ASCII escapes) that digests and byte-level provider parity
    are defined against. Values with no faithful strict-JSON form fail closed
    here: non-finite floats would serialize into bytes a strict RFC 8259
    reader rejects, so they must never become "canonical" bytes.
    """

    try:
        return json.dumps(
            head,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise HeadValidationError(
            f"head is not canonically serializable: {error}"
        ) from None


def head_digest(head: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_head_bytes(head)).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise HeadValidationError(message)


def _is_count(value: Any, *, minimum: int = 0) -> bool:
    # bool is an int subclass; a True epoch would silently mint True+1.
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _validated_todo(todo_id: str, source: Any) -> dict[str, Any]:
    _require(
        isinstance(todo_id, str) and bool(todo_id),
        "head todo ids must be non-empty strings",
    )
    _require(
        isinstance(source, dict) and set(source) == _TODO_FIELDS,
        f"head todo {todo_id!r} fields do not match v0",
    )
    _require(
        _is_count(source["todo_revision"]),
        f"head todo {todo_id!r} todo_revision must be a non-negative integer",
    )
    _require(
        _is_count(source["last_lease_epoch"]),
        f"head todo {todo_id!r} last_lease_epoch must be a non-negative integer",
    )
    repository = source["repository"]
    _require(
        isinstance(repository, str)
        and bool(repository)
        and not repository.startswith("file://")
        and not PurePosixPath(repository).is_absolute()
        and not PureWindowsPath(repository).is_absolute()
        and _REPOSITORY_PATTERN.fullmatch(repository) is not None,
        f"head todo {todo_id!r} repository is not portable",
    )
    code_revision = source["code_revision"]
    _require(
        isinstance(code_revision, str)
        and _CODE_REVISION_PATTERN.fullmatch(code_revision) is not None,
        f"head todo {todo_id!r} code_revision is invalid",
    )
    eligibility = source["eligibility"]
    _require(
        isinstance(eligibility, dict) and set(eligibility) == _ELIGIBILITY_FIELDS,
        f"head todo {todo_id!r} eligibility fields do not match v0",
    )
    for field in _ELIGIBILITY_REVISION_FIELDS:
        _require(
            _is_count(eligibility[field]),
            f"head todo {todo_id!r} eligibility revisions are invalid",
        )
    digest = eligibility["authorization_projection_digest"]
    _require(
        isinstance(digest, str) and digest.startswith("sha256:"),
        f"head todo {todo_id!r} authorization digest is invalid",
    )
    allowed = eligibility["allowed_agent_ids"]
    _require(
        isinstance(allowed, list)
        and all(isinstance(agent, str) and agent for agent in allowed),
        f"head todo {todo_id!r} allowed_agent_ids are invalid",
    )
    _require(
        isinstance(eligibility["dependencies_satisfied"], bool)
        and isinstance(eligibility["gates_open"], bool),
        f"head todo {todo_id!r} eligibility decisions are invalid",
    )
    return cast(dict[str, Any], source)


def validated_head(head: Any, *, goal_id: str) -> dict[str, Any]:
    """Fail closed unless ``head`` is a complete v0 aggregate for ``goal_id``."""

    _require(isinstance(head, dict), "coordination head must be an object")
    _require(set(head) == _HEAD_FIELDS, "coordination head fields do not match v0")
    _require(
        head["schema_version"] == HEAD_SCHEMA_VERSION and head["goal_id"] == goal_id,
        "coordination head identity mismatch",
    )
    _require(
        head["handoff_mode"] == HandoffMode.HARD_LEASE.value,
        "v0 shared authority is defined only for the hard_lease handoff mode",
    )
    _require(
        _is_count(head["authority_revision"]),
        "authority_revision must be a non-negative integer",
    )
    coordination = head["coordination"]
    _require(
        isinstance(coordination, dict) and set(coordination) == {"todos", "leases"},
        "coordination must contain todos and leases",
    )
    _require(
        isinstance(coordination["todos"], dict)
        and isinstance(coordination["leases"], dict),
        "coordination must contain todos and leases objects",
    )
    for todo_id, todo in coordination["todos"].items():
        _validated_todo(todo_id, todo)
    for todo_id, lease in coordination["leases"].items():
        _require(
            todo_id in coordination["todos"],
            f"lease {todo_id!r} has no todo in the head",
        )
        _require(
            isinstance(lease, dict) and set(lease) == _LEASE_FIELDS,
            f"lease {todo_id!r} fields do not match v0",
        )
        _require(
            isinstance(lease["lease_id"], str)
            and bool(lease["lease_id"])
            and isinstance(lease["owner"], str)
            and bool(lease["owner"]),
            f"lease {todo_id!r} identity fields must be non-empty strings",
        )
        _require(
            _is_count(lease["lease_epoch"], minimum=1),
            f"lease {todo_id!r} lease_epoch must be a positive integer",
        )
        _require(
            isinstance(lease["expires_at"], str) and bool(lease["expires_at"]),
            f"lease {todo_id!r} expires_at must be a timestamp string",
        )
        _require(
            lease["write_scopes"] == [],
            f"lease {todo_id!r} write_scopes must be empty in v0",
        )
    _require(isinstance(head["receipt_index"], dict), "receipt_index must be an object")
    _require(head["receipt_retention"] == RETAIN_ALL, "v0 requires retain_all_v0")
    return cast(dict[str, Any], head)


def bootstrap_head(goal_id: str, todos: dict[str, Any]) -> dict[str, Any]:
    """Build the explicit migration head from already-existing open todos."""

    _require(
        isinstance(goal_id, str) and bool(goal_id),
        "bootstrap goal_id must be a non-empty string",
    )
    _require(isinstance(todos, dict), "bootstrap todos must be an object")
    normalized: dict[str, Any] = {}
    for todo_id, source in todos.items():
        todo = _validated_todo(todo_id, source)
        _require(
            todo["status"] == "open" and todo["claimed_by"] is None,
            f"bootstrap todo {todo_id!r} must be open and unclaimed",
        )
        normalized[todo_id] = {
            "todo_revision": todo["todo_revision"],
            "status": "open",
            "claimed_by": None,
            "eligibility": {
                field: copy.deepcopy(todo["eligibility"][field])
                for field in sorted(_ELIGIBILITY_FIELDS)
            },
            "repository": todo["repository"],
            "code_revision": todo["code_revision"],
            "last_lease_epoch": todo["last_lease_epoch"],
        }
    return {
        "schema_version": HEAD_SCHEMA_VERSION,
        "goal_id": goal_id,
        # The shared head owns the mode once a goal migrates (Appendix B);
        # v0 defines shared coordination only for hard_lease, and recording
        # it in the CAS'd document keeps every acceptance auditable against
        # the mode that authorized it.
        "handoff_mode": HandoffMode.HARD_LEASE.value,
        "authority_revision": 0,
        "coordination": {"todos": normalized, "leases": {}},
        "receipt_index": {},
        "receipt_retention": copy.deepcopy(RETAIN_ALL),
    }


def _static_projection_digest(allowed_agent_ids: list[str]) -> str:
    encoded = json.dumps(sorted(allowed_agent_ids), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def bootstrap_head_from_goal_state(
    state_text: str,
    *,
    goal_id: str,
    repository: str,
    code_revision: str,
    allowed_agent_ids: list[str],
    with_report: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Shadow the current Markdown active state into a bootstrap head.

    Reads the goal state through loopx's own projection and admits exactly the
    open, unclaimed agent todos (the only shape v0 bootstrap accepts); claimed
    and done todos are reported, never silently dropped. This is the read side
    of the RFC section 11 shadow; nothing is written back.
    """

    from ..todos.active_state_todo_parser import parse_active_state_todos

    source_mode = goal_handoff_mode(state_text)
    _require(
        source_mode != HandoffMode.SOFT_CLAIM.value,
        "a soft_claim goal cannot bootstrap into shared authority: its"
        " declared mode rejects lease minting, which shared claim_work"
        " performs on every accepted claim",
    )
    projected = parse_active_state_todos(state_text)
    skipped: dict[str, str] = {}
    todos: dict[str, Any] = {}
    for item in projected["agent_todos"]["items"]:
        todo_id = normalize_todo_id(item.get("todo_id"))
        if not todo_id:
            continue
        if item.get("done"):
            skipped[todo_id] = "done"
            continue
        if normalize_todo_claimed_by(item.get("claimed_by")):
            skipped[todo_id] = "claimed"
            continue
        todos[todo_id] = {
            "todo_revision": 0,
            "status": "open",
            "claimed_by": None,
            "eligibility": {
                "authorization_projection_revision": 0,
                "authorization_projection_digest": _static_projection_digest(
                    allowed_agent_ids
                ),
                "allowed_agent_ids": list(allowed_agent_ids),
                "dependencies_satisfied": True,
                "dependency_revision": 0,
                "gates_open": True,
                "gate_revision": 0,
            },
            "repository": repository,
            "code_revision": code_revision,
            "last_lease_epoch": 0,
        }
    head = bootstrap_head(goal_id, todos)
    if not with_report:
        return head
    report = {
        "skipped": skipped,
        "source_handoff_mode": source_mode,
        "admitted": sorted(todos),
    }
    return head, report


def claim_snapshot_for_todo(
    head: dict[str, Any],
    todo_id: str,
    *,
    lease_active: bool = False,
) -> CoordinationSnapshot:
    """Project one todo's aggregate facts into the Stage 1 core snapshot.

    The aggregate's ``allowed_agent_ids`` play the registered-agent role for
    the core's actor and owner checks; dependency/gate booleans and every
    revision stay execution-layer preconditions because the core owns neither
    (Stage 1 boundary). ``handoff_mode`` comes from the head itself, where it
    is revision-covered by the aggregate CAS; v0 validation pins it to
    hard_lease, under which a claim and its lease travel together and the
    core's holder gate is a real invariant, not a vacuous branch. When the
    todo carries no lease the snapshot holds a non-present tombstone at the
    todo's ``last_lease_epoch`` so the core mints the next epoch monotonically
    (no-ABA); ``lease_active`` is the executor's clock decision, never
    computed here.
    """

    todo = head["coordination"]["todos"].get(todo_id)
    _require(todo is not None, f"head has no todo {todo_id!r}")
    lease = head["coordination"]["leases"].get(todo_id)
    if lease is not None:
        lease_snapshot = LeaseSnapshot(
            present=True,
            active=lease_active,
            status="active" if lease_active else "expired",
            owner=lease["owner"],
            idempotency_key=lease["lease_id"],
            version=lease["lease_epoch"],
            lease_epoch=lease["lease_epoch"],
            write_scopes=tuple(lease["write_scopes"]),
        )
    else:
        lease_snapshot = LeaseSnapshot(
            present=False,
            active=False,
            version=todo["last_lease_epoch"],
            lease_epoch=todo["last_lease_epoch"],
        )
    return CoordinationSnapshot(
        handoff_mode=HandoffMode(head["handoff_mode"]),
        registered_agents=tuple(todo["eligibility"]["allowed_agent_ids"]),
        todo=TodoSnapshot(
            todo_id=todo_id,
            status=todo["status"],
            role="agent",
            claimed_by=todo["claimed_by"],
        ),
        lease=lease_snapshot,
    )
