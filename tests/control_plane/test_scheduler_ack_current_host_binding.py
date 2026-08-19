from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

from examples.control_plane.quota_plan_fixtures import SCOPED_AGENT_ID, write_cli_fixture
from loopx.cli_commands import quota as quota_command
from loopx.control_plane.testing.canary_harness import run_json_cli, run_json_cli_result
from loopx.status import AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK


GOAL_ID = "needs-operator"


def _write_heartbeat_rrule(codex_home: Path, rrule: str) -> None:
    automation_path = codex_home / "automations" / "fixture" / "automation.toml"
    automation_path.parent.mkdir(parents=True, exist_ok=True)
    automation_path.write_text(
        "\n".join(
            [
                "version = 1",
                'id = "fixture"',
                'kind = "heartbeat"',
                'name = "Scheduler ACK fixture"',
                (
                    'prompt = "Advance `needs-operator` from active state. '
                    'Agent: `codex-side-bypass`."'
                ),
                'status = "ACTIVE"',
                f'rrule = "{rrule}"',
                'target_thread_id = "fixture-thread"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def _quota(
    registry_path: Path,
    runtime_root: Path,
    project: Path,
) -> dict:
    _returncode, payload = run_json_cli_result(
        "quota",
        "should-run",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        SCOPED_AGENT_ID,
        "--codex-app",
        registry_path=registry_path,
        runtime_root=runtime_root,
        cwd=project,
    )
    return payload


def test_scheduler_ack_current_replays_host_binding_after_update(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_path, runtime_root, project = write_cli_fixture(
        tmp_path / "fixture",
        scoped_agents=True,
    )
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_THREAD_ID", "fixture-thread")
    _write_heartbeat_rrule(codex_home, "FREQ=MINUTELY;INTERVAL=3")

    first = _quota(registry_path, runtime_root, project)
    app = first["scheduler_hint"]["codex_app"]
    target_rrule = app["recommended_rrule"]
    ack_hint = app["ack_hint"]
    assert app["stateful_backoff"]["apply_needed"] is True
    assert ack_hint["after"] == "automation_update_rrule_success"
    assert ack_hint["args"]["host_match_observed"] is True

    # Simulate a successful host update before executing the original ACK hint.
    _write_heartbeat_rrule(codex_home, target_rrule)
    ack = run_json_cli(
        *ack_hint["cli_args"],
        registry_path=registry_path,
        runtime_root=runtime_root,
        cwd=project,
    )
    assert ack["scheduler_state_mutated"] is True
    assert ack["already_applied"] is False

    settled = _quota(registry_path, runtime_root, project)
    settled_app = settled["scheduler_hint"]["codex_app"]
    assert settled_app["stateful_backoff"]["apply_needed"] is False
    assert settled_app["stateful_backoff"]["ack_needed"] is False
    assert settled_app["host_action"] == "none"


def test_quota_should_run_ignores_cross_agent_scheduler_state(tmp_path: Path) -> None:
    registry_path, runtime_root, project = write_cli_fixture(
        tmp_path / "fixture",
        scoped_agents=True,
    )
    first = _quota(registry_path, runtime_root, project)
    first_rrule = first["scheduler_hint"]["codex_app"]["recommended_rrule"]
    ack = run_json_cli(
        "quota",
        "scheduler-ack",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        SCOPED_AGENT_ID,
        "--applied-rrule",
        first_rrule,
        "--codex-app",
        "--execute",
        registry_path=registry_path,
        runtime_root=runtime_root,
        cwd=project,
    )
    state_path = Path(ack["scheduler_state_path"])
    persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
    persisted_state["agent_id"] = "codex-other-agent"
    state_path.write_text(
        json.dumps(persisted_state, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    repaired = _quota(registry_path, runtime_root, project)
    app = repaired["scheduler_hint"]["codex_app"]
    assert app["recommended_rrule"] == first_rrule
    assert app["stateful_backoff"]["state_status"] == "missing"
    assert app["stateful_backoff"]["apply_needed"] is True


def test_scheduler_ack_collects_the_periodic_should_run_lookback(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_collect_status(**kwargs):
        seen["limit"] = kwargs.get("limit")
        return {"ok": True, "runtime_root": "/tmp/runtime"}

    def fake_record_quota_scheduler_ack(status_payload, **kwargs):
        seen["status_payload"] = status_payload
        seen["ack_kwargs"] = kwargs
        return {"ok": True, "mode": "scheduler-ack", "dry_run": True}

    def fake_print_payload(payload, output_format, renderer):
        seen["payload"] = payload
        seen["output_format"] = output_format
        seen["renderer"] = renderer

    monkeypatch.setattr(quota_command, "collect_status", fake_collect_status)
    monkeypatch.setattr(
        quota_command,
        "record_quota_scheduler_ack",
        fake_record_quota_scheduler_ack,
    )
    args = Namespace(
        quota_command="scheduler-ack",
        goal_id="scheduler-state-ack-test",
        agent_id=SCOPED_AGENT_ID,
        available_capabilities=["shell", "network", "benchmark_runner"],
        include_scheduler_detail=False,
        runtime_profile=None,
        codex_app=True,
        host_surface=None,
        scheduler_owner=None,
        execution_mode=None,
        codex_app_current_rrule=None,
        slots=1,
        source="heartbeat",
        void_generated_at=None,
        reason_summary=None,
        todo_id=None,
        target_key=None,
        result_hash=None,
        material_change=False,
        cadence=None,
        next_due_at=None,
        next_agent_todo=None,
        next_user_todo=None,
        next_claimed_by=None,
        surface="codex_app",
        state_key="scheduler_hint.codex_app.stateful_backoff",
        applied_rrule="FREQ=MINUTELY;INTERVAL=10",
        reset_token="fixture-reset-token",
        identity_signature="fixture-identity-signature",
        host_match_observed=False,
        use_current_hint=False,
        dry_run=False,
        execute=False,
        scan_root=".",
        scan_path=[],
        limit=5,
        format="json",
    )

    result = quota_command.handle_quota_command(
        args,
        registry_path=Path(".loopx/registry.json"),
        runtime_root_arg=None,
        print_payload=fake_print_payload,
        append_cli_rollout_event=lambda **_: {},
    )

    assert result == 0
    assert seen["limit"] == AUTONOMOUS_REPLAN_PERIODIC_LOOKBACK
    assert seen["payload"] == {
        "ok": True,
        "mode": "scheduler-ack",
        "dry_run": True,
    }
    ack_kwargs = seen["ack_kwargs"]
    assert ack_kwargs["available_capabilities"] == [
        "shell",
        "network",
        "benchmark_runner",
    ]
    assert ack_kwargs["reset_token"] == "fixture-reset-token"
    assert ack_kwargs["identity_signature"] == "fixture-identity-signature"
