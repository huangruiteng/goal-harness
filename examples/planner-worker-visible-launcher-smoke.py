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
        bootstrap_command="printf 'bootstrap'",
        cli_bin="loopx",
        codex_bin="codex",
        reasoning_effort="high",
        model_name="gpt-5.5",
    )
    assert "LOOPX_CODEX_MODEL=gpt-5.5" in command, command
    assert 'args.extend(["--model", model])' in command, command
    assert "LOOPX_CODEX_REASONING_EFFORT=high" in command, command

    legacy_command = build_visible_lane_command(
        role_id="worker",
        role_profile_ref="coordination.agent_profiles.worker",
        role_profile_command="printf '[LoopX role profile]\\n'",
        bootstrap_command="printf 'bootstrap'",
        cli_bin="loopx",
        codex_bin="codex",
        reasoning_effort="medium",
    )
    assert "LOOPX_CODEX_MODEL=''" in legacy_command, legacy_command
    assert "LOOPX_CODEX_REASONING_EFFORT=medium" in legacy_command, legacy_command
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
