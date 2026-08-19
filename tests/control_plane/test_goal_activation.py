from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.chat_action_store import ChatActionStore
from loopx.chat_actions import ChatActionService
from loopx.control_plane.goals.activation import (
    GoalActivationState,
    build_goal_activation,
    goal_activation_state,
)
from loopx.control_plane.goals.activation_service import set_goal_activation_state
from loopx.control_plane.scheduler.execution_context import (
    SchedulerRuntimeProfile,
    scheduler_execution_context_for_runtime_profile,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload
from loopx.global_registry import sync_project_registry_to_global
from loopx.history import load_registry
from loopx.quota import build_quota_should_run, quota_status
from loopx.registry import registry_goals


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _goal(path: Path, goal_id: str = "goal-one") -> dict[str, object]:
    return next(
        goal
        for goal in registry_goals(load_registry(path))
        if goal.get("id") == goal_id
    )


@pytest.fixture()
def connected_registries(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    source_registry = tmp_path / "project" / ".loopx" / "registry.json"
    source_payload: dict[str, object] = {
        "schema_version": "0.1",
        "common_runtime_root": str(runtime_root),
        "goals": [
            {
                "id": "goal-one",
                "display_name": "A public Goal",
                "repo": str(tmp_path / "project"),
                "quota": {"compute": 1, "allowed_slots": 4, "spent_slots": 0},
            }
        ],
    }
    _write_json(source_registry, source_payload)
    synced = sync_project_registry_to_global(
        registry_path=source_registry,
        runtime_root_override=str(runtime_root),
        goal_id="goal-one",
        dry_run=False,
    )
    assert synced["ok"] is True
    return source_registry, runtime_root / "registry.global.json"


def test_activation_contract_defaults_active_and_rejects_unknown_state() -> None:
    assert goal_activation_state({}) is GoalActivationState.ACTIVE
    assert goal_activation_state({"activation_state": "stopped"}) is GoalActivationState.STOPPED
    with pytest.raises(ValueError, match="active or stopped"):
        goal_activation_state({"activation_state": "archived"})


def test_stop_preview_is_zero_write(connected_registries: tuple[Path, Path]) -> None:
    source_registry, global_registry = connected_registries
    before_source = source_registry.read_bytes()
    before_global = global_registry.read_bytes()

    result = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="stopped",
        execute=False,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["changed"] is True
    assert result["written"] is False
    assert source_registry.read_bytes() == before_source
    assert global_registry.read_bytes() == before_global


def test_stop_and_resume_sync_source_global_and_quota(
    connected_registries: tuple[Path, Path],
) -> None:
    source_registry, global_registry = connected_registries

    stopped = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="stopped",
        reason="Owner is reducing the active workspace",
        execute=True,
    )

    assert stopped["ok"] is True
    assert stopped["written"] is True
    assert stopped["readback"]["verified"] is True
    assert goal_activation_state(_goal(source_registry)) is GoalActivationState.STOPPED
    assert goal_activation_state(_goal(global_registry)) is GoalActivationState.STOPPED
    stopped_quota = quota_status(_goal(global_registry), waiting_on="codex")
    assert stopped_quota["state"] == "paused"
    assert stopped_quota["compute"] == 0
    assert stopped_quota["allowed_slots"] == 0
    assert stopped_quota["configured_compute"] == 1
    assert stopped_quota["configured_allowed_slots"] == 4
    assert stopped_quota["goal_activation_state"] == "stopped"
    assert stopped_quota["pause_cause"] == "goal_stopped"
    assert stopped_quota["blocked_action_scope"] == "automatic_agent_turns"

    resumed = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="active",
        execute=True,
    )

    assert resumed["ok"] is True
    assert resumed["readback"]["verified"] is True
    assert goal_activation_state(_goal(source_registry)) is GoalActivationState.ACTIVE
    assert goal_activation_state(_goal(global_registry)) is GoalActivationState.ACTIVE
    resumed_quota = quota_status(_goal(global_registry), waiting_on="codex")
    assert resumed_quota["state"] == "eligible"
    assert resumed_quota["compute"] == 1
    assert resumed_quota["allowed_slots"] == 4


def test_stopped_goal_and_zero_compute_keep_distinct_resume_authority() -> None:
    stopped_status = quota_status_payload(
        goal_id="goal-one",
        status="active",
        recommended_action="Continue the selected work.",
        quota_extra={"compute": 1},
        goal_extra={"activation_state": "stopped"},
    )
    # Stopped Goals are absent from active attention by design. The quota plan
    # must still derive the lifecycle pause from run history.
    stopped_status["attention_queue"]["items"] = []

    stopped = build_quota_should_run(
        stopped_status,
        goal_id="goal-one",
        codex_app_current_rrule="FREQ=MINUTELY;INTERVAL=30",
        scheduler_execution_context=scheduler_execution_context_for_runtime_profile(
            SchedulerRuntimeProfile.CODEX_APP_HEARTBEAT
        ),
    )

    assert stopped["should_run"] is False
    assert stopped["quota"]["compute"] == 0
    assert stopped["quota"]["configured_compute"] == 1
    assert stopped["pause_cause"] == "goal_stopped"
    assert stopped["heartbeat_recommendation"]["recommended_mode"] == "goal_stopped"
    assert stopped["automation_liveness"]["automation_action"] == "stop_goal_stopped"
    assert stopped["scheduler_hint"]["reason_code"] == "goal_stopped"
    assert (
        stopped["scheduler_hint"]["codex_app"]["resume_trigger"]
        == "explicit Goal lifecycle resume"
    )

    zero_compute = quota_status(
        {"id": "goal-one", "quota": {"compute": 0}},
        waiting_on="codex",
    )
    assert zero_compute["pause_cause"] == "compute_quota_zero"
    assert "goal_activation_state" not in zero_compute

    stopped_with_zero_compute = quota_status(
        {
            "id": "goal-one",
            "activation_state": "stopped",
            "quota": {"compute": 0},
        },
        waiting_on="codex",
    )
    assert stopped_with_zero_compute["pause_cause"] == "goal_stopped"
    assert stopped_with_zero_compute["configured_compute"] == 0

    resumed_with_zero_compute = quota_status(
        {
            "id": "goal-one",
            "activation_state": "active",
            "quota": {"compute": 0},
        },
        waiting_on="codex",
    )
    assert resumed_with_zero_compute["pause_cause"] == "compute_quota_zero"


def test_idempotent_execute_reconciles_drifted_global_projection(
    connected_registries: tuple[Path, Path],
) -> None:
    source_registry, global_registry = connected_registries
    source_payload = load_registry(source_registry)
    registry_goals(source_payload)[0]["activation"] = build_goal_activation(
        state="stopped",
        updated_at="2026-08-20T00:00:00+00:00",
        reason="Owner stopped the Goal",
    )
    _write_json(source_registry, source_payload)

    result = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="stopped",
        execute=True,
    )

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["written"] is False
    assert result["projection_reconciled"] is True
    assert result["readback"]["verified"] is True
    assert goal_activation_state(_goal(global_registry)) is GoalActivationState.STOPPED


def test_stop_migrates_legacy_projected_activation_state(
    connected_registries: tuple[Path, Path],
) -> None:
    source_registry, global_registry = connected_registries
    source_payload = load_registry(source_registry)
    registry_goals(source_payload)[0]["activation_state"] = "active"
    _write_json(source_registry, source_payload)
    sync_project_registry_to_global(
        registry_path=source_registry,
        runtime_root_override=None,
        goal_id="goal-one",
        dry_run=False,
    )

    stopped = set_goal_activation_state(
        registry_path=global_registry,
        goal_id="goal-one",
        state="stopped",
        execute=True,
    )

    assert stopped["ok"] is True
    source_goal = _goal(source_registry)
    global_goal = _goal(global_registry)
    assert "activation_state" not in source_goal
    assert "activation_state" not in global_goal
    assert goal_activation_state(source_goal) is GoalActivationState.STOPPED
    assert goal_activation_state(global_goal) is GoalActivationState.STOPPED


def test_owner_confirmed_typed_action_stops_goal(
    connected_registries: tuple[Path, Path], tmp_path: Path
) -> None:
    _source_registry, global_registry = connected_registries
    service = ChatActionService(
        store=ChatActionStore(tmp_path / "actions"),
        registry_path=global_registry,
    )
    proposal = service.preview(
        {
            "action_kind": "goal.lifecycle",
            "summary": "Stop a Goal",
            "normalized_parameters": {
                "goal_id": "goal-one",
                "operation": "stop",
                "reason": "Owner confirmed from the workspace",
            },
            "context": {"kind": "goal_directory"},
            "idempotency_key": "stop-goal-one",
        }
    )

    applied = service.apply(str(proposal["proposal_id"]))

    assert applied["proposal"]["status"] == "applied"
    assert applied["proposal"]["receipt"]["projection_verified"] is True
    assert applied["proposal"]["receipt"]["outcome"] == "goal_stopped"
    assert goal_activation_state(_goal(global_registry)) is GoalActivationState.STOPPED
