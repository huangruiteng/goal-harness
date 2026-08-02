#!/usr/bin/env python3
"""Run one real experimental planner-worker fixture and validation receipt."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from loopx.experiments.planner_worker.contract import (  # noqa: E402
    AdapterTurn,
    PLANNER_WORKER_PLAN_SCHEMA_VERSION,
    PLANNER_WORKER_STEP_SCHEMA_VERSION,
)
from loopx.experiments.planner_worker.runtime import (  # noqa: E402
    run_planner_worker_once,
)
from loopx.experiments.planner_worker.traex import (  # noqa: E402
    GitWorkspaceObserver,
    SubprocessValidationRunner,
)


class FixturePlanner:
    def plan(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn:
        assert "strict JSON" in prompt
        plan = {
            "schema_version": PLANNER_WORKER_PLAN_SCHEMA_VERSION,
            "plan_id": "runtime-smoke",
            "objective": "Repair the fixture value.",
            "steps": [{
                "schema_version": PLANNER_WORKER_STEP_SCHEMA_VERSION,
                "step_id": "repair-fixture",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["result.txt"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": True,
                "worker_blockers": [],
                "context_budget": {
                    "max_files": 1,
                    "max_bytes_per_file": 4096,
                    "allow_extra_files": False,
                },
                "research_summary": "result.txt contains stale.",
                "implementation_notes": "Replace stale with expected.",
                "instruction": "Write expected to result.txt.",
                "depends_on": [],
                "validation_commands": ["python3 verify.py"],
                "done_criteria": ["verify.py exits zero"],
                "escalation_policy": "Stop if result.txt is missing.",
                "verification": "Run python3 verify.py.",
            }],
        }
        return AdapterTurn(
            output_text=json.dumps(plan),
            usage={"input_tokens": 80, "output_tokens": 40},
            usage_complete=True,
        )


class FixtureWorker:
    def execute(
        self,
        *,
        prompt: str,
        model_route: dict[str, str],
        cwd: Path,
    ) -> AdapterTurn:
        assert model_route["model"] == "deepseek-v4-flash"
        assert "result.txt" in prompt
        (cwd / "result.txt").write_text("expected\n", encoding="utf-8")
        return AdapterTurn(
            output_text="updated result.txt",
            usage={"input_tokens": 40, "output_tokens": 20},
            usage_complete=True,
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-planner-worker-runtime-") as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "result.txt").write_text("stale\n", encoding="utf-8")
        (root / "verify.py").write_text(
            "from pathlib import Path\n"
            "raise SystemExit(0 if Path('result.txt').read_text() == 'expected\\n' else 1)\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "--", "result.txt", "verify.py"], cwd=root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=LoopX Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=root,
            check=True,
        )
        approved_commands = frozenset({"python3 verify.py"})
        receipt = run_planner_worker_once(
            objective="Repair the fixture value.",
            task_instruction="Use a bounded file-level plan.",
            cwd=root,
            planner=FixturePlanner(),
            worker=FixtureWorker(),
            validation_runner=SubprocessValidationRunner(
                timeout_seconds=5,
                approved_commands=approved_commands,
            ),
            workspace_observer=GitWorkspaceObserver(),
            approved_validation_commands=approved_commands,
            model_routes={
                "planner": {"model": "gpt-5.5", "effort": "high"},
                "cheap_worker": {
                    "model": "deepseek-v4-flash",
                    "effort": "medium",
                },
                "strong_worker": {"model": "gpt-5.5", "effort": "high"},
            },
        )
        assert receipt["status"] == "completed", receipt
        assert receipt["validation"][0]["passed"] is True, receipt
        assert receipt["executor"] == "cheap_worker", receipt
        assert receipt["usage"]["complete"] is True, receipt
        assert receipt["cost"]["complete"] is False, receipt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
