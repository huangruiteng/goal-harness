from __future__ import annotations

import pytest

from loopx.control_plane.turn_driver.subagent_host_adapter import (
    project_child_context_adapter,
    supported_child_context_modes,
)


@pytest.mark.parametrize(
    ("context_mode", "expected_operation", "expected_arguments", "requires_session"),
    [
        pytest.param(
            "fresh",
            "spawn_agent",
            {"fork_context": False},
            False,
            id="fresh_child_does_not_inherit_parent_context",
        ),
        pytest.param(
            "forked_snapshot",
            "spawn_agent",
            {"fork_context": True},
            False,
            id="explicit_parent_snapshot",
        ),
    ],
)
def test_codex_child_context_adapter_maps_modes(
    context_mode: str,
    expected_operation: str,
    expected_arguments: dict[str, bool],
    requires_session: bool,
) -> None:
    assert project_child_context_adapter(
        host="codex-cli",
        context_mode=context_mode,
    ) == {
        "host": "codex-cli",
        "native_operation": expected_operation,
        "arguments": expected_arguments,
        "requires_session": requires_session,
    }


def test_host_child_context_adapter_exposes_only_supported_modes() -> None:
    assert supported_child_context_modes("codex-cli") == (
        "fresh",
        "forked_snapshot",
    )
    assert supported_child_context_modes("claude-code") == ("fresh",)
    assert supported_child_context_modes("generic-cli") == ()
    assert (
        project_child_context_adapter(
            host="claude-code",
            context_mode="forked_snapshot",
        )
        is None
    )


def test_child_context_adapter_returns_isolated_native_arguments() -> None:
    first = project_child_context_adapter(
        host="codex-cli",
        context_mode="fresh",
    )
    assert first is not None
    first["arguments"]["fork_context"] = True

    second = project_child_context_adapter(
        host="codex-cli",
        context_mode="fresh",
    )
    assert second is not None
    assert second["arguments"] == {"fork_context": False}
    assert (
        project_child_context_adapter(
            host="codex-cli",
            context_mode="resume",
        )
        is None
    )
