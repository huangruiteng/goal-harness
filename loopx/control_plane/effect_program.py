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
    protocol_summary: str | None = None


@dataclass(frozen=True)
class EffectNext:
    cli_actions: tuple[str, ...] = ()
    execution_mode: str | None = None
    scheduler_action: str | None = None
    cadence_class: str | None = None
    ack_cli_args: tuple[str, ...] = ()
    failure_cli_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectTurn:
    request: EffectRequest
    interpretation: EffectInterpretation
    observation: EffectObservation
    next_effect: EffectNext


@dataclass(frozen=True)
class EffectStep:
    step_id: str | None = None
    kind: str | None = None
    command: str | None = None
    purpose: str | None = None


@dataclass(frozen=True)
class EffectProgram:
    steps: tuple[EffectStep, ...] = ()
    execution_mode: str | None = None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def effect_program_from_ordered_steps(
    ordered_steps: Sequence[Mapping[str, Any]],
    *,
    execution_mode: str | None = None,
) -> EffectProgram:
    """Map existing `guided_transaction.ordered_steps` onto an effect program."""

    steps: list[EffectStep] = []
    for step in ordered_steps:
        if not isinstance(step, Mapping):
            continue
        steps.append(
            EffectStep(
                step_id=str(step.get("id") or "") or None,
                kind=str(step.get("kind") or "") or None,
                command=(
                    str(
                        step.get("command")
                        or step.get("command_template")
                        or step.get("prompt")
                        or ""
                    )
                    or None
                ),
                purpose=str(step.get("purpose") or "") or None,
            )
        )
    return EffectProgram(
        steps=tuple(steps),
        execution_mode=str(execution_mode or "") or None,
    )


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
    codex_app = _mapping(scheduler.get("codex_app"))
    ack_hint = _mapping(codex_app.get("ack_hint"))
    failure_hint = _mapping(codex_app.get("failure_hint"))
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
        protocol_summary=(
            str(protocol.get("summary")) if protocol.get("summary") else None
        ),
    )
    next_effect = EffectNext(
        cli_actions=tuple(
            str(action)
            for action in cli_channel.get("next_cli_actions", [])
            if str(action).strip()
        ),
        execution_mode=(
            str(
                packet.get("execution_mode")
                or codex_app.get("execution_mode")
                or scheduler.get("execution_mode")
                or None
            )
            or None
        ),
        scheduler_action=str(scheduler.get("action") or None) or None,
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
        ack_cli_args=tuple(
            str(arg)
            for arg in ack_hint.get("cli_args", [])
            if str(arg).strip()
        ),
        failure_cli_args=tuple(
            str(arg)
            for arg in failure_hint.get("cli_args", [])
            if str(arg).strip()
        ),
    )
    return EffectTurn(
        request=request,
        interpretation=interpretation,
        observation=observation,
        next_effect=next_effect,
    )


def interpret_turn_result_packet(
    packet: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    """Map an existing `loopx_turn_result_v0` packet onto canonical slots."""

    scheduler = _mapping(packet.get("scheduler_hint"))
    codex_app = _mapping(scheduler.get("codex_app"))
    ack_hint = _mapping(codex_app.get("ack_hint"))
    failure_hint = _mapping(codex_app.get("failure_hint"))
    completed_phases = tuple(
        str(phase)
        for phase in packet.get("completed_phases", [])
        if str(phase).strip()
    )
    failed_phase = str(packet.get("failed_phase") or "") or None
    result_kind = str(packet.get("result_kind") or "")

    request = EffectRequest(
        kind="turn_result",
        source="host",
        goal_id=goal_id,
        agent_id=agent_id,
        capabilities=tuple(capabilities),
        context={
            "completed_phases": completed_phases,
            "failed_phase": failed_phase,
            "classification": packet.get("classification"),
            "delivery_outcome": packet.get("delivery_outcome"),
        },
    )
    interpretation = EffectInterpretation(
        route="turn_result_settlement",
        obligation="settle_turn_receipt",
        interaction_mode="host_result",
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
    )
    observation = EffectObservation(
        decision=result_kind,
        should_run=False,
        effective_action=str(packet.get("effective_action") or result_kind),
        recommended_action=(
            str(packet.get("recommended_action") or "")
            or "settle the turn receipt"
        ),
        protocol_summary=(
            str(packet.get("summary")) if packet.get("summary") else None
        ),
    )
    next_effect = EffectNext(
        cli_actions=tuple(
            str(action)
            for action in packet.get("next_cli_actions", [])
            if str(action).strip()
        ),
        execution_mode=(
            str(
                packet.get("execution_mode")
                or codex_app.get("execution_mode")
                or scheduler.get("execution_mode")
                or None
            )
            or None
        ),
        scheduler_action=str(scheduler.get("action") or None) or None,
        cadence_class=str(scheduler.get("cadence_class") or None) or None,
        ack_cli_args=tuple(
            str(arg)
            for arg in ack_hint.get("cli_args", [])
            if str(arg).strip()
        ),
        failure_cli_args=tuple(
            str(arg)
            for arg in failure_hint.get("cli_args", [])
            if str(arg).strip()
        ),
    )
    return EffectTurn(
        request=request,
        interpretation=interpretation,
        observation=observation,
        next_effect=next_effect,
    )
