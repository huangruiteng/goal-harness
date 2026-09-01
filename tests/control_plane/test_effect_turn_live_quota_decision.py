from __future__ import annotations

from pathlib import Path

from loopx.control_plane.effect_program import (
    interpret_quota_should_run_packet,
)
from loopx.control_plane.quota.live_decision import (
    bind_action_selection_cli_routes,
    build_live_quota_should_run_decision,
)
from loopx.control_plane.testing.quota_fixtures import quota_status_payload

GOAL_ID = "effect-interpreter-fixture"


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
