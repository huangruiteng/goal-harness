#!/usr/bin/env python3
"""Smoke-test autonomous replan obligation projection in status and quota."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GOAL_ID = "autonomous-replan-fixture"


def run_cli(*args: str, registry_path: Path, runtime: Path) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(runtime),
            "--format",
            "json",
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def write_fixture(root: Path, *, include_replan_signals: bool) -> tuple[Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_path = project / state_file
    registry_path = project / ".goal-harness" / "registry.json"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    replan_section = ""
    if include_replan_signals:
        replan_section = (
            "## Recent Progress\n\n"
            "- no-progress streak: three eligible heartbeats repeated the same dependency observation.\n"
            "- repeated-action loop: the same monitor-only next action appeared again.\n"
            "- phase transition: readiness work is done and the next phase should advance planning-trigger work.\n\n"
        )
    todo_text = (
        "[P1] Autonomous planning-trigger implementation slice: emit a machine-readable replan obligation."
        if include_replan_signals
        else "[P1] Advance the next bounded project hardening slice."
    )
    state_path.write_text(
        "---\n"
        "status: active\n"
        "updated_at: 2026-01-01T00:00:00+00:00\n"
        "---\n\n"
        "# Autonomous Replan Fixture\n\n"
        "## Next Action\n\n"
        "- Advance the first executable agent todo after observing current state.\n\n"
        f"{replan_section}"
        "## Agent Todo\n\n"
        f"- [ ] {todo_text}\n",
        encoding="utf-8",
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "autonomous-replan-fixture",
                        "status": "active",
                        "repo": str(project),
                        "state_file": state_file,
                        "adapter": {
                            "kind": "harness_self_improvement",
                            "status": "connected-read-only",
                        },
                        "authority_sources": [],
                        "quota": {
                            "compute": 1.0,
                            "window_hours": 24,
                            "allowed_slots": 5,
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path, runtime


def attention_item(status_payload: dict) -> dict:
    items = status_payload.get("attention_queue", {}).get("items") or []
    assert len(items) == 1, status_payload
    return items[0]


def assert_replan_obligation_projected() -> None:
    with tempfile.TemporaryDirectory(prefix="goal-harness-autonomous-replan-") as tmp:
        registry_path, runtime = write_fixture(Path(tmp), include_replan_signals=True)
        status_payload = run_cli("status", registry_path=registry_path, runtime=runtime)
        item = attention_item(status_payload)
        obligation = item["project_asset"]["autonomous_replan_obligation"]
        assert obligation["schema_version"] == "autonomous_replan_obligation_v0", obligation
        assert obligation["required"] is True, obligation
        assert obligation["trigger_count"] == 3, obligation
        assert [trigger["kind"] for trigger in obligation["triggers"]] == [
            "no_progress_streak",
            "repeated_action_loop",
            "phase_transition",
        ], obligation
        assert item["autonomous_replan_obligation"] == obligation, item
        assert obligation["next_validation_command"] == (
            "python3 examples/autonomous-replan-obligation-smoke.py"
        ), obligation
        assert obligation["todo_actions"][0]["action"] == "split", obligation
        assert obligation["todo_actions"][1]["action"] == "add", obligation
        assert obligation["todo_actions"][2]["action"] == "retire", obligation

        guard = run_cli("quota", "should-run", "--goal-id", GOAL_ID, registry_path=registry_path, runtime=runtime)
        assert guard["should_run"] is True, guard
        assert guard["autonomous_replan_obligation"] == obligation, guard
        recommendation = guard["heartbeat_recommendation"]
        assert recommendation["recommended_mode"] == "autonomous_replan_required", recommendation
        assert recommendation["replan_obligation"]["trigger_count"] == 3, recommendation
        assert guard["execution_obligation"]["must_attempt_work"] is True, guard


def assert_no_replan_obligation_without_signal() -> None:
    with tempfile.TemporaryDirectory(prefix="goal-harness-autonomous-replan-") as tmp:
        registry_path, runtime = write_fixture(Path(tmp), include_replan_signals=False)
        status_payload = run_cli("status", registry_path=registry_path, runtime=runtime)
        item = attention_item(status_payload)
        assert "autonomous_replan_obligation" not in item, item
        assert "autonomous_replan_obligation" not in item["project_asset"], item

        guard = run_cli("quota", "should-run", "--goal-id", GOAL_ID, registry_path=registry_path, runtime=runtime)
        assert "autonomous_replan_obligation" not in guard, guard
        assert guard["heartbeat_recommendation"]["recommended_mode"] != "autonomous_replan_required", guard


def main() -> int:
    assert_replan_obligation_projected()
    assert_no_replan_obligation_without_signal()
    print("autonomous-replan-obligation-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
