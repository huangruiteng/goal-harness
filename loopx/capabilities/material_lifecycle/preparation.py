"""Read-only provider orchestration for backup-safe material migration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ._validation import compact_token
from .inventory import (
    build_material_migration_plan,
    build_material_store_inventory,
)


class MaterialInventoryProvider(Protocol):
    """Private adapter boundary for one read-only legacy material store."""

    provider_id: str

    def inspect(
        self,
        *,
        store_id: str,
        observed_at: str,
    ) -> MaterialStoreSnapshot: ...


@dataclass(frozen=True)
class MaterialStoreSnapshot:
    """Transient provider result; it carries metadata but never raw material."""

    provider_id: str
    store_id: str
    store_revision: str
    observed_at: str
    source_snapshot_ref: str
    backup_ref: str
    source_digest: str
    lifecycle_counts: Mapping[str, int] = field(repr=False)
    parse_error_refs: tuple[str, ...] = ()
    stable_ids_verified: bool = False
    backup_verified: bool = False
    source_unchanged_verified: bool = False


@dataclass(frozen=True)
class MaterialMigrationPreparation:
    """Runtime result built from existing inventory and migration packets."""

    inventory: Mapping[str, Any]
    migration_plan: Mapping[str, Any] | None
    readiness_blockers: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.migration_plan is not None and not self.readiness_blockers


def prepare_material_migration(
    *,
    provider: MaterialInventoryProvider,
    provider_id: str,
    goal_id: str,
    store_id: str,
    plan_id: str,
    target_schema: str,
    observed_at: str,
    rollback_ref: str,
    protected_material_refs: Sequence[str] | None = None,
) -> MaterialMigrationPreparation:
    """Inspect one legacy store and build a plan only after safety checks pass."""

    expected_provider_id = compact_token(provider_id, field="provider_id")
    actual_provider_id = compact_token(
        getattr(provider, "provider_id", ""),
        field="provider.provider_id",
    )
    if actual_provider_id != expected_provider_id:
        raise ValueError("material inventory provider identity does not match")

    expected_store_id = compact_token(store_id, field="store_id")
    snapshot = provider.inspect(
        store_id=expected_store_id,
        observed_at=observed_at,
    )
    if not isinstance(snapshot, MaterialStoreSnapshot):
        raise TypeError("material inventory provider must return MaterialStoreSnapshot")
    if compact_token(snapshot.provider_id, field="snapshot.provider_id") != (
        expected_provider_id
    ):
        raise ValueError("material snapshot provider identity does not match")
    if compact_token(snapshot.store_id, field="snapshot.store_id") != (
        expected_store_id
    ):
        raise ValueError("material snapshot store identity does not match")
    if not isinstance(snapshot.source_unchanged_verified, bool):
        raise ValueError("source_unchanged_verified must be a boolean")

    inventory = build_material_store_inventory(
        goal_id=goal_id,
        store_id=snapshot.store_id,
        store_revision=snapshot.store_revision,
        observed_at=snapshot.observed_at,
        source_snapshot_ref=snapshot.source_snapshot_ref,
        backup_ref=snapshot.backup_ref,
        source_digest=snapshot.source_digest,
        lifecycle_counts=snapshot.lifecycle_counts,
        parse_error_refs=snapshot.parse_error_refs,
        stable_ids_verified=snapshot.stable_ids_verified,
        backup_verified=snapshot.backup_verified,
    )

    blockers: list[str] = []
    if not snapshot.source_unchanged_verified:
        blockers.append("source_unchanged_unverified")
    if not snapshot.backup_verified:
        blockers.append("backup_unverified")
    if not snapshot.stable_ids_verified:
        blockers.append("stable_ids_unverified")
    if snapshot.parse_error_refs:
        blockers.append("parse_errors_present")

    if blockers:
        return MaterialMigrationPreparation(
            inventory=inventory,
            migration_plan=None,
            readiness_blockers=tuple(blockers),
        )

    plan = build_material_migration_plan(
        goal_id=goal_id,
        plan_id=plan_id,
        inventory_ref=str(inventory["inventory_ref"]),
        source_revision=snapshot.store_revision,
        target_schema=target_schema,
        observed_at=snapshot.observed_at,
        backup_ref=snapshot.backup_ref,
        rollback_ref=rollback_ref,
        expected_item_count=int(inventory["item_count"]),
        protected_material_refs=protected_material_refs,
    )
    return MaterialMigrationPreparation(
        inventory=inventory,
        migration_plan=plan,
        readiness_blockers=(),
    )
