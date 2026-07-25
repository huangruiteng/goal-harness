from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from loopx.capabilities.decision_context import (
    DecisionEvidenceRecords,
    LocalFileDecisionSourceProvider,
    assemble_profile_decision_evidence,
    build_decision_outcome_receipt,
    build_decision_proposal,
    commit_profile_decision_cursors,
)
from loopx.cli import main
from loopx.rollout_event_log import append_rollout_event, build_rollout_event

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
    adapter: str = "local-file",
) -> Path:
    payload = {
        "schema_version": "decision_context_profile_v0",
        "goal_id": "example-decision-goal",
        "enabled": enabled,
        "enabled_agents": ["example-agent"],
        "source_provider_bindings": [
            {
                "provider_id": "local-authority",
                "adapter": adapter,
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


def semantic_rebase(collection: Any) -> DecisionEvidenceRecords:
    current = collection.authority[0]
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


def decision_chain(assembly: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    packet = assembly.public_packet()
    proposal = build_decision_proposal(
        goal_id="example-decision-goal",
        decision_id="decision:adoption",
        evidence_packet_ref=packet["evidence_packet"]["packet_ref"],
        observed_at=OBSERVED_AT,
        objective_scores=[
            {
                "objective_id": "adoption",
                "score": 0.8,
                "rationale": "The current authority supports a bounded pilot.",
            }
        ],
        recommended_decision={
            "option_id": "bounded-pilot",
            "summary": "Continue the bounded pilot.",
            "rationale": "Current first-party evidence remains positive.",
            "confidence": 0.8,
        },
        review_at="2100-01-02T00:00:00+00:00",
    )
    outcome = build_decision_outcome_receipt(
        goal_id="example-decision-goal",
        decision_id="decision:adoption",
        proposal_packet_ref=proposal["packet_ref"],
        recorded_at=OBSERVED_AT,
        verification_status="pending",
        accepted_decision={
            "option_id": "bounded-pilot",
            "summary": "Continue the bounded pilot.",
            "accepted_by": "example-owner",
            "accepted_at": OBSERVED_AT,
        },
        review_at="2100-01-02T00:00:00+00:00",
    )
    return proposal, outcome


def append_decision_writeback(
    path: Path,
    assembly: Any,
    proposal: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:
    packet = assembly.public_packet()
    event = build_rollout_event(
        goal_id="example-decision-goal",
        event_kind="validation",
        decision_id="decision:adoption",
        status="committed",
        summary="Decision packets were written through the existing lifecycle.",
        artifact_refs=[
            packet["evidence_packet"]["packet_ref"],
            proposal["packet_ref"],
            outcome["packet_ref"],
        ],
        recorded_at=OBSERVED_AT,
    )
    return append_rollout_event(path, event)


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


def test_private_host_provider_drives_generic_scan_exact_read_and_checkpoint(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(
        tmp_path / "profile.json",
        authority,
        adapter="private-host-adapter",
    )
    provider = LocalFileDecisionSourceProvider(
        provider_id="local-authority",
        max_bytes=4096,
    )

    activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=semantic_rebase,
        source_provider_overrides={"local-authority": provider},
    )

    assert activation["status"] == "available"
    assert activation["runtime_bound_provider_count"] == 1
    assert assembly is not None
    packet = assembly.public_packet()
    assert packet["source_scan_receipts"][0]["status"] == "completed"
    assert packet["source_scan_receipts"][0]["exact_read_count"] == 1
    assert packet["evidence_packet"]["provider_health"][0]["status"] == "healthy"
    assert packet["cursor_checkpoint"]["sources"][0]["disposition"] == (
        "ready_after_writeback"
    )
    assert PRIVATE_CONTENT not in json.dumps(packet, sort_keys=True)
    assert str(authority) not in json.dumps(packet, sort_keys=True)


def test_private_host_provider_can_commit_cursor_after_validated_writeback(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(
        tmp_path / "profile.json",
        authority,
        adapter="private-host-adapter",
    )
    provider = LocalFileDecisionSourceProvider(
        provider_id="local-authority",
        max_bytes=4096,
    )
    cursors = tmp_path / "cursors.json"
    event_log = tmp_path / "rollout-events.jsonl"

    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
        source_provider_overrides={"local-authority": provider},
    )
    assert assembly is not None
    assert assembly.runtime_bound_provider_ids == ("local-authority",)
    proposal, outcome = decision_chain(assembly)
    event = append_decision_writeback(event_log, assembly, proposal, outcome)

    receipt = commit_profile_decision_cursors(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        cursor_path=cursors,
        assembly=assembly,
        proposal=proposal,
        outcome_receipt=outcome,
        lifecycle_event_log_path=event_log,
        lifecycle_event_id=event["event_id"],
    )

    assert receipt["status"] == "committed"
    assert receipt["cursor_state_mutated"] is True
    assert receipt["readback_verified"] is True
    assert json.loads(cursors.read_text(encoding="utf-8")) == dict(
        assembly.proposed_cursors
    )


def test_runtime_provider_identity_mismatch_fails_open(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(
        tmp_path / "profile.json",
        authority,
        adapter="private-host-adapter",
    )
    provider = LocalFileDecisionSourceProvider(
        provider_id="another-provider",
        max_bytes=4096,
    )

    activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        rebase=lambda _collection: DecisionEvidenceRecords(),
        source_provider_overrides={"local-authority": provider},
    )

    assert activation["status"] == "available"
    assert assembly is not None
    receipt = assembly.public_packet()["source_scan_receipts"][0]
    assert receipt["status"] == "unavailable"
    assert receipt["reason_code"] == "runtime_provider_identity_mismatch"
    assert assembly.proposed_cursors == {}


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


def test_cursor_commit_requires_exact_read_lifecycle_writeback(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    event_log = tmp_path / "rollout-events.jsonl"
    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
    )
    assert assembly is not None
    proposal, outcome = decision_chain(assembly)

    with pytest.raises(ValueError, match="writeback event was not found"):
        commit_profile_decision_cursors(
            goal_id="example-decision-goal",
            agent_id="example-agent",
            profile_path=profile,
            cursor_path=cursors,
            assembly=assembly,
            proposal=proposal,
            outcome_receipt=outcome,
            lifecycle_event_log_path=event_log,
            lifecycle_event_id="missing-event",
        )

    assert not cursors.exists()


def test_thin_host_callsite_commits_cursor_after_lifecycle_writeback(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    event_log = tmp_path / "rollout-events.jsonl"
    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
    )
    assert assembly is not None
    proposal, outcome = decision_chain(assembly)
    event = append_decision_writeback(event_log, assembly, proposal, outcome)

    receipt = commit_profile_decision_cursors(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        cursor_path=cursors,
        assembly=assembly,
        proposal=proposal,
        outcome_receipt=outcome,
        lifecycle_event_log_path=event_log,
        lifecycle_event_id=event["event_id"],
    )

    assert receipt["status"] == "committed"
    assert receipt["cursor_state_mutated"] is True
    assert receipt["readback_verified"] is True
    assert receipt["sources"][0]["status"] == "advanced"
    assert json.loads(cursors.read_text(encoding="utf-8")) == dict(
        assembly.proposed_cursors
    )
    serialized = json.dumps(receipt, sort_keys=True)
    for private_value in (
        PRIVATE_CONTENT,
        str(authority),
        str(profile),
        str(cursors),
        next(iter(assembly.proposed_cursors.values())),
    ):
        assert private_value not in serialized

    replay = commit_profile_decision_cursors(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        cursor_path=cursors,
        assembly=assembly,
        proposal=proposal,
        outcome_receipt=outcome,
        lifecycle_event_log_path=event_log,
        lifecycle_event_id=event["event_id"],
    )
    assert replay["status"] == "replayed"
    assert replay["cursor_state_mutated"] is False
    assert replay["sources"][0]["status"] == "replayed"


def test_cursor_commit_rejects_concurrent_cursor_change(tmp_path: Path) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    cursors.write_text(
        json.dumps({"source:authority": "sha256:previous"}),
        encoding="utf-8",
    )
    event_log = tmp_path / "rollout-events.jsonl"
    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
    )
    assert assembly is not None
    proposal, outcome = decision_chain(assembly)
    event = append_decision_writeback(event_log, assembly, proposal, outcome)
    concurrent = {"source:authority": "sha256:concurrent"}
    cursors.write_text(json.dumps(concurrent), encoding="utf-8")

    with pytest.raises(ValueError, match="changed since evidence assembly"):
        commit_profile_decision_cursors(
            goal_id="example-decision-goal",
            agent_id="example-agent",
            profile_path=profile,
            cursor_path=cursors,
            assembly=assembly,
            proposal=proposal,
            outcome_receipt=outcome,
            lifecycle_event_log_path=event_log,
            lifecycle_event_id=event["event_id"],
        )

    assert json.loads(cursors.read_text(encoding="utf-8")) == concurrent


def test_cursor_commit_rejects_profile_change_after_assembly(tmp_path: Path) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    event_log = tmp_path / "rollout-events.jsonl"
    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
    )
    assert assembly is not None
    proposal, outcome = decision_chain(assembly)
    event = append_decision_writeback(event_log, assembly, proposal, outcome)
    changed_profile = json.loads(profile.read_text(encoding="utf-8"))
    changed_profile["sources"][0]["max_changes"] = 5
    profile.write_text(json.dumps(changed_profile), encoding="utf-8")

    with pytest.raises(ValueError, match="profile changed since evidence assembly"):
        commit_profile_decision_cursors(
            goal_id="example-decision-goal",
            agent_id="example-agent",
            profile_path=profile,
            cursor_path=cursors,
            assembly=assembly,
            proposal=proposal,
            outcome_receipt=outcome,
            lifecycle_event_log_path=event_log,
            lifecycle_event_id=event["event_id"],
        )

    assert not cursors.exists()


def test_cursor_commit_rejects_writeback_without_full_packet_chain(
    tmp_path: Path,
) -> None:
    authority = tmp_path / "authority.md"
    authority.write_text(PRIVATE_CONTENT, encoding="utf-8")
    profile = write_profile(tmp_path / "profile.json", authority)
    cursors = tmp_path / "cursors.json"
    event_log = tmp_path / "rollout-events.jsonl"
    _activation, assembly = assemble_profile_decision_evidence(
        goal_id="example-decision-goal",
        agent_id="example-agent",
        profile_path=profile,
        decision_id="decision:adoption",
        observed_at=OBSERVED_AT,
        before=BEFORE,
        cursor_path=cursors,
        rebase=semantic_rebase,
    )
    assert assembly is not None
    proposal, outcome = decision_chain(assembly)
    packet = assembly.public_packet()
    event = build_rollout_event(
        goal_id="example-decision-goal",
        event_kind="validation",
        decision_id="decision:adoption",
        status="committed",
        artifact_refs=[
            packet["evidence_packet"]["packet_ref"],
            proposal["packet_ref"],
        ],
        recorded_at=OBSERVED_AT,
    )
    append_rollout_event(event_log, event)

    with pytest.raises(ValueError, match="does not match decision"):
        commit_profile_decision_cursors(
            goal_id="example-decision-goal",
            agent_id="example-agent",
            profile_path=profile,
            cursor_path=cursors,
            assembly=assembly,
            proposal=proposal,
            outcome_receipt=outcome,
            lifecycle_event_log_path=event_log,
            lifecycle_event_id=event["event_id"],
        )

    assert not cursors.exists()
