from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from loopx.control_plane.effect_program import (
    SettlementIdentity,
    SettlementResult,
    SettlementStepKind,
)
from loopx.control_plane.quota.settlement import (
    build_codex_app_settlement_plan,
    require_settlement_spend,
    require_settlement_todo_completion,
    require_settlement_writeback,
    resolve_heartbeat_settlement_identity,
)
from loopx.control_plane.turn_driver.settlement import (
    TurnSettlementState,
    execute_turn_driver_settlement,
)
from loopx.control_plane.turn_driver.transaction import (
    TRANSACTION_PHASES,
    build_loopx_turn_transaction_plan,
)
from loopx.rollout_event_log import rollout_event_log_path

GOAL_ID = "adapter-conformance-goal"
AGENT_ID = "codex-adapter-conformance"
TODO_ID = "todo_adapter_conformance"
TURN_ID = "adapter-conformance-turn"


@dataclass(frozen=True, slots=True)
class AdapterObservation:
    result: SettlementResult[Any]
    effect_calls: tuple[SettlementStepKind, ...]
    settlement_plan: Mapping[str, Any]


AdapterRunner = Callable[[Path, str], AdapterObservation]


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    name: str
    run: AdapterRunner
    success_receipts: tuple[SettlementStepKind, ...]
    calls_before_writeback_failure: tuple[SettlementStepKind, ...]


def _append_event(
    runtime_root: Path,
    *,
    event_id: str,
    event_kind: str,
    effect_id: str,
) -> None:
    path = rollout_event_log_path(runtime_root, GOAL_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "loopx_rollout_event_v0",
        "event_id": event_id,
        "event_kind": event_kind,
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "run_id": TURN_ID,
        "details": {
            "todo_id": TODO_ID,
            "settlement_effect_id": effect_id,
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")


def _write_run_index(
    runtime_root: Path,
    *,
    include_writeback: bool,
    include_spend: bool,
) -> None:
    records: list[dict[str, Any]] = []
    if include_writeback:
        records.append(
            {
                "classification": "adapter_conformance_writeback",
                "delivery_outcome": "outcome_progress",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "todo_id": TODO_ID,
                "turn_instance_id": TURN_ID,
            }
        )
    if include_spend:
        records.append(
            {
                "classification": "quota_slot_spent",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "todo_id": TODO_ID,
                "turn_instance_id": TURN_ID,
            }
        )
    path = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def _preserve_identity(
    identity: SettlementIdentity,
    result: SettlementResult[dict[str, Any]],
) -> SettlementResult[SettlementIdentity]:
    return SettlementResult(
        value=identity if result.failure is None else None,
        receipts=result.receipts,
        failure=result.failure,
    )


def _run_quota_adapter(runtime_root: Path, scenario: str) -> AdapterObservation:
    plan = build_codex_app_settlement_plan(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        scoped_cli_args=f" --agent-id {AGENT_ID}",
        lifecycle_actor_args=f" --agent-id {AGENT_ID}",
        turn_instance_id_ref=TURN_ID,
    ).as_dict()
    identity = SettlementIdentity(GOAL_ID, AGENT_ID, TODO_ID, TURN_ID)
    guard_effect_id = (
        "mismatched-effect" if scenario == "invalid_identity" else identity.effect_id
    )
    _append_event(
        runtime_root,
        event_id="event-guard",
        event_kind="quota_should_run",
        effect_id=guard_effect_id,
    )
    _append_event(
        runtime_root,
        event_id="event-completion",
        event_kind="todo_complete",
        effect_id=identity.effect_id,
    )
    include_writeback = scenario != "writeback_failure"
    if include_writeback:
        _append_event(
            runtime_root,
            event_id="event-writeback",
            event_kind="refresh_state",
            effect_id=identity.effect_id,
        )
    # Keep spend evidence present in the writeback-failure case. The bind chain
    # must still refuse to inspect or accept it after the earlier failure.
    _append_event(
        runtime_root,
        event_id="event-spend",
        event_kind="quota_spend",
        effect_id=identity.effect_id,
    )
    _write_run_index(
        runtime_root,
        include_writeback=include_writeback,
        include_spend=True,
    )

    calls: list[SettlementStepKind] = []

    def completion(
        resolved: SettlementIdentity,
    ) -> SettlementResult[SettlementIdentity]:
        calls.append(SettlementStepKind.TODO_COMPLETION)
        return _preserve_identity(
            resolved,
            require_settlement_todo_completion(runtime_root, resolved),
        )

    def writeback(
        resolved: SettlementIdentity,
    ) -> SettlementResult[SettlementIdentity]:
        calls.append(SettlementStepKind.DURABLE_WRITEBACK)
        return _preserve_identity(
            resolved,
            require_settlement_writeback(runtime_root, resolved),
        )

    def spend(resolved: SettlementIdentity) -> SettlementResult[SettlementIdentity]:
        calls.append(SettlementStepKind.QUOTA_SPEND)
        return _preserve_identity(
            resolved,
            require_settlement_spend(runtime_root, resolved),
        )

    result = (
        resolve_heartbeat_settlement_identity(
            runtime_root,
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            todo_id=TODO_ID,
            turn_instance_id=TURN_ID,
        )
        .bind(completion)
        .bind(writeback)
        .bind(spend)
    )
    return AdapterObservation(result, tuple(calls), plan)


def _run_turn_adapter(_runtime_root: Path, scenario: str) -> AdapterObservation:
    transaction_plan = build_loopx_turn_transaction_plan(
        planned=True,
        lineage={
            "goal_id": GOAL_ID,
            "agent_id": AGENT_ID,
            "todo_id": TODO_ID,
        },
        host="generic-cli",
        execution_mode="isolated-headless",
        session_action="resume",
        turn_instance_id=TURN_ID,
    )
    settlement_plan = transaction_plan["settlement_plan"]
    assert isinstance(settlement_plan, Mapping)
    runtime_plan = dict(transaction_plan)
    if scenario == "invalid_identity":
        runtime_plan.pop("settlement_plan")

    calls: list[SettlementStepKind] = []

    def effect(step_kind: SettlementStepKind) -> Mapping[str, Any]:
        calls.append(step_kind)
        if scenario == "writeback_failure" and (
            step_kind is SettlementStepKind.DURABLE_WRITEBACK
        ):
            return {
                "ok": False,
                "appended": False,
                "reason": "writeback rejected by conformance fixture",
            }
        return {"ok": True, "appended": True}

    result: SettlementResult[TurnSettlementState] = execute_turn_driver_settlement(
        runtime_plan,
        transaction_phases=TRANSACTION_PHASES,
        completed_phases=TRANSACTION_PHASES[:3],
        writeback_payload=None,
        quota_spend_payload=None,
        writeback=lambda: effect(SettlementStepKind.DURABLE_WRITEBACK),
        spend=lambda: effect(SettlementStepKind.QUOTA_SPEND),
        checkpoint=lambda _step, _payload, _phases: None,
    )
    return AdapterObservation(result, tuple(calls), settlement_plan)


ADAPTERS = (
    AdapterSpec(
        name="quota",
        run=_run_quota_adapter,
        success_receipts=(
            SettlementStepKind.VALIDATION,
            SettlementStepKind.TODO_COMPLETION,
            SettlementStepKind.DURABLE_WRITEBACK,
            SettlementStepKind.QUOTA_SPEND,
        ),
        calls_before_writeback_failure=(
            SettlementStepKind.TODO_COMPLETION,
            SettlementStepKind.DURABLE_WRITEBACK,
        ),
    ),
    AdapterSpec(
        name="turn_driver",
        run=_run_turn_adapter,
        success_receipts=(
            SettlementStepKind.VALIDATION,
            SettlementStepKind.DURABLE_WRITEBACK,
            SettlementStepKind.QUOTA_SPEND,
        ),
        calls_before_writeback_failure=(SettlementStepKind.DURABLE_WRITEBACK,),
    ),
)


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
def test_adapters_preserve_one_identity_and_ordered_receipts(
    adapter: AdapterSpec,
    tmp_path: Path,
) -> None:
    observation = adapter.run(tmp_path / adapter.name, "success")

    assert observation.result.failure is None
    assert observation.result.value is not None
    assert (
        tuple(receipt.step_kind for receipt in observation.result.receipts)
        == adapter.success_receipts
    )
    effect_ids = {receipt.effect_id for receipt in observation.result.receipts}
    identity = observation.settlement_plan["identity"]
    assert isinstance(identity, Mapping)
    assert effect_ids == {identity["effect_id"]}


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
def test_adapters_preserve_failure_and_short_circuit_later_effects(
    adapter: AdapterSpec,
    tmp_path: Path,
) -> None:
    observation = adapter.run(tmp_path / adapter.name, "writeback_failure")

    assert observation.result.failure is not None
    assert observation.result.failure.step_kind is SettlementStepKind.DURABLE_WRITEBACK
    assert observation.effect_calls == adapter.calls_before_writeback_failure
    assert SettlementStepKind.QUOTA_SPEND not in observation.effect_calls
    assert all(
        receipt.step_kind is not SettlementStepKind.QUOTA_SPEND
        for receipt in observation.result.receipts
    )


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
def test_adapters_fail_validation_before_any_effect_for_invalid_identity(
    adapter: AdapterSpec,
    tmp_path: Path,
) -> None:
    observation = adapter.run(tmp_path / adapter.name, "invalid_identity")

    assert observation.result.failure is not None
    assert observation.result.failure.step_kind is SettlementStepKind.VALIDATION
    assert observation.effect_calls == ()
    assert observation.result.receipts == ()


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda adapter: adapter.name)
def test_scheduler_remains_outside_each_adapter_settlement(
    adapter: AdapterSpec,
    tmp_path: Path,
) -> None:
    observation = adapter.run(tmp_path / adapter.name, "success")

    host_handoff = observation.settlement_plan["host_handoff"]
    assert isinstance(host_handoff, Mapping)
    assert host_handoff == {
        "owner": "host",
        "kind": "scheduler_handoff",
        "inside_agent_settlement": False,
    }
    ordered_steps = observation.settlement_plan["ordered_steps"]
    assert isinstance(ordered_steps, list)
    assert {step["kind"] for step in ordered_steps} <= {
        step_kind.value for step_kind in SettlementStepKind
    }
    assert all(
        not receipt.step_kind.value.startswith("scheduler_")
        for receipt in observation.result.receipts
    )
