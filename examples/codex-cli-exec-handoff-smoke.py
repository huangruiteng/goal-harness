#!/usr/bin/env python3
"""Smoke-test explicit Codex CLI exec fallback handoff generation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.project_prompt import build_codex_cli_exec_handoff  # noqa: E402


PROJECT = Path("/tmp/public-codex-cli-project")
GOAL_ID = "public-codex-cli-goal"
AGENT_ID = "codex-side-bypass"


def run_cli(*extra_args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "goal_harness.cli", *extra_args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def assert_handoff_contract(payload: dict[str, object]) -> None:
    assert payload["ok"] is True, payload
    assert payload["schema_version"] == "codex_cli_exec_handoff_v0", payload
    assert payload["mode"] == "explicit_headless_fallback", payload
    assert payload["primary_experience"] == "codex_cli_tui_bootstrap", payload
    assert payload["goal_id"] == GOAL_ID, payload
    assert payload["agent_id"] == AGENT_ID, payload
    command = str(payload["handoff_command"])
    normalized = " ".join(command.split())
    assert "cat <<'GOAL_HARNESS_CODEX_PROMPT' | codex exec" in command, command
    assert "codex exec -" not in command, command
    assert "Start the Goal Harness loop for this repo from this same Codex CLI TUI session." in command, command
    assert "hidden headless `codex exec`" in command, command
    assert "explicit fallback" in command, command
    assert "quota should-run --goal-id public-codex-cli-goal --agent-id codex-side-bypass" in normalized, command
    assert "workspace_guard" in command, command
    assert "refresh-state" in command, command
    assert "quota spend-slot --goal-id public-codex-cli-goal" in normalized, command
    assert "GOAL_HARNESS_CODEX_PROMPT" in command, command
    boundary = payload["boundary"]
    assert boundary["runs_codex"] is False, payload
    assert boundary["reads_raw_transcripts"] is False, payload
    assert boundary["reads_credentials"] is False, payload
    assert boundary["reads_session_files"] is False, payload
    assert boundary["mutates_codex_session"] is False, payload
    assert boundary["spends_goal_harness_quota"] is False, payload


def main() -> int:
    payload = build_codex_cli_exec_handoff(
        project=PROJECT,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="goal-harness",
        codex_bin="codex",
    )
    assert_handoff_contract(payload)

    cli_json = json.loads(
        run_cli(
            "--format",
            "json",
            "codex-cli-exec-handoff",
            "--project",
            str(PROJECT),
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            AGENT_ID,
        )
    )
    assert_handoff_contract(cli_json)

    cli_markdown = run_cli(
        "codex-cli-exec-handoff",
        "--project",
        str(PROJECT),
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_ID,
    )
    assert "# Codex CLI Exec Handoff" in cli_markdown, cli_markdown
    assert "explicit headless fallback" in cli_markdown, cli_markdown
    assert "Prefer `goal-harness codex-cli-bootstrap-message`" in cli_markdown, cli_markdown
    assert "cat <<'GOAL_HARNESS_CODEX_PROMPT' | codex exec" in cli_markdown, cli_markdown

    print("codex-cli-exec-handoff-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
