from __future__ import annotations

import json

import pytest

from loopx.capabilities.decision_context import (
    DecisionSourceExactRead,
    DecisionSourceItem,
    DecisionSourceScan,
    DecisionSourceSpec,
    build_decision_source_manifest,
)

OBSERVED_AT = "2026-07-25T13:30:00+00:00"


def messaging_source() -> DecisionSourceSpec:
    return DecisionSourceSpec(
        source_id="source:messaging:owner",
        provider_id="messaging-provider",
        source_kind="person",
        priority="p0",
        evidence_level="s2",
        objectives=("product-adoption",),
        scan_mode="incremental",
        exact_read_policy="material_change",
        freshness_seconds=3 * 24 * 60 * 60,
        private_locator="private_conversation_locator",
        max_changes=20,
    )


def test_manifest_is_deterministic_and_omits_private_locator() -> None:
    owner = messaging_source()
    ecosystem = DecisionSourceSpec(
        source_id="source:repository:ecosystem",
        provider_id="repository-provider",
        source_kind="repository",
        priority="p1",
        evidence_level="s2",
        objectives=("ecosystem-adoption", "product-adoption"),
        scan_mode="incremental",
        exact_read_policy="material_change",
        freshness_seconds=3 * 24 * 60 * 60,
        private_locator="private_repository_locator",
    )

    first = build_decision_source_manifest(
        goal_id="goal:decision-advisor",
        observed_at=OBSERVED_AT,
        sources=[owner, ecosystem],
    )
    second = build_decision_source_manifest(
        goal_id="goal:decision-advisor",
        observed_at=OBSERVED_AT,
        sources=[ecosystem, owner],
    )

    assert first == second
    serialized = json.dumps(first, sort_keys=True)
    assert "private_conversation_locator" not in serialized
    assert "private_repository_locator" not in serialized
    ecosystem_record = next(
        record
        for record in first["sources"]
        if record["source_id"] == "source:repository:ecosystem"
    )
    assert ecosystem_record["objectives"] == [
        "ecosystem-adoption",
        "product-adoption",
    ]
    assert first["private_locators_captured"] is False


def test_manifest_rejects_duplicate_source_ids() -> None:
    with pytest.raises(ValueError, match="source_id values must be unique"):
        build_decision_source_manifest(
            goal_id="goal:decision-advisor",
            observed_at=OBSERVED_AT,
            sources=[messaging_source(), messaging_source()],
        )


def test_scan_receipt_hides_cursor_item_revision_and_content() -> None:
    item = DecisionSourceItem(
        resource_ref="om_private_message_id",
        revision="private_message_revision",
        observed_at=OBSERVED_AT,
    )
    exact_read = DecisionSourceExactRead(
        resource_ref=item.resource_ref,
        revision=item.revision,
        observed_at=OBSERVED_AT,
        content="private conversation content",
    )
    scan = DecisionSourceScan(
        provider_id="messaging-provider",
        source_id="source:messaging:owner",
        status="completed",
        observed_at=OBSERVED_AT,
        requested_limit=20,
        cursor_before="private_cursor_before",
        cursor_after="private_cursor_after",
        items=(item,),
        latency_ms=15,
    )

    receipt = scan.public_receipt(exact_reads=[exact_read])
    serialized = json.dumps(receipt, sort_keys=True)

    for private_value in (
        "private_cursor_before",
        "private_cursor_after",
        "om_private_message_id",
        "private_message_revision",
        "private conversation content",
    ):
        assert private_value not in serialized
    assert receipt["changed_count"] == 1
    assert receipt["exact_read_count"] == 1
    assert receipt["changes"][0]["exact_read_verified"] is True
    assert receipt["private_cursor_captured"] is False
    assert receipt["raw_content_captured"] is False


def test_scan_receipt_rejects_exact_read_from_another_scan() -> None:
    scan = DecisionSourceScan(
        provider_id="messaging-provider",
        source_id="source:messaging:owner",
        status="completed",
        observed_at=OBSERVED_AT,
        requested_limit=20,
        items=(
            DecisionSourceItem(
                resource_ref="message:a",
                revision="revision:a",
                observed_at=OBSERVED_AT,
            ),
        ),
    )
    unrelated = DecisionSourceExactRead(
        resource_ref="message:b",
        revision="revision:b",
        observed_at=OBSERVED_AT,
        content="transient",
    )

    with pytest.raises(ValueError, match="must reference an item"):
        scan.public_receipt(exact_reads=[unrelated])


def test_unavailable_provider_fails_open_without_changes() -> None:
    receipt = DecisionSourceScan(
        provider_id="messaging-provider",
        source_id="source:messaging:owner",
        status="unavailable",
        observed_at=OBSERVED_AT,
        requested_limit=20,
        reason_code="provider_auth_unavailable",
    ).public_receipt()

    assert receipt["provider_fail_open"] is True
    assert receipt["changed_count"] == 0
    assert receipt["exact_read_count"] == 0
    assert receipt["status"] == "unavailable"


def test_scan_receipt_rejects_unbounded_or_unsafe_public_metadata() -> None:
    item = DecisionSourceItem(
        resource_ref="resource:a",
        revision="revision:a",
        observed_at=OBSERVED_AT,
    )

    with pytest.raises(ValueError, match="cannot exceed requested_limit"):
        DecisionSourceScan(
            provider_id="repository-provider",
            source_id="source:repository:signals",
            status="completed",
            observed_at=OBSERVED_AT,
            requested_limit=1,
            items=(item, item),
        ).public_receipt()

    with pytest.raises(ValueError, match="compact token"):
        DecisionSourceScan(
            provider_id="repository-provider",
            source_id="source:repository:signals",
            status="unavailable",
            observed_at=OBSERVED_AT,
            requested_limit=1,
            reason_code="see https://example.invalid/error",
        ).public_receipt()


def test_no_change_scan_cannot_smuggle_items() -> None:
    with pytest.raises(ValueError, match="no-change"):
        DecisionSourceScan(
            provider_id="repository-provider",
            source_id="source:repository:signals",
            status="no_change",
            observed_at=OBSERVED_AT,
            requested_limit=1,
            items=(
                DecisionSourceItem(
                    resource_ref="resource:a",
                    revision="revision:a",
                    observed_at=OBSERVED_AT,
                ),
            ),
        ).public_receipt()
