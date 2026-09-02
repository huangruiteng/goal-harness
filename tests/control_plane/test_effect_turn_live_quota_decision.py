from __future__ import annotations

from pathlib import Path

from loopx.control_plane.effect_program import (
    interpret_quota_should_run_packet,
)
from loopx.control_plane.capability_hooks import (
    TURN_START_HOOK_RESULT_SCHEMA_VERSION,
    TurnStartHookRegistration,
    dispatch_turn_start_hooks,
)
from loopx.control_plane.quota.live_decision import (
    bind_action_selection_cli_routes,
    build_live_quota_should_run_decision,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload

GOAL_ID = "effect-interpreter-fixture"


def _turn_start_dispatch(
    *,
    required: bool = True,
    commands: tuple[str, ...] = ("loopx inbox drain --goal-id fixture",),
) -> dict[str, object]:
    hooks: list[TurnStartHookRegistration] = []
    for index, command in enumerate(commands):
        hook_id = f"operator_inbox.turn_start_sync_{index}"

        def produce(
            *, hook_id: str = hook_id, required: bool = required
        ) -> dict[str, object]:
            return {
                "schema_version": TURN_START_HOOK_RESULT_SCHEMA_VERSION,
                "hook_id": hook_id,
                "capability_id": "operator-inbox",
                "phase": "turn_start",
                "status": "observed" if required else "empty",
                "observation_count": 1 if required else 0,
                "agent_read_required": required,
                "external_reads_performed": True,
                "external_writes_performed": False,
                "local_private_state_mutated": required,
                "private_content_returned": False,
                "provider_payload_returned": False,
                "error_code": None,
            }

        hooks.append(
            TurnStartHookRegistration(
                hook_id=hook_id,
                capability_id="operator-inbox",
                requested_read_scope=("provider_history",),
                requested_write_scope=("owner_private_inbox",),
                producer=produce,
                required_read={
                    "kind": "operator_inbox",
                    "command": command,
                    "reason": "turn-start hook synchronized new operator inbox evidence",
                    "ordering": "before_work",
                },
            )
        )
    return dispatch_turn_start_hooks(hooks)


def _ordinary_status_payload() -> dict[str, object]:
    todo_text = "[P1] Keep advancing the selected task."
    return quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[
            {
                "todo_id": "todo_ordinary_work",
                "index": 1,
                "text": todo_text,
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
            }
        ],
        recommended_action=todo_text,
        next_action=todo_text,
    )


def test_live_quota_decision_maps_to_effect_turn(tmp_path: Path) -> None:
    todo_text = "[P1] Advance the bounded slice."
    payload = quota_status_payload(
        goal_id=GOAL_ID,
        status="active",
        agent_todo_items=[
            {
                "index": 1,
                "text": todo_text,
                "role": "agent",
                "status": "open",
                "priority": "P1",
                "task_class": "advancement_task",
            }
        ],
        recommended_action=todo_text,
        next_action=todo_text,
    )
    packet = build_live_quota_should_run_decision(
        payload,
        goal_id=GOAL_ID,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        scheduler_execution_context={
            "host_surface": "generic_cli",
            "scheduler_owner": "agent_cli_loop",
            "execution_mode": "interactive",
        },
    )
    turn = interpret_quota_should_run_packet(
        packet,
        goal_id=GOAL_ID,
        agent_id="codex-fixture",
        capabilities=["shell"],
    )

    assert turn.observation.decision == "run"
    assert turn.observation.effective_action == "normal_run"
    assert turn.interpretation.route == "advancement_task"
    assert turn.interpretation.obligation == "advance_one_bounded_segment"
    assert turn.interpretation.interaction_mode == "bounded_delivery"
    assert turn.next_effect.cli_actions
    assert turn.next_effect.cli_actions[0].startswith("loopx --runtime-root ")


def test_action_selection_route_binding_fails_closed_on_malformed_prefix(
    tmp_path: Path,
) -> None:
    payload = {
        "interaction_contract": {
            "cli_channel": {
                "selection_required": True,
                "selection_command": {"route_prefix": "loopx --runtime-root /tmp"},
            }
        }
    }

    bind_action_selection_cli_routes(
        payload,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
    )

    assert payload["interaction_contract"]["cli_channel"]["selection_command"][
        "route_prefix"
    ] == "loopx --runtime-root /tmp"


def test_turn_start_read_is_required_before_ordinary_work(tmp_path: Path) -> None:
    status = _ordinary_status_payload()
    baseline = build_live_quota_should_run_decision(
        status,
        goal_id=GOAL_ID,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
    )
    packet = build_live_quota_should_run_decision(
        status,
        goal_id=GOAL_ID,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        turn_start_hook_dispatch=_turn_start_dispatch(
            commands=(
                f"loopx --registry {tmp_path / 'registry.json'} "
                f"lark-inbox drain --goal-id {GOAL_ID}",
            )
        ),
    )

    required_reads = packet["interaction_contract"]["agent_channel"]["required_reads"]
    assert (
        required_reads
        == packet["interaction_contract"]["cli_channel"]["required_reads"]
    )
    assert required_reads == [
        {
            "kind": "operator_inbox",
            "command": (
                f"loopx --registry {tmp_path / 'registry.json'} "
                f"lark-inbox drain --goal-id {GOAL_ID}"
            ),
            "reason": "turn-start hook synchronized new operator inbox evidence",
            "source": "turn_start_capability_hook",
            "ordering": "before_work",
        }
    ]
    assert packet["interaction_contract"]["user_channel"]["notify"] == "DONT_NOTIFY"
    assert packet.get("selected_todo") == baseline.get("selected_todo")
    assert (
        packet["agent_todo_summary"]["first_executable_items"]
        == baseline["agent_todo_summary"]["first_executable_items"]
    )
    assert packet["recommended_action"] == baseline["recommended_action"]
    assert packet["effective_action"] == baseline["effective_action"] == "normal_run"


def test_turn_start_read_is_not_projected_for_empty_or_failed_dispatch(
    tmp_path: Path,
) -> None:
    status = _ordinary_status_payload()
    dispatches = [
        _turn_start_dispatch(required=False),
        {
            "registered_count": 1,
            "invoked_count": 0,
            "results": [],
            "failures": [
                {
                    "hook_id": "lark.turn_start_inbox_sync",
                    "capability_id": "lark-event-inbox",
                    "error_code": "producer_failed",
                }
            ],
        },
    ]

    for dispatch in dispatches:
        packet = build_live_quota_should_run_decision(
            status,
            goal_id=GOAL_ID,
            agent_id=None,
            available_capabilities=["shell"],
            include_scheduler_detail=False,
            codex_app_current_rrule=None,
            registry_path=tmp_path / "registry.json",
            runtime_root=tmp_path / "runtime",
            turn_start_hook_dispatch=dispatch,
        )

        assert "required_reads" not in packet["interaction_contract"]["agent_channel"]
        assert "required_reads" not in packet["interaction_contract"]["cli_channel"]


def test_duplicate_required_inbox_routes_project_one_public_safe_read(
    tmp_path: Path,
) -> None:
    command = "loopx lark-inbox drain --goal-id fixture"
    dispatch = _turn_start_dispatch(commands=(command, command))
    packet = build_live_quota_should_run_decision(
        _ordinary_status_payload(),
        goal_id=GOAL_ID,
        agent_id=None,
        available_capabilities=["shell"],
        include_scheduler_detail=False,
        codex_app_current_rrule=None,
        registry_path=tmp_path / "registry.json",
        runtime_root=tmp_path / "runtime",
        turn_start_hook_dispatch=dispatch,
    )

    assert len(packet["required_reads"]) == 1
    assert packet["required_reads"][0]["command"] == command
