from __future__ import annotations

from dataclasses import replace

import pytest

from loopx.capabilities.material_lifecycle import (
    MaterialAuthoritySnapshot,
    MaterialAuthorityTransition,
    MaterialDualReadReconciliation,
    MaterialStagedStore,
    apply_material_migration,
    build_material_migration_plan,
    build_material_store_inventory,
    rollback_material_migration,
)

OBSERVED_AT = "2026-07-26T04:30:00+00:00"


def migration_plan() -> dict[str, object]:
    inventory = build_material_store_inventory(
        goal_id="goal:material-example",
        store_id="store:learning-materials",
        store_revision="revision:42",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:revision-42",
        backup_ref="backup:revision-42",
        source_digest="sha256:0123456789abcdef",
        lifecycle_counts={"candidate": 30, "archived": 217},
        stable_ids_verified=True,
        backup_verified=True,
    )
    plan = build_material_migration_plan(
        goal_id="goal:material-example",
        plan_id="plan:migrate-v0",
        inventory_ref=str(inventory["inventory_ref"]),
        source_revision="revision:42",
        target_schema="material_store_v0",
        observed_at=OBSERVED_AT,
        backup_ref="backup:revision-42",
        rollback_ref="rollback:revision-42",
        expected_item_count=247,
    )
    return plan


class FakeApplyProvider:
    provider_id = "private-legacy-store"

    def __init__(self) -> None:
        self.authority_revision = "revision:42"
        self.calls: list[str] = []
        self.staged = MaterialStagedStore(
            provider_id=self.provider_id,
            store_id="store:learning-materials",
            source_revision="revision:42",
            target_revision="revision:43",
            target_schema="material_store_v0",
            target_store_ref="store-snapshot:revision-43",
            target_digest="sha256:fedcba9876543210",
            item_count=247,
            lifecycle_counts={"candidate": 30, "archived": 217},
            atomic_write_verified=True,
            readback_verified=True,
        )
        self.reconciliation = MaterialDualReadReconciliation(
            provider_id=self.provider_id,
            store_id="store:learning-materials",
            source_revision="revision:42",
            target_revision="revision:43",
            item_count=247,
            lifecycle_counts={"candidate": 30, "archived": 217},
            validation_ref="validation:dual-read-42-43",
            stable_ids_verified=True,
            content_mismatches=0,
        )

    def inspect_authority(
        self,
        *,
        store_id: str,
        observed_at: str,
    ) -> MaterialAuthoritySnapshot:
        self.calls.append("inspect")
        return MaterialAuthoritySnapshot(
            provider_id=self.provider_id,
            store_id=store_id,
            authority_revision=self.authority_revision,
            observed_at=observed_at,
        )

    def stage(
        self,
        *,
        store_id: str,
        plan_ref: str,
        source_revision: str,
        target_schema: str,
        owner_gate_ref: str,
        observed_at: str,
    ) -> MaterialStagedStore:
        self.calls.append("stage")
        return self.staged

    def reconcile(
        self,
        *,
        store_id: str,
        source_revision: str,
        target_revision: str,
        observed_at: str,
    ) -> MaterialDualReadReconciliation:
        self.calls.append("reconcile")
        return self.reconciliation

    def switch_authority(
        self,
        *,
        store_id: str,
        expected_revision: str,
        target_revision: str,
        owner_gate_ref: str,
        observed_at: str,
    ) -> MaterialAuthorityTransition:
        self.calls.append("switch")
        if self.authority_revision != expected_revision:
            raise ValueError("provider CAS failed")
        before_revision = self.authority_revision
        self.authority_revision = target_revision
        return MaterialAuthorityTransition(
            provider_id=self.provider_id,
            store_id=store_id,
            before_revision=before_revision,
            after_revision=target_revision,
            authority_ref=f"authority:{target_revision}",
            rollback_ref=f"rollback:{before_revision.replace(':', '-')}",
            atomic_write_verified=True,
            readback_verified=True,
        )


def apply(provider: FakeApplyProvider) -> dict[str, object]:
    return apply_material_migration(
        provider=provider,
        provider_id=provider.provider_id,
        store_id="store:learning-materials",
        migration_plan=migration_plan(),
        owner_gate_ref="owner-gate:material-cutover",
        receipt_id="receipt:material-cutover",
        observed_at=OBSERVED_AT,
    )


def test_apply_orders_cas_stage_reconcile_and_atomic_cutover() -> None:
    provider = FakeApplyProvider()

    receipt = apply(provider)

    assert provider.calls == ["inspect", "stage", "inspect", "reconcile", "switch"]
    assert provider.authority_revision == "revision:43"
    assert receipt["status"] == "applied"
    assert receipt["before_revision"] == "revision:42"
    assert receipt["after_revision"] == "revision:43"
    assert receipt["item_count"] == 247
    assert receipt["source_revision_cas_verified"] is True
    assert receipt["dual_read_verified"] is True
    assert receipt["atomic_write_verified"] is True
    assert receipt["readback_verified"] is True
    assert receipt["raw_content_captured"] is False
    assert receipt["private_locations_captured"] is False


def test_apply_fails_before_staging_when_source_revision_drifted() -> None:
    provider = FakeApplyProvider()
    provider.authority_revision = "revision:99"

    with pytest.raises(ValueError, match="CAS failed before staging"):
        apply(provider)

    assert provider.calls == ["inspect"]


def test_apply_does_not_cut_over_when_staging_or_reconciliation_is_unsafe() -> None:
    provider = FakeApplyProvider()
    provider.staged = replace(provider.staged, readback_verified=False)
    with pytest.raises(ValueError, match="readback_verified must be verified"):
        apply(provider)
    assert "switch" not in provider.calls
    assert provider.authority_revision == "revision:42"

    provider = FakeApplyProvider()
    provider.reconciliation = replace(
        provider.reconciliation,
        content_mismatches=1,
    )
    with pytest.raises(ValueError, match="content mismatches"):
        apply(provider)
    assert "switch" not in provider.calls
    assert provider.authority_revision == "revision:42"


def test_apply_rechecks_source_revision_after_staging() -> None:
    class DriftAfterStageProvider(FakeApplyProvider):
        def stage(self, **kwargs: str) -> MaterialStagedStore:
            result = super().stage(**kwargs)
            self.authority_revision = "revision:concurrent"
            return result

    provider = DriftAfterStageProvider()

    with pytest.raises(ValueError, match="CAS failed after staging"):
        apply(provider)

    assert provider.calls == ["inspect", "stage", "inspect"]
    assert "switch" not in provider.calls


def test_rollback_uses_owner_gated_authority_cas() -> None:
    provider = FakeApplyProvider()
    applied = apply(provider)
    provider.calls.clear()

    receipt = rollback_material_migration(
        provider=provider,
        provider_id=provider.provider_id,
        apply_receipt=applied,
        owner_gate_ref="owner-gate:material-rollback",
        receipt_id="receipt:material-rollback",
        observed_at=OBSERVED_AT,
    )

    assert provider.calls == ["inspect", "switch"]
    assert provider.authority_revision == "revision:42"
    assert receipt["status"] == "rolled_back"
    assert receipt["before_revision"] == "revision:43"
    assert receipt["after_revision"] == "revision:42"
    assert receipt["source_revision_cas_verified"] is True
    assert receipt["atomic_write_verified"] is True
    assert receipt["readback_verified"] is True


def test_rollback_rejects_authority_drift() -> None:
    provider = FakeApplyProvider()
    applied = apply(provider)
    provider.authority_revision = "revision:44"
    provider.calls.clear()

    with pytest.raises(ValueError, match="rollback authority revision CAS failed"):
        rollback_material_migration(
            provider=provider,
            provider_id=provider.provider_id,
            apply_receipt=applied,
            owner_gate_ref="owner-gate:material-rollback",
            receipt_id="receipt:material-rollback",
            observed_at=OBSERVED_AT,
        )

    assert provider.calls == ["inspect"]


def test_apply_rejects_private_refs_and_provider_identity_drift() -> None:
    provider = FakeApplyProvider()
    provider.staged = replace(
        provider.staged,
        target_store_ref="/Users/example/private-store",
    )
    with pytest.raises(ValueError, match="local path"):
        apply(provider)

    provider = FakeApplyProvider()
    provider.provider_id = "other-provider"
    with pytest.raises(ValueError, match="provider identity"):
        apply_material_migration(
            provider=provider,
            provider_id="private-legacy-store",
            store_id="store:learning-materials",
            migration_plan=migration_plan(),
            owner_gate_ref="owner-gate:material-cutover",
            receipt_id="receipt:material-cutover",
            observed_at=OBSERVED_AT,
        )


def test_apply_rejects_unsafe_or_unprepared_plan_payloads() -> None:
    provider = FakeApplyProvider()
    unsafe = migration_plan()
    unsafe["raw_content"] = "private source body"
    with pytest.raises(ValueError, match="unsafe fields"):
        apply_material_migration(
            provider=provider,
            provider_id=provider.provider_id,
            store_id="store:learning-materials",
            migration_plan=unsafe,
            owner_gate_ref="owner-gate:material-cutover",
            receipt_id="receipt:material-cutover",
            observed_at=OBSERVED_AT,
        )

    unprepared = migration_plan()
    unprepared["owner_gate_required"] = False
    with pytest.raises(ValueError, match="must require an owner gate"):
        apply_material_migration(
            provider=provider,
            provider_id=provider.provider_id,
            store_id="store:learning-materials",
            migration_plan=unprepared,
            owner_gate_ref="owner-gate:material-cutover",
            receipt_id="receipt:material-cutover",
            observed_at=OBSERVED_AT,
        )
