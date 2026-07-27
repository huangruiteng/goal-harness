#!/usr/bin/env python3
"""Smoke-test the TraeX planner-worker probe with a fake traex binary."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.traex_planner_worker import (  # noqa: E402
    build_synthetic_planner_worker_plan,
    run_traex_planner_worker_probe,
)


FAKE_TRAEX = """#!/usr/bin/env python3
import json
import sys

model = "unknown"
ignore_rules = "--ignore-rules" in sys.argv
ignore_user_config = "--ignore-user-config" in sys.argv
for index, arg in enumerate(sys.argv):
    if arg == "--model" and index + 1 < len(sys.argv):
        model = sys.argv[index + 1]

text = "planner answer" if model.endswith("5.5") else "worker answer"
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
        plan = build_synthetic_planner_worker_plan(objective="Synthetic objective.")
        payload = run_traex_planner_worker_probe(
            objective="Synthetic objective.",
            task_instruction="Synthetic task.",
            planner_output_plan=plan,
            traex_bin=str(fake),
            planner_model="GPT-5.5",
            worker_model="DeepSeek-V4-Flash",
            cwd=root,
            timeout_seconds=5,
        )
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
