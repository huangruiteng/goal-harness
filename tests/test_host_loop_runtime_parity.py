"""Thin parity contract for shell_worker and Pi scheduler-hint consumers."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import external_scheduler_worker as worker  # noqa: E402


def _payload(*, terminal: bool) -> dict[str, object]:
    hint: dict[str, object] = {
        "schema_version": "scheduler_hint_v0",
        "action": (
            "stop_until_explicit_resume" if terminal else "backoff_until_state_change"
        ),
        "cadence_class": "terminal_no_followup" if terminal else "quiet_wait",
        "unchanged_poll": {"local_scheduler": "stop"}
        if terminal
        else {
            "limits": {"local_scheduler": 3},
            "after_limits": {"local_scheduler": "stop_tick_loop"},
        },
    }
    if not terminal:
        hint["reset_policy"] = {"reset_token": "wait-1"}
        hint["cold_path_detail"] = {
            "local_scheduler": {
                "recommended_interval_minutes": 3,
                "example_progression_minutes": [3, 6, 12],
                "unchanged_poll_limit": 3,
                "after_limit": "stop_tick_loop",
                "final_quota_replan_check": {
                    "enabled": True,
                    "action": "rerun_quota_should_run_once",
                },
            }
        }
    return {"should_run": False, "scheduler_hint": hint}


def _shell_plan(payload: dict[str, object], unchanged_polls: int) -> dict[str, object]:
    decision = worker.parse_tick(payload)
    if decision.terminal:
        return {"stop": True}
    minutes, _ = worker.select_interval(decision, unchanged_count=unchanged_polls)
    return {"stop": False, "minutes": minutes}


def _pi_plan(payload: dict[str, object], unchanged_polls: int) -> dict[str, object]:
    runtime_uri = (REPO_ROOT / "loopx/pi_goal_mode/pi-goal-loop-runtime.mjs").as_uri()
    probe = f"""
import {{ waitPlan }} from {json.dumps(runtime_uri)}
let raw = ""
for await (const chunk of process.stdin) raw += chunk
const input = JSON.parse(raw)
process.stdout.write(JSON.stringify(waitPlan(input.decision, input.binding)))
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", probe],
        input=json.dumps(
            {
                "decision": payload,
                "binding": {
                    "schedulerToken": "wait-1",
                    "unchangedPolls": unchanged_polls,
                },
            }
        ),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    plan = json.loads(completed.stdout)
    if plan["stop"]:
        return {"stop": True}
    return {"stop": False, "minutes": plan["minutes"]}


def test_shell_worker_and_pi_interpret_same_scheduler_hint() -> None:
    cases = ((_payload(terminal=False), 1), (_payload(terminal=True), 0))
    for payload, unchanged_polls in cases:
        pi_plan = _pi_plan(payload, unchanged_polls)
        assert pi_plan == _shell_plan(payload, unchanged_polls)
