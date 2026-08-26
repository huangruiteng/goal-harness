from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from loopx.control_plane.effect_program import (
    SettlementResult,
    SettlementStepKind,
)
from loopx.control_plane.quota.settlement import (
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
from loopx.control_plane.work_items.task_lease_settlement import (
    execute_task_lease_settlement,
)
from loopx.rollout_event_log import rollout_event_log_path

GOAL_ID = "replay-goal"
AGENT_ID = "replay-agent"
TODO_ID = "todo_incident"
TURN_ID = "replay-turn"
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "control_plane"
    / "effect_program_incident_replay_v0.json"
)
ALLOWED_CASE_KEYS = {
    "case_id",
    "adapter",
    "incident_class",
    "invariant_id",
    "rationale",
    "input",
    "expected",
}
REQUIRED_INVARIANTS = {
    "INV-WRITEBACK-BEFORE-SPEND",
    "INV-FAILURE-SHORT-CIRCUIT",
    "INV-ONE-EFFECT-IDENTITY",
    "INV-AT-MOST-ONCE-SETTLEMENT",
}


def _load_corpus() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _assert_public_case(value: Any, *, excluded_keys: set[str]) -> None:
    if isinstance(value, Mapping):
        assert not ({str(key).casefold() for key in value} & excluded_keys)
        for nested in value.values():
            _assert_public_case(nested, excluded_keys=excluded_keys)
    elif isinstance(value, list):
        for nested in value:
            _assert_public_case(nested, excluded_keys=excluded_keys)
    elif isinstance(value, str):
        assert "://" not in value
        assert not value.startswith("/")
        assert "@" not in value


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


def _observe(
    result: SettlementResult[Any],
    *,
    effect_calls: list[SettlementStepKind],
    checkpoint_steps: list[SettlementStepKind],
) -> dict[str, Any]:
    failure = result.failure
    return {
        "status": "failure" if failure else "success",
        "failure_kind": failure.kind.value if failure else None,
        "failure_step": failure.step_kind.value if failure else None,
        "effect_calls": [step.value for step in effect_calls],
        "checkpoint_steps": [step.value for step in checkpoint_steps],
        "receipt_steps": [receipt.step_kind.value for receipt in result.receipts],
        "receipt_identity_count": len(
            {receipt.effect_id for receipt in result.receipts}
        ),
    }


def _replay_turn_driver(case: Mapping[str, Any]) -> dict[str, Any]:
    case_input = case["input"]
    assert isinstance(case_input, Mapping)
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
    effect_id = _effect_id(transaction_plan)
    reject_at = (
        SettlementStepKind(str(case_input["reject_at"]))
        if case_input.get("reject_at")
        else None
    )
    effect_calls: list[SettlementStepKind] = []
    checkpoint_steps: list[SettlementStepKind] = []

    def effect(step_kind: SettlementStepKind) -> Mapping[str, Any]:
        effect_calls.append(step_kind)
        if step_kind is reject_at:
            return {
                "ok": False,
                "appended": False,
                "reason": f"{step_kind.value} rejected by replay fixture",
            }
        return _committed_payload(step_kind, effect_id=effect_id)

    result: SettlementResult[TurnSettlementState] = execute_turn_driver_settlement(
        transaction_plan,
        transaction_phases=TRANSACTION_PHASES,
        completed_phases=tuple(case_input["completed_phases"]),
        writeback_payload=(
            _committed_payload(
                SettlementStepKind.DURABLE_WRITEBACK,
                effect_id=effect_id,
            )
            if case_input.get("writeback_committed")
            else None
        ),
        quota_spend_payload=(
            _committed_payload(SettlementStepKind.QUOTA_SPEND, effect_id=effect_id)
            if case_input.get("spend_committed")
            else None
        ),
        writeback=lambda: effect(SettlementStepKind.DURABLE_WRITEBACK),
        spend=lambda: effect(SettlementStepKind.QUOTA_SPEND),
        checkpoint=lambda step, _payload, _phases: checkpoint_steps.append(step),
    )
    return _observe(
        result,
        effect_calls=effect_calls,
        checkpoint_steps=checkpoint_steps,
    )


def _replay_quota(case: Mapping[str, Any], runtime_root: Path) -> dict[str, Any]:
    case_input = case["input"]
    assert isinstance(case_input, Mapping)
    event_path = rollout_event_log_path(runtime_root, GOAL_ID)
    event_path.parent.mkdir(parents=True, exist_ok=True)
    event_path.write_text(
        json.dumps(
            {
                "schema_version": "loopx_rollout_event_v0",
                "event_id": "incident-replay-guard",
                "event_kind": "quota_should_run",
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "run_id": TURN_ID,
                "details": {
                    "todo_id": TODO_ID,
                    "settlement_effect_id": case_input["guard_effect_id"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = resolve_heartbeat_settlement_identity(
        runtime_root,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        todo_id=TODO_ID,
        turn_instance_id=TURN_ID,
    )
    return _observe(result, effect_calls=[], checkpoint_steps=[])


def _replay_task_lease(
    case: Mapping[str, Any],
    runtime_root: Path,
) -> dict[str, Any]:
    case_input = case["input"]
    assert isinstance(case_input, Mapping)
    registry_path = runtime_root / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": GOAL_ID,
                        "status": "active",
                        "repo": str(registry_path.parent),
                        "state_file": "ACTIVE_GOAL_STATE.md",
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT_ID],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    idempotency_key = str(case_input.get("idempotency_key") or TURN_ID)
    acquire = bool(case_input.get("acquire", True))
    effect_calls: list[SettlementStepKind] = []
    checkpoint_steps: list[SettlementStepKind] = []

    with (
        patch(
            "loopx.control_plane.work_items.task_lease.require_task_lease_owner_allowed",
            return_value={"status": "open", "claimed_by": AGENT_ID},
        ),
        patch(
            "loopx.control_plane.work_items.task_lease.active_conflicts",
            return_value=[],
        ),
    ):
        result = execute_task_lease_settlement(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            owner=AGENT_ID,
            todo_id=TODO_ID,
            idempotency_key=idempotency_key,
            write_scopes=["docs/**"],
            ttl_seconds=600,
            acquire=acquire,
        )

    return _observe(
        result,
        effect_calls=effect_calls,
        checkpoint_steps=checkpoint_steps,
    )


def test_incident_replay_corpus_is_small_and_public_safe() -> None:
    corpus = _load_corpus()

    assert corpus["schema_version"] == "effect_program_incident_replay_v0"
    assert 3 <= len(corpus["cases"]) <= 6
    assert len({case["case_id"] for case in corpus["cases"]}) == len(
        corpus["cases"]
    )
    assert {case["invariant_id"] for case in corpus["cases"]} == REQUIRED_INVARIANTS
    assert all(set(case) == ALLOWED_CASE_KEYS for case in corpus["cases"])
    assert all(len(case["rationale"]) >= 60 for case in corpus["cases"])
    excluded_keys = {
        str(key).casefold() for key in corpus["public_boundary"]["excluded_fields"]
    }
    for case in corpus["cases"]:
        _assert_public_case(case, excluded_keys=excluded_keys)


@pytest.mark.parametrize(
    "case",
    _load_corpus()["cases"],
    ids=lambda case: case["case_id"],
)
def test_generalized_incidents_replay_against_real_adapters(
    case: Mapping[str, Any],
    tmp_path: Path,
) -> None:
    if case["adapter"] == "turn_driver":
        observed = _replay_turn_driver(case)
    elif case["adapter"] == "quota":
        observed = _replay_quota(case, tmp_path / str(case["case_id"]))
    elif case["adapter"] == "task_lease":
        observed = _replay_task_lease(case, tmp_path / str(case["case_id"]))
    else:
        pytest.fail(f"unsupported incident replay adapter: {case['adapter']}")

    assert observed == case["expected"]
