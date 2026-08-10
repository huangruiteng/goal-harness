"""Task-lease adapter for the shared typed settlement algebra.

Wraps the existing task_lease acquire path with typed identity, receipt,
and failure semantics so it participates in the same conformance, fault/replay,
and incident-replay coverage as the quota and Turn adapters.

Pure decision logic (owner eligibility, conflict detection, lease persistence)
remains in the owning ``task_lease`` module.  This adapter only models the
orchestration as a typed settlement chain.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loopx.control_plane.effect_program import (
    SettlementFailureKind,
    SettlementIdentity,
    SettlementPlan,
    SettlementReceipt,
    SettlementResult,
    SettlementStep,
    SettlementStepKind,
)
from loopx.control_plane.work_items.task_lease import (
    TaskLeaseError,
    acquire_task_lease,
    active_conflicts,
    lease_is_active,
    normalize_goal_id,
    normalize_idempotency_key,
    normalize_lease_todo_id,
    normalize_owner,
    normalize_ttl_seconds,
    read_lease,
    require_task_lease_owner_allowed,
    task_lease_path,
)

__all__ = [
    "build_task_lease_settlement_plan",
    "commit_task_lease_acquire",
    "execute_task_lease_settlement",
    "resolve_task_lease_validation",
]


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _typed_failure(
    *,
    kind: SettlementFailureKind,
    step_kind: SettlementStepKind,
    reason: str,
    code: str | None = None,
    task_lease_payload: dict[str, Any] | None = None,
) -> SettlementResult[Any]:
    details: dict[str, Any] = {}
    if code:
        details["task_lease_error_code"] = code
    if task_lease_payload:
        details["task_lease_payload"] = dict(task_lease_payload)
    return SettlementResult.failed(
        kind=kind,
        step_kind=step_kind,
        reason=reason,
        details=details or None,
    )



def _settlement_identity(
    *,
    goal_id: str,
    owner: str,
    todo_id: str,
    idempotency_key: str,
) -> SettlementIdentity:
    return SettlementIdentity(
        goal_id=normalize_goal_id(goal_id),
        agent_id=normalize_owner(owner),
        todo_id=normalize_lease_todo_id(todo_id),
        turn_instance_id=normalize_idempotency_key(idempotency_key),
    )


def build_task_lease_settlement_plan(
    *,
    goal_id: str,
    owner: str,
    todo_id: str,
    idempotency_key: str,
    write_scopes: list[str] | None = None,
    ttl_seconds: int | None = None,
) -> SettlementPlan:
    """Build a typed settlement plan for a task-lease acquire.

    The plan uses two ordered steps: validation (identity + eligibility +
    no-conflicts check) and acquire (committed file write). The scheduler
    is deliberately left outside the settlement boundary.
    """
    identity = _settlement_identity(
        goal_id=goal_id,
        owner=owner,
        todo_id=todo_id,
        idempotency_key=idempotency_key,
    )
    normalized_scopes = sorted(set(write_scopes or []))
    normalized_ttl = normalize_ttl_seconds(ttl_seconds)
    effect_ref = "$.identity.effect_id"
    return SettlementPlan(
        identity=identity,
        steps=(
            SettlementStep(
                kind=SettlementStepKind.VALIDATION,
                owner="agent",
                precondition=(
                    "owner is registered and eligible for this todo; "
                    "no active lease with different owner/key exists; "
                    "no write-scope conflict with another active lease"
                ),
                idempotency_key_ref=effect_ref,
                expected_receipt="task_lease_validation_receipt",
            ),
            SettlementStep(
                kind=SettlementStepKind.DURABLE_WRITEBACK,
                owner="agent",
                precondition=(
                    "validation succeeded; lease file can be committed"
                ),
                idempotency_key_ref=effect_ref,
                expected_receipt="task_lease_acquire_receipt",
                command_template=(
                    f"loopx task-lease acquire --goal-id {identity.goal_id}"
                    f" --todo-id {identity.todo_id}"
                    f" --owner {identity.agent_id}"
                    f" --ttl {normalized_ttl}"
                    + (
                        "".join(f" --write-scope {s}" for s in normalized_scopes)
                        if normalized_scopes
                        else ""
                    )
                ),
            ),
        ),
    )


def resolve_task_lease_validation(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    owner: str,
    todo_id: str,
    idempotency_key: str,
    write_scopes: list[str] | None = None,
) -> SettlementResult[SettlementIdentity]:
    """Validate task-lease acquire preconditions.

    Returns a typed result: either a pure identity with a validation receipt,
    or a typed failure that short-circuits the acquire step.
    """
    try:
        normalized_goal_id = normalize_goal_id(goal_id)
    except ValueError as exc:
        return _typed_failure(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
            code="invalid_goal_id",
        )
    try:
        normalized_owner = normalize_owner(owner)
    except ValueError as exc:
        return _typed_failure(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
            code="invalid_owner",
        )
    try:
        normalized_todo_id = normalize_lease_todo_id(todo_id)
    except ValueError as exc:
        return _typed_failure(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
            code="invalid_todo_id",
        )
    try:
        normalized_key = normalize_idempotency_key(idempotency_key)
    except ValueError as exc:
        return _typed_failure(
            kind=SettlementFailureKind.INVALID_IDENTITY,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
            code="invalid_idempotency_key",
        )

    identity = SettlementIdentity(
        goal_id=normalized_goal_id,
        agent_id=normalized_owner,
        todo_id=normalized_todo_id,
        turn_instance_id=normalized_key,
    )

    # --- owner eligibility (pure decision, owned by task_lease module) ---
    try:
        require_task_lease_owner_allowed(
            registry_path=registry_path,
            goal_id=normalized_goal_id,
            todo_id=normalized_todo_id,
            owner=normalized_owner,
        )
    except ValueError as exc:
        return _typed_failure(
            kind=SettlementFailureKind.PERMISSION_DENIED,
            step_kind=SettlementStepKind.VALIDATION,
            reason=str(exc),
            code=getattr(exc, "code", None),
        )

    # --- existing active lease check ---
    lease_path = task_lease_path(
        runtime_root=runtime_root,
        goal_id=normalized_goal_id,
        todo_id=normalized_todo_id,
    )
    existing = read_lease(lease_path)
    if existing is not None and lease_is_active(existing):
        existing_owner = str(existing.get("owner") or "")
        existing_key = str(existing.get("idempotency_key") or "")
        if existing_owner == normalized_owner and existing_key == normalized_key:
            # Same owner + key — would be idempotent; surface as already-settled
            return SettlementResult.pure(
                identity,
                receipts=(
                    SettlementReceipt(
                        step_kind=SettlementStepKind.VALIDATION,
                        status="idempotent",
                        effect_id=identity.effect_id,
                        source_ref=str(lease_path),
                    ),
                ),
            )
        return SettlementResult.failed(
            kind=SettlementFailureKind.WRITEBACK_REJECTED,
            step_kind=SettlementStepKind.VALIDATION,
            reason="todo already has an active lease with a different owner or key",
            details={
                "task_lease_error_code": "todo_lease_conflict",
                "lease": existing,
                "lease_path": str(lease_path),
            },
        )

    # --- write-scope conflict check ---
    normalized_scopes = sorted(set(write_scopes or []))
    if normalized_scopes:
        conflicts = active_conflicts(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=normalized_goal_id,
            todo_id=normalized_todo_id,
            write_scopes=normalized_scopes,
            at=_now_utc(),
        )
        if conflicts:
            return SettlementResult.failed(
                kind=SettlementFailureKind.WRITEBACK_REJECTED,
                step_kind=SettlementStepKind.VALIDATION,
                reason=f"write scopes overlap {len(conflicts)} active lease(s)",
                details={
                    "task_lease_error_code": "write_scope_conflict",
                    "conflicts": conflicts,
                },
            )

    return SettlementResult.pure(
        identity,
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.VALIDATION,
                status="committed",
                effect_id=identity.effect_id,
                source_ref=str(lease_path),
            ),
        ),
    )


def _map_task_lease_error(exc: TaskLeaseError) -> SettlementResult[dict[str, Any]]:
    """Map a ``TaskLeaseError`` raised by ``acquire_task_lease`` onto a typed failure."""
    code = exc.code
    if code in (
        "invalid_goal_id",
        "invalid_todo_id",
        "invalid_owner",
        "invalid_idempotency_key",
        "invalid_ttl",
        "idempotency_key_reuse",
    ):
        kind = SettlementFailureKind.INVALID_IDENTITY
    elif code in (
        "owner_not_registered",
        "todo_not_found",
        "todo_not_open",
        "owner_excluded_from_todo",
        "owner_conflicts_with_claim",
    ):
        kind = SettlementFailureKind.PERMISSION_DENIED
    else:
        kind = SettlementFailureKind.WRITEBACK_REJECTED
    return _typed_failure(
        kind=kind,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        reason=str(exc),
        code=exc.code,
        task_lease_payload=exc.payload,
    )


def commit_task_lease_acquire(
    identity: SettlementIdentity,
    *,
    registry_path: Path,
    runtime_root: Path,
    write_scopes: list[str] | None = None,
    ttl_seconds: int | None = None,
    expected_version: int | None = None,
    acquire: bool = True,
) -> SettlementResult[dict[str, Any]]:
    """Commit the task-lease file via ``acquire_task_lease``, producing a typed receipt.

    Routes through the owning module's ``acquire_task_lease`` so that the
    per-goal ``exclusive_file_lock``, ``expected_version`` CAS, idempotency-key
    parameter matching, and write-scope/ttl consistency checks are enforced
    atomically — the same path every other caller takes.

    When *acquire* is ``False`` the step is skipped (no-op receipt).  That
    path is used by the semantic oracle to test failure short-circuiting.
    """
    if not acquire:
        return SettlementResult.failed(
            kind=SettlementFailureKind.WRITEBACK_REJECTED,
            step_kind=SettlementStepKind.DURABLE_WRITEBACK,
            reason="task lease acquire rejected by settlement oracle",
        )
    try:
        result = acquire_task_lease(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=identity.goal_id,
            todo_id=identity.todo_id,
            owner=identity.agent_id,
            idempotency_key=identity.turn_instance_id,
            ttl_seconds=ttl_seconds,
            write_scopes=write_scopes,
            expected_version=expected_version,
        )
    except TaskLeaseError as exc:
        return _map_task_lease_error(exc)
    lease_path = str(result.get("lease_path", ""))
    return SettlementResult.pure(
        result["lease"],
        receipts=(
            SettlementReceipt(
                step_kind=SettlementStepKind.DURABLE_WRITEBACK,
                status="committed" if result.get("acquired") else "idempotent",
                effect_id=identity.effect_id,
                source_ref=lease_path,
            ),
        ),
    )


def execute_task_lease_settlement(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    owner: str,
    todo_id: str,
    idempotency_key: str,
    write_scopes: list[str] | None = None,
    ttl_seconds: int | None = None,
    expected_version: int | None = None,
    acquire: bool = True,
) -> SettlementResult[dict[str, Any]]:
    """Bind validation → acquire for the task-lease settlement adapter.

    Pure decision logic (owner eligibility, conflict detection) lives in the
    owning ``task_lease`` module.  This function only orchestrates the typed
    settlement chain.
    """
    return (
        resolve_task_lease_validation(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            owner=owner,
            todo_id=todo_id,
            idempotency_key=idempotency_key,
            write_scopes=write_scopes,
        )
        .bind(
            lambda identity: commit_task_lease_acquire(
                identity,
                registry_path=registry_path,
                runtime_root=runtime_root,
                write_scopes=write_scopes,
                ttl_seconds=ttl_seconds,
                expected_version=expected_version,
                acquire=acquire,
            )
        )
    )
