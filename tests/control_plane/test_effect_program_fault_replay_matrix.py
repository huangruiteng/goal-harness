from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from loopx.control_plane.effect_program import (
    SettlementFailureKind,
    SettlementResult,
    SettlementStepKind,
)
from loopx.control_plane.turn_driver.settlement import (
    TurnSettlementState,
    execute_turn_driver_settlement,
)
from loopx.control_plane.turn_driver.transaction import (
    TRANSACTION_PHASES,
    build_loopx_turn_transaction_plan,
)

EXPECTED_TRANSACTION_PHASES = (
    "host_execute",
    "typed_result",
    "validation",
    "durable_writeback",
    "quota_spend",
    "scheduler_apply",
    "scheduler_ack",
)
EXPECTED_SETTLEMENT_PHASES = (
    SettlementStepKind.VALIDATION,
    SettlementStepKind.DURABLE_WRITEBACK,
    SettlementStepKind.QUOTA_SPEND,
)
LEGAL_PHASE_PREFIXES = tuple(
    EXPECTED_TRANSACTION_PHASES[:prefix_length]
    for prefix_length in range(len(EXPECTED_TRANSACTION_PHASES) + 1)
)


def _transaction_plan() -> dict[str, Any]:
    return build_loopx_turn_transaction_plan(
        planned=True,
        lineage={
            "goal_id": "fault-matrix-goal",
            "agent_id": "codex-fault-matrix",
            "todo_id": "todo_faultmatrix1",
        },
        host="generic-cli",
        execution_mode="isolated-headless",
        session_action="resume",
        turn_instance_id="fault-matrix-turn-1",
    )


def _effect_id(transaction_plan: Mapping[str, Any]) -> str:
    settlement_plan = transaction_plan["settlement_plan"]
    assert isinstance(settlement_plan, Mapping)
    identity = settlement_plan["identity"]
    assert isinstance(identity, Mapping)
    return str(identity["effect_id"])


def _committed_payload(
    step_kind: SettlementStepKind,
    *,
    effect_id: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "appended": True,
        "effect_id": effect_id,
        "step_kind": step_kind.value,
    }


def _payload_for_prefix(
    prefix: Sequence[str],
    step_kind: SettlementStepKind,
    *,
    effect_id: str,
) -> Mapping[str, Any] | None:
    if step_kind.value not in prefix:
        return None
    return _committed_payload(step_kind, effect_id=effect_id)


def _run_settlement(
    transaction_plan: Mapping[str, Any],
    *,
    completed_phases: Sequence[str],
    writeback_payload: Mapping[str, Any] | None = None,
    quota_spend_payload: Mapping[str, Any] | None = None,
    reject_at: SettlementStepKind | None = None,
) -> tuple[
    SettlementResult[TurnSettlementState],
    list[SettlementStepKind],
    list[tuple[SettlementStepKind, tuple[str, ...]]],
]:
    calls: list[SettlementStepKind] = []
    checkpoints: list[tuple[SettlementStepKind, tuple[str, ...]]] = []
    effect_id = _effect_id(transaction_plan)

    def effect(step_kind: SettlementStepKind) -> Mapping[str, Any]:
        calls.append(step_kind)
        if reject_at is step_kind:
            return {
                "ok": False,
                "appended": False,
                "reason": f"{step_kind.value} rejected by fault matrix",
            }
        return _committed_payload(step_kind, effect_id=effect_id)

    result = execute_turn_driver_settlement(
        transaction_plan,
        transaction_phases=TRANSACTION_PHASES,
        completed_phases=completed_phases,
        writeback_payload=writeback_payload,
        quota_spend_payload=quota_spend_payload,
        writeback=lambda: effect(SettlementStepKind.DURABLE_WRITEBACK),
        spend=lambda: effect(SettlementStepKind.QUOTA_SPEND),
        checkpoint=lambda step_kind, _payload, phases: checkpoints.append(
            (step_kind, phases)
        ),
    )
    return result, calls, checkpoints


def _prefix_id(prefix: Sequence[str]) -> str:
    return "empty" if not prefix else "-".join(prefix)


def test_transaction_phase_order_matches_the_settlement_protocol() -> None:
    assert TRANSACTION_PHASES == EXPECTED_TRANSACTION_PHASES


@pytest.mark.parametrize(
    "prefix",
    LEGAL_PHASE_PREFIXES,
    ids=_prefix_id,
)
def test_every_legal_phase_prefix_replays_without_duplicate_effects(
    prefix: tuple[str, ...],
) -> None:
    transaction_plan = _transaction_plan()
    effect_id = _effect_id(transaction_plan)
    writeback_payload = _payload_for_prefix(
        prefix,
        SettlementStepKind.DURABLE_WRITEBACK,
        effect_id=effect_id,
    )
    quota_spend_payload = _payload_for_prefix(
        prefix,
        SettlementStepKind.QUOTA_SPEND,
        effect_id=effect_id,
    )

    result, first_calls, checkpoints = _run_settlement(
        transaction_plan,
        completed_phases=prefix,
        writeback_payload=writeback_payload,
        quota_spend_payload=quota_spend_payload,
    )

    if SettlementStepKind.VALIDATION.value not in prefix:
        assert result.failure is not None
        assert result.failure.kind is SettlementFailureKind.RECEIPT_MISSING
        assert result.failure.step_kind is SettlementStepKind.VALIDATION
        assert first_calls == []
        assert checkpoints == []
        return

    assert result.failure is None
    assert result.value is not None
    expected_first_calls = [
        step_kind
        for step_kind in EXPECTED_SETTLEMENT_PHASES[1:]
        if step_kind.value not in prefix
    ]
    assert first_calls == expected_first_calls
    assert [step_kind for step_kind, _phases in checkpoints] == expected_first_calls
    assert [receipt.step_kind for receipt in result.receipts] == list(
        EXPECTED_SETTLEMENT_PHASES
    )
    assert {receipt.effect_id for receipt in result.receipts} == {effect_id}

    replay, replay_calls, replay_checkpoints = _run_settlement(
        transaction_plan,
        completed_phases=result.value.completed_phases,
        writeback_payload=result.value.writeback,
        quota_spend_payload=result.value.quota_spend,
    )

    assert replay.failure is None
    assert replay_calls == []
    assert replay_checkpoints == []
    combined_calls = [*first_calls, *replay_calls]
    assert combined_calls.count(SettlementStepKind.DURABLE_WRITEBACK) <= 1
    assert combined_calls.count(SettlementStepKind.QUOTA_SPEND) <= 1


@pytest.mark.parametrize(
    ("completed_phases", "writeback_payload", "quota_spend_payload"),
    [
        (
            (
                *EXPECTED_TRANSACTION_PHASES[:3],
                SettlementStepKind.QUOTA_SPEND.value,
            ),
            None,
            {"ok": True, "appended": True},
        ),
        (
            EXPECTED_TRANSACTION_PHASES[:5],
            None,
            {"ok": True, "appended": True},
        ),
    ],
    ids=("skipped-writeback-phase", "missing-writeback-receipt"),
)
def test_spend_claim_without_writeback_fails_closed(
    completed_phases: tuple[str, ...],
    writeback_payload: Mapping[str, Any] | None,
    quota_spend_payload: Mapping[str, Any] | None,
) -> None:
    result, calls, checkpoints = _run_settlement(
        _transaction_plan(),
        completed_phases=completed_phases,
        writeback_payload=writeback_payload,
        quota_spend_payload=quota_spend_payload,
    )

    assert result.failure is not None
    assert calls == []
    assert checkpoints == []
    assert all(
        receipt.step_kind is not SettlementStepKind.QUOTA_SPEND
        for receipt in result.receipts
    )


@pytest.mark.parametrize(
    ("reject_at", "prefix", "expected_calls", "expected_receipts"),
    [
        (
            SettlementStepKind.DURABLE_WRITEBACK,
            EXPECTED_TRANSACTION_PHASES[:3],
            [SettlementStepKind.DURABLE_WRITEBACK],
            [SettlementStepKind.VALIDATION],
        ),
        (
            SettlementStepKind.QUOTA_SPEND,
            EXPECTED_TRANSACTION_PHASES[:3],
            [
                SettlementStepKind.DURABLE_WRITEBACK,
                SettlementStepKind.QUOTA_SPEND,
            ],
            [
                SettlementStepKind.VALIDATION,
                SettlementStepKind.DURABLE_WRITEBACK,
            ],
        ),
        (
            SettlementStepKind.QUOTA_SPEND,
            EXPECTED_TRANSACTION_PHASES[:4],
            [SettlementStepKind.QUOTA_SPEND],
            [
                SettlementStepKind.VALIDATION,
                SettlementStepKind.DURABLE_WRITEBACK,
            ],
        ),
    ],
    ids=(
        "writeback-rejected",
        "spend-rejected-after-writeback",
        "replayed-spend-rejected",
    ),
)
def test_failure_short_circuits_every_later_effect(
    reject_at: SettlementStepKind,
    prefix: tuple[str, ...],
    expected_calls: list[SettlementStepKind],
    expected_receipts: list[SettlementStepKind],
) -> None:
    transaction_plan = _transaction_plan()
    effect_id = _effect_id(transaction_plan)

    result, calls, checkpoints = _run_settlement(
        transaction_plan,
        completed_phases=prefix,
        writeback_payload=_payload_for_prefix(
            prefix,
            SettlementStepKind.DURABLE_WRITEBACK,
            effect_id=effect_id,
        ),
        quota_spend_payload=_payload_for_prefix(
            prefix,
            SettlementStepKind.QUOTA_SPEND,
            effect_id=effect_id,
        ),
        reject_at=reject_at,
    )

    assert result.failure is not None
    assert result.failure.step_kind is reject_at
    assert calls == expected_calls
    assert [receipt.step_kind for receipt in result.receipts] == expected_receipts
    committed_steps = [step_kind for step_kind, _phases in checkpoints]
    assert reject_at not in committed_steps
    assert all(
        EXPECTED_SETTLEMENT_PHASES.index(step_kind)
        < EXPECTED_SETTLEMENT_PHASES.index(reject_at)
        for step_kind in committed_steps
    )


# ── Task-lease fault/replay scenarios ──────────────────────────────────
