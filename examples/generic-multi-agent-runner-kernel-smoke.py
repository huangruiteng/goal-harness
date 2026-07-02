#!/usr/bin/env python3
"""Smoke-test the generic multi-agent runner kernel module."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from loopx.capabilities.multi_agent.contract import (  # noqa: E402
    GENERIC_MULTI_AGENT_COMPACT_STATUS_SCHEMA_VERSION,
    GENERIC_MULTI_AGENT_ROLE_PROFILE_SCHEMA_VERSION,
    TUI_MULTI_AGENT_RUNNER_CONTRACT_SCHEMA_VERSION,
    build_compact_human_status,
    build_generic_role_profile,
    build_tui_multi_agent_runner_contract,
    generic_role_prompt,
    role_skill_profile,
)


def main() -> int:
    skill = role_skill_profile({"name": "planner-skill", "source": "skills/planner/SKILL.md"})
    profile = build_generic_role_profile(
        role_id="planner",
        agent_id="codex-main-control",
        scope="Plan one bounded handoff.",
        responsibility="Turn shared state into the next runnable todo.",
        handoff_hints=["Write a todo for builder when ready."],
        skill_profile=skill,
    )
    assert profile["schema_version"] == GENERIC_MULTI_AGENT_ROLE_PROFILE_SCHEMA_VERSION, profile
    assert profile["required_skill"] == "planner-skill", profile

    prompt = generic_role_prompt(
        goal_id="loopx-meta",
        agent_id="codex-main-control",
        role_id="planner",
        scope=str(profile["agent_scope"]),
        handoff_hints=["Write a todo for builder when ready."],
        skill_name=str(profile["required_skill"]),
    )
    assert "$LOOPX_PANE_A2A_TICK" in prompt, prompt
    assert "$LOOPX_PANE_LOOPX_JSON" in prompt, prompt
    assert "normal Codex CLI agent" in prompt, prompt

    runner = build_tui_multi_agent_runner_contract(
        session_name="loopx-generic-team",
        lane_count=2,
        attach_command="tmux attach -t loopx-generic-team",
        stop_command="tmux kill-session -t loopx-generic-team",
        retry_command="rerun after quota/frontier refresh",
        all_lane_workspace_isolation=False,
    )
    assert runner["schema_version"] == TUI_MULTI_AGENT_RUNNER_CONTRACT_SCHEMA_VERSION, runner
    assert runner["coordination_model"]["leader_required"] is False, runner
    assert runner["pane_local_a2a"]["machine_json_policy"] == "file_or_explicit_machine_channel_only", runner
    assert runner["boundaries"]["domain_specific_research_logic"] is False, runner

    compact = build_compact_human_status(
        {
            "goal_id": "loopx-meta",
            "mode": "dry_run",
            "session_name": "loopx-generic-team",
            "commands": {
                "attach": "tmux attach -t loopx-generic-team",
                "stop": "tmux kill-session -t loopx-generic-team",
            },
            "lanes": [
                {
                    "lane_id": "planner",
                    "role_id": "planner",
                    "agent_id": "codex-main-control",
                    "agent_scope": "Plan one bounded handoff.",
                    "pane_local_a2a": {"worker_turn_configured": True},
                },
                {
                    "lane_id": "builder",
                    "role_id": "builder",
                    "agent_id": "codex-side-bypass",
                    "agent_scope": "Execute one claimed todo.",
                    "pane_local_a2a": {"worker_loop_configured": True},
                },
            ],
        }
    )
    assert compact["schema_version"] == GENERIC_MULTI_AGENT_COMPACT_STATUS_SCHEMA_VERSION, compact
    assert compact["role_count"] == 2, compact
    assert compact["roles"][0]["tick"] == "$LOOPX_PANE_A2A_TICK", compact
    assert compact["machine_json_policy"] == "artifact_only_in_visible_panes", compact

    source = (ROOT / "loopx/capabilities/multi_agent/contract.py").read_text(encoding="utf-8")
    assert "auto" + "_research" not in source
    assert "quickstart" not in source.lower()
    json.dumps(compact, sort_keys=True)
    print("generic-multi-agent-runner-kernel-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
