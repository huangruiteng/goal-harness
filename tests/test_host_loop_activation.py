from __future__ import annotations

import pytest

from loopx.host_loop_activation import (
    AgentTypeError,
    agent_type_for_host_surface,
    build_host_loop_activation_packet,
    normalize_agent_type,
)


def test_codex_ide_is_an_exact_host_type_with_visible_goal_activation() -> None:
    assert normalize_agent_type("VSCode Codex") == "codex-ide"
    assert agent_type_for_host_surface("codex-ide") == "codex-ide"

    packet = build_host_loop_activation_packet(
        agent_type="codex-ide",
        goal_id="fixture-goal",
        agent_id="codex-fixture",
        registered_agents=["codex-fixture"],
    )

    assert packet["host_surface"] == "codex_ide_visible_goal_mode"
    assert packet["activation_method"] == "set_visible_goal"
    assert packet["host_mutation"]["owner"] == "Codex IDE composer"
    assert packet["host_mutation"]["host_command"] == "/goal <task_body>"
    assert "automation_update" not in str(packet)


def test_ambiguous_codex_requires_app_ide_or_cli_selection() -> None:
    with pytest.raises(AgentTypeError) as caught:
        normalize_agent_type("codex")

    assert caught.value.suggestions == ["codex-app", "codex-ide", "codex-cli"]
