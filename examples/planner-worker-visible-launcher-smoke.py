#!/usr/bin/env python3
"""Smoke-test visible launcher model routing."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.visible_multi_agent_launcher import build_visible_lane_command


def main() -> int:
    command = build_visible_lane_command(
        role_id="planner",
        role_profile_ref="coordination.agent_profiles.planner",
        role_profile_command="printf '[LoopX role profile]\\n'",
        quota_command="printf '{}'",
        frontier_command="printf '{}'",
        bootstrap_command="printf 'bootstrap'",
        codex_bin="codex",
        reasoning_effort="high",
        model_name="gpt-5.5",
    )
    assert "--model gpt-5.5 -c model_reasoning_effort=high" in command, command
    assert "model_name=%s" in command and "gpt-5.5" in command, command
    assert "reasoning_effort=high" in command, command

    legacy_command = build_visible_lane_command(
        role_id="worker",
        role_profile_ref="coordination.agent_profiles.worker",
        role_profile_command="printf '[LoopX role profile]\\n'",
        quota_command="printf '{}'",
        frontier_command="printf '{}'",
        bootstrap_command="printf 'bootstrap'",
        codex_bin="codex",
        reasoning_effort="medium",
    )
    assert "--model" not in legacy_command, legacy_command
    assert "-c model_reasoning_effort=medium" in legacy_command, legacy_command
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
