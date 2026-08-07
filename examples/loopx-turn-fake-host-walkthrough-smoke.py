#!/usr/bin/env python3
"""Prove generic-host Turn transaction and terminal-routing contracts."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.turn_driver import (  # noqa: E402
    LOOPX_TURN_RESULT_SCHEMA_VERSION,
    build_loopx_turn_plan,
    load_loopx_turn_plan_from_journal,
    run_loopx_turn_once,
)


def _envelope(*, action_hash: str, should_run: bool = True) -> dict[str, Any]:
    terminal = not should_run
    return {
        "ok": True,
        "schema_version": "loopx_turn_envelope_v0",
        "goal_id": "fake-host-walkthrough",
        "agent_id": "generic-fixture-host",
        "should_run": should_run,
        "effective_action": "normal_run" if should_run else "terminal_no_followup",
        "action": {
            "must_attempt": should_run,
            "delivery_allowed": should_run,
            "quiet_noop_allowed": terminal,
            **(
                {
                    "selected_todo": {
                        "todo_id": "todo_fakehost0001",
                        "text": "Advance one synthetic public fixture.",
                    }
                }
                if should_run
                else {}
            ),
        },
        "user": {"action_required": False, "open_count": 0, "notify": "DONT_NOTIFY"},
        "writeback": {"spend_after_validation": should_run},
        "scheduler": {"action": "run_now" if should_run else "wait"},
        "action_signature": {
            "matches": True,
            "source_hash": action_hash,
            "envelope_hash": action_hash,
        },
        "compaction": {"within_budget": True},
    }


def _plan(*, action_hash: str) -> dict[str, Any]:
    return build_loopx_turn_plan(
        _envelope(action_hash=action_hash),
        host="generic-cli",
        execution_mode="isolated-headless",
    )


def _result(plan: dict[str, Any]) -> dict[str, Any]:
    transaction = plan["transaction"]
    assert isinstance(transaction, dict)
    return {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
        "turn_key": transaction["turn_key"],
        "result_kind": "validated_progress",
        "completed_phases": ["host_execute", "typed_result"],
        "classification": "fake_host_fixture_progress",
        "recommended_action": "Validate the synthetic fixture.",
        "next_action": "Stop after the independently validated fixture.",
        "delivery_batch_scale": "single_surface",
        "delivery_outcome": "outcome_progress",
        "vision_unchanged_reason": "The public fixture objective is unchanged.",
        "summary": "The generic fake host advanced one fixture.",
    }


def _validator(_plan: dict[str, Any], _result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "passed",
        "validator_kind": "synthetic_independent_callback",
        "summary": "Independent fixture postcondition passed.",
    }


def _callbacks(calls: dict[str, int], phases: list[str]):
    def writeback(_result: dict[str, Any]) -> dict[str, Any]:
        calls["writeback"] += 1
        phases.append("writeback")
        return {"ok": True, "appended": True, "classification": "fixture_progress"}

    def spend() -> dict[str, Any]:
        calls["spend"] += 1
        phases.append("spend")
        return {"ok": True, "appended": True, "slots": 1}

    def scheduler(_spend: dict[str, Any]) -> dict[str, Any]:
        calls["scheduler"] += 1
        phases.append("scheduler")
        return {
            "completed": True,
            "acknowledged": True,
            "disposition": "applied_and_acknowledged",
        }

    return writeback, spend, scheduler


def _common(
    *,
    plan: dict[str, Any],
    root: Path,
    calls: dict[str, int],
    phases: list[str],
) -> dict[str, Any]:
    def host(request: dict[str, Any]) -> dict[str, Any]:
        assert set(request) == {
            "schema_version",
            "turn_key",
            "route",
            "session",
            "turn_envelope",
            "result_contract",
        }
        assert request["schema_version"] == "loopx_turn_host_request_v0"
        assert request["session"] == {
            "schema_version": "loopx_turn_session_binding_v0",
            "action": "start_new",
        }
        assert "session_handle" not in request
        calls["host"] += 1
        phases.append("host")
        return _result(plan)

    writeback, spend, scheduler = _callbacks(calls, phases)
    return {
        "host_runner": host,
        "project": root / "project",
        "runtime_root": root / "runtime",
        "goal_id": "fake-host-walkthrough",
        "timeout_seconds": 5,
        "execute": True,
        "task_validator": _validator,
        "writeback": writeback,
        "spend": spend,
        "scheduler": scheduler,
    }


def _commit_replay_and_boundary(root: Path) -> dict[str, Any]:
    plan = _plan(action_hash="sha256:fake-host-commit")
    calls = {"host": 0, "writeback": 0, "spend": 0, "scheduler": 0}
    phases: list[str] = []
    kwargs = _common(plan=plan, root=root, calls=calls, phases=phases)

    preview = run_loopx_turn_once(plan, **{**kwargs, "execute": False})
    committed = run_loopx_turn_once(plan, **kwargs)
    replay = run_loopx_turn_once(plan, **kwargs)

    assert preview["status"] == "preview"
    assert not any(preview["effects"].values())
    assert committed["status"] == "committed"
    assert committed["receipt"]["status"] == "committed"
    assert committed["effects"] == {
        "host_invoked": True,
        "state_written": True,
        "quota_spent": True,
        "scheduler_acknowledged": True,
    }
    assert replay["replayed"] is True
    assert not any(replay["effects"].values())
    assert calls == {"host": 1, "writeback": 1, "spend": 1, "scheduler": 1}
    assert phases == ["host", "writeback", "spend", "scheduler"]

    journal = next(
        (root / "runtime" / "goals" / "fake-host-walkthrough" / "turns").glob("*.json")
    )
    journal_payload = json.loads(journal.read_text(encoding="utf-8"))
    assert journal_payload["host"] == {"executable": "built-in", "kind": "generic-cli"}
    assert set(journal_payload["host_result"]) == {
        "classification",
        "completed_phases",
        "delivery_batch_scale",
        "delivery_outcome",
        "next_action",
        "path_delta_mode",
        "recommended_action",
        "result_kind",
        "schema_version",
        "summary",
        "turn_key",
        "vision_unchanged_reason",
    }
    assert str(root) not in json.dumps(journal_payload, sort_keys=True)

    return {
        "compact_request_preserved": True,
        "preview_has_no_effects": True,
        "committed_once": True,
        "replay_has_no_effects": True,
        "ordered_effects": phases[1:],
        "public_boundary_preserved": True,
    }


def _recover_after_writeback(root: Path) -> dict[str, Any]:
    plan = _plan(action_hash="sha256:fake-host-recovery")
    calls = {"host": 0, "writeback": 0, "spend": 0, "scheduler": 0}
    phases: list[str] = []
    kwargs = _common(plan=plan, root=root, calls=calls, phases=phases)
    healthy_spend = kwargs["spend"]

    def interrupted_spend() -> dict[str, Any]:
        calls["spend"] += 1
        phases.append("spend-interrupted")
        raise SystemExit(8)

    try:
        run_loopx_turn_once(plan, **{**kwargs, "spend": interrupted_spend})
    except SystemExit as exc:
        assert exc.code == 8
    else:
        raise AssertionError("the synthetic spend interruption must escape")

    transaction = plan["transaction"]
    assert isinstance(transaction, dict)
    resumed_plan = load_loopx_turn_plan_from_journal(
        root / "runtime",
        goal_id="fake-host-walkthrough",
        turn_key=str(transaction["turn_key"]),
    )
    recovered = run_loopx_turn_once(
        resumed_plan,
        **{**kwargs, "spend": healthy_spend},
    )

    assert recovered["status"] == "committed"
    assert calls == {"host": 1, "writeback": 1, "spend": 2, "scheduler": 1}
    assert phases == ["host", "writeback", "spend-interrupted", "spend", "scheduler"]
    return {
        "resumed_after_writeback": True,
        "host_not_repeated": True,
        "writeback_not_repeated": True,
        "remaining_effects": ["spend", "scheduler"],
    }


def _terminal_envelope_blocks_host() -> dict[str, Any]:
    """The lifecycle owner supplies terminal state; Turn must honor it."""
    plan = build_loopx_turn_plan(
        _envelope(action_hash="sha256:fake-host-terminal", should_run=False),
        host="generic-cli",
        execution_mode="isolated-headless",
    )
    assert plan["route"]["kind"] == "wait"
    assert plan["route"]["would_invoke_host"] is False
    assert plan["route"]["host_invocation_allowed"] is False
    assert plan["transaction"]["status"] == "not_applicable"
    assert not any(plan["effects"].values())
    return {"host_followup_eligible": False, "effects": plan["effects"]}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-turn-fake-host-") as directory:
        root = Path(directory)
        summary = {
            "schema_version": "loopx_turn_fake_host_walkthrough_v1",
            "host": "generic-cli",
            "commit_and_replay": _commit_replay_and_boundary(root / "commit"),
            "recovery": _recover_after_writeback(root / "recovery"),
            "terminal_envelope_routing": _terminal_envelope_blocks_host(),
        }

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
