from __future__ import annotations

from loopx.host_mode_planner import build_host_mode_plan


def test_host_mode_plan_preserves_existing_goal_identity_selection() -> None:
    plan = build_host_mode_plan(
        goal_id="fixture-goal",
        user_intent="watch_each_turn",
        host_capabilities=["visible_session"],
        registered_agents=["codex-existing"],
        host_identity="codex-cli",
    )

    assert plan["agent_id"] == "codex-existing"
    assert plan["identity_contract"] == {
        "schema_version": "loopx_host_loop_identity_selection_v0",
        "agent_model": "peer_v1",
        "state": "single_registered_agent_selected",
        "activation_allowed": True,
        "selected_agent_id": "codex-existing",
        "registered_agents": ["codex-existing"],
        "action_required": False,
    }
