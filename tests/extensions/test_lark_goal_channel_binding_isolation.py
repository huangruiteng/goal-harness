from __future__ import annotations

import pytest

from loopx.extensions.lark.goal_channel_contracts import binding_for_goal


def _connection(agent_id: str, target_ref: str) -> dict[str, object]:
    return {
        "goal_id": "goal-alpha",
        "agent_id": agent_id,
        "provider": "lark",
        "enabled": True,
        "target_ref": target_ref,
        "channel": {},
    }


def _target(name: str, chat_id: str) -> dict[str, object]:
    return {
        "name": name,
        "provider": "lark",
        "channel": {"chat_id": chat_id},
        "identity": {
            "mode": "project_bot",
            "sender_identity": "bot",
            "sender_profile": f"{name}-profile",
        },
    }


def test_binding_resolution_isolates_selected_agent_from_sibling_target() -> None:
    payload = {
        "bindings": {
            "goal-alpha": {
                "schema_version": "loopx_goal_channel_connection_set_v0",
                "default_connection_id": "connection-alpha",
                "connections": {
                    "connection-alpha": _connection("agent-alpha", "target-alpha"),
                    "connection-beta": _connection("agent-beta", "target-beta"),
                },
            }
        }
    }

    alpha = binding_for_goal(
        payload,
        "goal-alpha",
        connection_id="connection-alpha",
        provider_target=_target("target-alpha", "oc_alpha"),
    )

    assert alpha is not None
    assert alpha["agent_id"] == "agent-alpha"
    assert alpha["channel"] == {"chat_id": "oc_alpha"}
    with pytest.raises(ValueError, match="does not match target_ref"):
        binding_for_goal(
            payload,
            "goal-alpha",
            connection_id="connection-beta",
            provider_target=_target("target-alpha", "oc_alpha"),
        )
