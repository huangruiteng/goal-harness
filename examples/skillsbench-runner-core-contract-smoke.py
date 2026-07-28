#!/usr/bin/env python3
"""Smoke-test SkillsBench runner use of shared benchmark_core lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.status import compact_benchmark_run  # noqa: E402


ROUTE = "codex-acp-blind-loop-baseline"
TASK_ID = "software-dependency-audit"


def _plan_only() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="skillsbench-core-plan-") as tmp:
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "skillsbench_automation_loop.py"),
                "--task-id",
                TASK_ID,
                "--route",
                ROUTE,
                "--jobs-dir",
                str(Path(tmp) / "jobs"),
                "--plan-only",
            ],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    return payload["launch_plan"]


def _assert_launch_lifecycle(lifecycle: dict[str, Any]) -> None:
    assert lifecycle["schema_version"] == "benchmark_canonical_lifecycle_v0", (
        lifecycle
    )
    assert lifecycle["current_phase"] == "runner_accepted_args", lifecycle
    assert lifecycle["entered_benchmark_case"] is False, lifecycle
    assert lifecycle["case_attempt_countable"] is False, lifecycle
    assert lifecycle["next_required_phase"] == "job_root_materialized", lifecycle
    assert lifecycle["phase_ready"]["process_started"] is True, lifecycle
    assert lifecycle["phase_ready"]["runner_accepted_args"] is True, lifecycle
    assert lifecycle["phase_ready"]["job_root_materialized"] is False, lifecycle


def test_launch_plan_exposes_core_lifecycle_without_wrapper() -> None:
    plan = _plan_only()
    lifecycle = plan["benchmark_canonical_lifecycle"]
    _assert_launch_lifecycle(lifecycle)
    assert plan["runner_prerequisites"]["benchmark_canonical_lifecycle"] == lifecycle
    assert "benchmark_core_runner_contract" not in plan, plan


def test_status_compact_keeps_lifecycle_and_drops_legacy_wrapper() -> None:
    lifecycle = _plan_only()["benchmark_canonical_lifecycle"]
    compact = compact_benchmark_run(
        {
            "schema_version": "benchmark_run_v0",
            "source_runner": "skillsbench",
            "benchmark_id": "skillsbench-1.1",
            "task_id": TASK_ID,
            "runner_prerequisites": {
                "schema_version": "skillsbench_runner_prerequisites_v0",
                "benchmark_core_runner_contract_available": True,
                "benchmark_core_runner_contract_source": "legacy-wrapper",
                "benchmark_canonical_lifecycle": lifecycle,
            },
        }
    )
    assert compact is not None
    prerequisites = compact["runner_prerequisites"]
    _assert_launch_lifecycle(prerequisites["benchmark_canonical_lifecycle"])
    assert "benchmark_core_runner_contract_available" not in prerequisites
    assert "benchmark_core_runner_contract_source" not in prerequisites


def main() -> int:
    test_launch_plan_exposes_core_lifecycle_without_wrapper()
    test_status_compact_keeps_lifecycle_and_drops_legacy_wrapper()
    print("skillsbench runner core contract smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
