"""Provider-neutral coordination decisions shared by current state writers.

Adapters normalize their persisted state while holding the existing lock, call
``decide``, and only then perform their current write.  A returned transition is
a proposal, not proof that any write committed.  Durable execution results and
storage outcomes deliberately live outside this module. Task-lease acquire is
adapted to the canonical pure TypeScript decision; the remaining command slices
stay local until their reviewed cutovers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from ..effect_runtime import effect_runtime_result


DecisionScope = tuple[str, str, str]


class HandoffMode(StrEnum):
    LEGACY = "legacy"
    SOFT_CLAIM = "soft_claim"
    HARD_LEASE = "hard_lease"


class TodoAction(StrEnum):
    CLAIM = "claim"
    UPDATE = "update"
    COMPLETE = "complete"
    SUPERSEDE = "supersede"


class LeaseAction(StrEnum):
    ACQUIRE = "acquire"
    RENEW = "renew"
    TRANSFER = "transfer"
    RELEASE = "release"


class DecisionOutcome(StrEnum):
    APPLY = "apply"
    NO_CHANGE = "no_change"
    CONFLICT = "conflict"
    REJECTED = "rejected"


class OwnershipGate(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRE_HOLDER = "require_holder"
    DELEGATED_OVERRIDE = "delegated_override"


class LeaseFence(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    AUTO_ACQUIRE = "auto_acquire"
    DELEGATED_OVERRIDE = "delegated_override"


@dataclass(frozen=True)
class LifecycleGrant:
    agent_id: str
    actions: frozenset[str]
    requires_reason: bool = True


@dataclass(frozen=True)
class TodoSnapshot:
    todo_id: str
    status: str
    role: str
    task_class: str | None = None
    claimed_by: str | None = None
    excluded_agents: frozenset[str] = frozenset()
    bound_agent: str | None = None
    blocks_agent: str | None = None
    decision_scope: DecisionScope | None = None
    required_decision_scopes: frozenset[DecisionScope] = frozenset()
    unblocks_todo_id: str | None = None


@dataclass(frozen=True)
class LeaseSnapshot:
    present: bool = False
    active: bool = False
    status: str | None = None
    owner: str | None = None
    idempotency_key: str | None = None
    version: int = 0
    lease_epoch: int = 0
    write_scopes: tuple[str, ...] = ()
    acquire_ttl_seconds: int | None = None


@dataclass(frozen=True)
class OtherLeaseSnapshot:
    todo_id: str
    active: bool
    effective: bool
    write_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoordinationSnapshot:
    handoff_mode: HandoffMode = HandoffMode.LEGACY
    registered_agents: tuple[str, ...] = ()
    lifecycle_grants: tuple[LifecycleGrant, ...] = ()
    todo: TodoSnapshot | None = None
    decision_target: TodoSnapshot | None = None
    lease: LeaseSnapshot | None = None
    other_leases: tuple[OtherLeaseSnapshot, ...] = ()
    active_claimed_todo_ids: tuple[str, ...] = ()
    active_lease_todo_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TodoMutationCommand:
    action: TodoAction
    actor_agent_id: str | None
    requested_claimed_by: str | None = None
    clear_claim: bool = False
    authority_action: str | None = None
    authority_reason: str | None = None
    decision_outcome: str | None = None
    ownership_mutation: bool = False
    lease_idempotency_key: str | None = None
    lease_expected_version: int | None = None
    allow_user_gate_auto_acquire: bool = False


@dataclass(frozen=True)
class LeaseAcquireCommand:
    owner: str
    idempotency_key: str
    ttl_seconds: int
    write_scopes: tuple[str, ...] = ()
    expected_version: int | None = None


@dataclass(frozen=True)
class LeaseRenewCommand:
    owner: str
    idempotency_key: str
    ttl_seconds: int
    expected_version: int | None = None


@dataclass(frozen=True)
class LeaseTransferCommand:
    owner: str
    idempotency_key: str
    new_owner: str
    new_idempotency_key: str
    ttl_seconds: int
    expected_version: int | None = None


@dataclass(frozen=True)
class LeaseReleaseCommand:
    owner: str
    idempotency_key: str
    expected_version: int | None = None


@dataclass(frozen=True)
class LeaseOwnerEligibilityCommand:
    owner: str | None


@dataclass(frozen=True)
class LeaseModeGateCommand:
    action: LeaseAction


@dataclass(frozen=True)
class TerminalFenceCommand:
    """Verify the lease side of an already-authorized terminal mutation."""

    actor_agent_id: str | None
    lease_idempotency_key: str | None = None
    lease_expected_version: int | None = None
    delegated_authority: bool = False
    allow_user_gate_auto_acquire: bool = False
    require_active_when_fence_supplied: bool = True


@dataclass(frozen=True)
class HandoffModeTransitionCommand:
    requested_mode: HandoffMode


CoordinationCommand = (
    TodoMutationCommand
    | LeaseAcquireCommand
    | LeaseRenewCommand
    | LeaseTransferCommand
    | LeaseReleaseCommand
    | LeaseOwnerEligibilityCommand
    | LeaseModeGateCommand
    | TerminalFenceCommand
    | HandoffModeTransitionCommand
)


@dataclass(frozen=True)
class TransitionPlan:
    outcome: DecisionOutcome
    code: str
    next_snapshot: CoordinationSnapshot | None = None
    authority_mode: str | None = None
    ownership_gate: OwnershipGate = OwnershipGate.NOT_REQUIRED
    lease_fence: LeaseFence = LeaseFence.NOT_REQUIRED
    idempotent: bool = False


def _result(
    outcome: DecisionOutcome,
    code: str,
    *,
    next_snapshot: CoordinationSnapshot | None = None,
    authority_mode: str | None = None,
    ownership_gate: OwnershipGate = OwnershipGate.NOT_REQUIRED,
    lease_fence: LeaseFence = LeaseFence.NOT_REQUIRED,
    idempotent: bool = False,
) -> TransitionPlan:
    return TransitionPlan(
        outcome=outcome,
        code=code,
        next_snapshot=next_snapshot,
        authority_mode=authority_mode,
        ownership_gate=ownership_gate,
        lease_fence=lease_fence,
        idempotent=idempotent,
    )


def _actual_version(lease: LeaseSnapshot | None) -> int:
    return lease.version if lease is not None and lease.present else 0


def _invalid_lease_snapshot(lease: LeaseSnapshot | None) -> bool:
    """Reject contradictory normalized states at the pure-core boundary."""

    return bool(
        lease is not None
        and lease.active
        and (not lease.present or lease.status == "released")
    )


def _version_conflict(
    lease: LeaseSnapshot | None,
    expected_version: int | None,
) -> bool:
    return expected_version is not None and _actual_version(lease) != expected_version


def _lease_owner_rejection(
    snapshot: CoordinationSnapshot,
    owner: str | None,
) -> str | None:
    todo = snapshot.todo
    if todo is None:
        return "todo_not_found"
    if todo.status != "open":
        return "todo_not_open"
    if not owner:
        return "invalid_owner"
    if owner not in snapshot.registered_agents:
        return "owner_not_registered"
    if owner in todo.excluded_agents:
        return "owner_excluded_from_todo"
    if todo.claimed_by and todo.claimed_by != owner:
        return "owner_conflicts_with_claim"
    return None


def _lease_is_effective(
    snapshot: CoordinationSnapshot,
    lease: LeaseSnapshot | None,
) -> bool:
    return bool(
        lease is not None
        and lease.present
        and lease.active
        and _lease_owner_rejection(snapshot, lease.owner) is None
    )


def write_scopes_overlap(
    left: tuple[str, ...] | list[str],
    right: tuple[str, ...] | list[str],
) -> bool:
    """Return the canonical native overlap decision for normalized scopes."""

    payload = effect_runtime_result(
        "task_lease.write_scopes.overlap",
        {"left": list(left), "right": list(right)},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("overlap"), bool):
        raise RuntimeError("native task-lease write-scope decision shape mismatch")
    return bool(payload["overlap"])


def _exact_user_gate_override(
    snapshot: CoordinationSnapshot,
    command: TodoMutationCommand,
) -> bool:
    todo = snapshot.todo
    target = snapshot.decision_target
    return bool(
        todo is not None
        and target is not None
        and command.action is TodoAction.COMPLETE
        and todo.role == "user"
        and todo.task_class == "user_gate"
        and command.decision_outcome
        and todo.decision_scope is not None
        and todo.unblocks_todo_id == target.todo_id
        and todo.decision_scope in target.required_decision_scopes
    )


def _todo_after_command(
    todo: TodoSnapshot,
    command: TodoMutationCommand,
) -> TodoSnapshot:
    if command.action in {TodoAction.COMPLETE, TodoAction.SUPERSEDE}:
        return replace(todo, status="done")
    if command.action is TodoAction.CLAIM:
        return replace(todo, claimed_by=command.requested_claimed_by)
    if command.ownership_mutation:
        return replace(
            todo,
            claimed_by=(None if command.clear_claim else command.requested_claimed_by),
        )
    return todo


def _authority_for_todo(
    snapshot: CoordinationSnapshot,
    command: TodoMutationCommand,
) -> tuple[str | None, str | None]:
    """Return ``(authority_mode, rejection_code)``."""

    todo = snapshot.todo
    if todo is None:
        return None, "todo_not_found"
    actor = command.actor_agent_id
    if len(snapshot.registered_agents) <= 1:
        if actor and snapshot.registered_agents and actor not in snapshot.registered_agents:
            return None, "actor_not_registered"
        return "single_agent_compatibility", None
    if _exact_user_gate_override(snapshot, command):
        return "exact_user_gate_decision_scope_override", None
    if not actor:
        return None, "actor_required"
    if actor not in snapshot.registered_agents:
        return None, "actor_not_registered"
    if actor in todo.excluded_agents:
        return None, "actor_excluded"
    bound_agent = todo.bound_agent
    if not bound_agent and todo.role == "user":
        bound_agent = todo.blocks_agent
    if bound_agent and bound_agent != actor:
        return None, "bound_agent_mismatch"
    if todo.claimed_by and todo.claimed_by != actor:
        action = command.authority_action or command.action.value
        grant = next(
            (item for item in snapshot.lifecycle_grants if item.agent_id == actor),
            None,
        )
        if grant is None:
            return None, "claim_owner_mismatch"
        if action not in grant.actions:
            return None, "delegation_action_not_granted"
        if grant.requires_reason and not str(command.authority_reason or "").strip():
            return None, "delegation_reason_required"
        return "delegated_orchestration_override", None
    if (
        command.action is TodoAction.CLAIM
        and command.requested_claimed_by != actor
    ):
        return None, "claim_actor_mismatch"
    return "registered_peer_actor", None


def _terminal_fence_decision(
    snapshot: CoordinationSnapshot,
    *,
    actor_agent_id: str | None,
    lease_idempotency_key: str | None,
    lease_expected_version: int | None,
    delegated_authority: bool,
    allow_user_gate_auto_acquire: bool,
    require_active_when_fence_supplied: bool,
) -> TransitionPlan:
    todo = snapshot.todo
    assert todo is not None
    lease = snapshot.lease
    time_active = bool(lease and lease.present and lease.active)
    effective = _lease_is_effective(snapshot, lease)
    explicit_fence = bool(
        lease_idempotency_key is not None or lease_expected_version is not None
    )
    auto_acquire = bool(
        snapshot.handoff_mode is HandoffMode.HARD_LEASE
        and not delegated_authority
        and allow_user_gate_auto_acquire
        and todo.role == "user"
        and todo.task_class == "user_gate"
    )
    if auto_acquire and not effective and not time_active:
        rejection = _lease_owner_rejection(snapshot, actor_agent_id)
        if rejection is not None:
            return _result(
                DecisionOutcome.REJECTED,
                "handoff_mode_requires_lease",
                lease_fence=LeaseFence.AUTO_ACQUIRE,
            )
        existing = lease or LeaseSnapshot()
        acquired = LeaseSnapshot(
            present=True,
            active=True,
            status="active",
            owner=actor_agent_id,
            idempotency_key=lease_idempotency_key or f"auto-{todo.todo_id}",
            version=_actual_version(existing) + 1,
            lease_epoch=existing.lease_epoch + 1,
            write_scopes=(),
            acquire_ttl_seconds=2700,
        )
        next_snapshot = replace(
            snapshot,
            lease=replace(acquired, active=False, status="released"),
        )
        return _result(
            DecisionOutcome.APPLY,
            "terminal_fence_verified",
            next_snapshot=next_snapshot,
            lease_fence=LeaseFence.AUTO_ACQUIRE,
        )
    if not effective:
        if (
            snapshot.handoff_mode is HandoffMode.HARD_LEASE
            and not delegated_authority
        ):
            return _result(
                DecisionOutcome.REJECTED,
                (
                    "handoff_mode_lease_claim_divergence"
                    if time_active
                    else "handoff_mode_requires_lease"
                ),
                lease_fence=LeaseFence.REQUIRED,
            )
        if explicit_fence and require_active_when_fence_supplied:
            return _result(
                DecisionOutcome.REJECTED,
                "lease_not_active",
            )
        return _result(
            DecisionOutcome.APPLY,
            "terminal_fence_not_required",
            next_snapshot=snapshot,
            lease_fence=(
                LeaseFence.DELEGATED_OVERRIDE
                if delegated_authority
                and snapshot.handoff_mode is HandoffMode.HARD_LEASE
                else LeaseFence.NOT_REQUIRED
            ),
        )
    assert lease is not None
    if lease_idempotency_key is None:
        return _result(
            DecisionOutcome.REJECTED,
            "lease_fence_required",
            lease_fence=LeaseFence.REQUIRED,
        )
    if (
        lease.owner != actor_agent_id
        or lease.idempotency_key != lease_idempotency_key
    ):
        return _result(
            DecisionOutcome.REJECTED,
            "lease_cas_mismatch",
            lease_fence=LeaseFence.REQUIRED,
        )
    if lease_expected_version is None:
        return _result(
            DecisionOutcome.REJECTED,
            "version_required",
            lease_fence=LeaseFence.REQUIRED,
        )
    if _version_conflict(lease, lease_expected_version):
        return _result(
            DecisionOutcome.CONFLICT,
            "version_mismatch",
            lease_fence=LeaseFence.REQUIRED,
        )
    next_snapshot = replace(
        snapshot,
        lease=replace(lease, active=False, status="released"),
    )
    return _result(
        DecisionOutcome.APPLY,
        "terminal_fence_verified",
        next_snapshot=next_snapshot,
        lease_fence=LeaseFence.REQUIRED,
    )


def _terminal_decision(
    snapshot: CoordinationSnapshot,
    command: TodoMutationCommand,
    *,
    authority_mode: str,
    ownership_gate: OwnershipGate,
) -> TransitionPlan:
    todo = snapshot.todo
    assert todo is not None
    if todo.status == "done":
        return _result(
            DecisionOutcome.NO_CHANGE,
            "terminal_replay",
            next_snapshot=snapshot,
            authority_mode=authority_mode,
            ownership_gate=ownership_gate,
            idempotent=True,
        )
    fence = _terminal_fence_decision(
        snapshot,
        actor_agent_id=command.actor_agent_id,
        lease_idempotency_key=command.lease_idempotency_key,
        lease_expected_version=command.lease_expected_version,
        delegated_authority=(
            authority_mode == "delegated_orchestration_override"
        ),
        allow_user_gate_auto_acquire=(
            command.allow_user_gate_auto_acquire
        ),
        require_active_when_fence_supplied=True,
    )
    if fence.outcome is not DecisionOutcome.APPLY:
        return replace(
            fence,
            authority_mode=authority_mode,
            ownership_gate=ownership_gate,
        )
    next_snapshot = fence.next_snapshot or snapshot
    return replace(
        fence,
        code="terminal_transition",
        next_snapshot=replace(
            next_snapshot,
            todo=_todo_after_command(todo, command),
        ),
        authority_mode=authority_mode,
        ownership_gate=ownership_gate,
    )


def ownership_gate_requirement(
    *,
    handoff_mode: HandoffMode,
    ownership_mutation: bool,
    authority_mode: str | None,
) -> OwnershipGate:
    """Route one claimed_by mutation on an existing todo into the holder gate.

    This is the single owner of the routing rule: only a hard_lease ownership
    mutation needs the holder gate, and the delegated orchestration override
    is the one audited door through it. Writers consult this instead of
    re-deriving the mode/door predicates at the edge.
    """

    if not ownership_mutation or handoff_mode is not HandoffMode.HARD_LEASE:
        return OwnershipGate.NOT_REQUIRED
    if authority_mode == "delegated_orchestration_override":
        return OwnershipGate.DELEGATED_OVERRIDE
    return OwnershipGate.REQUIRE_HOLDER


def _decide_todo(
    snapshot: CoordinationSnapshot,
    command: TodoMutationCommand,
) -> TransitionPlan:
    authority_mode, rejection = _authority_for_todo(snapshot, command)
    if rejection is not None:
        return _result(DecisionOutcome.REJECTED, rejection)
    assert authority_mode is not None and snapshot.todo is not None
    ownership_gate = ownership_gate_requirement(
        handoff_mode=snapshot.handoff_mode,
        ownership_mutation=command.ownership_mutation,
        authority_mode=authority_mode,
    )
    if ownership_gate is OwnershipGate.REQUIRE_HOLDER:
        lease = snapshot.lease
        if not lease or not lease.present or not lease.active:
            return _result(
                DecisionOutcome.REJECTED,
                "handoff_mode_requires_lease",
                authority_mode=authority_mode,
                ownership_gate=ownership_gate,
            )
        if lease.owner != command.actor_agent_id:
            return _result(
                DecisionOutcome.REJECTED,
                "handoff_mode_requires_lease",
                authority_mode=authority_mode,
                ownership_gate=ownership_gate,
            )
    if command.action in {TodoAction.COMPLETE, TodoAction.SUPERSEDE}:
        return _terminal_decision(
            snapshot,
            command,
            authority_mode=authority_mode,
            ownership_gate=ownership_gate,
        )
    return _result(
        DecisionOutcome.APPLY,
        "todo_transition",
        next_snapshot=replace(
            snapshot,
            todo=_todo_after_command(snapshot.todo, command),
        ),
        authority_mode=authority_mode,
        ownership_gate=ownership_gate,
    )


def _lease_handoff_rejection(snapshot: CoordinationSnapshot) -> str | None:
    if snapshot.handoff_mode is HandoffMode.SOFT_CLAIM:
        return "handoff_mode_forbids_lease"
    return None


def _decide_lease_mode_gate(
    snapshot: CoordinationSnapshot,
    command: LeaseModeGateCommand,
) -> TransitionPlan:
    if (
        command.action is not LeaseAction.RELEASE
        and (rejection := _lease_handoff_rejection(snapshot)) is not None
    ):
        return _result(DecisionOutcome.REJECTED, rejection)
    return _result(
        DecisionOutcome.APPLY,
        "lease_mutation_allowed",
        next_snapshot=snapshot,
    )


def _decide_lease_owner_eligibility(
    snapshot: CoordinationSnapshot,
    command: LeaseOwnerEligibilityCommand,
) -> TransitionPlan:
    rejection = _lease_owner_rejection(snapshot, command.owner)
    if rejection is not None:
        return _result(DecisionOutcome.REJECTED, rejection)
    return _result(
        DecisionOutcome.APPLY,
        "lease_owner_allowed",
        next_snapshot=snapshot,
    )


def _decide_acquire(
    snapshot: CoordinationSnapshot,
    command: LeaseAcquireCommand,
) -> TransitionPlan:
    todo = snapshot.todo
    lease = snapshot.lease
    payload = effect_runtime_result(
        "task_lease.acquire.decide",
        {
            "handoff_mode": snapshot.handoff_mode.value,
            "registered_agents": list(snapshot.registered_agents),
            "todo": (
                {
                    "todo_id": todo.todo_id,
                    "status": todo.status,
                    "claimed_by": todo.claimed_by,
                    "excluded_agents": sorted(todo.excluded_agents),
                }
                if todo is not None
                else None
            ),
            "lease": (
                {
                    "present": lease.present,
                    "active": lease.active,
                    "effective": _lease_is_effective(snapshot, lease),
                    "status": lease.status,
                    "owner": lease.owner,
                    "idempotency_key": lease.idempotency_key,
                    "version": lease.version,
                    "lease_epoch": lease.lease_epoch,
                    "write_scopes": list(lease.write_scopes),
                    "acquire_ttl_seconds": lease.acquire_ttl_seconds,
                }
                if lease is not None
                else None
            ),
            "other_leases": [
                {
                    "todo_id": other.todo_id,
                    "active": other.active,
                    "effective": other.effective,
                    "write_scopes": list(other.write_scopes),
                }
                for other in snapshot.other_leases
            ],
            "command": {
                "owner": command.owner,
                "idempotency_key": command.idempotency_key,
                "ttl_seconds": command.ttl_seconds,
                "write_scopes": list(command.write_scopes),
                "expected_version": command.expected_version,
            },
        },
    )
    if not isinstance(payload, dict):
        raise RuntimeError("native task-lease acquire decision must return an object")
    raw_outcome = payload.get("outcome")
    raw_code = payload.get("code")
    raw_idempotent = payload.get("idempotent")
    if (
        not isinstance(raw_outcome, str)
        or not isinstance(raw_code, str)
        or not isinstance(raw_idempotent, bool)
    ):
        raise RuntimeError("native task-lease acquire decision shape mismatch")
    try:
        outcome = DecisionOutcome(raw_outcome)
    except ValueError as exc:
        raise RuntimeError(
            f"native task-lease acquire decision has unsupported outcome: {raw_outcome}"
        ) from exc
    next_snapshot: CoordinationSnapshot | None = None
    if outcome is DecisionOutcome.APPLY:
        raw_next = payload.get("next_lease")
        if not isinstance(raw_next, dict):
            raise RuntimeError("native task-lease acquire apply result omitted next_lease")
        next_lease = _native_acquire_lease_snapshot(raw_next)
        next_snapshot = replace(snapshot, lease=next_lease)
    elif outcome is DecisionOutcome.NO_CHANGE:
        next_snapshot = snapshot
    return _result(
        outcome,
        raw_code,
        next_snapshot=next_snapshot,
        idempotent=raw_idempotent,
    )


def _native_acquire_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeError(f"native task-lease acquire {label} must be non-negative")
    return int(value)


def _native_acquire_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"native task-lease acquire {label} must be non-empty")
    return value


def _native_acquire_lease_snapshot(value: dict[str, Any]) -> LeaseSnapshot:
    if value.get("present") is not True or value.get("active") is not True:
        raise RuntimeError("native task-lease acquire apply lease must be active")
    raw_scopes = value.get("write_scopes")
    if not isinstance(raw_scopes, list) or any(
        not isinstance(scope, str) for scope in raw_scopes
    ):
        raise RuntimeError("native task-lease acquire write_scopes shape mismatch")
    return LeaseSnapshot(
        present=True,
        active=True,
        status=_native_acquire_string(value.get("status"), "status"),
        owner=_native_acquire_string(value.get("owner"), "owner"),
        idempotency_key=_native_acquire_string(
            value.get("idempotency_key"), "idempotency_key"
        ),
        version=_native_acquire_integer(value.get("version"), "version"),
        lease_epoch=_native_acquire_integer(
            value.get("lease_epoch"), "lease_epoch"
        ),
        write_scopes=tuple(raw_scopes),
        acquire_ttl_seconds=_native_acquire_integer(
            value.get("acquire_ttl_seconds"), "acquire_ttl_seconds"
        ),
    )


def _decide_renew(
    snapshot: CoordinationSnapshot,
    command: LeaseRenewCommand,
) -> TransitionPlan:
    handoff_rejection = _lease_handoff_rejection(snapshot)
    if handoff_rejection:
        return _result(DecisionOutcome.REJECTED, handoff_rejection)
    if command.expected_version is None:
        return _result(DecisionOutcome.REJECTED, "version_required")
    owner_rejection = _lease_owner_rejection(snapshot, command.owner)
    if owner_rejection:
        return _result(DecisionOutcome.REJECTED, owner_rejection)
    lease = snapshot.lease
    if _version_conflict(lease, command.expected_version):
        return _result(DecisionOutcome.CONFLICT, "version_mismatch")
    if not lease or not lease.present or not lease.active:
        return _result(DecisionOutcome.REJECTED, "lease_not_active")
    if lease.owner != command.owner or lease.idempotency_key != command.idempotency_key:
        return _result(DecisionOutcome.REJECTED, "lease_cas_mismatch")
    return _result(
        DecisionOutcome.APPLY,
        "lease_renew",
        next_snapshot=replace(
            snapshot,
            lease=replace(
                lease,
                version=lease.version + 1,
            ),
        ),
    )


def _decide_transfer(
    snapshot: CoordinationSnapshot,
    command: LeaseTransferCommand,
) -> TransitionPlan:
    handoff_rejection = _lease_handoff_rejection(snapshot)
    if handoff_rejection:
        return _result(DecisionOutcome.REJECTED, handoff_rejection)
    if command.expected_version is None:
        return _result(DecisionOutcome.REJECTED, "version_required")
    if command.owner not in snapshot.registered_agents:
        return _result(DecisionOutcome.REJECTED, "owner_not_registered")
    owner_rejection = _lease_owner_rejection(snapshot, command.new_owner)
    if owner_rejection:
        return _result(DecisionOutcome.REJECTED, owner_rejection)
    lease = snapshot.lease
    if _version_conflict(lease, command.expected_version):
        return _result(DecisionOutcome.CONFLICT, "version_mismatch")
    if not lease or not lease.present or not lease.active:
        return _result(DecisionOutcome.REJECTED, "lease_not_active")
    if lease.owner != command.owner or lease.idempotency_key != command.idempotency_key:
        return _result(DecisionOutcome.REJECTED, "lease_cas_mismatch")
    if command.new_idempotency_key == command.idempotency_key:
        return _result(DecisionOutcome.REJECTED, "idempotency_key_reuse")
    return _result(
        DecisionOutcome.APPLY,
        "lease_transfer",
        next_snapshot=replace(
            snapshot,
            lease=replace(
                lease,
                owner=command.new_owner,
                idempotency_key=command.new_idempotency_key,
                version=lease.version + 1,
                lease_epoch=lease.lease_epoch + 1,
            ),
        ),
    )


def _decide_release(
    snapshot: CoordinationSnapshot,
    command: LeaseReleaseCommand,
) -> TransitionPlan:
    lease = snapshot.lease
    if command.expected_version is None:
        return _result(DecisionOutcome.REJECTED, "version_required")
    if _version_conflict(lease, command.expected_version):
        return _result(DecisionOutcome.CONFLICT, "version_mismatch")
    if not lease or not lease.present:
        return _result(
            DecisionOutcome.NO_CHANGE,
            "lease_missing",
            next_snapshot=snapshot,
            idempotent=True,
        )
    if lease.status == "released":
        if lease.owner != command.owner or lease.idempotency_key != command.idempotency_key:
            return _result(DecisionOutcome.REJECTED, "lease_cas_mismatch")
        return _result(
            DecisionOutcome.NO_CHANGE,
            "lease_release_replay",
            next_snapshot=snapshot,
            idempotent=True,
        )
    if (
        lease.owner != command.owner or lease.idempotency_key != command.idempotency_key
    ):
        return _result(DecisionOutcome.REJECTED, "lease_cas_mismatch")
    return _result(
        DecisionOutcome.APPLY,
        "lease_release",
        next_snapshot=replace(
            snapshot,
            lease=replace(lease, active=False, status="released"),
        ),
    )


def _decide_handoff_transition(
    snapshot: CoordinationSnapshot,
    command: HandoffModeTransitionCommand,
) -> TransitionPlan:
    if snapshot.handoff_mode is command.requested_mode:
        return _result(
            DecisionOutcome.NO_CHANGE,
            "handoff_mode_unchanged",
            next_snapshot=snapshot,
            idempotent=True,
        )
    if snapshot.active_claimed_todo_ids or snapshot.active_lease_todo_ids:
        return _result(DecisionOutcome.REJECTED, "handoff_mode_not_quiescent")
    return _result(
        DecisionOutcome.APPLY,
        "handoff_mode_transition",
        next_snapshot=replace(snapshot, handoff_mode=command.requested_mode),
    )


def decide(
    snapshot: CoordinationSnapshot,
    command: CoordinationCommand,
) -> TransitionPlan:
    """Evaluate one normalized command without reading or writing state."""

    if isinstance(command, LeaseAcquireCommand):
        return _decide_acquire(snapshot, command)
    if _invalid_lease_snapshot(snapshot.lease):
        return _result(DecisionOutcome.REJECTED, "invalid_lease_snapshot")
    if isinstance(command, TodoMutationCommand):
        return _decide_todo(snapshot, command)
    if isinstance(command, LeaseRenewCommand):
        return _decide_renew(snapshot, command)
    if isinstance(command, LeaseTransferCommand):
        return _decide_transfer(snapshot, command)
    if isinstance(command, LeaseReleaseCommand):
        return _decide_release(snapshot, command)
    if isinstance(command, LeaseOwnerEligibilityCommand):
        return _decide_lease_owner_eligibility(snapshot, command)
    if isinstance(command, LeaseModeGateCommand):
        return _decide_lease_mode_gate(snapshot, command)
    if isinstance(command, TerminalFenceCommand):
        if snapshot.todo is None:
            return _result(DecisionOutcome.REJECTED, "todo_not_found")
        return _terminal_fence_decision(
            snapshot,
            actor_agent_id=command.actor_agent_id,
            lease_idempotency_key=command.lease_idempotency_key,
            lease_expected_version=command.lease_expected_version,
            delegated_authority=command.delegated_authority,
            allow_user_gate_auto_acquire=command.allow_user_gate_auto_acquire,
            require_active_when_fence_supplied=(
                command.require_active_when_fence_supplied
            ),
        )
    if isinstance(command, HandoffModeTransitionCommand):
        return _decide_handoff_transition(snapshot, command)
    raise TypeError(f"unsupported coordination command: {type(command).__name__}")
