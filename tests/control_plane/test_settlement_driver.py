"""Focused tests for the core-owned typed settlement receipt-chain driver.

The driver is the shared seam behind the quota adapter's validator chain and
the Turn adapter's effect executor.  Expectations are derived from the typed
settlement contract (RFC M7.1) and the existing parity behavior of both
adapters, not from implementation output.
"""

from __future__ import annotations

from typing import Any

import pytest

from loopx.control_plane.effect_program import (
    SettlementFailureKind,
    SettlementIdentity,
    SettlementStepKind,
)
from loopx.control_plane.settlement_driver import (
    commit_step_effect,
    effect_ids_match,
    require_matching_effect_id,
    seed_committed_steps,
    settlement_effect_ref,
    settlement_identity_from_plan,
    settlement_receipt,
)


IDENTITY = SettlementIdentity(
    goal_id="fixture-goal",
    agent_id="fixture-agent",
    todo_id="todo_fixture0001",
    turn_instance_id="fixture-turn",
)

SETTLEMENT_STEPS = (
    SettlementStepKind.VALIDATION,
    SettlementStepKind.DURABLE_WRITEBACK,
    SettlementStepKind.QUOTA_SPEND,
)

TRANSACTION_PHASES = (
    "host_execute",
    "typed_result",
    "validation",
    "durable_writeback",
    "quota_spend",
    "scheduler_apply",
    "scheduler_ack",
)

COMMITTED_PAYLOAD: dict[str, Any] = {"ok": True, "appended": True}


def _plan() -> dict[str, Any]:
    return {
        "transaction": {
            "turn_key": "sha256:fixture-turn",
            "settlement_plan": {
                "identity": {
                    "effect_id": IDENTITY.effect_id,
                    "goal_id": IDENTITY.goal_id,
                    "agent_id": IDENTITY.agent_id,
                    "todo_id": IDENTITY.todo_id,
                    "turn_instance_id": IDENTITY.turn_instance_id,
                }
            },
        }
    }


def _committed_payloads(
    *,
    writeback: bool = False,
    spend: bool = False,
) -> dict[SettlementStepKind, dict[str, Any] | None]:
    return {
        SettlementStepKind.VALIDATION: {},
        SettlementStepKind.DURABLE_WRITEBACK: (
            dict(COMMITTED_PAYLOAD) if writeback else None
        ),
        SettlementStepKind.QUOTA_SPEND: dict(COMMITTED_PAYLOAD) if spend else None,
    }


def test_effect_ids_match_allows_missing_and_equal_provenance() -> None:
    assert effect_ids_match(None, IDENTITY.effect_id) is True
    assert effect_ids_match(IDENTITY.effect_id, IDENTITY.effect_id) is True
    assert effect_ids_match("other-effect", IDENTITY.effect_id) is False


def test_settlement_receipt_is_committed_under_the_identity() -> None:
    receipt = settlement_receipt(
        IDENTITY,
        step_kind=SettlementStepKind.VALIDATION,
        source_ref="rollout_event:abc",
    )
    assert receipt.step_kind is SettlementStepKind.VALIDATION
    assert receipt.status == "committed"
    assert receipt.effect_id == IDENTITY.effect_id
    assert receipt.source_ref == "rollout_event:abc"


def test_settlement_identity_from_plan_fails_closed_on_incomplete_identity() -> None:
    plan = {"transaction": {"settlement_plan": {"identity": {"effect_id": "e"}}}}
    result = settlement_identity_from_plan(plan["transaction"])
    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.INVALID_IDENTITY
    assert result.failure.step_kind is SettlementStepKind.VALIDATION
    assert "incomplete identity" in result.failure.reason


@pytest.mark.parametrize(
    ("plan", "kind", "step", "reason_part"),
    [
        (
            {"transaction": {}},
            SettlementFailureKind.RECEIPT_MISSING,
            SettlementStepKind.VALIDATION,
            "no typed settlement plan",
        ),
        (
            {"transaction": {"settlement_plan": {}}},
            SettlementFailureKind.INVALID_IDENTITY,
            SettlementStepKind.VALIDATION,
            "has no identity",
        ),
        (
            {"transaction": {"settlement_plan": {"identity": {}}}},
            SettlementFailureKind.INVALID_IDENTITY,
            SettlementStepKind.VALIDATION,
            "incomplete identity",
        ),
    ],
)
def test_settlement_identity_from_plan_fails_closed(
    plan: dict[str, Any],
    kind: SettlementFailureKind,
    step: SettlementStepKind,
    reason_part: str,
) -> None:
    result = settlement_identity_from_plan(plan["transaction"])
    assert result.failure is not None
    assert result.failure.kind is kind
    assert result.failure.step_kind is step
    assert reason_part in result.failure.reason


def test_settlement_identity_from_plan_rejects_effect_id_mismatch() -> None:
    plan = _plan()
    plan["transaction"]["settlement_plan"]["identity"]["effect_id"] = "other"
    result = settlement_identity_from_plan(plan["transaction"])
    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.INVALID_IDENTITY
    assert "does not match its identity" in result.failure.reason


def test_require_matching_effect_id_fails_closed_on_mismatch() -> None:
    ok = require_matching_effect_id(None, IDENTITY.effect_id)
    assert ok.failure is None
    matched = require_matching_effect_id(IDENTITY.effect_id, IDENTITY.effect_id)
    assert matched.failure is None
    mismatch = require_matching_effect_id("other-effect", IDENTITY.effect_id)
    assert mismatch.failure is not None
    assert mismatch.failure.kind is SettlementFailureKind.IDENTITY_MISMATCH
    assert mismatch.failure.step_kind is SettlementStepKind.VALIDATION
    assert "other-effect" in mismatch.failure.reason
    assert IDENTITY.effect_id in mismatch.failure.reason


def test_seed_committed_steps_emits_ordered_receipts_for_committed_phases() -> None:
    result = seed_committed_steps(
        IDENTITY,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=_committed_payloads(writeback=True, spend=True),
        completed_phases=TRANSACTION_PHASES[:5],
        transaction_phases=TRANSACTION_PHASES,
        require_validation=True,
    )
    assert result.failure is None
    assert [r.step_kind for r in result.receipts] == [
        SettlementStepKind.VALIDATION,
        SettlementStepKind.DURABLE_WRITEBACK,
        SettlementStepKind.QUOTA_SPEND,
    ]
    assert all(r.effect_id == IDENTITY.effect_id for r in result.receipts)
    assert set(result.value) == set(SETTLEMENT_STEPS)


def test_seed_committed_steps_skips_pending_steps_when_phases_are_given() -> None:
    result = seed_committed_steps(
        IDENTITY,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=_committed_payloads(),
        completed_phases=TRANSACTION_PHASES[:3],
        transaction_phases=TRANSACTION_PHASES,
        require_validation=True,
    )
    assert result.failure is None
    assert [r.step_kind for r in result.receipts] == [
        SettlementStepKind.VALIDATION
    ]
    assert set(result.value) == {SettlementStepKind.VALIDATION}


def test_seed_committed_steps_fails_on_missing_committed_writeback_payload() -> None:
    result = seed_committed_steps(
        IDENTITY,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=_committed_payloads(),
        completed_phases=TRANSACTION_PHASES[:4],
        transaction_phases=TRANSACTION_PHASES,
        require_validation=True,
    )
    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.RECEIPT_MISSING
    assert result.failure.step_kind is SettlementStepKind.DURABLE_WRITEBACK
    assert result.failure.reason == (
        "Turn journal is missing its committed writeback payload"
    )
    assert [r.step_kind for r in result.receipts] == [
        SettlementStepKind.VALIDATION
    ]


def test_seed_committed_steps_rejects_non_prefix_phases() -> None:
    result = seed_committed_steps(
        IDENTITY,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=_committed_payloads(writeback=True),
        completed_phases=["host_execute", "validation"],
        transaction_phases=TRANSACTION_PHASES,
        require_validation=True,
    )
    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.RECEIPT_MISSING
    assert result.failure.step_kind is SettlementStepKind.VALIDATION
    assert "ordered transaction prefix" in result.failure.reason


def test_seed_committed_steps_validator_mode_fails_on_missing_step() -> None:
    result = seed_committed_steps(
        IDENTITY,
        ordered_steps=SETTLEMENT_STEPS,
        committed_payloads=_committed_payloads(writeback=True),
        completed_phases=None,
        require_validation=True,
    )
    assert result.failure is not None
    assert result.failure.step_kind is SettlementStepKind.QUOTA_SPEND
    assert result.failure.kind is SettlementFailureKind.RECEIPT_MISSING


def test_commit_step_effect_records_receipt_and_checkpoint() -> None:
    checkpoints: list[tuple[SettlementStepKind, Any, tuple[str, ...]]] = []

    def checkpoint(
        step_kind: SettlementStepKind,
        payload: Any,
        phases: tuple[str, ...],
    ) -> None:
        checkpoints.append((step_kind, payload, phases))

    result = commit_step_effect(
        IDENTITY,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        transaction_phases=TRANSACTION_PHASES,
        effect=lambda: dict(COMMITTED_PAYLOAD),
        checkpoint=checkpoint,
    )
    assert result.failure is None
    assert result.value == COMMITTED_PAYLOAD
    assert [r.step_kind for r in result.receipts] == [
        SettlementStepKind.DURABLE_WRITEBACK
    ]
    assert checkpoints == [
        (
            SettlementStepKind.DURABLE_WRITEBACK,
            COMMITTED_PAYLOAD,
            ("host_execute", "typed_result", "validation", "durable_writeback"),
        )
    ]


@pytest.mark.parametrize("keyword_only", [False, True])
def test_commit_step_effect_passes_stable_ref_to_new_callbacks(
    keyword_only: bool,
) -> None:
    observed_refs: list[str] = []

    def positional_effect(effect_ref: str) -> dict[str, Any]:
        observed_refs.append(effect_ref)
        return dict(COMMITTED_PAYLOAD)

    def keyword_effect(*, effect_ref: str) -> dict[str, Any]:
        observed_refs.append(effect_ref)
        return dict(COMMITTED_PAYLOAD)

    result = commit_step_effect(
        IDENTITY,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        transaction_phases=TRANSACTION_PHASES,
        effect=keyword_effect if keyword_only else positional_effect,
        checkpoint=lambda *_args: None,
    )

    assert result.failure is None
    assert observed_refs == [
        settlement_effect_ref(IDENTITY, SettlementStepKind.DURABLE_WRITEBACK)
    ]


def test_commit_step_effect_maps_callback_failure_kinds() -> None:
    writeback = commit_step_effect(
        IDENTITY,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        transaction_phases=TRANSACTION_PHASES,
        effect=lambda: {"ok": False, "reason": "writeback rejected"},
        checkpoint=lambda *_args: None,
    )
    assert writeback.failure is not None
    assert writeback.failure.kind is SettlementFailureKind.WRITEBACK_REJECTED

    budget = commit_step_effect(
        IDENTITY,
        step_kind=SettlementStepKind.QUOTA_SPEND,
        transaction_phases=TRANSACTION_PHASES,
        effect=lambda: {"ok": False, "reason": "compute budget exhausted"},
        checkpoint=lambda *_args: None,
    )
    assert budget.failure is not None
    assert budget.failure.kind is SettlementFailureKind.BUDGET_REJECTED

    rejected = commit_step_effect(
        IDENTITY,
        step_kind=SettlementStepKind.QUOTA_SPEND,
        transaction_phases=TRANSACTION_PHASES,
        effect=lambda: {"ok": False, "reason": "spend rejected"},
        checkpoint=lambda *_args: None,
    )
    assert rejected.failure is not None
    assert rejected.failure.kind is SettlementFailureKind.QUOTA_SPEND_REJECTED
