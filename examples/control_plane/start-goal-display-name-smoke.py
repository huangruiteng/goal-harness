#!/usr/bin/env python3
"""Smoke: guided /loopx goal starts persist a public-safe display_name."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GOAL_TEXT = "Fix dashboard goal title fallback for guided start"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-display-name-smoke-") as tmp:
        project = Path(tmp) / "project"
        project.mkdir()
        (project / "README.md").write_text("# demo\n", encoding="utf-8")

        bootstrap = subprocess.run(
            [
                sys.executable,
                "-m",
                "loopx.cli",
                "bootstrap",
                "--project",
                str(project),
                "--goal-id",
                "demo-display-name-goal",
                "--objective",
                GOAL_TEXT,
                "--no-onboarding-scan",
                "--codex-app-heartbeat",
                "no",
                "--no-global-sync",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if bootstrap.returncode != 0:
            print(bootstrap.stdout)
            print(bootstrap.stderr, file=sys.stderr)
            return bootstrap.returncode

        registry_path = project / ".loopx" / "registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        goal = next(
            item for item in registry["goals"] if item["id"] == "demo-display-name-goal"
        )
        assert goal.get("display_name") == GOAL_TEXT, goal

        guided = subprocess.run(
            [
                sys.executable,
                "-m",
                "loopx.cli",
                "--format",
                "json",
                "start-goal",
                "--guided",
                "--project",
                str(project),
                "--goal-id",
                "demo-display-name-goal",
                "--agent-id",
                "smoke-display-name-agent",
                "--host-surface",
                "cursor-agent",
                "--goal-text",
                GOAL_TEXT,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if guided.returncode != 0:
            print(guided.stdout)
            print(guided.stderr, file=sys.stderr)
            return guided.returncode

        payload = json.loads(guided.stdout)
        connect_command = payload["guided_transaction"]["ordered_steps"][1]["command"]
        assert "--display-name" in connect_command, connect_command
        assert GOAL_TEXT in connect_command, connect_command

    print("ok: start-goal display_name smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
