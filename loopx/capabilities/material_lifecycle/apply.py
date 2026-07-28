"""Owner-gated apply and rollback orchestration for material migrations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ._validation import (
    capability_contract,
    check_record_keys,
    compact_token,
    iso_timestamp,
    nonnegative_int,
    packet_ref,
)
from .inventory import (
    MATERIAL_LIFECYCLE_STATES,
    MATERIAL_MIGRATION_PLAN_SCHEMA_VERSION,
)

MATERIAL_MIGRATION_APPLY_RECEIPT_SCHEMA_VERSION = "material_migration_apply_receipt_v0"
MATERIAL_MIGRATION_ROLLBACK_RECEIPT_SCHEMA_VERSION = (
    "material_migration_rollback_receipt_v0"
)


class MaterialMigrationApplyProvider(Protocol):
    """Private adapter boundary for staged writes and authority-pointer CAS."""

    provider_id: str

    def inspect_authority(
        self,
        *,
        store_id: str,
        observed_at: str,
    ) -> MaterialAuthoritySnapshot: ...

    def stage(
        self,
        *,
        store_id: str,
        plan_ref: str,
        source_revision: str,
        target_schema: str,
        owner_gate_ref: str,
        observed_at: str,
    ) -> MaterialStagedStore: ...

    def reconcile(
        self,
        *,
        store_id: str,
        source_revision: str,
        target_revision: str,
        observed_at: str,
    ) -> MaterialDualReadReconciliation: ...

    def switch_authority(
        self,
        *,
        store_id: str,
        expected_revision: str,
        target_revision: str,
        owner_gate_ref: str,
        observed_at: str,
    ) -> MaterialAuthorityTransition: ...


@dataclass(frozen=True)
class MaterialAuthoritySnapshot:
    """Current authority pointer observed by a private provider."""

    provider_id: str
    store_id: str
    authority_revision: str
    observed_at: str


@dataclass(frozen=True)
class MaterialStagedStore:
    """Validated staging result without raw content or private locations."""

    provider_id: str
    store_id: str
    source_revision: str
    target_revision: str
    target_schema: str
    target_store_ref: str
    target_digest: str
    item_count: int
    lifecycle_counts: Mapping[str, int] = field(repr=False)
    atomic_write_verified: bool = False
    readback_verified: bool = False


@dataclass(frozen=True)
class MaterialDualReadReconciliation:
    """Source/target parity result produced before authority cutover."""

    provider_id: str
    store_id: str
    source_revision: str
    target_revision: str
    item_count: int
    lifecycle_counts: Mapping[str, int] = field(repr=False)
    validation_ref: str = ""
    stable_ids_verified: bool = False
    content_mismatches: int = 0


@dataclass(frozen=True)
class MaterialAuthorityTransition:
    """Atomic authority-pointer transition with verified readback."""

    provider_id: str
    store_id: str
    before_revision: str
    after_revision: str
    authority_ref: str
    rollback_ref: str
    atomic_write_verified: bool = False
    readback_verified: bool = False


def _provider_identity(
    provider: MaterialMigrationApplyProvider,
    *,
    provider_id: str,
) -> str:
    expected = compact_token(provider_id, field="provider_id")
    actual = compact_token(
        getattr(provider, "provider_id", ""),
        field="provider.provider_id",
    )
    if actual != expected:
        raise ValueError("material apply provider identity does not match")
    return expected


def _validate_identity(
    value: Any,
    *,
    expected_provider_id: str,
    expected_store_id: str,
    field: str,
) -> None:
    if compact_token(value.provider_id, field=f"{field}.provider_id") != (
        expected_provider_id
    ):
        raise ValueError(f"{field} provider identity does not match")
    if compact_token(value.store_id, field=f"{field}.store_id") != expected_store_id:
        raise ValueError(f"{field} store identity does not match")


def _lifecycle_counts(
    value: Mapping[str, int],
    *,
    field: str,
) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be an object")
    unexpected = sorted(set(value) - MATERIAL_LIFECYCLE_STATES)
    if unexpected:
        raise ValueError(
            f"{field} contains unsupported states: {', '.join(unexpected)}"
        )
    return {
        state: nonnegative_int(value.get(state, 0), field=f"{field}.{state}")
        for state in sorted(MATERIAL_LIFECYCLE_STATES)
    }


def _verified_boolean(value: Any, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a boolean")
    if not value:
        raise ValueError(f"{field} must be verified")
    return value


def _migration_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, Mapping):
        raise TypeError("migration_plan must be an object")
    check_record_keys(
        plan,
        field="migration_plan",
        allowed={
            "backup_ref",
            "capability",
            "cutover_mode",
            "expected_item_count",
            "goal_id",
            "inventory_ref",
            "observed_at",
            "owner_gate_required",
            "phases",
            "plan_id",
            "plan_ref",
            "private_locations_captured",
            "protected_material_refs",
            "raw_content_captured",
            "rollback_ref",
            "schema_version",
            "source_mutation_authorized",
            "source_revision",
            "target_schema",
            "visibility",
        },
        required={
            "backup_ref",
            "expected_item_count",
            "goal_id",
            "inventory_ref",
            "owner_gate_required",
            "plan_ref",
            "rollback_ref",
            "schema_version",
            "source_mutation_authorized",
            "source_revision",
            "target_schema",
        },
    )
    if plan.get("schema_version") != MATERIAL_MIGRATION_PLAN_SCHEMA_VERSION:
        raise ValueError("migration_plan has an unsupported schema_version")
    if plan.get("owner_gate_required") is not True:
        raise ValueError("migration_plan must require an owner gate")
    if plan.get("source_mutation_authorized") is not False:
        raise ValueError("migration_plan must not authorize source mutation")
    if plan.get("raw_content_captured") is not False:
        raise ValueError("migration_plan must not capture raw content")
    if plan.get("private_locations_captured") is not False:
        raise ValueError("migration_plan must not capture private locations")
    return {
        "goal_id": compact_token(plan.get("goal_id"), field="migration_plan.goal_id"),
        "plan_ref": compact_token(
            plan.get("plan_ref"),
            field="migration_plan.plan_ref",
        ),
        "inventory_ref": compact_token(
            plan.get("inventory_ref"),
            field="migration_plan.inventory_ref",
        ),
        "source_revision": compact_token(
            plan.get("source_revision"),
            field="migration_plan.source_revision",
        ),
        "target_schema": compact_token(
            plan.get("target_schema"),
            field="migration_plan.target_schema",
        ),
        "expected_item_count": nonnegative_int(
            plan.get("expected_item_count"),
            field="migration_plan.expected_item_count",
        ),
        "backup_ref": compact_token(
            plan.get("backup_ref"),
            field="migration_plan.backup_ref",
        ),
        "rollback_ref": compact_token(
            plan.get("rollback_ref"),
            field="migration_plan.rollback_ref",
        ),
    }


def _authority_snapshot(
    provider: MaterialMigrationApplyProvider,
    *,
    provider_id: str,
    store_id: str,
    observed_at: str,
) -> MaterialAuthoritySnapshot:
    snapshot = provider.inspect_authority(
        store_id=store_id,
        observed_at=observed_at,
    )
    if not isinstance(snapshot, MaterialAuthoritySnapshot):
        raise TypeError("material apply provider must return MaterialAuthoritySnapshot")
    _validate_identity(
        snapshot,
        expected_provider_id=provider_id,
        expected_store_id=store_id,
        field="authority_snapshot",
    )
    iso_timestamp(snapshot.observed_at, field="authority_snapshot.observed_at")
    compact_token(
        snapshot.authority_revision,
        field="authority_snapshot.authority_revision",
    )
    return snapshot


def apply_material_migration(
    *,
    provider: MaterialMigrationApplyProvider,
    provider_id: str,
    store_id: str,
    migration_plan: Mapping[str, Any],
    owner_gate_ref: str,
    receipt_id: str,
    observed_at: str,
) -> dict[str, Any]:
    """Apply a prepared migration only after CAS, parity, and owner validation."""

    expected_provider_id = _provider_identity(provider, provider_id=provider_id)
    normalized_plan = _migration_plan(migration_plan)
    expected_store_id = compact_token(store_id, field="store_id")
    source_revision = normalized_plan["source_revision"]
    normalized_observed_at = iso_timestamp(observed_at, field="observed_at")
    normalized_owner_gate_ref = compact_token(
        owner_gate_ref,
        field="owner_gate_ref",
    )

    before = _authority_snapshot(
        provider,
        provider_id=expected_provider_id,
        store_id=expected_store_id,
        observed_at=normalized_observed_at,
    )
    if before.authority_revision != source_revision:
        raise ValueError("source revision CAS failed before staging")

    staged = provider.stage(
        store_id=expected_store_id,
        plan_ref=normalized_plan["plan_ref"],
        source_revision=source_revision,
        target_schema=normalized_plan["target_schema"],
        owner_gate_ref=normalized_owner_gate_ref,
        observed_at=normalized_observed_at,
    )
    if not isinstance(staged, MaterialStagedStore):
        raise TypeError("material apply provider must return MaterialStagedStore")
    _validate_identity(
        staged,
        expected_provider_id=expected_provider_id,
        expected_store_id=expected_store_id,
        field="staged_store",
    )
    if compact_token(staged.source_revision, field="staged_store.source_revision") != (
        source_revision
    ):
        raise ValueError("staged store source revision does not match")
    target_revision = compact_token(
        staged.target_revision,
        field="staged_store.target_revision",
    )
    if target_revision == source_revision:
        raise ValueError("target revision must differ from source revision")
    if (
        compact_token(staged.target_schema, field="staged_store.target_schema")
        != (normalized_plan["target_schema"])
    ):
        raise ValueError("staged store target schema does not match")
    target_store_ref = compact_token(
        staged.target_store_ref,
        field="staged_store.target_store_ref",
    )
    target_digest = compact_token(
        staged.target_digest,
        field="staged_store.target_digest",
    )
    staged_item_count = nonnegative_int(
        staged.item_count,
        field="staged_store.item_count",
    )
    staged_counts = _lifecycle_counts(
        staged.lifecycle_counts,
        field="staged_store.lifecycle_counts",
    )
    if staged_item_count != normalized_plan["expected_item_count"]:
        raise ValueError("staged store item count does not match migration plan")
    if sum(staged_counts.values()) != staged_item_count:
        raise ValueError("staged lifecycle counts do not match item count")
    _verified_boolean(
        staged.atomic_write_verified,
        field="staged_store.atomic_write_verified",
    )
    _verified_boolean(
        staged.readback_verified,
        field="staged_store.readback_verified",
    )

    before_cutover = _authority_snapshot(
        provider,
        provider_id=expected_provider_id,
        store_id=expected_store_id,
        observed_at=normalized_observed_at,
    )
    if before_cutover.authority_revision != source_revision:
        raise ValueError("source revision CAS failed after staging")

    reconciliation = provider.reconcile(
        store_id=expected_store_id,
        source_revision=source_revision,
        target_revision=target_revision,
        observed_at=normalized_observed_at,
    )
    if not isinstance(reconciliation, MaterialDualReadReconciliation):
        raise TypeError(
            "material apply provider must return MaterialDualReadReconciliation"
        )
    _validate_identity(
        reconciliation,
        expected_provider_id=expected_provider_id,
        expected_store_id=expected_store_id,
        field="reconciliation",
    )
    if (
        compact_token(
            reconciliation.source_revision,
            field="reconciliation.source_revision",
        )
        != source_revision
    ):
        raise ValueError("reconciliation source revision does not match")
    if (
        compact_token(
            reconciliation.target_revision,
            field="reconciliation.target_revision",
        )
        != target_revision
    ):
        raise ValueError("reconciliation target revision does not match")
    reconciled_item_count = nonnegative_int(
        reconciliation.item_count,
        field="reconciliation.item_count",
    )
    reconciled_counts = _lifecycle_counts(
        reconciliation.lifecycle_counts,
        field="reconciliation.lifecycle_counts",
    )
    if reconciled_item_count != staged_item_count:
        raise ValueError("dual-read item count does not match staged store")
    if reconciled_counts != staged_counts:
        raise ValueError("dual-read lifecycle counts do not match staged store")
    _verified_boolean(
        reconciliation.stable_ids_verified,
        field="reconciliation.stable_ids_verified",
    )
    if nonnegative_int(
        reconciliation.content_mismatches,
        field="reconciliation.content_mismatches",
    ):
        raise ValueError("dual-read reconciliation contains content mismatches")
    validation_ref = compact_token(
        reconciliation.validation_ref,
        field="reconciliation.validation_ref",
    )

    transition = provider.switch_authority(
        store_id=expected_store_id,
        expected_revision=source_revision,
        target_revision=target_revision,
        owner_gate_ref=normalized_owner_gate_ref,
        observed_at=normalized_observed_at,
    )
    if not isinstance(transition, MaterialAuthorityTransition):
        raise TypeError(
            "material apply provider must return MaterialAuthorityTransition"
        )
    _validate_identity(
        transition,
        expected_provider_id=expected_provider_id,
        expected_store_id=expected_store_id,
        field="authority_transition",
    )
    if (
        compact_token(
            transition.before_revision,
            field="authority_transition.before_revision",
        )
        != source_revision
    ):
        raise ValueError("authority transition before revision does not match")
    if (
        compact_token(
            transition.after_revision,
            field="authority_transition.after_revision",
        )
        != target_revision
    ):
        raise ValueError("authority transition after revision does not match")
    authority_ref = compact_token(
        transition.authority_ref,
        field="authority_transition.authority_ref",
    )
    rollback_ref = compact_token(
        transition.rollback_ref,
        field="authority_transition.rollback_ref",
    )
    if rollback_ref != normalized_plan["rollback_ref"]:
        raise ValueError("authority transition rollback reference does not match")
    _verified_boolean(
        transition.atomic_write_verified,
        field="authority_transition.atomic_write_verified",
    )
    _verified_boolean(
        transition.readback_verified,
        field="authority_transition.readback_verified",
    )

    receipt: dict[str, Any] = {
        "schema_version": MATERIAL_MIGRATION_APPLY_RECEIPT_SCHEMA_VERSION,
        "goal_id": normalized_plan["goal_id"],
        "receipt_id": compact_token(receipt_id, field="receipt_id"),
        "plan_ref": normalized_plan["plan_ref"],
        "inventory_ref": normalized_plan["inventory_ref"],
        "provider_id": expected_provider_id,
        "store_id": expected_store_id,
        "observed_at": normalized_observed_at,
        "status": "applied",
        "owner_gate_ref": normalized_owner_gate_ref,
        "before_revision": source_revision,
        "after_revision": target_revision,
        "target_schema": normalized_plan["target_schema"],
        "target_store_ref": target_store_ref,
        "target_digest": target_digest,
        "item_count": staged_item_count,
        "lifecycle_counts": staged_counts,
        "backup_ref": normalized_plan["backup_ref"],
        "validation_ref": validation_ref,
        "authority_ref": authority_ref,
        "rollback_ref": rollback_ref,
        "source_revision_cas_verified": True,
        "atomic_write_verified": True,
        "readback_verified": True,
        "dual_read_verified": True,
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="migration_apply_receipt"),
        "raw_content_captured": False,
        "private_locations_captured": False,
    }
    receipt["receipt_ref"] = packet_ref("material-migration-apply", receipt)
    return receipt


def rollback_material_migration(
    *,
    provider: MaterialMigrationApplyProvider,
    provider_id: str,
    apply_receipt: Mapping[str, Any],
    owner_gate_ref: str,
    receipt_id: str,
    observed_at: str,
) -> dict[str, Any]:
    """Roll back one applied migration through the same authority-pointer CAS."""

    if not isinstance(apply_receipt, Mapping):
        raise TypeError("apply_receipt must be an object")
    if (
        apply_receipt.get("schema_version")
        != MATERIAL_MIGRATION_APPLY_RECEIPT_SCHEMA_VERSION
    ):
        raise ValueError("apply_receipt has an unsupported schema_version")
    if apply_receipt.get("status") != "applied":
        raise ValueError("apply_receipt must record an applied migration")

    expected_provider_id = _provider_identity(provider, provider_id=provider_id)
    receipt_provider_id = compact_token(
        apply_receipt.get("provider_id"),
        field="apply_receipt.provider_id",
    )
    if receipt_provider_id != expected_provider_id:
        raise ValueError("apply receipt provider identity does not match")
    store_id = compact_token(
        apply_receipt.get("store_id"),
        field="apply_receipt.store_id",
    )
    source_revision = compact_token(
        apply_receipt.get("before_revision"),
        field="apply_receipt.before_revision",
    )
    current_revision = compact_token(
        apply_receipt.get("after_revision"),
        field="apply_receipt.after_revision",
    )
    normalized_observed_at = iso_timestamp(observed_at, field="observed_at")
    normalized_owner_gate_ref = compact_token(
        owner_gate_ref,
        field="owner_gate_ref",
    )

    current = _authority_snapshot(
        provider,
        provider_id=expected_provider_id,
        store_id=store_id,
        observed_at=normalized_observed_at,
    )
    if current.authority_revision != current_revision:
        raise ValueError("rollback authority revision CAS failed")

    transition = provider.switch_authority(
        store_id=store_id,
        expected_revision=current_revision,
        target_revision=source_revision,
        owner_gate_ref=normalized_owner_gate_ref,
        observed_at=normalized_observed_at,
    )
    if not isinstance(transition, MaterialAuthorityTransition):
        raise TypeError(
            "material apply provider must return MaterialAuthorityTransition"
        )
    _validate_identity(
        transition,
        expected_provider_id=expected_provider_id,
        expected_store_id=store_id,
        field="rollback_transition",
    )
    if (
        compact_token(
            transition.before_revision,
            field="rollback_transition.before_revision",
        )
        != current_revision
    ):
        raise ValueError("rollback transition before revision does not match")
    if (
        compact_token(
            transition.after_revision,
            field="rollback_transition.after_revision",
        )
        != source_revision
    ):
        raise ValueError("rollback transition after revision does not match")
    _verified_boolean(
        transition.atomic_write_verified,
        field="rollback_transition.atomic_write_verified",
    )
    _verified_boolean(
        transition.readback_verified,
        field="rollback_transition.readback_verified",
    )

    receipt: dict[str, Any] = {
        "schema_version": MATERIAL_MIGRATION_ROLLBACK_RECEIPT_SCHEMA_VERSION,
        "goal_id": compact_token(
            apply_receipt.get("goal_id"),
            field="apply_receipt.goal_id",
        ),
        "receipt_id": compact_token(receipt_id, field="receipt_id"),
        "apply_receipt_ref": compact_token(
            apply_receipt.get("receipt_ref"),
            field="apply_receipt.receipt_ref",
        ),
        "provider_id": expected_provider_id,
        "store_id": store_id,
        "observed_at": normalized_observed_at,
        "status": "rolled_back",
        "owner_gate_ref": normalized_owner_gate_ref,
        "before_revision": current_revision,
        "after_revision": source_revision,
        "authority_ref": compact_token(
            transition.authority_ref,
            field="rollback_transition.authority_ref",
        ),
        "rollback_ref": compact_token(
            transition.rollback_ref,
            field="rollback_transition.rollback_ref",
        ),
        "source_revision_cas_verified": True,
        "atomic_write_verified": True,
        "readback_verified": True,
        "visibility": "public_safe",
        "capability": capability_contract(packet_role="migration_rollback_receipt"),
        "raw_content_captured": False,
        "private_locations_captured": False,
    }
    receipt["receipt_ref"] = packet_ref("material-migration-rollback", receipt)
    return receipt
