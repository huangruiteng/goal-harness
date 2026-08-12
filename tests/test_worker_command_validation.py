from __future__ import annotations

import pytest

from loopx.visible_multi_agent_launcher import (
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
