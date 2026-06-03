#!/usr/bin/env python3
"""Smoke-test the automatic heartbeat quota lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GOAL_ID = "heartbeat-flow-main-control"
LONG_NEXT_ACTION_TAIL = "without truncating the final private-safe boundary sentence."


def run_cli(root: Path, *args: str, registry_path: Path, runtime: Path) -> dict:
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


def write_fixture(root: Path) -> tuple[Path, Path, Path]:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_path = project / state_file
    registry_path = project / ".goal-harness" / "registry.json"

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        "---\n"
        "status: active-read-only\n"
        "owner_mode: goal\n"
        'objective: "Exercise heartbeat quota accounting."\n'
        "updated_at: 2026-01-01T00:00:00+00:00\n"
        "---\n\n"
        "# Heartbeat Flow Main Control\n\n"
        "## Objective\n\n"
        "Exercise heartbeat quota accounting.\n\n"
        "## Next Action\n\n"
        "- Run one bounded heartbeat marker, preserve the wrapped next-action\n"
        "  continuation across more than eight public-safe lines, keep the current\n"
        "  owner gate context intact, keep the validation context intact, keep the\n"
        "  quota accounting context intact, keep the project-agent handoff context\n"
        "  intact, keep the public/private boundary context intact, keep the\n"
        "  status-queue routing context intact, keep the review packet context\n"
        "  intact, and finish " + LONG_NEXT_ACTION_TAIL + "\n\n"
        "## Progress Ledger\n\n"
        "- Initialized fixture.\n",
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
                        "domain": "heartbeat-flow-fixture",
                        "status": "active-read-only",
                        "repo": str(project),
                        "state_file": state_file,
                        "adapter": {
                            "kind": "heartbeat_flow_fixture_v0",
                            "status": "connected-read-only",
                        },
                        "authority_sources": [],
                        "quota": {
                            "compute": 1.0,
                            "window_hours": 24,
                            "allowed_slots": 2,
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
    return project, runtime, registry_path


def count_spend_events(runtime: Path) -> int:
    index_path = runtime / "goals" / GOAL_ID / "runs" / "index.jsonl"
    if not index_path.exists():
        return 0
    count = 0
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("classification") == "quota_slot_spent":
            count += 1
    return count


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="goal-harness-heartbeat-quota-flow-") as tmp:
        root = Path(tmp)
        project, runtime, registry_path = write_fixture(root)
        registry_before = registry_path.read_text(encoding="utf-8")

        guard = run_cli(
            root,
            "quota",
            "should-run",
            "--goal-id",
            GOAL_ID,
            "--scan-path",
            str(project),
            registry_path=registry_path,
            runtime=runtime,
        )
        assert guard["should_run"] is True, guard
        assert guard["quota"]["spent_slots"] == 0, guard
        assert guard["quota"]["allowed_slots"] == 2, guard

        marker = project / "heartbeat-work-marker.txt"
        marker.write_text("bounded heartbeat work completed\n", encoding="utf-8")
        check = run_cli(
            root,
            "check",
            "--scan-path",
            str(marker),
            registry_path=registry_path,
            runtime=runtime,
        )
        assert check["ok"] is True, check

        refresh = run_cli(
            root,
            "refresh-state",
            "--goal-id",
            GOAL_ID,
            "--no-global-sync",
            registry_path=registry_path,
            runtime=runtime,
        )
        assert refresh["ok"] is True, refresh
        assert refresh["appended"] is True, refresh
        assert LONG_NEXT_ACTION_TAIL in refresh["recommended_action"], refresh
        assert count_spend_events(runtime) == 0

        spend = run_cli(
            root,
            "quota",
            "spend-slot",
            "--goal-id",
            GOAL_ID,
            "--slots",
            "1",
            "--source",
            "heartbeat",
            "--execute",
            "--scan-path",
            str(project),
            registry_path=registry_path,
            runtime=runtime,
        )
        assert spend["ok"] is True, spend
        assert spend["appended"] is True, spend
        assert spend["registry_mutated"] is False, spend
        assert spend["quota_event"]["source"] == "heartbeat", spend
        assert spend["quota_event"]["before"]["spent_slots"] == 0, spend
        assert spend["quota_event"]["after"]["spent_slots"] == 1, spend
        assert count_spend_events(runtime) == 1

        follow_up = run_cli(
            root,
            "quota",
            "should-run",
            "--goal-id",
            GOAL_ID,
            "--scan-path",
            str(project),
            registry_path=registry_path,
            runtime=runtime,
        )
        assert follow_up["should_run"] is True, follow_up
        assert follow_up["state"] == "eligible", follow_up
        assert follow_up["status"] == "state_refreshed", follow_up
        assert follow_up["quota"]["spent_slots"] == 1, follow_up
        assert follow_up["quota"]["allowed_slots"] == 2, follow_up
        assert LONG_NEXT_ACTION_TAIL in follow_up["recommended_action"], follow_up
        assert registry_path.read_text(encoding="utf-8") == registry_before

    print("heartbeat-quota-flow-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
