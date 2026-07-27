#!/usr/bin/env python3
"""Smoke-test planner-worker model route configuration."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.agent_registry import model_route_for_role, model_routes_for_goal


GOAL_ID = "planner-worker-config-fixture"


def write_registry(root: Path) -> Path:
    registry_path = root / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "planner-worker-config-smoke",
                        "status": "active",
                        "repo": str(root / "project"),
                        "state_file": ".codex/goals/planner-worker-config-fixture/STATE.md",
                        "spawn_policy": {"mode": "default", "allowed": False, "max_children": 0},
                        "coordination": {
                            "agent_profiles": {
                                "codex-worker": {
                                    "model": "deepseek-v4-flash",
                                    "reasoning_effort": "low",
                                }
                            }
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path


def run_cli(registry_path: Path, *args: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--registry",
            str(registry_path),
            "--format",
            "json",
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-planner-worker-config-") as tmp:
        root = Path(tmp)
        registry_path = write_registry(root)
        dry = run_cli(
            registry_path,
            "configure-goal",
            "--goal-id",
            GOAL_ID,
            "--orchestration-mode",
            "planner_worker",
            "--planner-model",
            "gpt-5.5",
            "--planner-effort",
            "high",
            "--worker-model",
            "deepseek-v4-flash",
            "--worker-effort",
            "medium",
        )
        assert dry["ok"] is True, dry
        assert dry["dry_run"] is True, dry
        assert dry["after"]["orchestration"]["mode"] == "planner_worker", dry
        assert dry["after"]["model_routes"]["planner"]["model"] == "gpt-5.5", dry
        assert dry["after"]["model_routes"]["worker"]["model"] == "deepseek-v4-flash", dry

        applied = run_cli(
            registry_path,
            "configure-goal",
            "--goal-id",
            GOAL_ID,
            "--orchestration-mode",
            "planner_worker",
            "--planner-model",
            "gpt-5.5",
            "--planner-effort",
            "high",
            "--worker-model",
            "deepseek-v4-flash",
            "--worker-effort",
            "medium",
            "--execute",
        )
        assert applied["written"] is True, applied
        goal = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0]
        assert goal["spawn_policy"]["mode"] == "planner_worker", goal
        routes = model_routes_for_goal(goal)
        assert routes["planner"] == {"model": "gpt-5.5", "effort": "high"}, routes
        assert routes["worker"] == {"model": "deepseek-v4-flash", "effort": "medium"}, routes
        worker_route = model_route_for_role(goal, "worker", agent_id="codex-worker")
        assert worker_route == {"model": "deepseek-v4-flash", "effort": "low"}, worker_route

        cleared = run_cli(
            registry_path,
            "configure-goal",
            "--goal-id",
            GOAL_ID,
            "--clear-model-routes",
            "--execute",
        )
        assert cleared["ok"] is True, cleared
        goal = json.loads(registry_path.read_text(encoding="utf-8"))["goals"][0]
        assert "model_routes" not in goal["spawn_policy"], goal
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
