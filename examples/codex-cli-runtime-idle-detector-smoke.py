#!/usr/bin/env python3
"""Smoke-test the Codex CLI runtime idle detector packet."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.codex_cli_probe import build_codex_cli_runtime_idle_detector  # noqa: E402


PROJECT = Path("/tmp/public-codex-cli-project")
GOAL_ID = "public-codex-cli-goal"
AGENT_ID = "codex-side-bypass"


PASSING_IDLE_FIXTURE = {
    "observed_surface": "visible_resume_prompt",
    "idle_guard": {
        "no_active_human_typing": True,
        "no_running_turn": True,
        "checked_before_prompt": True,
    },
    "turn_visibility": {"visible_to_user": True},
    "interruptibility": {
        "user_can_interrupt": True,
        "manual_takeover_available": True,
    },
    "boundary": {
        "reads_raw_transcripts": False,
        "reads_session_files": False,
        "reads_stdout_stderr": False,
        "reads_credentials": False,
        "mutates_hidden_session_state": False,
    },
}


def build_idle(payload: dict[str, object] | None) -> dict[str, object]:
    return build_codex_cli_runtime_idle_detector(
        project=PROJECT,
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        cli_bin="goal-harness",
        idle_payload=payload,
    )


def assert_boundary(payload: dict[str, object]) -> None:
    boundary = payload["boundary"]
    assert boundary["fixture_only"] is True, payload
    assert boundary["runs_codex"] is False, payload
    assert boundary["reads_raw_transcripts"] is False, payload
    assert boundary["reads_session_files"] is False, payload
    assert boundary["reads_stdout_stderr"] is False, payload
    assert boundary["reads_credentials"] is False, payload
    assert boundary["mutates_codex_session"] is False, payload
    assert boundary["spends_goal_harness_quota"] is False, payload


def run_cli(*extra_args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "goal_harness.cli", *extra_args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def run_cli_fail_closed(*extra_args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "goal_harness.cli", *extra_args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout
    return result.stdout


def main() -> int:
    missing = build_idle(None)
    assert missing["ok"] is False, missing
    assert missing["schema_version"] == "codex_cli_runtime_idle_detector_v0", missing
    assert missing["decision"] == "runtime_idle_fixture_required", missing
    assert missing["approved_for_visible_later_turn"] is False, missing
    assert "missing_runtime_idle_fixture" in missing["failures"], missing
    assert_boundary(missing)

    failing_fixture = dict(PASSING_IDLE_FIXTURE)
    failing_fixture["idle_guard"] = dict(PASSING_IDLE_FIXTURE["idle_guard"])
    failing_fixture["idle_guard"]["no_running_turn"] = False
    incomplete = build_idle(failing_fixture)
    assert incomplete["ok"] is True, incomplete
    assert incomplete["decision"] == "runtime_idle_detector_incomplete", incomplete
    assert incomplete["approved_for_visible_later_turn"] is False, incomplete
    assert "idle_no_running_turn" in incomplete["failures"], incomplete
    assert_boundary(incomplete)

    passing = build_idle(PASSING_IDLE_FIXTURE)
    assert passing["ok"] is True, passing
    assert passing["decision"] == "runtime_idle_detector_passed", passing
    assert passing["approved_for_visible_later_turn"] is True, passing
    assert passing["observed_surface"] == "visible_resume_prompt", passing
    assert not passing["failures"], passing
    assert_boundary(passing)

    with tempfile.TemporaryDirectory(prefix="goal-harness-codex-cli-runtime-idle-") as tmp:
        fixture = Path(tmp) / "runtime-idle.json"
        fixture.write_text(json.dumps(PASSING_IDLE_FIXTURE))

        cli_json = json.loads(
            run_cli(
                "--format",
                "json",
                "codex-cli-runtime-idle-detector",
                "--project",
                str(PROJECT),
                "--goal-id",
                GOAL_ID,
                "--agent-id",
                AGENT_ID,
                "--idle-fixture",
                str(fixture),
            )
        )
        assert cli_json["decision"] == "runtime_idle_detector_passed", cli_json
        assert cli_json["approved_for_visible_later_turn"] is True, cli_json
        assert_boundary(cli_json)

        cli_markdown = run_cli_fail_closed(
            "codex-cli-runtime-idle-detector",
            "--project",
            str(PROJECT),
            "--goal-id",
            GOAL_ID,
        )
        assert "# Codex CLI Runtime Idle Detector" in cli_markdown, cli_markdown
        assert "runtime_idle_fixture_required" in cli_markdown, cli_markdown
        assert "reads_stdout_stderr: `False`" in cli_markdown, cli_markdown

    print("codex-cli-runtime-idle-detector-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
