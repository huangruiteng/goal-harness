#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def assert_markdown_list() -> None:
    result = run_cli("preset", "list")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert "LoopX beginner preset picker" in result.stdout, result.stdout
    assert "Daily Triage L1" in result.stdout, result.stdout
    assert "Changelog Draft L1" in result.stdout, result.stdout
    assert "PR Watch L1" in result.stdout, result.stdout
    assert "CI Sweeper L2" in result.stdout, result.stdout
    assert "Dependency Sweeper L2" in result.stdout, result.stdout
    assert "advanced_opt_in" in result.stdout, result.stdout
    assert "/loopx Run Daily Triage L1" in result.stdout, result.stdout
    assert "loopx start-goal --guided --project" in result.stdout, result.stdout
    assert "quota should-run" in result.stdout, result.stdout
    assert "loopx heartbeat-prompt --thin" in result.stdout, result.stdout
    assert "Mutation policy: read_only" in result.stdout, result.stdout


def assert_json_show_with_placeholders() -> None:
    result = run_cli(
        "preset",
        "show",
        "daily-triage",
        "--format",
        "json",
        "--goal-id",
        "demo-goal",
        "--agent-id",
        "codex-demo",
        "--agent-scope",
        "daily triage lane",
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "loopx_beginner_preset_picker_v0", payload
    assert payload["mutation_policy"].startswith("read_only"), payload
    assert payload["recommended_order"] == [
        "daily-triage",
        "changelog-draft",
        "pr-watch",
        "ci-sweeper",
        "dependency-sweeper",
    ], payload
    assert payload["default_preset_ids"] == ["daily-triage", "changelog-draft", "pr-watch"], payload
    assert payload["advanced_preset_ids"] == ["ci-sweeper", "dependency-sweeper"], payload
    presets = payload["presets"]
    assert len(presets) == 1, payload
    preset = presets[0]
    assert preset["id"] == "daily-triage", preset
    assert preset["tier"] == "beginner_default", preset
    assert preset["maturity"] == "L1 report-only", preset
    commands = preset["commands"]
    assert "--goal-id demo-goal --agent-id codex-demo" in commands["quota_guard"], commands
    assert "--agent-scope 'daily triage lane'" in commands["heartbeat_prompt"], commands
    assert "start-goal --guided" in commands["cli_start"], commands


def assert_pr_watch_is_watch_only() -> None:
    result = run_cli("preset", "show", "pr-watch")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert "L1 watch-only" in result.stdout, result.stdout
    assert "No auto-merge." in result.stdout, result.stdout
    assert "No code edits unless the owner upgrades" in result.stdout, result.stdout
    assert "Quiet unchanged polls should not spend quota." in result.stdout, result.stdout


def assert_ci_sweeper_is_opt_in() -> None:
    result = run_cli("preset", "show", "ci-sweeper")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert "CI Sweeper L2" in result.stdout, result.stdout
    assert "L2 opt-in patch lane" in result.stdout, result.stdout
    assert "dry_run_report_first" in result.stdout, result.stdout
    assert "Dry-run report first; no patch until owner opt-in." in result.stdout, result.stdout
    assert "isolated codex/ worktree" in result.stdout, result.stdout
    assert "Human review before push, merge" in result.stdout, result.stdout
    assert "Escalate after repeated failures" in result.stdout, result.stdout


def assert_dependency_sweeper_policy_gates() -> None:
    result = run_cli("preset", "show", "dependency-sweeper")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert "Dependency Sweeper L2" in result.stdout, result.stdout
    assert "policy_report_first" in result.stdout, result.stdout
    assert "patch/minor policy and denylist" in result.stdout, result.stdout
    assert "Policy report first; no dependency edit until owner opt-in." in result.stdout, result.stdout
    assert "deny major, runtime, lockfile-wide" in result.stdout, result.stdout
    assert "Human review before push, merge, publish, rollout" in result.stdout, result.stdout


def assert_command_reference_mentions_presets() -> None:
    result = run_cli("commands")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert "loopx preset list" in result.stdout, result.stdout
    assert "beginner-safe and opt-in advanced" in result.stdout, result.stdout


def main() -> int:
    assert_markdown_list()
    assert_json_show_with_placeholders()
    assert_pr_watch_is_watch_only()
    assert_ci_sweeper_is_opt_in()
    assert_dependency_sweeper_policy_gates()
    assert_command_reference_mentions_presets()
    print("beginner-preset-picker-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
