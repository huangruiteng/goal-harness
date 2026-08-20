from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from loopx.control_plane import effect_program as core_effect_program
from loopx.control_plane.effect_program import (
    SettlementFailureKind,
    SettlementIdentity,
    SettlementReceipt,
    SettlementResult,
    SettlementStepKind,
)
from loopx.control_plane.quota import effect_program as quota_effect_program
from loopx.control_plane.quota.heartbeat_receipt import (
    heartbeat_receipt_settlement_replan_obligation_id,
    heartbeat_receipt_settlement_todo_id,
)
from loopx.control_plane.quota.settlement import (
    build_codex_app_settlement_plan,
    infer_persisted_heartbeat_settlement_identity,
    require_settlement_terminal_closeout,
    resolve_heartbeat_settlement_identity,
    settlement_step_command,
)
from loopx.control_plane.quota.settlement_cli import (
    quota_rollout_replan_obligation_id,
    quota_rollout_todo_id,
)
from loopx.control_plane.scheduler.execution_context import (
    SchedulerRuntimeProfile,
    scheduler_execution_context_for_runtime_profile,
)
from loopx.control_plane.work_items.interaction_contract import (
    interaction_next_cli_actions,
)
from loopx.rollout_event_log import rollout_event_log_path

GOAL_ID = "settlement-goal"
AGENT_ID = "codex-settlement"
TODO_ID = "todo_settlement"
TURN_ID = "turn-settlement-1"


def _receipt(step: SettlementStepKind, marker: str) -> SettlementReceipt:
    return SettlementReceipt(
        step_kind=step,
        status="committed",
        effect_id="effect-1",
        source_ref=marker,
    )


def test_quota_reexports_the_core_settlement_algebra() -> None:
    assert (
        quota_effect_program.SettlementIdentity
        is core_effect_program.SettlementIdentity
    )
    assert quota_effect_program.SettlementPlan is core_effect_program.SettlementPlan
    assert quota_effect_program.SettlementResult is core_effect_program.SettlementResult


def test_settlement_identity_rejects_dual_binding_before_projection() -> None:
    with pytest.raises(ValueError, match="cannot bind both"):
        SettlementIdentity(
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            todo_id=TODO_ID,
            turn_instance_id=TURN_ID,
            replan_obligation_id="replan-0000000000000001",
        )


def test_replan_bound_heartbeat_receipt_is_not_projected_as_a_todo() -> None:
    obligation_id = "replan-0000000000000001"
    event = {
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "run_id": TURN_ID,
        "details": {"replan_obligation_id": obligation_id},
    }

    assert heartbeat_receipt_settlement_todo_id(event) is None
    assert heartbeat_receipt_settlement_replan_obligation_id(event) == obligation_id


def test_selected_todo_suppresses_stale_replan_packet_binding() -> None:
    payload = {
        "selected_todo": {"todo_id": TODO_ID},
        "replan_action_packet": {
            "obligation_id": "replan-0000000000000001",
        },
    }
    args = SimpleNamespace(todo_id=None, replan_obligation_id=None)

    assert quota_rollout_todo_id(payload, args) == TODO_ID
    assert quota_rollout_replan_obligation_id(payload, args) is None


def test_explicit_replan_binding_survives_newly_selected_todo() -> None:
    obligation_id = "replan-0000000000000001"
    payload = {"selected_todo": {"todo_id": TODO_ID}}
    args = SimpleNamespace(
        todo_id=None,
        replan_obligation_id=obligation_id,
    )

    assert quota_rollout_todo_id(payload, args) is None
    assert quota_rollout_replan_obligation_id(payload, args) == obligation_id


def test_rollout_projection_rejects_corrupted_dual_bound_plan() -> None:
    payload = {
        "interaction_contract": {
            "cli_channel": {
                "settlement_plan": {
                    "identity": {
                        "todo_id": TODO_ID,
                        "replan_obligation_id": "replan-0000000000000001",
                    }
                }
            }
        }
    }
    args = SimpleNamespace(todo_id=None, replan_obligation_id=None)

    with pytest.raises(ValueError, match="cannot bind both"):
        quota_rollout_todo_id(payload, args)


def _append_guard_receipt(
    runtime_root: Path,
    *,
    todo_id: str = TODO_ID,
    replan_obligation_id: str | None = None,
    effect_id: str | None = None,
) -> None:
    path = rollout_event_log_path(runtime_root, GOAL_ID)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "loopx_rollout_event_v0",
                "event_id": "event-guard",
                "event_kind": "quota_should_run",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "run_id": TURN_ID,
                "details": {
                    "todo_id": todo_id,
                    **(
                        {"replan_obligation_id": replan_obligation_id}
                        if replan_obligation_id is not None
                        else {}
                    ),
                    **(
                        {"settlement_effect_id": effect_id}
                        if effect_id is not None
                        else {}
                    ),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _append_run_index_record(runtime_root: Path, record: dict) -> None:
    path = runtime_root / "goals" / GOAL_ID / "runs" / "index.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")


def test_terminal_closeout_receipt_rejects_ordinary_completion_event(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    identity = SettlementIdentity(GOAL_ID, AGENT_ID, TODO_ID, TURN_ID)
    path = rollout_event_log_path(runtime_root, GOAL_ID)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "loopx_rollout_event_v0",
                "event_id": "event-ordinary-completion",
                "event_kind": "todo_complete",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "run_id": TURN_ID,
                "details": {
                    "settlement_effect_id": identity.effect_id,
                    "no_followup": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = require_settlement_terminal_closeout(runtime_root, identity)

    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.RECEIPT_MISSING
    assert result.failure.step_kind is SettlementStepKind.TERMINAL_CLOSEOUT


def test_settlement_result_satisfies_left_and_right_identity() -> None:
    def writeback(value: int) -> SettlementResult[int]:
        return SettlementResult.pure(
            value + 1,
            receipts=(_receipt(SettlementStepKind.DURABLE_WRITEBACK, "writeback"),),
        )

    assert SettlementResult.pure(2).bind(writeback) == writeback(2)
    result = writeback(2)
    assert result.bind(SettlementResult.pure) == result


def test_settlement_result_satisfies_associativity_and_preserves_order() -> None:
    def writeback(value: int) -> SettlementResult[int]:
        return SettlementResult.pure(
            value + 1,
            receipts=(_receipt(SettlementStepKind.DURABLE_WRITEBACK, "writeback"),),
        )

    def spend(value: int) -> SettlementResult[str]:
        return SettlementResult.pure(
            str(value),
            receipts=(_receipt(SettlementStepKind.QUOTA_SPEND, "spend"),),
        )

    initial = SettlementResult.pure(1)
    left = initial.bind(writeback).bind(spend)
    right = initial.bind(lambda value: writeback(value).bind(spend))

    assert left == right
    assert [receipt.step_kind for receipt in left.receipts] == [
        SettlementStepKind.DURABLE_WRITEBACK,
        SettlementStepKind.QUOTA_SPEND,
    ]
    assert (
        initial.bind(spend).bind(lambda value: writeback(int(value))).receipts
        != left.receipts
    )


@pytest.mark.parametrize(
    "failure_kind",
    [
        SettlementFailureKind.CANCELLED,
        SettlementFailureKind.PERMISSION_DENIED,
        SettlementFailureKind.BUDGET_REJECTED,
    ],
)
def test_settlement_result_short_circuits_without_erasing_failure(
    failure_kind: SettlementFailureKind,
) -> None:
    failed: SettlementResult[int] = SettlementResult.failed(
        kind=failure_kind,
        step_kind=SettlementStepKind.DURABLE_WRITEBACK,
        reason="writeback denied",
        receipts=(_receipt(SettlementStepKind.VALIDATION, "validation"),),
    )
    called = False

    def spend(_value: int) -> SettlementResult[str]:
        nonlocal called
        called = True
        return SettlementResult.pure("spent")

    result = failed.bind(spend)

    assert called is False
    assert result.failure == failed.failure
    assert result.failure is not None
    assert result.failure.kind is failure_kind
    assert result.receipts == failed.receipts


def test_codex_app_plan_projects_one_identity_across_settlement_steps() -> None:
    plan = build_codex_app_settlement_plan(
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        scoped_cli_args=f" --agent-id {AGENT_ID}",
        lifecycle_actor_args=f" --agent-id {AGENT_ID}",
    ).as_dict()

    assert plan["identity"]["todo_id"] == TODO_ID
    assert plan["identity"]["turn_instance_id"] == "${LOOPX_TURN:?}"
    assert [step["kind"] for step in plan["ordered_steps"]] == [
        "validation",
        "durable_writeback",
        "quota_spend",
        "terminal_closeout",
    ]
    for kind in (
        SettlementStepKind.DURABLE_WRITEBACK,
        SettlementStepKind.QUOTA_SPEND,
        SettlementStepKind.TERMINAL_CLOSEOUT,
    ):
        command = settlement_step_command(plan, kind)
        assert command is not None
        assert f"--todo-id {TODO_ID}" in command
        assert '--turn-instance-id "${LOOPX_TURN:?}"' in command
    assert plan["host_handoff"]["inside_agent_settlement"] is False


@pytest.mark.parametrize(
    ("todo_id", "replan_obligation_id"),
    [
        (None, None),
        (TODO_ID, "replan-0000000000000001"),
    ],
)
def test_codex_app_plan_rejects_ambiguous_settlement_binding(
    todo_id: str | None,
    replan_obligation_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="requires exactly one"):
        build_codex_app_settlement_plan(
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            todo_id=todo_id,
            replan_obligation_id=replan_obligation_id,
            scoped_cli_args=f" --agent-id {AGENT_ID}",
            lifecycle_actor_args=f" --agent-id {AGENT_ID}",
        )


def test_standard_codex_app_actions_use_typed_settlement_before_turn_driver() -> None:
    todo_id = "todo_123456789abc"
    actions = interaction_next_cli_actions(
        {
            "goal_id": GOAL_ID,
            "agent_identity": {"agent_id": AGENT_ID},
            "selected_todo": {"todo_id": todo_id},
        },
        mode="bounded_delivery",
        scheduler_execution_context=scheduler_execution_context_for_runtime_profile(
            SchedulerRuntimeProfile.CODEX_APP_HEARTBEAT
        ),
    )

    assert len(actions) == 2
    assert actions[0].startswith("loopx refresh-state")
    assert actions[1].startswith("loopx quota spend-slot")
    for command in actions:
        assert f"--todo-id {todo_id}" in command
        assert '--turn-instance-id "${LOOPX_TURN:?}"' in command


@pytest.mark.parametrize(
    "profile",
    (
        SchedulerRuntimeProfile.ARK_MANAGED_AGENT_GOAL,
        SchedulerRuntimeProfile.CODEX_APP_SSH_VISIBLE,
        SchedulerRuntimeProfile.CODEX_CLI_VISIBLE,
    ),
)
def test_native_goal_actions_preserve_visible_goal_spend_attribution(
    profile: SchedulerRuntimeProfile,
) -> None:
    todo_id = "todo_visible_goal"
    actions = interaction_next_cli_actions(
        {
            "goal_id": GOAL_ID,
            "agent_identity": {"agent_id": AGENT_ID},
            "selected_todo": {"todo_id": todo_id},
        },
        mode="bounded_delivery",
        scheduler_execution_context=scheduler_execution_context_for_runtime_profile(
            profile
        ),
    )

    assert len(actions) == 2
    assert actions[0].startswith("loopx refresh-state")
    assert actions[1] == (
        f"loopx quota spend-slot --goal-id {GOAL_ID} --slots 1 "
        f"--source visible-goal --execute --agent-id {AGENT_ID}"
    )
    assert all("--todo-id" not in command for command in actions)
    assert all("--turn-instance-id" not in command for command in actions)


def test_codex_app_external_observation_settles_only_substantive_writeback() -> None:
    todo_id = "todo_external_observation"
    actions = interaction_next_cli_actions(
        {
            "goal_id": GOAL_ID,
            "agent_identity": {"agent_id": AGENT_ID},
            "selected_todo": {"todo_id": todo_id},
        },
        mode="external_evidence_observation",
        scheduler_execution_context=scheduler_execution_context_for_runtime_profile(
            SchedulerRuntimeProfile.CODEX_APP_HEARTBEAT
        ),
    )

    assert len(actions) == 3
    assert actions[0].startswith("read approved")
    assert actions[1].startswith("on a substantive transition or blocker only:")
    assert "--delivery-outcome <outcome>" in actions[1]
    assert f"--todo-id {todo_id}" in actions[1]
    assert '--turn-instance-id "${LOOPX_TURN:?}"' in actions[1]
    assert actions[2].startswith("after that accountable writeback receipt only:")
    assert f"--todo-id {todo_id}" in actions[2]
    assert '--turn-instance-id "${LOOPX_TURN:?}"' in actions[2]
    assert "otherwise do not spend for unchanged observation" in actions[2]


def test_guard_receipt_resolves_stable_settlement_identity(tmp_path: Path) -> None:
    _append_guard_receipt(tmp_path)

    result = resolve_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        turn_instance_id=TURN_ID,
    )

    assert result.failure is None
    assert result.value is not None
    assert result.value.effect_id == (f"{GOAL_ID}:{AGENT_ID}:{TODO_ID}:{TURN_ID}")
    assert result.receipts[0].step_kind is SettlementStepKind.VALIDATION


def test_guard_receipt_rejects_different_todo(tmp_path: Path) -> None:
    _append_guard_receipt(tmp_path, todo_id="todo_original")

    result = resolve_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id="todo_successor",
        turn_instance_id=TURN_ID,
    )

    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.IDENTITY_MISMATCH
    assert result.failure.step_kind is SettlementStepKind.VALIDATION


def test_guard_receipt_rejects_different_effect_identity(tmp_path: Path) -> None:
    _append_guard_receipt(tmp_path, effect_id="different-effect")

    result = resolve_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        turn_instance_id=TURN_ID,
    )

    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.IDENTITY_MISMATCH
    assert "different-effect" in result.failure.reason


def test_guard_receipt_rejects_corrupted_dual_binding(tmp_path: Path) -> None:
    _append_guard_receipt(
        tmp_path,
        replan_obligation_id="replan-0000000000000001",
        effect_id=f"{GOAL_ID}:{AGENT_ID}:{TODO_ID}:{TURN_ID}",
    )

    result = resolve_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        turn_instance_id=TURN_ID,
    )

    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.IDENTITY_MISMATCH
    assert "conflicting Todo and autonomous replan bindings" in result.failure.reason


def test_guard_receipt_returns_typed_failure_for_effect_without_todo(
    tmp_path: Path,
) -> None:
    _append_guard_receipt(tmp_path, todo_id="", effect_id="effect-without-todo")

    result = resolve_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        turn_instance_id=TURN_ID,
    )

    assert result.failure is not None
    assert result.failure.kind is SettlementFailureKind.IDENTITY_MISMATCH
    assert "effect identity without a Todo" in result.failure.reason


def test_typed_material_poll_is_recovered_not_shadowed(tmp_path: Path) -> None:
    _append_guard_receipt(tmp_path)
    _append_run_index_record(
        tmp_path,
        {
            "classification": "quota_slot_spent",
            "agent_id": AGENT_ID,
            "todo_id": TODO_ID,
            "turn_instance_id": "turn-settlement-stale",
        },
    )
    _append_run_index_record(
        tmp_path,
        {
            "classification": "quota_monitor_poll",
            "material_change": True,
            "delivery_outcome": "outcome_progress",
            "agent_id": AGENT_ID,
            "todo_id": TODO_ID,
            "turn_instance_id": TURN_ID,
        },
    )

    result = infer_persisted_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
    )

    assert result is not None
    assert result.value is not None
    assert result.value.turn_instance_id == TURN_ID


def test_unknown_non_neutral_record_fails_closed(tmp_path: Path) -> None:
    _append_guard_receipt(tmp_path)
    _append_run_index_record(
        tmp_path,
        {
            "classification": "quota_slot_spent",
            "agent_id": AGENT_ID,
            "todo_id": TODO_ID,
            "turn_instance_id": TURN_ID,
        },
    )
    _append_run_index_record(
        tmp_path,
        {
            "classification": "quota_monitor_poll",
            "material_change": True,
            "agent_id": AGENT_ID,
        },
    )

    result = infer_persisted_heartbeat_settlement_identity(
        tmp_path,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
    )

    assert result is None
