"""The authority execution layer over a coordination provider (RFC section 5).

The executor owns exactly what the Stage 1 core refuses: envelope
normalization and request digests, aggregate-level preconditions
(todo revisions, eligibility snapshots, dependency and gate booleans),
receipt construction and replay, wall-clock expiry minting, the three version
domains (``provider_generation`` / ``authority_revision`` / ``lease_epoch``),
and the bounded load -> decide -> compare_and_put -> reload loop. Every
domain decision about actors and leases is delegated to
``authority_core.decide``; no coordination rule is re-derived here.

The only command in this slice is ``claim_work`` (RFC section 5.1): one
accepted transition records the claim, the lease with its next epoch, and the
original receipt in the same provider CAS.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from .authority_core import (
    DecisionOutcome,
    LeaseAcquireCommand,
    TodoAction,
    TodoMutationCommand,
    decide,
)
from .head import (
    HeadValidationError,
    canonical_head_bytes,
    claim_snapshot_for_todo,
    validated_head,
)

COMMAND_SCHEMA_VERSION = "loopx_command_v0"
RECEIPT_SCHEMA_VERSION = "loopx_authority_receipt_v0"

_ENVELOPE_FIELDS = {"schema_version", "operation_id", "actor", "goal_id", "command", "transport"}
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
# The local task-lease authority's ceiling
# (work_items.task_lease.MAX_TASK_LEASE_TTL_SECONDS), mirrored here so this
# module's import closure stays inside the strict type gate; a pin test
# asserts the two never drift.
MAX_LEASE_TTL_SECONDS = 24 * 60 * 60

# Core code -> RFC reason vocabulary for the claim_work slice. Actor and
# owner ineligibility collapse onto the RFC's one actor reason; ownership
# codes that the executor's aggregate prechecks should have intercepted are
# aggregate-integrity failures, so they fail closed instead of masquerading
# as caller errors.
_CORE_TO_RFC_REASON = {
    "actor_required": "actor_ineligible",
    "actor_not_registered": "actor_ineligible",
    "actor_excluded": "actor_ineligible",
    "claim_actor_mismatch": "actor_ineligible",
    "invalid_owner": "actor_ineligible",
    "owner_not_registered": "actor_ineligible",
    "owner_excluded_from_todo": "actor_ineligible",
    "todo_not_open": "todo_not_open",
    "todo_not_found": "todo_not_found",
}
_FAIL_CLOSED_CORE_CODES = {
    "claim_owner_mismatch",
    "owner_conflicts_with_claim",
    "invalid_lease_snapshot",
}


def _classified(plan: Any) -> dict[str, Any]:
    """Map one non-APPLY core TransitionPlan onto an RFC result class."""

    if plan.code in _FAIL_CLOSED_CORE_CODES:
        # The executor's revision and open/unclaimed prechecks make these
        # unreachable on a well-formed head; reaching one means the aggregate
        # and the core disagree, which is an integrity failure, not caller error.
        return {"result": "failed", "reason": f"aggregate_integrity:{plan.code}"}
    if plan.outcome is DecisionOutcome.CONFLICT:
        return {"result": "conflict", "reason": plan.code}
    if plan.outcome is DecisionOutcome.NO_CHANGE:
        # A replay the receipt index does not know about cannot be proven to
        # be this operation's own effect (acceptance check 6): fail closed.
        return {"result": "failed", "reason": f"state_without_receipt:{plan.code}"}
    return {
        "result": "rejected",
        "reason": _CORE_TO_RFC_REASON.get(plan.code, plan.code),
    }


class EnvelopeError(ValueError):
    """The command envelope violates the reviewed v0 contract."""


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _lease_id(operation_id: str) -> str:
    return "lease_" + hashlib.sha256(f"lease:{operation_id}".encode()).hexdigest()[:24]


def _format_time(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def sample_claim_envelope(
    *,
    goal_id: str,
    operation_id: str,
    agent_id: str,
    device_id: str,
    todo_id: str,
    expected_todo_revision: int,
    expected_preconditions: dict[str, Any],
    lease_ttl_seconds: int,
    transport: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one well-formed ``claim_work`` envelope (tests and adapters)."""

    envelope: dict[str, Any] = {
        "schema_version": COMMAND_SCHEMA_VERSION,
        "operation_id": operation_id,
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


class CoordinationAuthorityExecutor:
    """Apply normalized coordination commands through one provider CAS."""

    def __init__(
        self,
        provider: Any,
        *,
        goal_id: str,
        now: Callable[[], float],
    ):
        self.provider = provider
        self.goal_id = goal_id
        self.now = now

    # ---- envelope normalization (RFC section 5) -----------------------------

    def _semantic_request(self, envelope: Any) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            raise EnvelopeError("command envelope must be an object")
        unknown = set(envelope) - _ENVELOPE_FIELDS
        if unknown:
            raise EnvelopeError(f"unknown command envelope fields: {sorted(unknown)}")
        if envelope.get("schema_version") != COMMAND_SCHEMA_VERSION:
            raise EnvelopeError("unsupported command envelope schema")
        operation_id = envelope.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise EnvelopeError("operation_id must be a non-empty string")
        if envelope.get("goal_id") != self.goal_id:
            raise EnvelopeError("command goal_id does not match this authority")
        if "transport" in envelope and not isinstance(envelope["transport"], dict):
            raise EnvelopeError("transport metadata must be an object")
        actor = envelope.get("actor")
        if not isinstance(actor, dict) or set(actor) != _ACTOR_FIELDS:
            raise EnvelopeError("actor must contain only agent_id and device_id")
        if not all(isinstance(actor[key], str) and actor[key] for key in _ACTOR_FIELDS):
            raise EnvelopeError("actor ids must be non-empty strings")
        command = envelope.get("command")
        if not isinstance(command, dict) or set(command) != _COMMAND_FIELDS:
            raise EnvelopeError("claim_work fields do not match the v0 contract")
        if command.get("type") != "claim_work":
            raise EnvelopeError("this slice supports only claim_work")
        if not isinstance(command["todo_id"], str) or not command["todo_id"]:
            raise EnvelopeError("todo_id must be a non-empty string")
        revision = command["expected_todo_revision"]
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise EnvelopeError("expected_todo_revision must be an integer")
        preconditions = command["expected_preconditions"]
        if not isinstance(preconditions, dict) or set(preconditions) != _PRECONDITION_FIELDS:
            raise EnvelopeError("expected_preconditions fields do not match v0")
        for field in (
            "authorization_projection_revision",
            "dependency_revision",
            "gate_revision",
        ):
            value = preconditions[field]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise EnvelopeError("expected_preconditions revisions must be non-negative")
        digest = preconditions["authorization_projection_digest"]
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise EnvelopeError("expected authorization projection digest is invalid")
        ttl = command["lease_ttl_seconds"]
        # The bound is the local task-lease authority's own ceiling, so the
        # shared envelope cannot mint a lease the local contract would refuse,
        # and an unbounded caller value can never reach wall-clock arithmetic
        # (an astronomical TTL overflows timestamp formatting).
        if (
            not isinstance(ttl, int)
            or isinstance(ttl, bool)
            or ttl <= 0
            or ttl > MAX_LEASE_TTL_SECONDS
        ):
            raise EnvelopeError(
                f"lease_ttl_seconds must be between 1 and {MAX_LEASE_TTL_SECONDS}"
            )
        # Transport metadata is deliberately excluded from the semantic request.
        return {
            "schema_version": COMMAND_SCHEMA_VERSION,
            "operation_id": operation_id,
            "actor": {key: actor[key] for key in sorted(_ACTOR_FIELDS)},
            "goal_id": self.goal_id,
            "command": {
                key: copy.deepcopy(command[key]) for key in sorted(_COMMAND_FIELDS)
            },
        }

    # ---- replay -------------------------------------------------------------

    def _replay(
        self,
        head: dict[str, Any],
        provider_generation: int,
        operation_id: str,
        request_digest: str,
    ) -> dict[str, Any] | None:
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
            raise HeadValidationError("receipt entry lacks original_receipt")
        return self._success("already_applied", receipt, head, provider_generation)

    def _success(
        self,
        result: str,
        receipt: dict[str, Any],
        head: dict[str, Any],
        generation: int,
    ) -> dict[str, Any]:
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

    # ---- the one transition of this slice -----------------------------------

    def _claim_transition(
        self,
        head: dict[str, Any],
        request: dict[str, Any],
        request_digest: str,
    ) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
        """Return either a typed non-apply dict, or (next_head, receipt)."""

        command = request["command"]
        todo_id = command["todo_id"]
        todo = head["coordination"]["todos"].get(todo_id)
        if todo is None:
            return {"result": "rejected", "reason": "todo_not_found"}
        if todo["todo_revision"] != command["expected_todo_revision"]:
            return {
                "result": "conflict",
                "reason": "todo_revision_mismatch",
                "expected_todo_revision": command["expected_todo_revision"],
                "observed_todo_revision": todo["todo_revision"],
            }
        eligibility = todo["eligibility"]
        observed_preconditions = {
            field: eligibility[field] for field in _PRECONDITION_FIELDS
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
        if todo["status"] != "open" or todo["claimed_by"] is not None:
            return {"result": "rejected", "reason": "todo_not_open"}
        if eligibility["dependencies_satisfied"] is not True:
            return {"result": "rejected", "reason": "dependencies_not_satisfied"}
        if eligibility["gates_open"] is not True:
            return {"result": "rejected", "reason": "gate_closed"}

        actor = request["actor"]["agent_id"]
        snapshot = claim_snapshot_for_todo(head, todo_id)

        # Composition order is fixed by the Stage 1 core: the lease is minted
        # first, then the claim passes the hard-lease holder gate against the
        # freshly minted lease. Claim-first would silently bypass the
        # Appendix B invariant that ownership changes require the holder.
        acquire_plan = decide(
            snapshot,
            LeaseAcquireCommand(
                owner=actor,
                idempotency_key=_lease_id(request["operation_id"]),
                ttl_seconds=command["lease_ttl_seconds"],
            ),
        )
        if acquire_plan.outcome is not DecisionOutcome.APPLY:
            return _classified(acquire_plan)
        assert acquire_plan.next_snapshot is not None

        claim_plan = decide(
            acquire_plan.next_snapshot,
            TodoMutationCommand(
                action=TodoAction.CLAIM,
                actor_agent_id=actor,
                requested_claimed_by=actor,
                ownership_mutation=True,
            ),
        )
        if claim_plan.outcome is not DecisionOutcome.APPLY:
            return _classified(claim_plan)
        assert claim_plan.next_snapshot is not None
        core_lease = claim_plan.next_snapshot.lease
        assert core_lease is not None

        now = float(self.now())
        expires_at = _format_time(now + command["lease_ttl_seconds"])
        next_head = copy.deepcopy(head)
        next_head["authority_revision"] += 1
        next_todo = next_head["coordination"]["todos"][todo_id]
        next_todo.update(
            {
                "todo_revision": todo["todo_revision"] + 1,
                # LoopX keeps a claimed todo open; ``claimed_by`` plus the
                # lease carry ownership without a new lifecycle status.
                "status": "open",
                "claimed_by": actor,
                "last_lease_epoch": core_lease.lease_epoch,
            }
        )
        next_head["coordination"]["leases"][todo_id] = {
            "lease_id": core_lease.idempotency_key,
            "owner": core_lease.owner,
            "lease_epoch": core_lease.lease_epoch,
            "expires_at": expires_at,
            "write_scopes": list(core_lease.write_scopes),
        }
        receipt = {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "operation_id": request["operation_id"],
            "request_digest": request_digest,
            "command": "claim_work",
            "actor": copy.deepcopy(request["actor"]),
            "todo_id": todo_id,
            "accepted_authority_revision": next_head["authority_revision"],
            "accepted_todo_revision": next_todo["todo_revision"],
            "applied_at": _format_time(now),
            "lease_id": core_lease.idempotency_key,
            "lease_epoch": core_lease.lease_epoch,
            "expires_at": expires_at,
        }
        next_head["receipt_index"][request["operation_id"]] = {
            "request_digest": request_digest,
            "original_receipt": copy.deepcopy(receipt),
        }
        return next_head, receipt

    # ---- RFC section 5 steps 1-10 -------------------------------------------

    def apply(self, envelope: dict[str, Any]) -> dict[str, Any]:
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
        head = validated_head(head, goal_id=self.goal_id)

        for _attempt in range(_MAX_CAS_ATTEMPTS):
            replay = self._replay(head, provider_generation, operation_id, request_digest)
            if replay is not None:
                return replay
            transition = self._claim_transition(head, request, request_digest)
            if isinstance(transition, dict):
                transition.update(
                    {
                        "observed_authority_revision": head["authority_revision"],
                        "provider_generation": provider_generation,
                    }
                )
                return transition
            proposed, original_receipt = transition
            provider_result = self.provider.compare_and_put(
                provider_generation, proposed
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
                raise HeadValidationError(
                    f"unknown provider result: {provider_result!r}"
                )
            if result_kind == "failed":
                # The verb claims the write provably never happened. That
                # claim is verified, not trusted: one reload against the
                # receipt index catches a provider that misreported a landed
                # write as failed, at the cost of a single load.
                try:
                    check, check_generation = self.provider.load()
                    if check is not None:
                        check = validated_head(check, goal_id=self.goal_id)
                        replay = self._replay(
                            check, check_generation, operation_id, request_digest
                        )
                        if replay is not None:
                            return replay
                except Exception:  # noqa: BLE001 - verification is best-effort
                    pass
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
            latest = validated_head(latest, goal_id=self.goal_id)
            replay = self._replay(
                latest, latest_generation, operation_id, request_digest
            )
            if replay is not None:
                return replay
            if latest_generation == provider_generation:
                # Same generation and no receipt: the ambiguous attempt
                # provably did not land. Receipt absence never proves success,
                # so an eventual applied requires a new successful CAS.
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


def deterministic_head_bytes(head: dict[str, Any]) -> bytes:
    """Canonical bytes for providers that store raw bytes (NoKV adapter)."""

    return canonical_head_bytes(head)
