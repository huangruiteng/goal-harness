#!/usr/bin/env python3
"""Smoke-test the public Material Lifecycle Stage-0 contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.material_lifecycle import (  # noqa: E402
    build_material_lifecycle_architecture_packet,
    build_material_lifecycle_receipt,
    build_material_migration_plan,
    build_material_rerank_apply_receipt,
    build_material_rerank_proposal,
    build_material_store_inventory,
)

OBSERVED_AT = "2026-07-25T16:30:00+00:00"


def run_cli(*args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--format", "json", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def main() -> int:
    architecture = build_material_lifecycle_architecture_packet()
    assert architecture["capability"]["default_enabled"] is False
    assert architecture["provider_boundaries"]["raw_material_store"] == (
        "private_external_authority"
    )
    assert run_cli("material-lifecycle", "architecture") == architecture

    inventory = build_material_store_inventory(
        goal_id="goal:material-example",
        store_id="store:materials",
        store_revision="revision:1",
        observed_at=OBSERVED_AT,
        source_snapshot_ref="snapshot:1",
        backup_ref="backup:1",
        source_digest="sha256:0123456789abcdef",
        lifecycle_counts={"candidate": 3, "archived": 7},
        stable_ids_verified=True,
        backup_verified=True,
    )
    migration = build_material_migration_plan(
        goal_id="goal:material-example",
        plan_id="plan:migrate-1",
        inventory_ref=str(inventory["inventory_ref"]),
        source_revision="revision:1",
        target_schema="material_store_v0",
        observed_at=OBSERVED_AT,
        backup_ref="backup:1",
        rollback_ref="rollback:1",
        expected_item_count=10,
    )
    lifecycle = build_material_lifecycle_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:archive-1",
        material_ref="material:1",
        from_state="active",
        to_state="archived",
        observed_at=OBSERVED_AT,
        source_ref="source:1",
        source_revision="revision:1",
        transition_authority_ref="decision-outcome:archive-1",
        archive_ref="archive:1",
    )
    proposal = build_material_rerank_proposal(
        goal_id="goal:material-example",
        proposal_id="proposal:rerank-1",
        inventory_ref=str(inventory["inventory_ref"]),
        decision_evidence_ref="decision-evidence-0123456789abcdef",
        observed_at=OBSERVED_AT,
        target_window_size=10,
        max_moved_items=2,
        max_rank_displacement=3,
        moves=[
            {
                "material_ref": "material:2",
                "from_rank": 5,
                "to_rank": 2,
                "reason_code": "current_objective_fit",
            }
        ],
    )
    apply_receipt = build_material_rerank_apply_receipt(
        goal_id="goal:material-example",
        receipt_id="receipt:rerank-1",
        proposal_ref=str(proposal["proposal_ref"]),
        observed_at=OBSERVED_AT,
        status="applied",
        before_revision="revision:1",
        after_revision="revision:2",
        owner_gate_ref="gate:rerank-1",
        validation_ref="validation:rerank-1",
        applied_material_refs=["material:2"],
        rollback_ref="rollback:revision-1",
    )

    serialized = json.dumps(
        {
            "architecture": architecture,
            "inventory": inventory,
            "migration": migration,
            "lifecycle": lifecycle,
            "proposal": proposal,
            "apply_receipt": apply_receipt,
        },
        sort_keys=True,
    )
    for forbidden in (
        "private material body",
        "private_locator",
        "/Users/",
        "https://",
    ):
        assert forbidden not in serialized
    assert inventory["raw_content_captured"] is False
    assert lifecycle["raw_content_captured"] is False
    assert proposal["raw_content_captured"] is False
    assert apply_receipt["raw_content_captured"] is False

    print(
        json.dumps(
            {
                "ok": True,
                "schema_version": architecture["schema_version"],
                "inventory_ref": inventory["inventory_ref"],
                "plan_ref": migration["plan_ref"],
                "lifecycle_ref": lifecycle["receipt_ref"],
                "proposal_ref": proposal["proposal_ref"],
                "apply_ref": apply_receipt["receipt_ref"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
