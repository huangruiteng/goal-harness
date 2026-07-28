from __future__ import annotations

from dataclasses import replace

import pytest

from loopx.capabilities.material_lifecycle import (
    MaterialMigrationPreparation,
    MaterialStoreSnapshot,
    prepare_material_migration,
)

OBSERVED_AT = "2026-07-25T22:55:00+00:00"


class FakeInventoryProvider:
    provider_id = "private-legacy-store"

    def __init__(self, snapshot: MaterialStoreSnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, str]] = []

    def inspect(
        self,
        *,
        store_id: str,
        observed_at: str,
    ) -> MaterialStoreSnapshot:
        self.calls.append((store_id, observed_at))
        return self.snapshot


def ready_snapshot() -> MaterialStoreSnapshot:
    return MaterialStoreSnapshot(
        provider_id="private-legacy-store",
        store_id="store:learning-materials",
        store_revision="revision:42",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:revision-42",
        backup_ref="backup:revision-42",
        source_digest="sha256:0123456789abcdef",
        lifecycle_counts={
            "candidate": 30,
            "active": 10,
            "archived": 200,
            "unread": 5,
            "carryover": 2,
        },
        stable_ids_verified=True,
        backup_verified=True,
        source_unchanged_verified=True,
    )


def prepare(provider: FakeInventoryProvider) -> MaterialMigrationPreparation:
    return prepare_material_migration(
        provider=provider,
        provider_id="private-legacy-store",
        goal_id="goal:material-example",
        store_id="store:learning-materials",
        plan_id="plan:migrate-v0",
        target_schema="material_store_v0",
        observed_at=OBSERVED_AT,
        rollback_ref="rollback:revision-42",
        protected_material_refs=["material:pinned"],
    )


def test_preparation_builds_existing_packets_without_source_write_surface() -> None:
    provider = FakeInventoryProvider(ready_snapshot())

    first = prepare(provider)
    second = prepare(provider)

    assert first == second
    assert first.ready is True
    assert first.readiness_blockers == ()
    assert first.inventory["item_count"] == 247
    assert first.inventory["source_mutation_authorized"] is False
    assert first.migration_plan is not None
    assert first.migration_plan["expected_item_count"] == 247
    assert first.migration_plan["source_mutation_authorized"] is False
    assert provider.calls == [
        ("store:learning-materials", OBSERVED_AT),
        ("store:learning-materials", OBSERVED_AT),
    ]
    assert not hasattr(provider, "apply")


@pytest.mark.parametrize(
    ("snapshot", "expected_blockers"),
    [
        (
            replace(ready_snapshot(), source_unchanged_verified=False),
            ("source_unchanged_unverified",),
        ),
        (
            replace(ready_snapshot(), backup_verified=False),
            ("backup_unverified",),
        ),
        (
            replace(ready_snapshot(), stable_ids_verified=False),
            ("stable_ids_unverified",),
        ),
        (
            replace(
                ready_snapshot(),
                parse_error_refs=("parse-error:duplicate-id",),
            ),
            ("parse_errors_present",),
        ),
    ],
)
def test_preparation_fails_closed_before_plan(
    snapshot: MaterialStoreSnapshot,
    expected_blockers: tuple[str, ...],
) -> None:
    result = prepare(FakeInventoryProvider(snapshot))

    assert result.ready is False
    assert result.migration_plan is None
    assert result.readiness_blockers == expected_blockers
    assert result.inventory["source_mutation_authorized"] is False


def test_preparation_reports_all_readiness_blockers_deterministically() -> None:
    snapshot = replace(
        ready_snapshot(),
        source_unchanged_verified=False,
        backup_verified=False,
        stable_ids_verified=False,
        parse_error_refs=("parse-error:1",),
    )

    result = prepare(FakeInventoryProvider(snapshot))

    assert result.readiness_blockers == (
        "source_unchanged_unverified",
        "backup_unverified",
        "stable_ids_unverified",
        "parse_errors_present",
    )


def test_preparation_rejects_provider_and_store_identity_drift() -> None:
    provider = FakeInventoryProvider(ready_snapshot())
    provider.provider_id = "other-provider"
    with pytest.raises(ValueError, match="provider identity"):
        prepare(provider)

    wrong_snapshot = replace(ready_snapshot(), store_id="store:other")
    with pytest.raises(ValueError, match="store identity"):
        prepare(FakeInventoryProvider(wrong_snapshot))


def test_preparation_rejects_private_locations_before_plan() -> None:
    snapshot = replace(
        ready_snapshot(),
        source_snapshot_ref="/Users/example/private-materials.md",
    )

    with pytest.raises(ValueError, match="local path"):
        prepare(FakeInventoryProvider(snapshot))


def test_preparation_rejects_non_boolean_source_verification() -> None:
    snapshot = replace(
        ready_snapshot(),
        source_unchanged_verified="yes",  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="must be a boolean"):
        prepare(FakeInventoryProvider(snapshot))
