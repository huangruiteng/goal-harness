from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
from loopx.control_plane.work_items import task_lease_settlement
from loopx.control_plane.work_items.task_lease_settlement import (
    execute_task_lease_settlement,
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

TASK_LEASE_FAULT_GOAL = "task-lease-fault-goal"
TASK_LEASE_FAULT_AGENT = "task-lease-fault-agent"
TASK_LEASE_FAULT_TODO = "todo_lease_fault"
TASK_LEASE_FAULT_KEY = "fault-key-1"


def _write_task_lease_fault_registry(registry_path: Path) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": TASK_LEASE_FAULT_GOAL,
                        "status": "active",
                        "repo": str(registry_path.parent),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [TASK_LEASE_FAULT_AGENT],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("acquire_first", "expected_second_effect_calls"),
    [
        (True, []),  # second call is idempotent — no duplicate effect
    ],
    ids=("idempotent-replay",),
)
def test_task_lease_acquire_idempotent_replay(
    acquire_first: bool,
    expected_second_effect_calls: list[SettlementStepKind],
    tmp_path: Path,
) -> None:
    """Same identity + same params must not produce a duplicate side effect."""

    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"

    common = dict(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=TASK_LEASE_FAULT_GOAL,
        owner=TASK_LEASE_FAULT_AGENT,
        todo_id=TASK_LEASE_FAULT_TODO,
        idempotency_key=TASK_LEASE_FAULT_KEY,
        write_scopes=["docs/**"],
        ttl_seconds=600,
    )

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        first = execute_task_lease_settlement(**common, acquire=acquire_first)
        second = execute_task_lease_settlement(**common, acquire=True)

    assert first.failure is None
    assert second.failure is None
    assert first.value is not None
    assert second.value is not None

    first_effect_id = first.receipts[0].effect_id
    second_effect_id = second.receipts[0].effect_id
    assert first_effect_id == second_effect_id

    # The second call should discover the existing lease and return idempotent
    second_statuses = {r.status for r in second.receipts}
    assert "idempotent" in second_statuses


def test_task_lease_retries_after_provider_commit_before_final_reduction(
    tmp_path: Path,
) -> None:
    """A lost final reduction replays through the provider's same-key fence."""

    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"
    real_reduce = task_lease_settlement._reduce_task_lease_acquire
    dropped = False

    def drop_first_final(params: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal dropped
        result = real_reduce(params)
        if params.get("phase") == "finalize" and not dropped:
            dropped = True
            raise RuntimeError("simulated response loss after provider commit")
        return result

    common = {
        "registry_path": registry_path,
        "runtime_root": runtime_root,
        "goal_id": TASK_LEASE_FAULT_GOAL,
        "owner": TASK_LEASE_FAULT_AGENT,
        "todo_id": TASK_LEASE_FAULT_TODO,
        "idempotency_key": TASK_LEASE_FAULT_KEY,
        "write_scopes": ["docs/**"],
        "ttl_seconds": 600,
    }
    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
        patch.object(
            task_lease_settlement,
            "_reduce_task_lease_acquire",
            side_effect=drop_first_final,
        ),
    ):
        with pytest.raises(RuntimeError, match="simulated response loss"):
            execute_task_lease_settlement(**common)
        replay = execute_task_lease_settlement(**common)

    assert replay.failure is None
    assert replay.value is not None
    assert {receipt.status for receipt in replay.receipts} == {"idempotent"}
    assert len({receipt.effect_id for receipt in replay.receipts}) == 1


def test_task_lease_validation_fails_before_acquire(
    tmp_path: Path,
) -> None:
    """Invalid idempotency key must fail at validation with zero effects."""
    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        result = execute_task_lease_settlement(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=TASK_LEASE_FAULT_GOAL,
            owner=TASK_LEASE_FAULT_AGENT,
            todo_id=TASK_LEASE_FAULT_TODO,
            idempotency_key="bad key!",
            write_scopes=["docs/**"],
            ttl_seconds=600,
            acquire=True,
        )

    assert result.failure is not None
    assert result.failure.step_kind is SettlementStepKind.VALIDATION
    assert result.failure.kind is SettlementFailureKind.INVALID_IDENTITY
    assert result.receipts == ()


def test_task_lease_acquire_failure_short_circuits(
    tmp_path: Path,
) -> None:
    """When acquire is rejected, the result must carry failure at DURABLE_WRITEBACK."""
    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        result = execute_task_lease_settlement(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=TASK_LEASE_FAULT_GOAL,
            owner=TASK_LEASE_FAULT_AGENT,
            todo_id=TASK_LEASE_FAULT_TODO,
            idempotency_key=TASK_LEASE_FAULT_KEY,
            write_scopes=["docs/**"],
            ttl_seconds=600,
            acquire=False,
        )

    assert result.failure is not None
    assert result.failure.step_kind is SettlementStepKind.DURABLE_WRITEBACK
    assert result.failure.kind is SettlementFailureKind.WRITEBACK_REJECTED
    # Receipts should only contain validation (not acquire)
    receipt_kinds = {r.step_kind for r in result.receipts}
    assert SettlementStepKind.DURABLE_WRITEBACK not in receipt_kinds


def test_task_lease_same_key_different_params_rejected(
    tmp_path: Path,
) -> None:
    """Same idempotency key with different write_scopes or ttl must be rejected.

    This is the regression test for the maintainer-requested idempotency-key
    parameter-matching check inside ``acquire_task_lease``.  The adapter must
    route through the real acquire path so the check is enforced atomically
    under the per-goal exclusive_file_lock.
    """
    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"

    common = dict(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=TASK_LEASE_FAULT_GOAL,
        owner=TASK_LEASE_FAULT_AGENT,
        todo_id=TASK_LEASE_FAULT_TODO,
        idempotency_key=TASK_LEASE_FAULT_KEY,
    )

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        # First acquire succeeds with docs/** scopes and 600s ttl
        first = execute_task_lease_settlement(
            **common,
            write_scopes=["docs/**"],
            ttl_seconds=600,
            acquire=True,
        )
        assert first.failure is None

        # Same key, different write_scopes — must be rejected
        second = execute_task_lease_settlement(
            **common,
            write_scopes=["src/**"],
            ttl_seconds=600,
            acquire=True,
        )
        assert second.failure is not None
        assert second.failure.step_kind is SettlementStepKind.DURABLE_WRITEBACK
        assert second.failure.kind is SettlementFailureKind.INVALID_IDENTITY
        assert "idempotency" in str(second.failure.reason).lower()

        # Same key, different ttl — must be rejected
        third = execute_task_lease_settlement(
            **common,
            write_scopes=["docs/**"],
            ttl_seconds=300,
            acquire=True,
        )
        assert third.failure is not None
        assert third.failure.step_kind is SettlementStepKind.DURABLE_WRITEBACK
        assert "idempotency" in str(third.failure.reason).lower()


def test_task_lease_effect_id_consistency(
    tmp_path: Path,
) -> None:
    """All receipts within one settlement run must share a single effect_id."""
    registry_path = tmp_path / "registry.json"
    _write_task_lease_fault_registry(registry_path)
    runtime_root = tmp_path / "runtime"

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": TASK_LEASE_FAULT_AGENT},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        result = execute_task_lease_settlement(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=TASK_LEASE_FAULT_GOAL,
            owner=TASK_LEASE_FAULT_AGENT,
            todo_id=TASK_LEASE_FAULT_TODO,
            idempotency_key=TASK_LEASE_FAULT_KEY,
            write_scopes=["docs/**"],
            ttl_seconds=600,
            acquire=True,
        )

    assert result.failure is None
    effect_ids = {receipt.effect_id for receipt in result.receipts}
    assert len(effect_ids) == 1
    expected_effect_id = (
        f"{TASK_LEASE_FAULT_GOAL}:{TASK_LEASE_FAULT_AGENT}"
        f":{TASK_LEASE_FAULT_TODO}:{TASK_LEASE_FAULT_KEY}"
    )
    assert effect_ids == {expected_effect_id}
