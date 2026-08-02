#!/usr/bin/env python3
"""Smoke-test the TraeX adapter against the real planner-worker runtime."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from loopx.experiments.planner_worker.traex import (  # noqa: E402
    TraexPlannerWorkerError,
    run_traex_planner_worker_probe,
)


FAKE_TRAEX = """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

model = "unknown"
sandbox = "unknown"
for index, arg in enumerate(sys.argv):
    if arg == "--model" and index + 1 < len(sys.argv):
        model = sys.argv[index + 1]
    if arg == "--sandbox" and index + 1 < len(sys.argv):
        sandbox = sys.argv[index + 1]

calls_path = os.environ.get("FAKE_TRAEX_CALLS")
if calls_path:
    with open(calls_path, "a", encoding="utf-8") as handle:
        handle.write(model + ":" + sandbox + "\\n")

if sandbox == "read-only":
    text = os.environ.get("FAKE_TRAEX_PLANNER_TEXT") or json.dumps({
        "schema_version": "planner_worker_plan_v0",
        "plan_id": "fake-planner-plan",
        "objective": "Update one fixture.",
        "steps": [{
            "schema_version": "planner_worker_step_v0",
            "step_id": "edit-fixture",
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
                "allow_extra_files": False
            },
            "research_summary": "The fixture contains one stale value.",
            "implementation_notes": "Replace the stale value.",
            "instruction": "Write expected to result.txt.",
            "depends_on": [],
            "validation_commands": ["python3 verify.py"],
            "done_criteria": ["verify.py exits zero"],
            "escalation_policy": "Stop if result.txt is outside the workspace.",
            "verification": "Run python3 verify.py."
        }]
    })
else:
    pathlib.Path("result.txt").write_text("expected\\n", encoding="utf-8")
    text = "updated result.txt"

usage = {
    "input_tokens": 100 if sandbox == "read-only" else 50,
    "output_tokens": 20 if sandbox == "read-only" else 30,
}
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}}))
print(json.dumps({"type": "turn.completed", "usage": usage}))
"""


def write_fake_traex(root: Path) -> Path:
    fake = root / "traex"
    fake.write_text(FAKE_TRAEX, encoding="utf-8")
    fake.chmod(0o755)
    (root / "verify.py").write_text(
        "from pathlib import Path\n"
        "raise SystemExit(0 if Path('result.txt').read_text() == 'expected\\n' else 1)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "--", "traex", "verify.py"], cwd=root, check=True)
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
    return fake


def run_probe(root: Path, fake: Path) -> dict:
    return run_traex_planner_worker_probe(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        traex_bin=str(fake),
        planner_model="GPT-5.5",
        worker_model="DeepSeek-V4-Flash",
        cwd=root,
        approved_validation_commands=("python3 verify.py",),
        timeout_seconds=5,
    )


def new_calls_path() -> Path:
    descriptor, path = tempfile.mkstemp(prefix="loopx-traex-calls-")
    os.close(descriptor)
    return Path(path)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-traex-probe-smoke-") as tmp:
        root = Path(tmp)
        fake = write_fake_traex(root)
        calls = new_calls_path()
        os.environ["FAKE_TRAEX_CALLS"] = str(calls)
        payload = run_probe(root, fake)
        receipt = payload["receipt"]
        assert calls.read_text(encoding="utf-8").splitlines() == [
            "GPT-5.5:read-only",
            "DeepSeek-V4-Flash:workspace-write",
        ]
        assert payload["schema_version"] == "traex_planner_worker_probe_v1", payload
        assert payload["mode"] == "experimental_planner_worker", payload
        assert receipt["schema_version"] == "planner_worker_receipt_v0", receipt
        assert receipt["status"] == "completed", receipt
        assert receipt["executor"] == "cheap_worker", receipt
        assert receipt["model_route"]["model"] == "DeepSeek-V4-Flash", receipt
        assert receipt["validation"][0]["passed"] is True, receipt
        assert receipt["usage"]["total_tokens"] == 200, receipt
        assert receipt["usage"]["complete"] is True, receipt
        assert receipt["cost"]["complete"] is False, receipt
        assert payload["boundary"]["planner_sandbox"] == "read-only", payload
        assert payload["boundary"]["worker_sandbox"] == "workspace-write", payload

    with tempfile.TemporaryDirectory(prefix="loopx-traex-probe-blocked-") as tmp:
        root = Path(tmp)
        fake = write_fake_traex(root)
        calls = new_calls_path()
        os.environ["FAKE_TRAEX_CALLS"] = str(calls)
        blocked_plan = {
            "schema_version": "planner_worker_plan_v0",
            "plan_id": "blocked-plan",
            "objective": "Update one fixture.",
            "steps": [{
                "schema_version": "planner_worker_step_v0",
                "step_id": "edit-fixture",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["result.txt"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": False,
                "worker_blockers": ["missing symbol"],
                "context_budget": {
                    "max_files": 1,
                    "max_bytes_per_file": 4096,
                    "allow_extra_files": False
                },
                "research_summary": "One symbol is missing.",
                "implementation_notes": "Wait for Planner evidence.",
                "instruction": "Do not execute yet.",
                "depends_on": [],
                "validation_commands": [],
                "done_criteria": [],
                "escalation_policy": "Return to Planner.",
                "verification": "No validation until unblocked."
            }]
        }
        os.environ["FAKE_TRAEX_PLANNER_TEXT"] = json.dumps(blocked_plan)
        payload = run_probe(root, fake)
        assert payload["receipt"]["status"] == "blocked", payload
        assert calls.read_text(encoding="utf-8") == "GPT-5.5:read-only\n"

    with tempfile.TemporaryDirectory(prefix="loopx-traex-probe-invalid-") as tmp:
        root = Path(tmp)
        fake = write_fake_traex(root)
        calls = new_calls_path()
        os.environ["FAKE_TRAEX_CALLS"] = str(calls)
        os.environ["FAKE_TRAEX_PLANNER_TEXT"] = "THIS IS NOT JSON"
        try:
            run_probe(root, fake)
        except TraexPlannerWorkerError as exc:
            assert "invalid planner-worker contract" in str(exc), exc
        else:
            raise AssertionError("invalid Planner output must fail before Worker launch")
        assert calls.read_text(encoding="utf-8") == "GPT-5.5:read-only\n"

    os.environ.pop("FAKE_TRAEX_CALLS", None)
    os.environ.pop("FAKE_TRAEX_PLANNER_TEXT", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
