from __future__ import annotations

from pathlib import Path

import pytest

from loopx.agent_onboarding import build_agent_onboarding_packet


@pytest.mark.parametrize("agent_type", ["claude-code", "codex-app"])
def test_agent_onboard_serves_a_packet_before_the_project_registry_exists(
    tmp_path: Path,
    agent_type: str,
) -> None:
    """First-run onboarding must answer, not raise, when .loopx/registry.json is absent."""
    project = tmp_path / "fresh-project"
    project.mkdir()

    packet = build_agent_onboarding_packet(project=project, agent_type=agent_type)

    assert packet["ok"] is True
    assert packet["agent_type"] == agent_type
    assert not (project / ".loopx" / "registry.json").exists()
