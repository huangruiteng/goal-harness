from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.decision_context import (
    DecisionEvidenceRecords,
    assemble_profile_decision_evidence,
)
from loopx.cli import main

OBSERVED_AT = "2100-01-01T00:00:00+00:00"
BEFORE = "2100-01-01T00:01:00+00:00"
PRIVATE_CONTENT = "Current authority keeps adoption at a bounded pilot."


def write_profile(
    path: Path,
    authority_path: Path,
    *,
    enabled: bool = True,
    max_bytes: int = 4096,
    scan_mode: str = "incremental",
) -> Path:
    payload = {
        "schema_version": "decision_context_profile_v0",
        "goal_id": "example-decision-goal",
        "enabled": enabled,
        "enabled_agents": ["example-agent"],
        "source_provider_bindings": [
            {
                "provider_id": "local-authority",
                "adapter": "local-file",
                "config": {"max_bytes": max_bytes},
            }
        ],
        "sources": [
            {
                "source_id": "source:authority",
                "provider_id": "local-authority",
                "source_kind": "artifact",
                "priority": "p0",
                "evidence_level": "s3",
                "objectives": ["adoption"],
                "scan_mode": scan_mode,
                "exact_read_policy": "material_change",
                "freshness_seconds": 3600,
                "private_locator": str(authority_path),
                "max_changes": 4,
                "enabled": True,
            }
        ],
        "context_provider": None,
        "automation": {
            "automatic_capture": False,
            "fail_open": True,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_profile_runtime_builds_providers_and_returns_private_cursor_proposal(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    callback_contents: list[str] = []

    def rebase(collection: Any) -> DecisionEvidenceRecords:
        current = collection.authority[0]
        callback_contents.append(current.content)
        return DecisionEvidenceRecords(
            changed_facts=(
                {
                    "fact_id": "fact:pilot",
                    "summary": "Current authority keeps adoption at pilot.",
                    "source_ref": current.source_ref,
                    "source_revision": current.source_revision,
                    "observed_at": current.observed_at,
                    "freshness": "current",
                    "authority": "first_party",
                },
            )
        )

    activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=rebase,
    )

    assert activation["status"] == "available"
    assert assembly is not None
    assert callback_contents == [PRIVATE_CONTENT]
    assert assembly.proposed_cursors["source:authority"].startswith("sha256:")
    packet = assembly.public_packet()
    assert packet["evidence_packet"]["changed_facts"][0]["fact_id"] == "fact:pilot"
    assert packet["cursor_checkpoint"]["sources"][0]["disposition"] == (
        "ready_after_writeback"
    )
    assert PRIVATE_CONTENT not in json.dumps(packet, sort_keys=True)
    assert str(authority) not in json.dumps(packet, sort_keys=True)


def test_prepare_evidence_cli_preserves_private_cursor_until_semantic_rebase(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    cursor_payload = {"source:authority": "sha256:previous"}
    cursors.write_text(json.dumps(cursor_payload), encoding="utf-8")
    cursor_before = cursors.read_bytes()

    assert (
        main(
            [
                "--format",
                "json",
                "decision-context",
                "prepare-evidence",
                "--goal-id",
                "example-decision-goal",
                "--agent-id",
                "example-agent",
                "--profile",
                str(profile),
                "--decision-id",
                "decision:adoption",
                "--cursor-state",
                str(cursors),
                "--observed-at",
                OBSERVED_AT,
                "--before",
                BEFORE,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    serialized = json.dumps(payload, sort_keys=True)
    assembly = payload["assembly"]

    assert payload["status"] == "available"
    assert payload["semantic_rebase_performed"] is False
    assert payload["validated_writeback_required"] is True
    assert payload["cursor_commit_allowed"] is False
    assert payload["cursor_state_mutated"] is False
    assert assembly["source_scan_receipts"][0]["exact_read_count"] == 1
    assert assembly["cursor_checkpoint"]["sources"][0]["disposition"] == "preserve"
    assert assembly["cursor_checkpoint"]["sources"][0]["reason_code"] == (
        "rebase_incomplete"
    )
    assert cursors.read_bytes() == cursor_before
    for private_value in (
        PRIVATE_CONTENT,
        str(authority),
        str(profile),
        str(cursors),
        "sha256:previous",
    ):
        assert private_value not in serialized


def test_profile_runtime_fails_open_when_provider_config_cannot_build(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(
        tmp_path / "profile.json",
        authority,
        max_bytes=-1,
    )

    activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=lambda _collection: DecisionEvidenceRecords(),
    )

    assert activation["status"] == "available"
    assert assembly is not None
    receipt = assembly.public_packet()["source_scan_receipts"][0]
    assert receipt["status"] == "unavailable"
    assert receipt["reason_code"] == "provider_configuration_failed"
    assert assembly.proposed_cursors == {}


def test_disabled_profile_does_not_touch_authority_provider(tmp_path: Path) -> None:
    missing_authority = tmp_path / "missing.md"
    profile = write_profile(
        tmp_path / "profile.json",
        missing_authority,
        enabled=False,
    )

    activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=lambda _collection: DecisionEvidenceRecords(),
    )

    assert activation["status"] == "disabled"
    assert assembly is None


def test_private_cursor_state_rejects_unknown_source_ids(tmp_path: Path) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    cursors.write_text(json.dumps({"source:unknown": "cursor"}), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown source ids"):
        assemble_profile_decision_evidence(
            goal_id="example-decision-goal",
            agent_id="example-agent",
            profile_path=profile,
            decision_id="decision:adoption",
            observed_at=OBSERVED_AT,
            before=BEFORE,
            cursor_path=cursors,
            rebase=lambda _collection: DecisionEvidenceRecords(),
        )


def test_on_demand_source_requires_explicit_selection(tmp_path: Path) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(
        tmp_path / "profile.json",
        authority,
        scan_mode="on_demand",
    )

    _activation, automatic = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=lambda _collection: DecisionEvidenceRecords(),
    )
    _activation, explicit = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        source_ids={"source:authority"},
        rebase=lambda _collection: DecisionEvidenceRecords(),
    )

    assert automatic is not None
    assert automatic.public_packet()["source_manifest"]["source_count"] == 0
    assert explicit is not None
    assert explicit.public_packet()["source_manifest"]["source_count"] == 1
    assert explicit.public_packet()["source_scan_receipts"][0]["status"] == "completed"
