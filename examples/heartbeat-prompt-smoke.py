#!/usr/bin/env python3
"""Smoke-test the reusable heartbeat automation prompt contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.heartbeat_prompt import build_heartbeat_prompt  # noqa: E402

DOC = REPO_ROOT / "docs" / "heartbeat-automation-prompt.md"
README = REPO_ROOT / "README.md"
INTEGRATION_DOC = REPO_ROOT / "docs" / "integration.md"
PROJECT_SKILL = REPO_ROOT / "skills" / "goal-harness-project" / "SKILL.md"
GOAL_ID = "public-heartbeat-goal"
ACTIVE_STATE = Path("/tmp/public-heartbeat-goal/ACTIVE_GOAL_STATE.md")


def normalized(text: str) -> str:
    return " ".join(text.split())


def assert_ordered(text: str, phrases: tuple[str, ...]) -> None:
    compact = normalized(text)
    positions = []
    for phrase in phrases:
        assert phrase in compact, phrase
        positions.append(compact.index(phrase))
    assert positions == sorted(positions), positions


def main() -> int:
    payload = build_heartbeat_prompt(goal_id=GOAL_ID, active_state=ACTIVE_STATE)
    assert payload["quota_guard_command"] == (
        "goal-harness --format json quota should-run --goal-id public-heartbeat-goal"
    ), payload
    assert payload["quota_spend_command"] == (
        "goal-harness quota spend-slot --goal-id public-heartbeat-goal --slots 1 --source heartbeat --execute"
    ), payload

    doc = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    integration_doc = INTEGRATION_DOC.read_text(encoding="utf-8")
    project_skill = PROJECT_SKILL.read_text(encoding="utf-8")
    generated = str(payload["task_body"])
    compact_generated = normalized(generated)

    must_have = (
        "<ACTIVE_GOAL_STATE_PATH>",
        "<GOAL_ID>",
        'export PATH="$HOME/.local/bin:$PATH"',
        'install_script="$HOME/goal-harness/scripts/install-local.sh"',
        "goal-harness doctor >/dev/null",
        "goal-harness --format json quota should-run --goal-id <GOAL_ID>",
        "If that preflight still fails",
        "should_run=false",
        "state=operator_gate",
        "gate_prompt",
        "operator_question",
        "user_todo_summary",
        "user_todo_summary.open_count > 0",
        "never summarize this case as \"no new user action\"",
        "NOTIFY",
        "safe_bypass_allowed=true",
        "gate blocks only the gated delivery path",
        "one bounded safe-bypass step",
        "that report must include the existing open user todos",
        "DONT_NOTIFY",
        "should_run=true",
        "Run a short steering audit before choosing work",
        "list at least three plausible next-action candidates across different P0/P1/P2 lanes",
        "apply a continuation check",
        "keep compute quota separate from focus quota",
        "Choose exactly one bounded, verifiable step from that audit",
        "Run the smallest useful validation",
        "Write back changed files, validation, critic, and next action",
        "If the step discovers a concrete user/owner action",
        "do not hide it in `Next Action`, a review doc, or chat",
        "goal-harness todo add --goal-id <GOAL_ID> --role user --text \"<public-safe user/owner action>\"",
        "Use `--role agent` for project-agent follow-up work",
        "goal-harness refresh-state --goal-id <GOAL_ID>",
        "goal-harness quota spend-slot --goal-id <GOAL_ID> --slots 1 --source heartbeat --execute",
        "append exactly one",
        "Do not append spend for quiet should_run=false skips, preflight failures, pure dry-run previews, or duplicate accounting attempts",
        "safe_bypass_allowed=true and you actually completed a bounded safe-bypass step",
        "Return a compact final report",
    )
    compact_doc = normalized(doc)
    for phrase in must_have:
        assert phrase in compact_doc, phrase
    for phrase in (
        'export PATH="$HOME/.local/bin:$PATH"',
        'install_script="$HOME/goal-harness/scripts/install-local.sh"',
        "goal-harness doctor >/dev/null",
        "goal-harness --format json quota should-run --goal-id public-heartbeat-goal",
        "If that preflight still fails",
        "should_run=false",
        "state=operator_gate",
        "gate_prompt",
        "operator_question",
        "user_todo_summary",
        "user_todo_summary.open_count > 0",
        "never summarize this case as \"no new user action\"",
        "NOTIFY",
        "safe_bypass_allowed=true",
        "gate blocks only the gated delivery path",
        "one bounded safe-bypass step",
        "that report must include the existing open user todos",
        "DONT_NOTIFY",
        "Run a short steering audit before choosing work",
        "list at least three plausible next-action candidates across different P0/P1/P2 lanes",
        "apply a continuation check",
        "keep compute quota separate from focus quota",
        "Choose exactly one bounded, verifiable step from that audit",
        "If the step discovers a concrete user/owner action",
        "goal-harness todo add --goal-id public-heartbeat-goal --role user --text \"<public-safe user/owner action>\"",
        "goal-harness refresh-state --goal-id public-heartbeat-goal",
        "goal-harness quota spend-slot --goal-id public-heartbeat-goal --slots 1 --source heartbeat --execute",
        "Do not append spend for quiet `should_run=false` skips",
    ):
        assert phrase in compact_generated, phrase

    assert_ordered(
        doc,
        (
            "Before spending delivery compute, first make the Goal Harness CLI reachable",
            'export PATH="$HOME/.local/bin:$PATH"',
            "goal-harness doctor >/dev/null",
            "goal-harness --format json quota should-run --goal-id <GOAL_ID>",
            "If that preflight still fails",
            "If the result says should_run=false",
            "state=operator_gate",
            "gate_prompt",
            "safe_bypass_allowed=true",
            "If the result says should_run=true",
            "Run a short steering audit before choosing work",
            "Choose exactly one bounded, verifiable step from that audit",
            "Run the smallest useful validation",
            "goal-harness refresh-state --goal-id <GOAL_ID>",
            "goal-harness quota spend-slot --goal-id <GOAL_ID> --slots 1 --source heartbeat --execute",
            "Return a compact final report",
        ),
    )

    assert "docs/heartbeat-automation-prompt.md" in readme, readme
    assert "goal-harness heartbeat-prompt" in readme, readme
    assert "goal-harness heartbeat-prompt" in doc, doc
    assert "goal-harness heartbeat-prompt" in integration_doc, integration_doc
    assert "visible goal text can stay short" in integration_doc, integration_doc
    assert "shares the same quota, gate," in integration_doc, integration_doc
    assert "steering-audit, writeback, refresh, and spend lifecycle" in integration_doc, integration_doc
    assert "Two Prompt Layers" in doc, doc
    assert "Visible goal text" in doc, doc
    assert "Heartbeat automation task body" in doc, doc
    assert "goal-harness heartbeat-prompt" in project_skill, project_skill
    assert "Set Up Recurring Heartbeats" in project_skill, project_skill
    assert "visible goal text short" in project_skill, project_skill
    assert "--source heartbeat --execute" in project_skill, project_skill

    cli_json = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--format",
            "json",
            "heartbeat-prompt",
            "--goal-id",
            GOAL_ID,
            "--active-state",
            str(ACTIVE_STATE),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    cli_payload = json.loads(cli_json.stdout)
    assert cli_payload["task_body"] == payload["task_body"], cli_payload

    cli_markdown = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "heartbeat-prompt",
            "--goal-id",
            GOAL_ID,
            "--active-state",
            str(ACTIVE_STATE),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "# Heartbeat Automation Prompt" in cli_markdown, cli_markdown
    assert "Copy this task body into a Codex App heartbeat automation." in cli_markdown, cli_markdown
    assert str(ACTIVE_STATE) in cli_markdown, cli_markdown
    print("heartbeat-prompt-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
