"""Claim-only coordination authority proof with a NoKV byte-CAS adapter.

LoopX authority owns domain semantics and receipts.  The provider sees only
deterministic bytes plus an opaque generation.  Coordination state and the
complete receipt index are committed in one CAS; v0 performs no receipt GC.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath
from typing import Callable


HEAD_SCHEMA = "loopx_coordination_head_v0"
COMMAND_SCHEMA = "loopx_command_v0"
RECEIPT_SCHEMA = "loopx_authority_receipt_v0"
RETAIN_ALL = {"mode": "retain_all_v0"}


def _deterministic_bytes(value: dict) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: dict) -> str:
    return "sha256:" + hashlib.sha256(_deterministic_bytes(value)).hexdigest()


def _lease_id(operation_id: str) -> str:
    value = hashlib.sha256(f"lease:{operation_id}".encode()).hexdigest()
    return "lease_" + value[:24]


def _format_time(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def bootstrap_aggregate(goal_id: str, todos: dict) -> dict:
    """Build the explicit migration head from already-existing open todos."""
    todo_fields = {
        "todo_revision",
        "status",
        "claimed_by",
        "eligibility",
        "repository",
        "code_revision",
        "last_lease_epoch",
    }
    eligibility_fields = {
        "authorization_projection_revision",
        "authorization_projection_digest",
        "allowed_agent_ids",
        "dependencies_satisfied",
        "dependency_revision",
        "gates_open",
        "gate_revision",
    }
    if not isinstance(goal_id, str) or not goal_id:
        raise ValueError("bootstrap goal_id must be a non-empty string")
    if not isinstance(todos, dict):
        raise ValueError("bootstrap todos must be an object")
    normalized = {}
    for todo_id, source in todos.items():
        if not isinstance(todo_id, str) or not todo_id:
            raise ValueError("bootstrap todo ids must be non-empty strings")
        if not isinstance(source, dict) or set(source) != todo_fields:
            raise ValueError(f"bootstrap todo {todo_id!r} fields do not match v0")
        if not isinstance(source.get("todo_revision"), int):
            raise ValueError(f"bootstrap todo {todo_id!r} lacks todo_revision")
        if source.get("status") != "open" or source.get("claimed_by") is not None:
            raise ValueError(f"bootstrap todo {todo_id!r} must be open and unclaimed")
        if not isinstance(source.get("last_lease_epoch"), int):
            raise ValueError(f"bootstrap todo {todo_id!r} lacks last_lease_epoch")
        repository = source.get("repository")
        if (
            not isinstance(repository, str)
            or not repository
            or repository.startswith("file://")
            or PurePosixPath(repository).is_absolute()
            or PureWindowsPath(repository).is_absolute()
            or re.fullmatch(
                r"git:[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+",
                repository,
            ) is None
        ):
            raise ValueError(f"bootstrap todo {todo_id!r} repository is not portable")
        code_revision = source.get("code_revision")
        if not isinstance(code_revision, str) or re.fullmatch(
            r"[0-9a-fA-F]{7,64}",
            code_revision,
        ) is None:
            raise ValueError(f"bootstrap todo {todo_id!r} code_revision is invalid")

        eligibility = source.get("eligibility")
        if not isinstance(eligibility, dict) or set(eligibility) != eligibility_fields:
            raise ValueError(f"bootstrap todo {todo_id!r} eligibility fields do not match v0")
        revision_fields = (
            "authorization_projection_revision",
            "dependency_revision",
            "gate_revision",
        )
        if any(
            not isinstance(eligibility[field], int) or eligibility[field] < 0
            for field in revision_fields
        ):
            raise ValueError(f"bootstrap todo {todo_id!r} eligibility revisions are invalid")
        digest = eligibility["authorization_projection_digest"]
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ValueError(f"bootstrap todo {todo_id!r} authorization digest is invalid")
        allowed = eligibility["allowed_agent_ids"]
        if not isinstance(allowed, list) or any(
            not isinstance(agent_id, str) or not agent_id for agent_id in allowed
        ):
            raise ValueError(f"bootstrap todo {todo_id!r} allowed_agent_ids are invalid")
        if not isinstance(eligibility["dependencies_satisfied"], bool) or not isinstance(
            eligibility["gates_open"], bool
        ):
            raise ValueError(f"bootstrap todo {todo_id!r} eligibility decisions are invalid")
        normalized[todo_id] = {
            "todo_revision": source["todo_revision"],
            "status": "open",
            "claimed_by": None,
            "eligibility": {
                field: copy.deepcopy(eligibility[field])
                for field in sorted(eligibility_fields)
            },
            "repository": repository,
            "code_revision": code_revision,
            "last_lease_epoch": source["last_lease_epoch"],
        }
    return {
        "schema_version": HEAD_SCHEMA,
        "goal_id": goal_id,
        "authority_revision": 0,
        "coordination": {"todos": normalized, "leases": {}},
        "receipt_index": {},
        "receipt_retention": copy.deepcopy(RETAIN_ALL),
    }


class ProviderProtocolError(RuntimeError):
    """Persisted bytes or a provider result violated the reviewed contract."""


class NoKVCoordinationProvider:
    """Map one goal's deterministic head bytes to a NoKV generation CAS."""

    _TRANSIENT_READ_ERRORS = (
        "exceeds the artifact logical size",
        "fence changed",
        "retry budget",
        "read fence",
    )

    def __init__(self, client, workbench: str, goal_id: str):
        self.client = client
        self.workbench = workbench
        self.goal_id = goal_id
        self.head_path = f"goals/{goal_id}/coordination-head.json"

    @staticmethod
    def _not_found(exc: RuntimeError) -> bool:
        message = str(exc).lower()
        return any(token in message for token in (
            "not found",
            "does not exist",
            "no such path",
        ))

    def load(self, retries: int = 10):
        """Return ``(aggregate | None, provider_generation)``."""
        last_error = None
        for attempt in range(retries):
            try:
                result = self.client.read(self.workbench, self.head_path)
            except RuntimeError as exc:
                if self._not_found(exc):
                    return None, 0
                message = str(exc).lower()
                if any(token in message for token in self._TRANSIENT_READ_ERRORS):
                    last_error = exc
                    time.sleep(0.01 * (attempt + 1))
                    continue
                raise
            aggregate = json.loads(bytes(result["bytes"]))
            if not isinstance(aggregate, dict):
                raise ProviderProtocolError("coordination head must be an object")
            return aggregate, int(result["metadata"]["generation"])
        raise last_error or RuntimeError("NoKV read retry budget exhausted")

    def _generation(self) -> int:
        try:
            metadata = self.client.stat(self.workbench, self.head_path)
        except RuntimeError as exc:
            if self._not_found(exc):
                return 0
            raise
        return int(metadata["generation"])

    def compare_and_put(
        self,
        expected_provider_generation: int,
        aggregate: dict,
    ) -> dict:
        """Serialize and conditionally store an opaque aggregate."""
        try:
            current = self._generation()
        except RuntimeError as exc:
            # No publish was attempted, so this provider failure proves no write.
            return {"result": "failed", "error": str(exc)}
        if current != expected_provider_generation:
            return {"result": "conflict", "current_provider_generation": current}
        try:
            result = self.client.publish_bytes(
                self.workbench,
                self.head_path,
                _deterministic_bytes(aggregate),
                content_type="application/json",
                expected_generation=(
                    None if expected_provider_generation == 0
                    else expected_provider_generation
                ),
                operation_id=uuid.uuid4().hex,
                artifact_revision_id=uuid.uuid4().hex,
            )
        except RuntimeError:
            # Do not parse human error text as commit proof.  The authority
            # reloads and trusts only its atomically stored receipt index.
            return {"result": "ambiguous"}
        return {
            "result": "applied",
            "provider_generation": int(result["generation"]),
        }


class CoordinationAuthority:
    """Reference proof for one command: claim an existing runnable todo."""

    _TOP_FIELDS = {
        "schema_version",
        "operation_id",
        "actor",
        "goal_id",
        "command",
        "transport",
    }
    _ACTOR_FIELDS = {"agent_id", "device_id"}
    _COMMAND_FIELDS = {
        "type",
        "todo_id",
        "expected_todo_revision",
        "expected_preconditions",
        "lease_ttl_seconds",
    }
    _PRECONDITION_FIELDS = {
        "authorization_projection_revision",
        "authorization_projection_digest",
        "dependency_revision",
        "gate_revision",
    }
    _MAX_CAS_ATTEMPTS = 8

    def __init__(
        self,
        provider,
        goal_id: str,
        now: Callable[[], float] = time.time,
    ):
        self.provider = provider
        self.goal_id = goal_id
        self.now = now

    def apply(self, envelope: dict) -> dict:
        request = self._semantic_request(envelope)
        operation_id = request["operation_id"]
        request_digest = _digest(request)
        head, provider_generation = self.provider.load()
        if head is None:
            return {
                "result": "failed",
                "reason": "coordination_head_uninitialized",
                "provider_generation": provider_generation,
            }
        head = self._validated_head(head)

        for attempt in range(self._MAX_CAS_ATTEMPTS):
            replay = self._replay(
                head,
                provider_generation,
                operation_id,
                request_digest,
            )
            if replay is not None:
                return replay
            transition = self._claim(head, request, request_digest)
            if isinstance(transition, dict):
                transition.update({
                    "observed_authority_revision": head["authority_revision"],
                    "provider_generation": provider_generation,
                })
                return transition
            proposed, original_receipt = transition
            provider_result = self.provider.compare_and_put(
                provider_generation,
                proposed,
            )
            result_kind = provider_result.get("result")
            if result_kind == "applied":
                return self._success(
                    "applied",
                    original_receipt,
                    proposed,
                    provider_result["provider_generation"],
                )
            if result_kind not in {"conflict", "ambiguous", "failed"}:
                raise ProviderProtocolError(
                    f"unknown provider result: {provider_result!r}"
                )
            if result_kind == "failed":
                return {
                    "result": "failed",
                    "reason": "provider_failed_before_cas",
                    "observed_authority_revision": head["authority_revision"],
                    "provider_generation": provider_generation,
                }

            latest, latest_generation = self.provider.load()
            if latest is None:
                return {
                    "result": "failed",
                    "reason": "coordination_head_missing_after_cas",
                    "provider_generation": latest_generation,
                }
            latest = self._validated_head(latest)
            replay = self._replay(
                latest,
                latest_generation,
                operation_id,
                request_digest,
            )
            if replay is not None:
                return replay
            if latest_generation == provider_generation:
                return {
                    "result": "failed",
                    "reason": "provider_outcome_unproved",
                    "observed_authority_revision": latest["authority_revision"],
                    "provider_generation": latest_generation,
                }
            head, provider_generation = latest, latest_generation

        return {
            "result": "failed",
            "reason": "provider_contention_exhausted",
            "observed_authority_revision": head["authority_revision"],
            "provider_generation": provider_generation,
        }

    def _semantic_request(self, envelope: dict) -> dict:
        if not isinstance(envelope, dict):
            raise ValueError("command envelope must be an object")
        unknown = set(envelope) - self._TOP_FIELDS
        if unknown:
            raise ValueError(f"unknown command envelope fields: {sorted(unknown)}")
        if envelope.get("schema_version") != COMMAND_SCHEMA:
            raise ValueError("unsupported command envelope schema")
        operation_id = envelope.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("operation_id must be a non-empty string")
        if envelope.get("goal_id") != self.goal_id:
            raise ValueError("command goal_id does not match this authority")
        if "transport" in envelope and not isinstance(envelope["transport"], dict):
            raise ValueError("transport metadata must be an object")

        actor = envelope.get("actor")
        if not isinstance(actor, dict) or set(actor) != self._ACTOR_FIELDS:
            raise ValueError("actor must contain only agent_id and device_id")
        if not all(isinstance(actor[key], str) and actor[key] for key in self._ACTOR_FIELDS):
            raise ValueError("actor ids must be non-empty strings")
        command = envelope.get("command")
        if not isinstance(command, dict) or set(command) != self._COMMAND_FIELDS:
            raise ValueError("claim_work fields do not match the v0 proof")
        if command.get("type") != "claim_work":
            raise ValueError("reference proof supports only claim_work")
        if not isinstance(command["todo_id"], str) or not command["todo_id"]:
            raise ValueError("todo_id must be a non-empty string")
        if not isinstance(command["expected_todo_revision"], int):
            raise ValueError("expected_todo_revision must be an integer")
        preconditions = command["expected_preconditions"]
        if not isinstance(preconditions, dict) or set(preconditions) != (
            self._PRECONDITION_FIELDS
        ):
            raise ValueError("expected_preconditions fields do not match v0")
        revision_fields = (
            "authorization_projection_revision",
            "dependency_revision",
            "gate_revision",
        )
        if any(
            not isinstance(preconditions[field], int) or preconditions[field] < 0
            for field in revision_fields
        ):
            raise ValueError("expected_preconditions revisions must be non-negative")
        digest = preconditions["authorization_projection_digest"]
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise ValueError("expected authorization projection digest is invalid")
        if not isinstance(command["lease_ttl_seconds"], int) or command[
            "lease_ttl_seconds"
        ] <= 0:
            raise ValueError("lease_ttl_seconds must be positive")

        # ``transport`` is deliberately excluded; all semantic fields are
        # explicitly projected, and unknown fields already failed closed.
        return {
            "schema_version": COMMAND_SCHEMA,
            "operation_id": operation_id,
            "actor": {key: actor[key] for key in sorted(self._ACTOR_FIELDS)},
            "goal_id": self.goal_id,
            "command": {key: copy.deepcopy(command[key]) for key in sorted(self._COMMAND_FIELDS)},
        }

    def _validated_head(self, head: dict) -> dict:
        expected_fields = {
            "schema_version",
            "goal_id",
            "authority_revision",
            "coordination",
            "receipt_index",
            "receipt_retention",
        }
        if set(head) != expected_fields:
            raise ProviderProtocolError("coordination head fields do not match v0")
        if head["schema_version"] != HEAD_SCHEMA or head["goal_id"] != self.goal_id:
            raise ProviderProtocolError("coordination head identity mismatch")
        if not isinstance(head["authority_revision"], int):
            raise ProviderProtocolError("authority_revision must be an integer")
        coordination = head["coordination"]
        if not isinstance(coordination, dict) or set(coordination) != {"todos", "leases"}:
            raise ProviderProtocolError("coordination must contain todos and leases")
        if not isinstance(coordination["todos"], dict) or not isinstance(
            coordination["leases"], dict
        ):
            raise ProviderProtocolError("todos and leases must be objects")
        if not isinstance(head["receipt_index"], dict):
            raise ProviderProtocolError("receipt_index must be an object")
        if head["receipt_retention"] != RETAIN_ALL:
            raise ProviderProtocolError("v0 requires retain_all_v0")
        return head

    def _replay(
        self,
        head: dict,
        provider_generation: int,
        operation_id: str,
        request_digest: str,
    ):
        entry = head["receipt_index"].get(operation_id)
        if entry is None:
            return None
        if entry.get("request_digest") != request_digest:
            return {
                "result": "rejected",
                "reason": "operation_identity_mismatch",
                "operation_id": operation_id,
                "observed_authority_revision": head["authority_revision"],
                "provider_generation": provider_generation,
            }
        receipt = entry.get("original_receipt")
        if not isinstance(receipt, dict):
            raise ProviderProtocolError("receipt entry lacks original_receipt")
        return self._success("already_applied", receipt, head, provider_generation)

    def _claim(self, head: dict, request: dict, request_digest: str):
        command = request["command"]
        todo = head["coordination"]["todos"].get(command["todo_id"])
        if todo is None:
            return {"result": "rejected", "reason": "todo_not_found"}
        if todo.get("todo_revision") != command["expected_todo_revision"]:
            return {
                "result": "conflict",
                "reason": "todo_revision_mismatch",
                "expected_todo_revision": command["expected_todo_revision"],
                "observed_todo_revision": todo.get("todo_revision"),
            }
        if todo.get("status") != "open" or todo.get("claimed_by") is not None:
            return {"result": "rejected", "reason": "todo_not_open"}
        eligibility = todo.get("eligibility")
        if not isinstance(eligibility, dict):
            return {"result": "rejected", "reason": "eligibility_missing"}
        observed_preconditions = {
            field: eligibility.get(field)
            for field in self._PRECONDITION_FIELDS
        }
        if observed_preconditions != command["expected_preconditions"]:
            return {
                "result": "conflict",
                "reason": "precondition_snapshot_mismatch",
                "expected_preconditions": copy.deepcopy(
                    command["expected_preconditions"]
                ),
                "observed_preconditions": observed_preconditions,
            }
        if request["actor"]["agent_id"] not in eligibility.get("allowed_agent_ids", []):
            return {"result": "rejected", "reason": "actor_ineligible"}
        if eligibility.get("dependencies_satisfied") is not True:
            return {"result": "rejected", "reason": "dependencies_not_satisfied"}
        if eligibility.get("gates_open") is not True:
            return {"result": "rejected", "reason": "gate_closed"}

        now = float(self.now())
        lease_epoch = int(todo.get("last_lease_epoch", 0)) + 1
        lease = {
            "lease_id": _lease_id(request["operation_id"]),
            "owner": request["actor"]["agent_id"],
            "lease_epoch": lease_epoch,
            "expires_at": _format_time(now + command["lease_ttl_seconds"]),
            "write_scopes": [],
        }
        proposed = copy.deepcopy(head)
        proposed["authority_revision"] += 1
        proposed_todo = proposed["coordination"]["todos"][command["todo_id"]]
        proposed_todo.update({
            "todo_revision": todo["todo_revision"] + 1,
            # LoopX keeps a claimed todo open; ``claimed_by`` and the hard
            # lease carry ownership without inventing a new lifecycle state.
            "status": "open",
            "claimed_by": request["actor"]["agent_id"],
            "last_lease_epoch": lease_epoch,
        })
        proposed["coordination"]["leases"][command["todo_id"]] = lease
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "operation_id": request["operation_id"],
            "request_digest": request_digest,
            "actor": copy.deepcopy(request["actor"]),
            "todo_id": command["todo_id"],
            "command": "claim_work",
            "accepted_authority_revision": proposed["authority_revision"],
            "accepted_todo_revision": proposed_todo["todo_revision"],
            "applied_at": _format_time(now),
            "lease_id": lease["lease_id"],
            "lease_epoch": lease_epoch,
            "expires_at": lease["expires_at"],
        }
        proposed["receipt_index"][request["operation_id"]] = {
            "request_digest": request_digest,
            "original_receipt": copy.deepcopy(receipt),
        }
        return proposed, receipt

    def _success(self, result: str, receipt: dict, head: dict, generation: int) -> dict:
        lease = head["coordination"]["leases"].get(receipt["todo_id"])
        if lease is None or (
            lease.get("lease_id") != receipt.get("lease_id")
            or lease.get("lease_epoch") != receipt.get("lease_epoch")
        ):
            status = "superseded"
        elif _parse_time(lease["expires_at"]) <= self.now():
            status = "expired"
        else:
            status = "active"
        return {
            "result": result,
            "original_receipt": copy.deepcopy(receipt),
            "observed_authority_revision": head["authority_revision"],
            "authorization_status": status,
            "provider_generation": generation,
        }


def sample_envelope(
    operation_id: str | None = None,
    agent_id: str = "agent-a",
    device_id: str = "dev-laptop",
    goal_id: str = "ark-agent-loop-shared",
    todo_id: str = "todo-0042",
    expected_todo_revision: int = 7,
    expected_preconditions: dict | None = None,
    lease_ttl_seconds: int = 600,
    transport: dict | None = None,
) -> dict:
    if expected_preconditions is None:
        expected_preconditions = {
            "authorization_projection_revision": 3,
            "authorization_projection_digest": "sha256:bootstrap-auth",
            "dependency_revision": 12,
            "gate_revision": 5,
        }
    envelope = {
        "schema_version": COMMAND_SCHEMA,
        "operation_id": operation_id or str(uuid.uuid4()),
        "actor": {"agent_id": agent_id, "device_id": device_id},
        "goal_id": goal_id,
        "command": {
            "type": "claim_work",
            "todo_id": todo_id,
            "expected_todo_revision": expected_todo_revision,
            "expected_preconditions": copy.deepcopy(expected_preconditions),
            "lease_ttl_seconds": lease_ttl_seconds,
        },
    }
    if transport is not None:
        envelope["transport"] = copy.deepcopy(transport)
    return envelope
