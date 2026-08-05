#!/usr/bin/env python3
"""Synthetic Codex App thread-to-agent identity smoke."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from loopx.bootstrap_command_pack import build_start_goal_guided_packet
from loopx.thread_agent_binding import bind_thread_agent_in_registry


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loopx-thread-agent-") as raw:
        root = Path(raw)
        project = root / "project"
        state = project / ".codex" / "goals" / "goal" / "ACTIVE_GOAL_STATE.md"
        state.parent.mkdir(parents=True)
        state.write_text("# Active Goal State\n", encoding="utf-8")
        registry = project / ".loopx" / "registry.json"
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                {
                    "schema_version": "0.1",
                    "goals": [
                        {
                            "id": "goal",
                            "status": "active",
                            "repo": str(project),
                            "state_file": str(state.relative_to(project)),
                            "coordination": {
                                "registered_agents": ["codex-a", "codex-b"]
                            },
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        bound = bind_thread_agent_in_registry(
            registry_path=registry,
            goal_id="goal",
            host_surface="codex-app",
            thread_id="thread-a",
            agent_id="codex-a",
            execute=True,
        )
        assert bound["ok"] and bound["written"], bound
        reused = build_start_goal_guided_packet(
            project=project,
            goal_id="goal",
            agent_id=None,
            thread_id="thread-a",
            cli_bin="loopx",
            host_surface="codex-app",
            goal_text="continue the task",
        )
        assert reused["agent_id"] == "codex-a", reused
        assert reused["thread_agent_binding"]["status"] == "bound", reused
        commands = reused["command_pack"]["commands"]
        assert "--agent-id codex-a" in commands["goal_start_quota_should_run"], commands
        assert "--agent-id codex-a" in commands["goal_start_refresh_state"], commands

        unbound = build_start_goal_guided_packet(
            project=project,
            goal_id="goal",
            agent_id=None,
            thread_id="thread-b",
            cli_bin="loopx",
            host_surface="codex-app",
            goal_text="start another task",
        )
        gate = unbound["guided_transaction"]["identity_selection_gate"]
        assert gate["default_action"] == "select_agent_identity", gate
        assert gate["fresh_agent_registration"] is None, gate
        assert "do not register a new one" in gate["reason"], gate

        explicit_lane = build_start_goal_guided_packet(
            project=project,
            goal_id="goal",
            agent_id="codex-b",
            thread_id="thread-b",
            cli_bin="loopx",
            host_surface="codex-app",
            goal_text="select the existing lane",
        )
        assert explicit_lane["agent_id"] == "codex-b", explicit_lane
        assert "bind-agent-thread" in explicit_lane["command_pack"]["commands"]["goal_start_bind_thread"]

        fresh = build_start_goal_guided_packet(
            project=project,
            goal_id="goal",
            agent_id=None,
            thread_id=None,
            cli_bin="loopx",
            host_surface="codex-app",
            goal_text="start a genuinely new peer",
            new_peer=True,
        )
        fresh_gate = fresh["guided_transaction"]["identity_selection_gate"]
        assert fresh_gate["default_action"] == "register_fresh_agent", fresh_gate
        assert fresh_gate["fresh_agent_registration"]["recommended"] is True, fresh_gate
    print("codex-app-thread-agent-identity-smoke ok")


if __name__ == "__main__":
    main()
