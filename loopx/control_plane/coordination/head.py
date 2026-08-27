"""The ``loopx_coordination_head_v1`` aggregate for the shared-goal RFC.

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
from datetime import datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, cast

from .authority_core import (
    CoordinationSnapshot,
    HandoffMode,
    LeaseSnapshot,
    TodoSnapshot,
)

HEAD_SCHEMA_VERSION = "loopx_coordination_head_v1"
# v0 predates the store-lineage binding: it is recognized, never read as
# current, and upgraded only through migrate_head_v0_to_v1.
LEGACY_HEAD_SCHEMA_V0 = "loopx_coordination_head_v0"
RECEIPT_SCHEMA_VERSION = "loopx_authority_receipt_v0"
RETAIN_ALL = {"mode": "retain_all_v0"}

_HEAD_FIELDS = {
    "schema_version",
    "goal_id",
    "handoff_mode",
    "authority_revision",
    "store_binding",
    "coordination",
    "receipt_index",
    "receipt_retention",
}
_LEGACY_HEAD_V0_FIELDS = _HEAD_FIELDS - {"store_binding"}
_TODO_FIELDS = {
    "todo_revision",
    "status",
    "claimed_by",
    "eligibility",
    "repository",
    "code_revision",
    "last_lease_epoch",
}
_TODO_STATUS_VALUES = {"open", "done"}
_COMPLETION_FIELDS = {
    "completion_continuation",
    "no_followup",
    "successor_todo_ids",
    "evidence",
}
_CONTINUATION_VALUES = {"active_goal", "successor", "no_followup"}
_EVIDENCE_FIELDS = {"pointer", "digest", "privacy_class"}
_EVIDENCE_PRIVACY_CLASSES = {"public", "private"}
# One provider-neutral URI shape binds privacy into the pointer itself. A
# sibling privacy_class can therefore be checked rather than merely trusted,
# while the opaque id remains portable across artifact providers.
_EVIDENCE_POINTER_PATTERN = re.compile(
    r"artifact://(?P<privacy_class>public|private)/"
    r"(?P<artifact_id>[A-Za-z0-9][A-Za-z0-9._~/-]{0,511})"
)
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
_RECEIPT_ENTRY_FIELDS = {"request_digest", "original_receipt"}
_RECEIPT_BASE_FIELDS = {
    "schema_version",
    "operation_id",
    "request_digest",
    "command",
    "actor",
    "todo_id",
    "accepted_authority_revision",
    "accepted_todo_revision",
    "applied_at",
}
# Each verb persists exactly the authority proof it minted: lease verbs carry
# the fence they issued, reclaim additionally records whom it superseded, and
# completion records the continuation it accepted.
_RECEIPT_COMMAND_FIELDS = {
    "claim_work": _RECEIPT_BASE_FIELDS | {"lease_id", "lease_epoch", "expires_at"},
    "renew_work": _RECEIPT_BASE_FIELDS | {"lease_id", "lease_epoch", "expires_at"},
    "release_work": _RECEIPT_BASE_FIELDS | {"lease_id", "lease_epoch"},
    "reclaim_work": _RECEIPT_BASE_FIELDS
    | {
        "lease_id",
        "lease_epoch",
        "expires_at",
        "superseded_owner",
        "superseded_lease_epoch",
    },
    "complete_work": _RECEIPT_BASE_FIELDS
    | {"lease_id", "lease_epoch", "completion_continuation"},
}
_RECEIPT_ACTOR_FIELDS = {"agent_id", "device_id"}
_REPOSITORY_PATTERN = re.compile(r"git:[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+")
_CODE_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{7,64}")
_REQUEST_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class HeadValidationError(ValueError):
    """The aggregate document violates the reviewed contract."""


class HeadMigrationRequired(HeadValidationError):
    """A legacy v0 head was read: it lacks the store-lineage binding.

    This is a classification, not corruption: the head is a valid Stage 2
    document that must pass through the explicit, operator-reviewed
    ``migrate_head_v0_to_v1`` before any command applies. The binding is
    never inferred automatically - a restored copy of the store would then
    authorize itself, which is exactly what the binding fence exists to
    prevent (RFC section 6.4).
    """


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


def evidence_contract_violation(evidence: Any) -> str | None:
    """Why ``evidence`` violates the portable contract, or ``None``.

    The pointer must use the provider-neutral
    ``artifact://<privacy>/<opaque-id>`` shape: never a host filesystem
    location, provider URL, query, or credential-bearing URI. Its privacy
    namespace must match the sibling closed enum. One validator serves both
    the command boundary and head validation so the two can never drift.
    """

    if not isinstance(evidence, dict) or set(evidence) != _EVIDENCE_FIELDS:
        return "evidence fields do not match the portable contract"
    pointer = evidence["pointer"]
    pointer_match = (
        _EVIDENCE_POINTER_PATTERN.fullmatch(pointer)
        if isinstance(pointer, str)
        else None
    )
    if pointer_match is None:
        return (
            "evidence pointer must use "
            "artifact://<public|private>/<opaque-artifact-id>"
        )
    artifact_id = pointer_match.group("artifact_id")
    if any(part in {"", ".", ".."} for part in artifact_id.split("/")):
        return "evidence artifact id must not contain empty or traversal segments"
    if not isinstance(evidence["digest"], str) or not _is_request_digest(
        evidence["digest"]
    ):
        return "evidence digest must be a sha256 content digest"
    privacy_class = evidence["privacy_class"]
    if (
        not isinstance(privacy_class, str)
        or privacy_class not in _EVIDENCE_PRIVACY_CLASSES
    ):
        return "evidence privacy_class must be one of " + "|".join(
            sorted(_EVIDENCE_PRIVACY_CLASSES)
        )
    if pointer_match.group("privacy_class") != privacy_class:
        return "evidence pointer privacy namespace does not match privacy_class"
    return None


def _validated_legacy_head_v0(head: dict[str, Any], *, goal_id: str) -> None:
    """Prove a document is valid Stage 2 v0 before classifying migration.

    A schema token alone is not migration evidence. Project the exact v0
    field set into a validation-only v1 copy and reuse the complete validator
    for every shared field. No binding is inferred or returned.
    """

    _require(
        set(head) == _LEGACY_HEAD_V0_FIELDS,
        "legacy coordination head fields do not match v0",
    )
    _require(
        head.get("schema_version") == LEGACY_HEAD_SCHEMA_V0
        and head.get("goal_id") == goal_id,
        "legacy coordination head identity mismatch",
    )
    coordination = head.get("coordination")
    if not isinstance(coordination, dict):
        raise HeadValidationError("legacy coordination head todos are invalid")
    todos = coordination.get("todos")
    if not isinstance(todos, dict):
        raise HeadValidationError("legacy coordination head todos are invalid")
    for todo_id, todo in todos.items():
        _require(
            isinstance(todo, dict) and set(todo) == _TODO_FIELDS,
            f"legacy head todo {todo_id!r} fields do not match v0",
        )
        # Stage 2 bootstrap and its only command, claim_work, emitted open
        # records. The old validator forgot to close the status vocabulary;
        # migration must not grant v1 authority to an untyped legacy value.
        _require(
            todo.get("status") == "open",
            f"legacy head todo {todo_id!r} status is not safely migratable",
        )
    receipt_index = head.get("receipt_index")
    if not isinstance(receipt_index, dict):
        raise HeadValidationError(
            "legacy coordination head receipt_index is invalid"
        )
    for operation_id, entry in receipt_index.items():
        receipt = entry.get("original_receipt") if isinstance(entry, dict) else None
        _require(
            isinstance(receipt, dict)
            and receipt.get("command") == "claim_work"
            and set(receipt) == _RECEIPT_COMMAND_FIELDS["claim_work"],
            f"legacy receipt {operation_id!r} is outside the Stage 2 slice",
        )
    validation_copy = copy.deepcopy(head)
    validation_copy["schema_version"] = HEAD_SCHEMA_VERSION
    validation_copy["store_binding"] = "validation-only:legacy-v0"
    validated_head(validation_copy, goal_id=goal_id)
    _validated_legacy_claim_history(validation_copy)


def _is_count(value: Any, *, minimum: int = 0) -> bool:
    # bool is an int subclass; a True epoch would silently mint True+1.
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _is_timestamp(value: Any) -> bool:
    # The executor parses these fields unconditionally (expiry decisions,
    # authorization status); an unparseable persisted timestamp must fail
    # closed here instead of escaping as a bare ValueError later. The value
    # must also be timezone-aware UTC: a naive timestamp is interpreted in
    # the executing host's local timezone, so the same persisted bytes would
    # read as active on one endpoint and expired on another, and v0 mints
    # UTC only, so UTC is also what it accepts.
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _is_request_digest(value: Any) -> bool:
    return isinstance(value, str) and _REQUEST_DIGEST_PATTERN.fullmatch(value) is not None


def _validated_todo(todo_id: str, source: Any) -> dict[str, Any]:
    _require(
        isinstance(todo_id, str) and bool(todo_id),
        "head todo ids must be non-empty strings",
    )
    _require(isinstance(source, dict), f"head todo {todo_id!r} must be an object")
    status = source.get("status")
    _require(
        status in _TODO_STATUS_VALUES,
        f"head todo {todo_id!r} status must be one of {sorted(_TODO_STATUS_VALUES)}",
    )
    if status == "done":
        _require(
            _TODO_FIELDS <= set(source)
            and set(source) <= (_TODO_FIELDS | _COMPLETION_FIELDS)
            and "completion_continuation" in source,
            f"head todo {todo_id!r} fields do not match v0",
        )
    else:
        _require(
            set(source) == _TODO_FIELDS,
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
    if status == "done":
        _validated_completion(todo_id, source)
    return cast(dict[str, Any], source)


def _validated_completion(todo_id: str, source: dict[str, Any]) -> None:
    """Durably-done records must satisfy the same fail-closed continuation
    rules as the local durable-completion projection seam: an explicit
    continuation always, never both no_followup and successors, and the
    continuation must match the recorded fields."""

    continuation = source["completion_continuation"]
    _require(
        continuation in _CONTINUATION_VALUES,
        f"head todo {todo_id!r} completion_continuation is invalid",
    )
    no_followup = source.get("no_followup")
    successors = source.get("successor_todo_ids")
    _require(
        no_followup is None or no_followup is True,
        f"head todo {todo_id!r} no_followup must be true when present",
    )
    _require(
        not (no_followup and successors),
        f"head todo {todo_id!r} records both no_followup and successor_todo_ids",
    )
    if successors is not None:
        _require(
            isinstance(successors, list)
            and bool(successors)
            and len(set(successors)) == len(successors)
            and all(isinstance(item, str) and item for item in successors),
            f"head todo {todo_id!r} successor_todo_ids are invalid",
        )
    expected = (
        "no_followup"
        if no_followup
        else ("successor" if successors else "active_goal")
    )
    _require(
        continuation == expected,
        f"head todo {todo_id!r} completion_continuation contradicts its fields",
    )
    evidence = source.get("evidence")
    if evidence is not None:
        violation = evidence_contract_violation(evidence)
        _require(violation is None, f"head todo {todo_id!r}: {violation}")


def _validated_receipt_entry(
    operation_id: Any,
    entry: Any,
    todos: dict[str, Any],
) -> None:
    """Fail closed unless one receipt-index entry is a complete v0 record.

    The executor dereferences these fields unconditionally on the replay and
    success paths, so this is part of the trust boundary persisted state must
    cross before any of it is consumed.
    """

    _require(
        isinstance(operation_id, str) and bool(operation_id),
        "receipt index keys must be non-empty operation ids",
    )
    _require(
        isinstance(entry, dict) and set(entry) == _RECEIPT_ENTRY_FIELDS,
        f"receipt entry {operation_id!r} fields do not match v0",
    )
    _require(
        _is_request_digest(entry["request_digest"]),
        f"receipt entry {operation_id!r} request_digest is invalid",
    )
    receipt = entry["original_receipt"]
    _require(isinstance(receipt, dict), f"receipt {operation_id!r} must be an object")
    command = receipt.get("command")
    _require(
        command in _RECEIPT_COMMAND_FIELDS,
        f"receipt {operation_id!r} command is outside the v0 slice",
    )
    _require(
        set(receipt) == _RECEIPT_COMMAND_FIELDS[command],
        f"receipt {operation_id!r} fields do not match v0",
    )
    _require(
        receipt["schema_version"] == RECEIPT_SCHEMA_VERSION,
        f"receipt {operation_id!r} schema_version is invalid",
    )
    _require(
        receipt["operation_id"] == operation_id,
        f"receipt {operation_id!r} does not record its own operation id",
    )
    _require(
        receipt["request_digest"] == entry["request_digest"],
        f"receipt {operation_id!r} digest disagrees with its index entry",
    )

    actor = receipt["actor"]
    _require(
        isinstance(actor, dict)
        and set(actor) == _RECEIPT_ACTOR_FIELDS
        and all(isinstance(actor[key], str) and actor[key] for key in _RECEIPT_ACTOR_FIELDS),
        f"receipt {operation_id!r} actor identity is invalid",
    )
    _require(
        isinstance(receipt["todo_id"], str) and receipt["todo_id"] in todos,
        f"receipt {operation_id!r} names a todo the head does not carry",
    )
    _require(
        _is_count(receipt["accepted_authority_revision"], minimum=1)
        and _is_count(receipt["accepted_todo_revision"], minimum=1),
        f"receipt {operation_id!r} accepted revisions are invalid",
    )
    _require(
        isinstance(receipt["lease_id"], str) and bool(receipt["lease_id"]),
        f"receipt {operation_id!r} lease_id is invalid",
    )
    _require(
        _is_count(receipt["lease_epoch"], minimum=1),
        f"receipt {operation_id!r} lease_epoch must be a positive integer",
    )
    _require(
        _is_timestamp(receipt["applied_at"]),
        f"receipt {operation_id!r} timestamps are invalid",
    )
    if "expires_at" in receipt:
        _require(
            _is_timestamp(receipt["expires_at"]),
            f"receipt {operation_id!r} timestamps are invalid",
        )
    if "superseded_owner" in receipt:
        _require(
            isinstance(receipt["superseded_owner"], str)
            and bool(receipt["superseded_owner"])
            and _is_count(receipt["superseded_lease_epoch"], minimum=1),
            f"receipt {operation_id!r} superseded lease facts are invalid",
        )
    if "completion_continuation" in receipt:
        _require(
            receipt["completion_continuation"] in _CONTINUATION_VALUES,
            f"receipt {operation_id!r} completion_continuation is invalid",
        )


def _validated_claim_lease_relationships(
    todos: dict[str, Any],
    leases: dict[str, Any],
) -> None:
    """Bind every open claim to the one live lease that authorizes it."""

    for todo_id, todo in todos.items():
        if todo["status"] != "open":
            # Completion deliberately retains claimed_by as attribution while
            # retiring the lease. The done/lease exclusion is checked above.
            continue
        lease = leases.get(todo_id)
        claimed_by = todo["claimed_by"]
        if claimed_by is None:
            _require(
                lease is None,
                f"unclaimed todo {todo_id!r} cannot carry an active lease",
            )
            continue
        if not isinstance(lease, dict):
            raise HeadValidationError(
                f"claimed todo {todo_id!r} must carry an active lease"
            )
        _require(
            lease["owner"] == claimed_by,
            f"lease {todo_id!r} owner does not match claimed_by",
        )
        _require(
            lease["lease_epoch"] == todo["last_lease_epoch"],
            f"lease {todo_id!r} lease_epoch does not match the todo watermark",
        )


def _validated_legacy_claim_history(head: dict[str, Any]) -> None:
    """Prove that a v0 live claim is exactly the Stage 2 writer's output.

    Stage 2 could only bootstrap and apply ``claim_work``. With retain-all
    receipts, a claimed todo therefore has exactly one live claim receipt and
    no authority revision can be missing. This check prevents migration from
    granting v1 authority to a partially edited or provider-corrupted v0 head.
    """

    coordination = cast(dict[str, Any], head["coordination"])
    todos = cast(dict[str, Any], coordination["todos"])
    leases = cast(dict[str, Any], coordination["leases"])
    receipt_index = cast(dict[str, Any], head["receipt_index"])
    receipts = [
        cast(dict[str, Any], entry["original_receipt"])
        for entry in receipt_index.values()
    ]
    accepted_revisions = sorted(
        receipt["accepted_authority_revision"] for receipt in receipts
    )
    _require(
        accepted_revisions == list(range(1, head["authority_revision"] + 1)),
        "legacy authority receipt sequence does not reconstruct the head",
    )

    claimed_todo_ids = {
        todo_id for todo_id, todo in todos.items() if todo["claimed_by"] is not None
    }
    receipt_todo_ids = [receipt["todo_id"] for receipt in receipts]
    _require(
        len(receipt_todo_ids) == len(set(receipt_todo_ids))
        and set(receipt_todo_ids) == claimed_todo_ids,
        "legacy claim receipts do not match the live claimed todos",
    )
    for receipt in receipts:
        todo_id = receipt["todo_id"]
        todo = cast(dict[str, Any], todos[todo_id])
        lease = cast(dict[str, Any], leases[todo_id])
        _require(
            receipt["actor"]["agent_id"]
            == todo["claimed_by"]
            == lease["owner"]
            and receipt["accepted_todo_revision"] == todo["todo_revision"]
            and receipt["lease_id"] == lease["lease_id"]
            and receipt["lease_epoch"]
            == todo["last_lease_epoch"]
            == lease["lease_epoch"]
            and receipt["expires_at"] == lease["expires_at"],
            f"legacy claim receipt for {todo_id!r} does not prove the live claim",
        )


def validated_head(head: Any, *, goal_id: str) -> dict[str, Any]:
    """Fail closed unless ``head`` is a complete v1 aggregate for ``goal_id``."""

    _require(isinstance(head, dict), "coordination head must be an object")
    if head.get("schema_version") == LEGACY_HEAD_SCHEMA_V0:
        # Only a complete Stage 2 document receives the migration class;
        # malformed input remains an ordinary validation failure.
        _validated_legacy_head_v0(head, goal_id=goal_id)
        raise HeadMigrationRequired(
            "coordination head is a legacy loopx_coordination_head_v0 "
            "document: an explicit store-binding migration is required"
        )
    _require(set(head) == _HEAD_FIELDS, "coordination head fields do not match v1")
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
    _require(
        isinstance(head["store_binding"], str) and bool(head["store_binding"]),
        "store_binding must be the provider-issued store identity",
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
    for todo_id, todo in coordination["todos"].items():
        for successor in todo.get("successor_todo_ids") or ():
            _require(
                successor in coordination["todos"],
                f"head todo {todo_id!r} declares missing successor {successor!r}",
            )
    for todo_id, lease in coordination["leases"].items():
        _require(
            todo_id in coordination["todos"],
            f"lease {todo_id!r} has no todo in the head",
        )
        _require(
            coordination["todos"][todo_id]["status"] == "open",
            f"lease {todo_id!r} attached to a durably done todo",
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
            _is_timestamp(lease["expires_at"]),
            f"lease {todo_id!r} expires_at must be a parseable timestamp",
        )
        _require(
            lease["write_scopes"] == [],
            f"lease {todo_id!r} write_scopes must be empty in v0",
        )
    _validated_claim_lease_relationships(
        coordination["todos"],
        coordination["leases"],
    )
    _require(isinstance(head["receipt_index"], dict), "receipt_index must be an object")
    for operation_id, entry in head["receipt_index"].items():
        _validated_receipt_entry(operation_id, entry, coordination["todos"])
    _require(head["receipt_retention"] == RETAIN_ALL, "v0 requires retain_all_v0")
    return cast(dict[str, Any], head)


def bootstrap_head(
    goal_id: str,
    todos: dict[str, Any],
    *,
    store_binding: str,
) -> dict[str, Any]:
    """Build the explicit migration head from already-existing open todos.

    ``store_binding`` is the provider-issued store identity
    (``provider.store_identity()``): the head is permanently bound to the
    store lineage it was bootstrapped into, so a restore into a different
    lineage is detectable before any write (the Stage 3 binding fence).
    """

    _require(
        isinstance(goal_id, str) and bool(goal_id),
        "bootstrap goal_id must be a non-empty string",
    )
    _require(
        isinstance(store_binding, str) and bool(store_binding),
        "bootstrap store_binding must be the provider-issued store identity",
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
        "store_binding": store_binding,
        "coordination": {"todos": normalized, "leases": {}},
        "receipt_index": {},
        "receipt_retention": copy.deepcopy(RETAIN_ALL),
    }


def migrate_head_v0_to_v1(
    head: Any,
    *,
    goal_id: str,
    store_binding: str,
) -> dict[str, Any]:
    """Explicitly upgrade a legacy v0 head by attesting its store lineage.

    ``store_binding`` is an operator attestation that the store this head
    lives in IS its authoritative lineage - typically the operator calls
    ``provider.store_identity()`` on the store they have reviewed and passes
    the result here, then writes the migrated head back through the same
    provider CAS. The binding is deliberately a required argument and never
    read from the loading provider: an automatic binding would let any
    restored copy of a v0 store authorize itself as the live lineage, which
    is the exact capture the binding fence exists to prevent.
    """

    _require(isinstance(head, dict), "coordination head must be an object")
    _validated_legacy_head_v0(head, goal_id=goal_id)
    migrated = copy.deepcopy(head)
    migrated["schema_version"] = HEAD_SCHEMA_VERSION
    migrated["store_binding"] = store_binding
    # Full v1 validation guards the rest of the document (including the
    # binding shape); migration adds authority to nothing else.
    return validated_head(migrated, goal_id=goal_id)


def claim_snapshot_for_todo(
    head: dict[str, Any],
    todo_id: str,
    *,
    lease_active: bool = False,
    lifecycle_grants: tuple[Any, ...] = (),
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
        lifecycle_grants=lifecycle_grants,
    )
