#!/usr/bin/env python3
"""Provider-neutral host-loop parity: shell_worker + one visible host (Pi).

Runs the same synthetic quota decision through:

1. ``scripts/external_scheduler_worker.py`` (headless ``shell_worker``)
2. Pi visible goal loop (activation + Turn via ``generic-cli``)

Compares signed action selection, compact Turn receipts, independent
validation, recoverable timeout/termination, replan, and terminal
no-followup — without retaining raw sessions or host-local paths.

This is the GH-C70 walkthrough. It does not re-test the full Turn driver
matrix; those contracts live in focused pytest.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
for path in (str(REPO_ROOT), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import external_scheduler_worker as worker  # noqa: E402
from loopx.control_plane.quota.turn_envelope import build_turn_envelope  # noqa: E402
from loopx.control_plane.turn_driver import (  # noqa: E402
    LoopDisposition,
    build_loopx_turn_command_validator,
    build_loopx_turn_plan,
    decide_loop_disposition,
    run_loopx_turn_once,
)
from loopx.host_loop_activation import build_host_loop_activation_packet  # noqa: E402
from loopx.host_mode_planner import build_host_mode_plan  # noqa: E402

GOAL_ID = "gh-c70-parity"
AGENT_ID = "parity-agent"
TODO_ID = "todo_ghc70parity01"
TASK_TEXT = "Advance one synthetic public parity fixture."

_PRIVATE_RE = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"\\\\Users\\\\"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
]


def _public_safe(obj: object) -> bool:
    text = json.dumps(obj, sort_keys=True) if not isinstance(obj, str) else obj
    return not any(pattern.search(text) for pattern in _PRIVATE_RE)


def _quota(
    *,
    should_run: bool = True,
    effective_action: str = "normal_run",
    scheduler_action: str = "run_now",
    cadence_class: str = "active_work",
    decision: str = "run",
    state: str = "eligible",
    replan_limit: int | None = None,
) -> dict[str, Any]:
    selected = (
        {"todo_id": TODO_ID, "text": TASK_TEXT}
        if should_run and effective_action not in {"quiet_noop", "terminal_no_followup"}
        else {}
    )
    local_scheduler: dict[str, Any] = {
        "recommended_interval_minutes": 3,
        "example_progression_minutes": [3, 10, 30],
        "unchanged_poll_limit": replan_limit,
        "after_limit": "stop_tick_loop" if replan_limit is not None else "continue",
        "final_quota_replan_check": {
            "enabled": replan_limit is not None,
            "trigger": "before_unchanged_poll_after_limit",
            "action": "rerun_quota_should_run_once",
            "if_changed": "follow_new_scheduler_hint",
            "if_run_now": "execute_new_quota_contract",
            "if_unchanged": "apply_after_limit_without_spend",
        },
    }
    return {
        "ok": True,
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "agent_identity": {"agent_id": AGENT_ID},
        "decision": decision,
        "should_run": should_run,
        "effective_action": effective_action,
        "state": state,
        "recommended_action": TASK_TEXT if should_run else "Stop until explicit resume.",
        "selected_todo": selected or None,
        "interaction_contract": {
            "schema_version": "loopx_interaction_contract_v0",
            "mode": effective_action,
            "user_channel": {"action_required": False, "notify": "DONT_NOTIFY"},
            "agent_channel": {
                "must_attempt": should_run,
                "delivery_allowed": should_run,
                "quiet_noop_allowed": not should_run,
            },
            "cli_channel": {"spend_after_validation": should_run},
        },
        "open_count": 0,
        "action_required": False,
        "scheduler_hint": {
            "action": scheduler_action,
            "cadence_class": cadence_class,
            "reason": "gh-c70-synthetic",
            "reset_policy": {"reset_token": "parity-token-1"},
            "cold_path_detail": {"local_scheduler": local_scheduler},
        },
    }


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _signed_action_parity() -> dict[str, Any]:
    run_payload = _quota()
    stop_payload = _quota(
        should_run=False,
        effective_action="terminal_no_followup",
        scheduler_action="stop_until_explicit_resume",
        cadence_class="terminal_no_followup",
        decision="stop",
        state="terminal_no_followup",
    )
    run_env = build_turn_envelope(run_payload)
    stop_env = build_turn_envelope(stop_payload)
    assert run_env["action_signature"]["matches"] is True
    assert stop_env["action_signature"]["matches"] is True
    assert run_env["action_signature"]["source_hash"] == (
        run_env["action_signature"]["envelope_hash"]
    )
    assert (
        run_env["action_signature"]["source_hash"]
        != stop_env["action_signature"]["source_hash"]
    )
    assert run_env["compaction"]["within_budget"] is True
    assert _public_safe(run_env) and _public_safe(stop_env)
    return {
        "run_source_hash": run_env["action_signature"]["source_hash"],
        "stop_source_hash": stop_env["action_signature"]["source_hash"],
        "within_budget": True,
    }


def _shell_worker_lane(action_hash: str) -> dict[str, Any]:
    run_payload = _quota()
    tick = worker.parse_tick(run_payload)
    assert tick.should_run is True
    assert tick.terminal is False
    assert tick.action == "run_now"

    replan_payload = _quota(
        should_run=False,
        effective_action="quiet_noop",
        scheduler_action="backoff_until_state_change",
        cadence_class="quiet_wait",
        decision="wait",
        state="waiting",
        replan_limit=2,
    )
    replan_tick = worker.parse_tick(replan_payload)
    assert replan_tick.should_run is False
    assert replan_tick.final_probe_enabled is True
    assert replan_tick.final_probe_action == "rerun_quota_should_run_once"
    assert replan_tick.unchanged_limit == 2

    terminal_payload = _quota(
        should_run=False,
        effective_action="terminal_no_followup",
        scheduler_action="stop_until_explicit_resume",
        cadence_class="terminal_no_followup",
        decision="stop",
        state="terminal_no_followup",
    )
    terminal_tick = worker.parse_tick(terminal_payload)
    assert terminal_tick.terminal is True
    assert terminal_tick.should_run is False

    # Recoverable wake timeout: worker must stop promptly and record timeout.
    with tempfile.TemporaryDirectory(prefix="gh-c70-worker-") as directory:
        root = Path(directory)
        fake_cli = root / "fake-loopx"
        wake = root / "wake"
        state_file = root / "worker-state.json"
        run_json = json.dumps(run_payload)
        _write_executable(
            fake_cli,
            "#!/usr/bin/env python3\n"
            "import json,sys\n"
            f"print(json.dumps(json.loads({run_json!r})))\n",
        )
        _write_executable(
            wake,
            "#!/usr/bin/env python3\n"
            "import time\n"
            "time.sleep(1)\n",
        )
        started = time.monotonic()
        args = argparse.Namespace(
            cli_bin=str(fake_cli),
            registry=str(root / "registry"),
            runtime_root=None,
            runtime_profile="generic_cli",
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            state_file=str(state_file),
            wake_cmd=shlex.join([sys.executable, str(wake)]),
            once=True,
            error_backoff_seconds=5.0,
            quota_timeout_seconds=5.0,
            wake_timeout_seconds=0.1,
        )
        rc = worker.run_worker(args)
        elapsed = time.monotonic() - started
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert rc == 2
        # Bound includes process-group terminate grace (~1s) after the 0.1s cap.
        assert elapsed < 5.0
        assert state["last_wake_status"] == "wake_failed"
        assert state["last_wake_failure_kind"] == "timeout"
        public_state = {
            "last_wake_status": state["last_wake_status"],
            "last_wake_failure_kind": state["last_wake_failure_kind"],
            "reset_token": state.get("reset_token"),
        }
        assert _public_safe(public_state)

    return {
        "connector": "shell_worker",
        "run_now": True,
        "replan_final_probe": True,
        "terminal": True,
        "wake_timeout_recoverable": True,
        "action_hash_ref": action_hash,
        "public_wake_failure": public_state,
    }


def _pi_visible_lane(action_hash: str) -> dict[str, Any]:
    activation = build_host_loop_activation_packet(
        agent_type="pi",
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        registered_agents=[AGENT_ID],
        cli_bin="loopx",
    )
    assert activation["host_surface"] == "pi_visible_goal_mode"
    assert activation["activation_method"] == "activate_loopx_pi_goal_extension"
    assert _public_safe(activation)
    # Authority token is host-derived; activation must not embed absolute paths.
    activation_text = json.dumps(activation, sort_keys=True)
    assert "pi_session_authority" in activation_text
    assert "/Users/" not in activation_text
    assert "/home/" not in activation_text

    visible = build_host_mode_plan(
        goal_id=GOAL_ID,
        user_intent="watch_each_turn",
        host_capabilities=["visible_session", "loopx_turn", "typed_host_adapter", "independent_validator"],
        agent_id=AGENT_ID,
        registered_agents=[AGENT_ID],
        host_identity="pi",
    )
    assert visible["ok"] is True
    assert visible["selected_mode"] == "visible_tui"
    assert visible["selected_connector_id"] == "pi_goal_loop"

    shell = build_host_mode_plan(
        goal_id=GOAL_ID,
        user_intent="timer_keepalive",
        host_capabilities=[
            "service_timer",
            "shell",
            "loopx_turn",
            "typed_host_adapter",
            "independent_validator",
        ],
        agent_id=AGENT_ID,
        registered_agents=[AGENT_ID],
        host_identity="generic-cli",
    )
    assert shell["selected_connector_id"] == "shell_worker"
    assert shell["selected_mode"] == "shell_service"

    run_env = build_turn_envelope(_quota())
    assert run_env["action_signature"]["source_hash"] == action_hash
    plan = build_loopx_turn_plan(
        run_env,
        host="generic-cli",
        execution_mode="isolated-headless",
    )
    assert plan["ok"] is True
    assert plan["route"]["kind"] == "ready_for_host"
    receipt_seed = plan["transaction"]["receipt_seed"]
    settlement = plan["transaction"]["settlement_plan"]["identity"]
    assert settlement["goal_id"] == GOAL_ID
    assert settlement["agent_id"] == AGENT_ID
    assert settlement["todo_id"] == TODO_ID
    assert receipt_seed["status"] == "not_executed"
    assert _public_safe(plan)

    # Independent validation + compact receipt commit, then recoverable timeout.
    with tempfile.TemporaryDirectory(prefix="gh-c70-pi-") as directory:
        root = Path(directory)
        project = root / "project"
        project.mkdir()
        effect = project / "parity-effect.json"
        host_ok = root / "host-ok.py"
        host_hang = root / "host-hang.py"
        validator = root / "validator.py"
        host_ok.write_text(
            "import json, pathlib, sys\n"
            "req = json.load(sys.stdin)\n"
            "contract = req['result_contract']\n"
            "effect_path = pathlib.Path(sys.argv[1])\n"
            "effect_path.write_text(\n"
            "    json.dumps({'task': 'parity', 'turn_key': req['turn_key']}),\n"
            "    encoding='utf-8',\n"
            ")\n"
            "json.dump(\n"
            "    {\n"
            "        'schema_version': contract['schema_version'],\n"
            "        'turn_key': req['turn_key'],\n"
            "        'result_kind': 'validated_progress',\n"
            "        'completed_phases': contract['completed_phases'],\n"
            "        'classification': 'parity_fixture',\n"
            "        'recommended_action': 'Validate parity fixture.',\n"
            "        'next_action': 'Stop after validated parity.',\n"
            "        'delivery_batch_scale': 'single_surface',\n"
            "        'delivery_outcome': 'outcome_progress',\n"
            "        'vision_unchanged_reason': 'Synthetic parity objective unchanged.',\n"
            "        'summary': 'Pi fake host advanced the parity fixture.',\n"
            "    },\n"
            "    sys.stdout,\n"
            ")\n",
            encoding="utf-8",
        )
        host_hang.write_text(
            "import time\n"
            "time.sleep(5)\n",
            encoding="utf-8",
        )
        validator.write_text(
            "import json, pathlib, sys\n"
            "result = json.load(sys.stdin)\n"
            "effect = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
            "ok = (\n"
            "    effect.get('task') == 'parity'\n"
            "    and effect.get('turn_key') == result.get('turn_key')\n"
            ")\n"
            "raise SystemExit(0 if ok else 9)\n",
            encoding="utf-8",
        )

        calls = {"writeback": 0, "spend": 0, "scheduler": 0}

        def writeback(_result: dict[str, Any]) -> dict[str, Any]:
            calls["writeback"] += 1
            return {"ok": True, "appended": True, "classification": "parity_progress"}

        def spend() -> dict[str, Any]:
            calls["spend"] += 1
            return {"ok": True, "appended": True, "slots": 1}

        def scheduler(_spend: dict[str, Any]) -> dict[str, Any]:
            calls["scheduler"] += 1
            return {
                "completed": True,
                "acknowledged": True,
                "disposition": "applied_and_acknowledged",
            }

        common = {
            "project": project,
            "runtime_root": root / "runtime",
            "goal_id": GOAL_ID,
            "timeout_seconds": 5,
            "execute": True,
            "task_validator": build_loopx_turn_command_validator(
                [sys.executable, str(validator), str(effect)],
                project=project,
                timeout_seconds=5,
            ),
            "writeback": writeback,
            "spend": spend,
            "scheduler": scheduler,
        }

        timed_out = run_loopx_turn_once(
            plan,
            **{
                **common,
                "host_argv": [sys.executable, str(host_hang)],
                "timeout_seconds": 1,
            },
        )
        assert timed_out["status"] == "failed"
        assert timed_out.get("result_kind") == "host_failure"
        assert calls == {"writeback": 0, "spend": 0, "scheduler": 0}

        # Fresh plan for the healthy commit (distinct turn instance).
        commit_env = build_turn_envelope(
            {
                **_quota(),
                "recommended_action": TASK_TEXT + " commit",
            }
        )
        commit_plan = build_loopx_turn_plan(
            commit_env,
            host="generic-cli",
            execution_mode="isolated-headless",
        )
        committed = run_loopx_turn_once(
            commit_plan,
            **{
                **common,
                "host_argv": [sys.executable, str(host_ok), str(effect)],
            },
        )
        assert committed["status"] == "committed"
        assert committed["receipt"]["status"] == "committed"
        assert committed["effects"] == {
            "host_invoked": True,
            "state_written": True,
            "quota_spent": True,
            "scheduler_acknowledged": True,
        }
        assert calls == {"writeback": 1, "spend": 1, "scheduler": 1}
        journals = list(
            (root / "runtime" / "goals" / GOAL_ID / "turns").glob("*.json")
        )
        assert len(journals) >= 2
        journal_payloads = [
            json.loads(path.read_text(encoding="utf-8")) for path in journals
        ]
        committed_journals = [
            payload for payload in journal_payloads if payload.get("status") == "committed"
        ]
        failed_journals = [
            payload for payload in journal_payloads if payload.get("status") == "failed"
        ]
        assert len(committed_journals) == 1
        assert len(failed_journals) >= 1
        journal_payload = committed_journals[0]
        assert journal_payload["host"] == {
            "executable": Path(sys.executable).name,
            "argv_count": 3,
        }
        assert "session" not in journal_payload
        assert str(root) not in json.dumps(journal_payload, sort_keys=True)
        assert _public_safe(journal_payload)

    terminal_env = build_turn_envelope(
        _quota(
            should_run=False,
            effective_action="terminal_no_followup",
            scheduler_action="stop_until_explicit_resume",
            cadence_class="terminal_no_followup",
            decision="stop",
            state="terminal_no_followup",
        )
    )
    terminal_plan = build_loopx_turn_plan(
        terminal_env,
        host="generic-cli",
        execution_mode="isolated-headless",
    )
    assert terminal_plan["route"]["would_invoke_host"] is False
    terminal_disp = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=terminal_env,
    )
    assert terminal_disp["disposition"] == LoopDisposition.TERMINAL.value

    replan_env = build_turn_envelope(
        _quota(effective_action="autonomous_replan", decision="run")
    )
    replan_disp = decide_loop_disposition(
        turn_receipt=None,
        quota_decision=replan_env,
    )
    assert replan_disp["disposition"] == LoopDisposition.REPLAN.value
    assert replan_disp["replan_continuation"]["requires_bounded_delta"] is True
    assert replan_disp["replan_continuation"]["fresh_envelope_required"] is True

    return {
        "connector": "pi_goal_loop",
        "activation_surface": activation["host_surface"],
        "visible_connector": visible["selected_connector_id"],
        "shell_connector": shell["selected_connector_id"],
        "settlement_identity": {
            "goal_id": settlement["goal_id"],
            "agent_id": settlement["agent_id"],
            "todo_id": settlement["todo_id"],
        },
        "compact_receipt_seed_status": receipt_seed["status"],
        "independent_validation_and_commit": True,
        "host_timeout_recoverable": True,
        "terminal_no_followup": True,
        "replan_requires_bounded_delta": True,
        "action_hash_ref": action_hash,
    }


def main() -> int:
    signed = _signed_action_parity()
    shell = _shell_worker_lane(signed["run_source_hash"])
    pi = _pi_visible_lane(signed["run_source_hash"])

    assert shell["action_hash_ref"] == pi["action_hash_ref"] == signed["run_source_hash"]
    assert pi["settlement_identity"] == {
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "todo_id": TODO_ID,
    }
    assert shell["terminal"] is True and pi["terminal_no_followup"] is True
    assert shell["replan_final_probe"] is True and pi["replan_requires_bounded_delta"] is True
    assert shell["wake_timeout_recoverable"] is True and pi["host_timeout_recoverable"] is True
    assert pi["shell_connector"] == "shell_worker"
    assert pi["visible_connector"] == "pi_goal_loop"

    summary = {
        "schema_version": "loopx_host_loop_parity_walkthrough_v1",
        "claim": "GH-C70",
        "synthetic_task": TASK_TEXT,
        "lanes": {
            "external_scheduler_worker": shell,
            "visible_host_pi": {
                k: v
                for k, v in pi.items()
                if k != "settlement_identity"
            },
        },
        "parity": {
            "same_signed_action_hash": True,
            "settlement_identity": pi["settlement_identity"],
            "compact_receipts": True,
            "independent_validation": True,
            "recoverable_timeout_termination": True,
            "replan": True,
            "terminal_no_followup": True,
            "no_raw_sessions_or_host_paths": True,
        },
    }
    assert _public_safe(summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    # Skip POSIX-only wake-timeout process-group path on non-posix when needed.
    if os.name != "posix":
        print(
            json.dumps(
                {
                    "schema_version": "loopx_host_loop_parity_walkthrough_v1",
                    "skipped": "posix_required_for_wake_timeout",
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(0)
    raise SystemExit(main())
