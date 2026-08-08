from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_type_hints

from loopx.control_plane.quota.decision_summary import (
    QuotaDecisionPacket,
    compact_quota_decision,
)
from loopx.control_plane.work_items.interaction_contract import (
    InteractionContractPacket,
    build_interaction_contract,
)


def _shape_ok(packet: Mapping[str, Any], contract: Any) -> bool:
    annotations = set(get_type_hints(contract))
    required = set(getattr(contract, "__required_keys__", frozenset()))
    return required <= set(packet) and set(packet) <= annotations


def test_quota_decision_packet_accepts_representative_packet() -> None:
    packet = compact_quota_decision(
        {
            "goal_id": "loopx-meta",
            "decision": "run",
            "should_run": True,
            "effective_action": "normal_run",
            "normal_delivery_allowed": True,
            "recovery_delivery_allowed": False,
            "self_repair_allowed": False,
            "capability_repair_allowed": False,
            "workspace_repair_allowed": False,
            "state": "normal",
            "safe_bypass_allowed": False,
            "safe_bypass_kind": None,
            "blocked_action_scope": None,
            "quota": {
                "compute": 1.0,
                "window_hours": 24,
                "slot_minutes": 1,
                "spent_slots": 3,
                "allowed_slots": 10,
            },
            "reason": "runnable work",
        }
    )

    assert _shape_ok(packet, QuotaDecisionPacket)
    assert packet["safe_bypass_kind"] is None
    assert packet["blocked_action_scope"] is None


def test_interaction_contract_packet_accepts_representative_packet() -> None:
    packet = build_interaction_contract(
        {
            "goal_id": "loopx-meta",
            "effective_action": "normal_run",
            "agent_identity": {"agent_id": "codex-quality-qualification"},
            "heartbeat_recommendation": {"recommended_mode": "bounded_delivery"},
        }
    )

    assert _shape_ok(packet, InteractionContractPacket)


def test_packet_contracts_reject_unknown_keys() -> None:
    assert not _shape_ok({"unknown": True}, QuotaDecisionPacket)
    assert not _shape_ok({"unknown": True}, InteractionContractPacket)


def test_packet_contracts_reject_missing_required_keys() -> None:
    quota_packet = compact_quota_decision({})
    interaction_packet = build_interaction_contract({})

    quota_without_should_run = dict(quota_packet)
    interaction_without_mode = dict(interaction_packet)
    quota_without_should_run.pop("should_run")
    interaction_without_mode.pop("mode")

    assert not _shape_ok(quota_without_should_run, QuotaDecisionPacket)
    assert not _shape_ok(interaction_without_mode, InteractionContractPacket)


def test_contract_required_keys_match_producer_invariants() -> None:
    assert QuotaDecisionPacket.__optional_keys__ == frozenset()
    assert QuotaDecisionPacket.__required_keys__ == frozenset(
        {
            "should_run",
            "normal_delivery_allowed",
            "recovery_delivery_allowed",
            "effective_action",
            "self_repair_allowed",
            "capability_repair_allowed",
            "workspace_repair_allowed",
            "state",
            "safe_bypass_allowed",
            "safe_bypass_kind",
            "blocked_action_scope",
            "compute",
            "window_hours",
            "slot_minutes",
            "spent_slots",
            "allowed_slots",
        }
    )
    assert InteractionContractPacket.__required_keys__ == frozenset(
        {"schema_version", "mode", "user_channel", "agent_channel", "cli_channel"}
    )
    assert InteractionContractPacket.__optional_keys__ == frozenset(
        {"response_plan", "fallback_policy"}
    )
