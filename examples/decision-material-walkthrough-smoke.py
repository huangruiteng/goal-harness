#!/usr/bin/env python3
"""Smoke-test revision-bound Decision Context to Material Lifecycle planning."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.capabilities.decision_context import (  # noqa: E402
    build_decision_context_architecture_packet,
    build_decision_evidence_packet,
)
from loopx.capabilities.material_lifecycle import (  # noqa: E402
    MaterialDecisionPolicyResult,
    build_material_lifecycle_architecture_packet,
    build_material_store_inventory,
    plan_material_decision_actions,
)


OBSERVED_AT = "2026-08-11T12:00:00+08:00"
GOAL_ID = "goal:decision-material-walkthrough"


class WalkthroughPolicy:
    policy_id = "policy:material-fit"

    def evaluate(self, **_: Any) -> MaterialDecisionPolicyResult:
        return MaterialDecisionPolicyResult(
            moves=(
                {
                    "material_ref": "material:runtime",
                    "from_rank": 8,
                    "to_rank": 4,
                    "reason_code": "current_objective_fit",
                    "evidence_refs": ["fact:priority-shift"],
                },
            ),
            explore_topics=(
                {
                    "topic_ref": "topic:runtime-adoption",
                    "reason_code": "evidence_gap",
                    "evidence_refs": ["fact:priority-shift"],
                },
            ),
        )


def run_cli(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "loopx.cli", "--format", "json", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def assert_public_safe(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "private-repository-locator",
        "private_locator",
        "private material body",
        "/Users/",
        "https://",
        "provider_payload",
    ):
        assert forbidden not in text, forbidden


def main() -> int:
    decision_architecture = build_decision_context_architecture_packet()
    material_architecture = build_material_lifecycle_architecture_packet()
    assert run_cli("decision-context", "architecture") == decision_architecture
    assert run_cli("material-lifecycle", "architecture") == material_architecture
    assert decision_architecture["capability"]["creates_authority"] is False
    assert material_architecture["capability"]["default_enabled"] is False
    assert material_architecture["provider_boundaries"]["raw_material_store"] == (
        "private_external_authority"
    )

    private_locator = "private-repository-locator"
    evidence = build_decision_evidence_packet(
        goal_id=GOAL_ID,
        decision_id="decision:material-rerank",
        observed_at=OBSERVED_AT,
        changed_facts=[
            {
                "fact_id": "fact:priority-shift",
                "summary": "The current objective favors runtime evidence.",
                "source_ref": "source:decision-ledger",
                "source_revision": "revision:7",
                "observed_at": OBSERVED_AT,
                "freshness": "fresh",
                "authority": "curated-ledger",
            }
        ],
        stale_or_rejected_claims=[
            {
                "claim_id": "claim:old-priority",
                "summary": "The prior ranking objective is no longer current.",
                "source_ref": "source:decision-ledger",
                "source_revision": "revision:6",
                "observed_at": OBSERVED_AT,
                "reason_code": "superseded_revision",
            }
        ],
        conflicts=[
            {
                "conflict_id": "conflict:priority",
                "summary": "A recalled claim disagrees with the current ledger.",
                "source_refs": ["provider:memory", "source:decision-ledger"],
                "conflict_rule": "canonical_revision_wins",
                "status": "resolved",
            }
        ],
        source_revisions=[
            {
                "source_ref": "source:decision-ledger",
                "revision": "revision:7",
                "observed_at": OBSERVED_AT,
                "freshness": "fresh",
            }
        ],
        provider_health=[
            {
                "provider": "provider:memory",
                "status": "healthy",
                "observed_at": OBSERVED_AT,
                "fail_open": True,
            }
        ],
    )
    inventory = build_material_store_inventory(
        goal_id=GOAL_ID,
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
    planning = plan_material_decision_actions(
        policy=WalkthroughPolicy(),
        policy_id="policy:material-fit",
        goal_id=GOAL_ID,
        proposal_id="proposal:decision-rerank",
        explore_intent_id="intent:decision-explore",
        inventory_ref=str(inventory["inventory_ref"]),
        decision_evidence=evidence,
        observed_at=OBSERVED_AT,
        target_window_size=30,
        max_moved_items=3,
        max_rank_displacement=5,
        protected_material_refs=["material:pinned"],
        max_explore_topics=2,
        max_provider_calls=2,
        max_new_candidates=5,
        explore_stop_condition="Stop after bounded evidence gap resolution.",
    )
    preview = planning.rerank_proposal
    explore_intent = planning.explore_intent
    assert explore_intent is not None

    assert evidence["raw_context_captured"] is False
    assert evidence["changed_facts"][0]["source_revision"] == "revision:7"
    assert evidence["source_revisions"][0]["revision"] == "revision:7"
    assert evidence["stale_or_rejected_claims"][0]["reason_code"] == (
        "superseded_revision"
    )
    assert evidence["conflicts"][0]["status"] == "resolved"
    assert planning.policy_status == "ready"
    assert preview["decision_evidence_ref"] == evidence["packet_ref"]
    assert preview["inventory_ref"] == inventory["inventory_ref"]
    assert preview["apply_authorized"] is False
    assert preview["raw_content_captured"] is False
    assert preview["moves"][0]["evidence_refs"] == ["fact:priority-shift"]
    assert explore_intent["execution_authorized"] is False
    assert explore_intent["source_cursor_apply_authorized"] is False
    assert explore_intent["provider_calls_performed"] is False

    walkthrough = {
        "decision_architecture": decision_architecture,
        "material_architecture": material_architecture,
        "evidence": evidence,
        "inventory": inventory,
        "preview": preview,
        "explore_intent": explore_intent,
    }
    assert private_locator not in json.dumps(walkthrough, sort_keys=True)
    assert_public_safe(walkthrough)

    print(
        json.dumps(
            {
                "ok": True,
                "evidence_ref": evidence["packet_ref"],
                "inventory_ref": inventory["inventory_ref"],
                "proposal_ref": preview["proposal_ref"],
                "stale_claim_count": len(evidence["stale_or_rejected_claims"]),
                "conflict_count": len(evidence["conflicts"]),
                "apply_authorized": preview["apply_authorized"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
