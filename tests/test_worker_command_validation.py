from __future__ import annotations

import pytest

from demo.visible_multi_agent_launcher import (
    build_visible_multi_agent_payload_from_spec,
    validate_worker_command,
)


@pytest.mark.parametrize(
    "command",
    [
        None,
        "",
        "loopx turn run-once",
        "python3 worker.py --flag 1",
        "printf turn-streamed",
        "/usr/bin/env python3",
    ],
)
def test_validate_worker_command_accepts_safe_commands(command: str | None) -> None:
    assert validate_worker_command(command, field="worker_turn_command") == (
        command if command is not None else ""
    )


@pytest.mark.parametrize(
    "command",
    [
        "evil; id",
        "evil | cat",
        "evil > /tmp/pwned",
        "evil $(id)",
        "`id`",
        "printf 'x'",
        "a\nb",
        "a&b",
        "a${x}",
        "a b'c",
    ],
)
def test_validate_worker_command_rejects_unsafe_commands(command: str) -> None:
    with pytest.raises(ValueError, match="unsafe shell metacharacters"):
        validate_worker_command(command, field="worker_turn_command")


@pytest.mark.parametrize(
    "command",
    [
        "ENV=x python3 worker.py",
        "LD_PRELOAD=/tmp/x python3",
        "evil *",
        "evil ?",
        "a\tb",
    ],
)
def test_validate_worker_command_rejects_env_assignment_and_glob_variants(
    command: str,
) -> None:
    with pytest.raises(ValueError, match="unsafe shell metacharacters"):
        validate_worker_command(command, field="worker_turn_command")


def test_validate_worker_command_rejects_input_redirect() -> None:
    # Output redirect (>) is already covered; input redirect must fail closed too.
    with pytest.raises(ValueError, match="unsafe shell metacharacters"):
        validate_worker_command("evil < /tmp/x", field="worker_turn_command")


def test_spec_builder_rejects_unsafe_worker_command() -> None:
    spec = {
        "goal_id": "loopx-meta",
        "roles": [
            {
                "agent_id": "codex-side-bypass",
                "worker_turn_command": "evil; id",
            }
        ],
    }

    with pytest.raises(ValueError, match="unsafe shell metacharacters"):
        build_visible_multi_agent_payload_from_spec(spec)


def test_auto_research_supervisor_visible_worker_turn_hook_is_safe() -> None:
    from demo.auto_research.demo_supervisor import (
        build_auto_research_demo_supervisor_plan,
        build_visible_worker_turn_command,
    )
    from demo.auto_research.user_contract import (
        build_auto_research_preset_context,
    )

    command = build_visible_worker_turn_command(
        goal_id="loopx-auto-research-safe-hook",
        agent_id="auto-research-observer",
        lane_count=1,
    )
    assert validate_worker_command(command, field="worker_turn_command") == command

    payload = build_auto_research_demo_supervisor_plan(
        goal_id="loopx-auto-research-safe-hook",
        open_question="如何提升 KNN 精确近邻检索速度？",
        preset_context=build_auto_research_preset_context("knn-demo"),
        configure_visible_worker_turn=True,
    )
    assert payload["auto_research"]["visible_worker_turn_configured"] is True
    for lane in payload["lanes"]:
        assert lane["pane_local_a2a"]["worker_turn_configured"] is True
