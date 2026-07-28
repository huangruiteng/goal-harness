from __future__ import annotations

import pytest

from loopx.capabilities.material_lifecycle import (
    build_material_readable_projection,
)

OBSERVED_AT = "2026-07-26T15:50:00+00:00"


def material(ref: str, title: str) -> dict[str, str]:
    return {
        "material_ref": ref,
        "display_label": ref.upper(),
        "title": title,
        "primary_url": f"https://example.com/{ref}",
        "summary": f"Summary for {ref}.",
        "judgment": f"Judgment for {ref}.",
        "action": f"Action for {ref}.",
        "source_status": "Exact read completed.",
        "audit_ref": f"audit:{ref}",
        "source_note": "See the project authority for complete backing.",
    }


def entry(
    rank: int,
    refs: list[str],
) -> dict[str, object]:
    return {
        "entry_ref": f"entry:{rank}",
        "rank": rank,
        "title": f"Priority {rank}",
        "stage": "active" if rank <= 2 else "backlog",
        "judgment": f"Rank judgment {rank}.",
        "action": f"Entry action {rank}.",
        "labels": [ref.upper() for ref in refs],
        "materials": [material(ref, f"Material {ref}") for ref in refs],
    }


def test_readable_projection_is_detailed_and_receipt_is_content_free() -> None:
    projection, receipt = build_material_readable_projection(
        goal_id="goal:materials",
        projection_id="projection:current",
        authority_revision="revision:42",
        observed_at=OBSERVED_AT,
        entries=[
            entry(1, ["m1", "m2"]),
            entry(2, ["m3"]),
            entry(3, ["m4"]),
        ],
        expected_material_refs=["m1", "m2", "m3", "m4"],
        canonical_item_count=20,
        top_window_size=2,
        intro_lines=["Use this view for navigation, not authority."],
        footer_lines=["Every selected material appears exactly once."],
    )

    rendered = projection.decode("utf-8")
    assert "### 1. Priority 1" in rendered
    assert "## Ranked Backlog" in rendered
    assert "[Material m1](<https://example.com/m1>)" in rendered
    assert "Summary for m1." in rendered
    assert receipt["summary"] == {
        "canonical_item_count": 20,
        "ranked_entry_count": 3,
        "top_window_entry_count": 2,
        "ranked_backlog_entry_count": 1,
        "ranked_material_count": 4,
        "unique_ranked_material_count": 4,
    }
    assert receipt["verification"]["complete_coverage_verified"] is True
    assert receipt["projection_visibility"] == "local_private_allowed"
    receipt_text = str(receipt)
    assert "Summary for m1." not in receipt_text
    assert "https://example.com" not in receipt_text


def test_readable_projection_supports_project_local_labels() -> None:
    projection, _ = build_material_readable_projection(
        goal_id="goal:materials",
        projection_id="projection:zh",
        authority_revision="revision:42",
        observed_at=OBSERVED_AT,
        entries=[entry(1, ["m1"])],
        expected_material_refs=["m1"],
        canonical_item_count=1,
        top_window_size=1,
        labels={
            "top_section": "Top 30",
            "entry_materials": "素材",
            "position": "位置",
            "why": "为什么在这里",
            "action": "建议动作",
            "summary": "核心内容",
            "current_judgment": "当前判断",
            "source_status": "来源状态",
            "audit_reference": "审计引用",
            "source_note": "原始账本",
        },
    )

    rendered = projection.decode("utf-8")
    assert "**素材:** `M1`" in rendered
    assert "- **核心内容:** Summary for m1." in rendered


def test_readable_projection_rejects_hidden_or_duplicate_coverage() -> None:
    with pytest.raises(ValueError, match="cover expected_material_refs exactly"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:missing",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1"])],
            expected_material_refs=["m1", "m2"],
            canonical_item_count=2,
            top_window_size=1,
        )

    duplicate = entry(2, ["m1"])
    with pytest.raises(ValueError, match="globally unique"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:duplicate",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1"]), duplicate],
            expected_material_refs=["m1"],
            canonical_item_count=2,
            top_window_size=1,
        )


def test_readable_projection_rejects_oversized_entries() -> None:
    with pytest.raises(ValueError, match="between 1 and 3"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:oversized",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1", "m2", "m3", "m4"])],
            expected_material_refs=["m1", "m2", "m3", "m4"],
            canonical_item_count=4,
            top_window_size=1,
        )


def test_readable_projection_rejects_invalid_counts_lines_and_rank_gaps() -> None:
    with pytest.raises(ValueError, match="canonical_item_count"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:count",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1", "m2"])],
            expected_material_refs=["m1", "m2"],
            canonical_item_count=1,
            top_window_size=1,
        )

    with pytest.raises(TypeError, match="intro_lines"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:lines",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1"])],
            expected_material_refs=["m1"],
            canonical_item_count=1,
            top_window_size=1,
            intro_lines="not a line sequence",
        )

    with pytest.raises(ValueError, match="contiguous"):
        build_material_readable_projection(
            goal_id="goal:materials",
            projection_id="projection:gap",
            authority_revision="revision:42",
            observed_at=OBSERVED_AT,
            entries=[entry(1, ["m1"]), entry(3, ["m2"])],
            expected_material_refs=["m1", "m2"],
            canonical_item_count=2,
            top_window_size=1,
        )
