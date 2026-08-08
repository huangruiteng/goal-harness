"""Parity fixture helpers for `quota should-run` extraction."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...quota import build_quota_should_run


def compact_quota_should_run_parity(
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a compact stable surface for old/new quota builder comparison."""

    interaction = (
        packet.get("interaction_contract")
        if isinstance(packet.get("interaction_contract"), Mapping)
        else {}
    )
    lane = (
        packet.get("work_lane_contract")
        if isinstance(packet.get("work_lane_contract"), Mapping)
        else {}
    )
    scheduler = (
        packet.get("scheduler_hint")
        if isinstance(packet.get("scheduler_hint"), Mapping)
        else {}
    )
    gate = packet.get("capability_gate")
    gate = gate if isinstance(gate, Mapping) else {}
    return {
        "decision": packet.get("decision"),
        "should_run": packet.get("should_run"),
        "effective_action": packet.get("effective_action"),
        "recommended_action": packet.get("recommended_action"),
        "interaction_mode": interaction.get("mode"),
        "interaction_action_required": interaction.get("action_required"),
        "lane": lane.get("lane"),
        "obligation": lane.get("obligation"),
        "must_attempt_work": lane.get("must_attempt_work"),
        "scheduler_action": scheduler.get("action"),
        "scheduler_cadence_class": scheduler.get("cadence_class"),
        "capability_gate_action": gate.get("action"),
    }


def build_quota_should_run_parity(
    status_payload: Mapping[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Build `quota should-run` and reduce it to the compact parity surface."""

    return compact_quota_should_run_parity(
        build_quota_should_run(dict(status_payload), **kwargs)
    )
