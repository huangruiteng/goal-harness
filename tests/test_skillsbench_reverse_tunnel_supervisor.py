from __future__ import annotations

import importlib.util
import json
import signal
import stat
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SUPERVISOR_PATH = REPO_ROOT / "scripts" / "skillsbench_reverse_tunnel_supervisor.py"


def _load_supervisor_module():
    spec = importlib.util.spec_from_file_location(
        "skillsbench_reverse_tunnel_supervisor_test",
        SUPERVISOR_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fake_ssh(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import os
import signal
import sys
import time

if "loopx_reverse_tunnel_keepalive" in sys.argv[-1]:
    time.sleep(10)
elif "# LOOPX_REVERSE_TUNNEL_PROBE" in sys.argv[-1]:
    print("HTTP/1.1 200 OK")
elif sys.argv[-1] == "run-benchmark":
    time.sleep(0.2)
elif sys.argv[-1] == "terminate-supervisor":
    time.sleep(0.1)
    os.kill(os.getppid(), signal.SIGTERM)
elif sys.argv[-1] == "fail-arguments":
    print("usage: runner [--known]", file=sys.stderr)
    print("runner: error: unrecognized arguments: --private-value", file=sys.stderr)
    raise SystemExit(2)
raise SystemExit(0)
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _write_fake_codex(path: Path) -> None:
    path.write_text(
        """#!/bin/sh
exit 0
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_proxy_port_coherence_guard_allows_shared_forward_reuse() -> None:
    supervisor = _load_supervisor_module()

    args = supervisor.parse_args(
        [
            "--ssh-destination",
            "runner.example",
            "--remote-forward",
            "127.0.0.1:18184:127.0.0.1:18184",
            "--codex-reverse-proxy-port",
            "18184",
            "--benchmark-egress-proxy-port",
            "18184",
            "--container-forwarder-port",
            "18184",
        ]
    )

    assert args.proxy_port_coherence == {
        "schema_version": "skillsbench_proxy_port_coherence_v0",
        "state": "coherent",
        "guard_enforced": True,
        "declared_surface_count": 3,
        "expected_surface_count": 3,
        "raw_command_read": False,
        "raw_command_recorded": False,
        "coherent_port": 18184,
    }


@pytest.mark.parametrize(
    "extra_args",
    [
        [
            "--codex-reverse-proxy-port",
            "18184",
            "--benchmark-egress-proxy-port",
            "18184",
        ],
        [
            "--codex-reverse-proxy-port",
            "18184",
            "--benchmark-egress-proxy-port",
            "18185",
            "--container-forwarder-port",
            "18184",
        ],
    ],
)
def test_proxy_port_coherence_guard_rejects_incomplete_or_mismatched_ports(
    extra_args: list[str],
) -> None:
    supervisor = _load_supervisor_module()

    with pytest.raises(SystemExit) as exc_info:
        supervisor.parse_args(
            [
                "--ssh-destination",
                "runner.example",
                "--remote-forward",
                "127.0.0.1:18184:127.0.0.1:18184",
                *extra_args,
            ]
        )

    assert exc_info.value.code == 2


def test_proxy_port_coherence_guard_is_compatible_when_not_requested() -> None:
    supervisor = _load_supervisor_module()

    args = supervisor.parse_args(
        [
            "--ssh-destination",
            "runner.example",
        ]
    )

    assert args.proxy_port_coherence["state"] == "not_requested"
    assert args.proxy_port_coherence["guard_enforced"] is False
    assert args.proxy_port_coherence["declared_surface_count"] == 0


def test_supervisor_writes_starting_periodic_and_terminal_public_liveness(
    tmp_path: Path,
    monkeypatch,
) -> None:
    supervisor = _load_supervisor_module()
    supervisor.PUBLIC_LIVENESS_INTERVAL_SEC = 0.05
    checkpoint_states: list[str] = []
    write_checkpoint = supervisor._write_public_checkpoint

    def record_checkpoint(*args, **kwargs) -> None:
        checkpoint_states.append(kwargs["state"])
        write_checkpoint(*args, **kwargs)

    monkeypatch.setattr(supervisor, "_write_public_checkpoint", record_checkpoint)
    fake_ssh = tmp_path / "fake-ssh"
    public_output = tmp_path / "public" / "supervisor.public.json"
    _write_fake_ssh(fake_ssh)

    args = supervisor.parse_args(
        [
            "--ssh-bin",
            str(fake_ssh),
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "run-benchmark",
            "--public-output-path",
            str(public_output),
            "--probe-interval-sec",
            "0.01",
            "--probe-timeout-sec",
            "5",
            "--tunnel-ready-timeout-sec",
            "5",
            "--tunnel-health-interval-sec",
            "0",
            "--run-timeout-sec",
            "5",
        ]
    )

    returncode, payload = supervisor.run_supervisor(args)
    persisted = json.loads(public_output.read_text(encoding="utf-8"))

    assert returncode == 0
    assert payload["ok"] is True
    assert persisted == payload
    assert checkpoint_states[0] == "starting"
    assert checkpoint_states.count("running") >= 2
    assert checkpoint_states[-1] == "succeeded"
    assert persisted["public_liveness"]["state"] == "succeeded"
    assert persisted["public_liveness"]["terminal"] is True
    assert persisted["public_liveness"]["process_alive"] is False
    assert persisted["public_liveness"]["heartbeat_count"] >= 4
    assert persisted["public_liveness"]["elapsed_sec"] >= 0.2
    assert persisted["public_liveness"]["raw_task_text_recorded"] is False
    assert persisted["public_liveness"]["raw_logs_recorded"] is False
    assert persisted["public_liveness"]["raw_trajectory_recorded"] is False
    assert persisted["public_liveness"]["raw_verifier_output_recorded"] is False
    assert persisted["public_liveness"]["local_paths_recorded"] is False
    assert persisted["proxy_port_coherence"]["state"] == "not_requested"
    assert persisted["proxy_port_coherence"]["raw_command_read"] is False
    assert persisted["proxy_port_coherence"]["raw_command_recorded"] is False
    assert persisted["active_phase"] == {
        "schema_version": "skillsbench_supervisor_active_phase_v0",
        "state": "not_observed",
        "receipt_count": 0,
        "public_artifact_read": False,
        "raw_artifacts_read": False,
        "raw_task_text_read": False,
        "raw_logs_read": False,
        "raw_trajectory_read": False,
        "raw_verifier_output_read": False,
        "local_paths_recorded": False,
    }


def test_supervisor_projects_existing_public_live_worker_phase(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    public_dir = tmp_path / "public"
    receipt_dir = public_dir / "opaque-job"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "runner_prerequisites.public.json").write_text(
        json.dumps(
            {
                "benchflow_lifecycle_receipt_sequence": 7,
                "benchmark_live_worker_phase": {
                    "schema_version": "benchmark_live_worker_phase_v0",
                    "current_phase": "worker_running",
                    "next_required_phase": "agent_active",
                    "phase_ready": {
                        "runtime_preparing": True,
                        "worker_prepared": True,
                        "worker_running": True,
                        "agent_active": False,
                    },
                    "worker_live": True,
                    "agent_active_observed": False,
                    "terminal": False,
                    "terminal_disposition": "open",
                    "public_evidence_only": True,
                    "private_detail": "PRIVATE_DETAIL_MUST_NOT_PROJECT",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    args = supervisor.parse_args(
        [
            "--ssh-destination",
            "runner.example",
            "--remote-public-artifact-root",
            "/opaque/public-jobs",
            "--remote-public-artifact-glob",
            "*/runner_prerequisites.public.json",
            "--local-public-artifact-dir",
            str(public_dir),
        ]
    )

    projected = supervisor._active_phase_public_contract(args)

    assert projected["state"] == "observed"
    assert projected["receipt_count"] == 1
    assert projected["receipt_sequence"] == 7
    assert projected["public_artifact_read"] is True
    assert projected["benchmark_live_worker_phase"]["current_phase"] == (
        "worker_running"
    )
    assert projected["benchmark_live_worker_phase"]["worker_live"] is True
    assert projected["raw_artifacts_read"] is False
    assert projected["local_paths_recorded"] is False
    serialized = json.dumps(projected, sort_keys=True)
    assert "PRIVATE_DETAIL_MUST_NOT_PROJECT" not in serialized
    assert str(tmp_path) not in serialized


def test_terminal_checkpoint_closes_projected_live_worker_phase(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    public_output = tmp_path / "public" / "supervisor.public.json"
    payload = {
        "active_phase": {
            "schema_version": "skillsbench_supervisor_active_phase_v0",
            "state": "observed",
            "benchmark_live_worker_phase": {
                "schema_version": "benchmark_live_worker_phase_v0",
                "current_phase": "agent_active",
                "next_required_phase": "",
                "phase_ready": {
                    "runtime_preparing": True,
                    "worker_prepared": True,
                    "worker_running": True,
                    "agent_active": True,
                },
                "worker_live": True,
                "agent_active_observed": True,
                "terminal": False,
                "terminal_disposition": "open",
                "public_evidence_only": True,
            },
        }
    }

    supervisor._write_public_checkpoint(
        str(public_output),
        payload,
        state="failed",
        started_at=time.time() - 10,
        heartbeat_count=3,
        terminal=True,
    )

    persisted = json.loads(public_output.read_text(encoding="utf-8"))
    phase = persisted["active_phase"]["benchmark_live_worker_phase"]
    assert persisted["public_liveness"]["terminal"] is True
    assert phase["current_phase"] == "agent_active"
    assert phase["agent_active_observed"] is True
    assert phase["worker_live"] is False
    assert phase["terminal"] is True
    assert phase["terminal_disposition"] == "failed"


def test_supervisor_finalizes_public_liveness_on_early_launch_failure(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    public_output = tmp_path / "public" / "supervisor.public.json"
    args = supervisor.parse_args(
        [
            "--ssh-bin",
            str(tmp_path / "missing-ssh"),
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "run-benchmark",
            "--public-output-path",
            str(public_output),
        ]
    )

    returncode, payload = supervisor.run_supervisor(args)
    persisted = json.loads(public_output.read_text(encoding="utf-8"))

    assert returncode == 2
    assert payload["first_blocker"] == "reverse_tunnel_launch_failed"
    assert persisted == payload
    assert persisted["public_liveness"]["state"] == "failed"
    assert persisted["public_liveness"]["terminal"] is True
    assert persisted["public_liveness"]["process_alive"] is False
    assert persisted["public_liveness"]["heartbeat_count"] == 2


def test_main_finalizes_public_liveness_after_unhandled_supervisor_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    supervisor = _load_supervisor_module()
    public_output = tmp_path / "public" / "supervisor.public.json"
    previous_payload = supervisor._initial_public_payload(
        supervisor.parse_args(
            [
                "--ssh-destination",
                "runner.example",
                "--remote-command",
                "run-benchmark",
                "--public-output-path",
                str(public_output),
            ]
        )
    )
    previous_payload["tunnel_ready"] = True
    previous_payload["active_phase"] = {
        "schema_version": "skillsbench_supervisor_active_phase_v0",
        "state": "observed",
        "benchmark_live_worker_phase": {
            "schema_version": "benchmark_live_worker_phase_v0",
            "current_phase": "agent_active",
            "next_required_phase": "",
            "phase_ready": {
                "runtime_preparing": True,
                "worker_prepared": True,
                "worker_running": True,
                "agent_active": True,
            },
            "worker_live": True,
            "agent_active_observed": True,
            "terminal": False,
            "terminal_disposition": "open",
            "public_evidence_only": True,
        },
    }
    supervisor._write_public_checkpoint(
        str(public_output),
        previous_payload,
        state="running",
        started_at=time.time() - 10,
        heartbeat_count=4,
        terminal=False,
    )

    def raise_private_failure(_args):
        raise RuntimeError("PRIVATE_FAILURE_DETAIL_MUST_NOT_PROJECT")

    monkeypatch.setattr(supervisor, "run_supervisor", raise_private_failure)

    returncode = supervisor.main(
        [
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "run-benchmark",
            "--public-output-path",
            str(public_output),
        ]
    )
    persisted = json.loads(public_output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()
    serialized = json.dumps(persisted, sort_keys=True)

    assert returncode == 70
    assert persisted["ok"] is False
    assert persisted["first_blocker"] == "supervisor_unhandled_exception"
    assert persisted["supervisor_error_type"] == "RuntimeError"
    assert persisted["public_liveness"]["state"] == "failed"
    assert persisted["public_liveness"]["terminal"] is True
    assert persisted["public_liveness"]["process_alive"] is False
    assert persisted["public_liveness"]["heartbeat_count"] == 5
    phase = persisted["active_phase"]["benchmark_live_worker_phase"]
    assert phase["agent_active_observed"] is True
    assert phase["terminal"] is True
    assert phase["worker_live"] is False
    assert phase["terminal_disposition"] == "failed"
    fallback = persisted["public_terminal_fallback"]
    assert fallback["triggered"] is True
    assert fallback["exception_message_recorded"] is False
    assert fallback["previous_liveness"]["state"] == "running"
    assert fallback["previous_liveness"]["heartbeat_count"] == 4
    assert fallback["previous_liveness"]["last_known_tunnel_ready"] is True
    assert "PRIVATE_FAILURE_DETAIL_MUST_NOT_PROJECT" not in serialized
    assert "PRIVATE_FAILURE_DETAIL_MUST_NOT_PROJECT" not in captured.err
    assert "RuntimeError" in captured.err


def test_main_finalizes_public_liveness_after_termination_signal(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    supervisor = _load_supervisor_module()
    public_output = tmp_path / "public" / "supervisor.public.json"

    def request_termination(_args):
        signal.raise_signal(signal.SIGTERM)

    monkeypatch.setattr(supervisor, "run_supervisor", request_termination)

    returncode = supervisor.main(
        [
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "run-benchmark",
            "--public-output-path",
            str(public_output),
        ]
    )
    persisted = json.loads(public_output.read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert returncode == 128 + signal.SIGTERM
    assert persisted["first_blocker"] == "supervisor_termination_signal"
    assert persisted["public_liveness"]["terminal"] is True
    assert persisted["public_liveness"]["process_alive"] is False
    fallback = persisted["public_terminal_fallback"]
    assert fallback["trigger"] == "supervisor_termination_signal"
    assert fallback["signal_name"] == "SIGTERM"
    assert fallback["exception_message_recorded"] is False
    closeout = persisted["terminal_closeout"]
    assert closeout["status"] == "complete"
    assert closeout["disposition"] == "typed_exclusion"
    assert closeout["official_score_countable"] is False
    assert closeout["retry_recommended"] is False
    assert closeout["rotation_allowed"] is True
    closeout_path = public_output.with_name("supervisor_closeout.compact.json")
    assert json.loads(closeout_path.read_text(encoding="utf-8")) == closeout
    assert '"signal_name": "SIGTERM"' in captured.out
    assert "_SupervisorTerminationSignal" in captured.err


def test_runtime_termination_writes_closeout_and_cleans_local_processes(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    supervisor.PUBLIC_LIVENESS_INTERVAL_SEC = 0.05
    fake_ssh = tmp_path / "fake-ssh"
    public_output = tmp_path / "public" / "supervisor.public.json"
    _write_fake_ssh(fake_ssh)

    returncode = supervisor.main(
        [
            "--ssh-bin",
            str(fake_ssh),
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "terminate-supervisor",
            "--public-output-path",
            str(public_output),
            "--probe-interval-sec",
            "0.01",
            "--probe-timeout-sec",
            "5",
            "--tunnel-ready-timeout-sec",
            "5",
            "--tunnel-health-interval-sec",
            "0",
            "--run-timeout-sec",
            "5",
        ]
    )
    persisted = json.loads(public_output.read_text(encoding="utf-8"))

    assert returncode == 128 + signal.SIGTERM
    assert persisted["first_blocker"] == "supervisor_termination_signal"
    assert persisted["public_liveness"]["terminal"] is True
    assert persisted["tunnel_cleanup_status"] == "terminated"
    assert persisted["terminal_closeout"]["disposition"] == "typed_exclusion"
    assert persisted["terminal_closeout"]["signal_name"] == "SIGTERM"
    assert (
        persisted["public_terminal_fallback"]["trigger"]
        == "supervisor_termination_signal"
    )


def test_remote_command_failure_subtype_uses_public_allowlist() -> None:
    supervisor = _load_supervisor_module()

    assert supervisor._remote_command_failure_subtype(
        "RuntimeError: loopx_runner_source_git_head_mismatch"
    ) == "runner_source_git_head_mismatch"
    assert supervisor._remote_command_failure_subtype(
        "runner: error: unrecognized arguments: --private-value"
    ) == "cli_argument_incompatible"
    assert supervisor._remote_command_failure_subtype(
        "usage: runner [--mode MODE]\nrunner: error: "
        "argument --mode: invalid choice"
    ) == "cli_argument_error"
    assert supervisor._remote_command_failure_subtype(
        "python3: can't open file 'opaque-runner.py': "
        "[Errno 2] No such file or directory"
    ) == "remote_entrypoint_missing"
    assert supervisor._remote_command_failure_subtype(
        "SkillsBenchSetupPreflightBlocked: private setup detail"
    ) == "setup_preflight_blocked"
    assert supervisor._remote_command_failure_subtype(
        "secret-host.example failed with private-token"
    ) == "unclassified"


def test_supervisor_projects_only_allowlisted_remote_failure_subtype(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    fake_ssh = tmp_path / "fake-ssh"
    public_output = tmp_path / "public" / "supervisor.public.json"
    _write_fake_ssh(fake_ssh)
    args = supervisor.parse_args(
        [
            "--ssh-bin",
            str(fake_ssh),
            "--ssh-destination",
            "runner.example",
            "--remote-command",
            "fail-arguments",
            "--public-output-path",
            str(public_output),
            "--probe-interval-sec",
            "0.01",
            "--probe-timeout-sec",
            "5",
            "--tunnel-ready-timeout-sec",
            "5",
            "--tunnel-health-interval-sec",
            "0",
            "--run-timeout-sec",
            "5",
        ]
    )

    returncode, payload = supervisor.run_supervisor(args)
    persisted = json.loads(public_output.read_text(encoding="utf-8"))
    public_text = json.dumps(persisted, sort_keys=True)

    assert returncode == 2
    assert payload["first_blocker"] == "remote_command_exit_nonzero"
    assert payload["remote_command_failure_subtype"] == (
        "cli_argument_incompatible"
    )
    assert persisted == payload
    assert "--private-value" not in public_text
    assert "usage: runner" not in public_text
    assert persisted["raw_remote_output_recorded"] is False


def test_supervisor_codex_bridge_preflight_is_task_free_and_public_safe(
    tmp_path: Path,
) -> None:
    supervisor = _load_supervisor_module()
    fake_ssh = tmp_path / "fake-ssh"
    fake_codex = tmp_path / "fake-codex"
    public_output = tmp_path / "public" / "supervisor.public.json"
    _write_fake_ssh(fake_ssh)
    _write_fake_codex(fake_codex)
    private_socket = "/tmp/private-codex-socket"
    private_client = "/tmp/private-codex-client"
    private_prompt_bridge = "private-prompt-bridge sentinel-bridge"
    args = supervisor.parse_args(
        [
            "--ssh-bin",
            str(fake_ssh),
            "--ssh-destination",
            "runner.example",
            "--codex-bridge",
            "--codex-bin",
            str(fake_codex),
            "--codex-remote-socket",
            private_socket,
            "--codex-remote-client-path",
            private_client,
            "--codex-prompt-bridge-command",
            private_prompt_bridge,
            "--codex-participant-sandbox",
            "workspace-write",
            "--preflight-only",
            "--public-output-path",
            str(public_output),
            "--probe-interval-sec",
            "0.01",
            "--probe-timeout-sec",
            "5",
            "--tunnel-ready-timeout-sec",
            "5",
            "--codex-socket-ready-timeout-sec",
            "1",
            "--codex-participant-probe-timeout-sec",
            "1",
        ]
    )

    returncode, payload = supervisor.run_supervisor(args)
    persisted = json.loads(public_output.read_text(encoding="utf-8"))
    public_text = json.dumps(persisted, sort_keys=True)

    assert returncode == 0
    assert payload["ok"] is True
    assert persisted == payload
    assert persisted["remote_command_requested"] is False
    assert persisted["codex_bridge"]["enabled"] is True
    assert persisted["codex_bridge"]["server_started"] is True
    assert persisted["codex_bridge"]["local_socket_ready"] is True
    assert persisted["codex_bridge"]["remote_socket_ready"] is True
    assert persisted["codex_bridge"]["remote_client_materialized"] is True
    assert persisted["codex_bridge"]["participant_probe_passed"] is True
    assert persisted["codex_bridge"]["participant_probe"]["sandbox"] == (
        "workspace-write"
    )
    assert persisted["codex_bridge"]["participant_probe"]["raw_output_recorded"] is (
        False
    )
    assert private_socket not in public_text
    assert private_client not in public_text
    assert private_prompt_bridge not in public_text
    assert "runner.example" not in public_text
    assert "sentinel-bridge" not in public_text
