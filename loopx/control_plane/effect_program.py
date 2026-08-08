from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EffectRequest:
    kind: str
    source: str
    goal_id: str | None = None
    agent_id: str | None = None
    capabilities: tuple[str, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EffectInterpretation:
    route: str
    obligation: str
    interaction_mode: str
    capability_action: str | None = None
    cadence_class: str | None = None


@dataclass(frozen=True)
class EffectObservation:
    decision: str
    should_run: bool
    effective_action: str
    recommended_action: str
    next_cli_actions: tuple[str, ...] = ()
    protocol_summary: str | None = None


@dataclass(frozen=True)
class EffectTurn:
    request: EffectRequest
    interpretation: EffectInterpretation
    observation: EffectObservation


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def interpret_quota_should_run_packet(
    packet: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    """Map an existing `quota should-run` packet onto canonical effect slots."""

    interaction = _mapping(packet.get("interaction_contract"))
    lane = _mapping(packet.get("work_lane_contract"))
    scheduler = _mapping(packet.get("scheduler_hint"))
    cli_channel = _mapping(interaction.get("cli_channel"))
    gate = packet.get("capability_gate")
    protocol = _mapping(packet.get("protocol_action_packet"))

    request = EffectRequest(
        kind="quota_should_run",
        source="agent_or_host",
        goal_id=goal_id,
        agent_id=agent_id,
        capabilities=tuple(capabilities),
    )
    interpretation = EffectInterpretation(
        route=str(lane.get("lane") or ""),
        obligation=str(lane.get("obligation") or ""),
        interaction_mode=str(interaction.get("mode") or ""),
        capability_action=(
            str(gate.get("action")) if isinstance(gate, Mapping) else None
        ),
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
    )
    observation = EffectObservation(
        decision=str(packet.get("decision") or ""),
        should_run=bool(packet.get("should_run")),
        effective_action=str(packet.get("effective_action") or ""),
        recommended_action=str(packet.get("recommended_action") or ""),
        next_cli_actions=tuple(
            str(action)
            for action in cli_channel.get("next_cli_actions", [])
            if str(action).strip()
        ),
        protocol_summary=(
            str(protocol.get("summary")) if protocol.get("summary") else None
        ),
    )
    return EffectTurn(
        request=request,
        interpretation=interpretation,
        observation=observation,
    )
