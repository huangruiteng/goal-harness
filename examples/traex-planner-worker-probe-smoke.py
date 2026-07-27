#!/usr/bin/env python3
"""Smoke-test the TraeX planner-worker probe with a fake traex binary."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.traex_planner_worker import (  # noqa: E402
    TraexPlannerWorkerError,
    run_traex_planner_worker_probe,
)


FAKE_TRAEX = """#!/usr/bin/env python3
import json
import os
import sys

model = "unknown"
ignore_rules = "--ignore-rules" in sys.argv
ignore_user_config = "--ignore-user-config" in sys.argv
for index, arg in enumerate(sys.argv):
    if arg == "--model" and index + 1 < len(sys.argv):
        model = sys.argv[index + 1]

calls_path = os.environ.get("FAKE_TRAEX_CALLS")
if calls_path:
    with open(calls_path, "a", encoding="utf-8") as handle:
        handle.write(model + "\\n")

if model.endswith("5.5"):
    text = os.environ.get("FAKE_TRAEX_PLANNER_TEXT") or json.dumps({
        "schema_version": "planner_worker_plan_v0",
        "plan_id": "fake-planner-plan",
        "objective": "Synthetic objective.",
        "steps": [
            {
                "schema_version": "planner_worker_step_v0",
                "step_id": "inspect-contract",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["loopx/planner_worker.py"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": True,
                "worker_blockers": [],
                "context_budget": {
                    "max_files": 1,
                    "max_bytes_per_file": 12000,
                    "allow_extra_files": False
                },
                "research_summary": "The planner-worker contract helpers own prompt construction.",
                "implementation_notes": "Keep the worker step bounded to the listed file.",
                "instruction": "Inspect the planner-worker helper contract.",
                "depends_on": [],
                "validation_commands": ["python3 examples/planner-worker-contract-smoke.py"],
                "done_criteria": ["Focused smoke passes."],
                "escalation_policy": "Stop if the helper file is absent.",
                "verification": "Run python3 examples/planner-worker-contract-smoke.py.",
                "status": "planned"
            }
        ]
    })
else:
    text = "worker answer"
usage = {
    "input_tokens": 100 if model.endswith("5.5") else 50,
    "output_tokens": 20 if model.endswith("5.5") else 30,
    "reasoning_output_tokens": 5 if model.endswith("5.5") else 7,
}
print(json.dumps({"type": "thread.started", "thread_id": "fake"}))
print(json.dumps({"type": "turn.started"}))
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text + str(ignore_rules) + str(ignore_user_config)}}))
print(json.dumps({"type": "turn.completed", "usage": usage}))
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-traex-probe-smoke-") as tmp:
        root = Path(tmp)
        fake = root / "traex"
        fake.write_text(FAKE_TRAEX, encoding="utf-8")
        fake.chmod(0o755)
        calls = root / "calls.txt"
        old_calls = os.environ.get("FAKE_TRAEX_CALLS")
        os.environ["FAKE_TRAEX_CALLS"] = str(calls)
        try:
            payload = run_traex_planner_worker_probe(
                objective="Synthetic objective.",
                task_instruction="Synthetic task.",
                traex_bin=str(fake),
                planner_model="GPT-5.5",
                worker_model="DeepSeek-V4-Flash",
                cwd=root,
                timeout_seconds=5,
            )
        finally:
            if old_calls is None:
                os.environ.pop("FAKE_TRAEX_CALLS", None)
            else:
                os.environ["FAKE_TRAEX_CALLS"] = old_calls
        calls_text = calls.read_text(encoding="utf-8")
        assert "GPT-5.5" in calls_text, calls_text
        assert "DeepSeek-V4-Flash" in calls_text, calls_text
        assert payload["schema_version"] == "traex_planner_worker_probe_v0", payload
        assert payload["runtime"] == "traex", payload
        assert payload["planner_turn"]["assistant_message_present"] is True, payload
        assert payload["worker_turn"]["assistant_message_present"] is True, payload
        assert payload["planner_turn"]["raw_assistant_message_recorded"] is False, payload
        assert payload["worker_turn"]["raw_assistant_message_recorded"] is False, payload
        assert payload["total_usage"]["input_tokens"] == 150, payload
        assert payload["total_usage"]["output_tokens"] == 50, payload
        assert payload["total_usage"]["reasoning_output_tokens"] == 12, payload
        assert payload["boundary"]["read_only_traex_exec"] is True, payload
        assert payload["boundary"]["worker_minimal_context"] is True, payload
        assert payload["worker_model"] == "DeepSeek-V4-Flash", payload
        assert "planner answer" not in json.dumps(payload), payload

    with tempfile.TemporaryDirectory(prefix="loopx-traex-probe-invalid-") as tmp:
        root = Path(tmp)
        fake = root / "traex"
        fake.write_text(FAKE_TRAEX, encoding="utf-8")
        fake.chmod(0o755)
        calls = root / "calls.txt"
        old_calls = os.environ.get("FAKE_TRAEX_CALLS")
        old_text = os.environ.get("FAKE_TRAEX_PLANNER_TEXT")
        os.environ["FAKE_TRAEX_CALLS"] = str(calls)
        os.environ["FAKE_TRAEX_PLANNER_TEXT"] = "THIS IS NOT JSON"
        try:
            try:
                run_traex_planner_worker_probe(
                    objective="Synthetic objective.",
                    task_instruction="Synthetic task.",
                    traex_bin=str(fake),
                    planner_model="GPT-5.5",
                    worker_model="DeepSeek-V4-Flash",
                    cwd=root,
                    timeout_seconds=5,
                )
            except TraexPlannerWorkerError as exc:
                assert "invalid planner-worker plan" in str(exc), exc
            else:
                raise AssertionError("invalid planner output should fail before worker launch")
            assert calls.read_text(encoding="utf-8") == "GPT-5.5\n", calls.read_text(encoding="utf-8")
        finally:
            if old_calls is None:
                os.environ.pop("FAKE_TRAEX_CALLS", None)
            else:
                os.environ["FAKE_TRAEX_CALLS"] = old_calls
            if old_text is None:
                os.environ.pop("FAKE_TRAEX_PLANNER_TEXT", None)
            else:
                os.environ["FAKE_TRAEX_PLANNER_TEXT"] = old_text
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
