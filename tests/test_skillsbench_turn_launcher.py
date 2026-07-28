from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "skillsbench-launch-goal-xhigh.sh"


def _dry_run_value(output: str, key: str) -> str:
    prefix = f"{key}="
    return next(
        line.removeprefix(prefix)
        for line in output.splitlines()
        if line.startswith(prefix)
    )


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SKILLSBENCH_RUNNER_PROFILE", None)
    env.pop("SKILLSBENCH_LOCAL_CODEX_PROXY_COMMAND", None)
    env.pop("SKILLSBENCH_REMOTE_CODEX_PROXY_PORT", None)
    env.update(
        {
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "SKILLSBENCH_SSH_DESTINATION": "example.invalid",
            "SKILLSBENCH_REMOTE_ROOT": "/remote/loopx",
            "SKILLSBENCH_ROOT": "/remote/skillsbench",
            "SKILLSBENCH_EXPECTED_LOOPX_GIT_HEAD": "abc1234",
            "SKILLSBENCH_DOCKER_PROXY_HOST": "host.docker.internal",
            "SKILLSBENCH_DOCKER_API_VERSION": "1.43",
            "SKILLSBENCH_RUN_STAMP": "20260716T000000CST",
        }
    )
    return env


def test_turn_launcher_wires_private_commands_without_echoing_values(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    private_values = {
        "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_PROBE_COMMAND": (
            "private-probe-command sentinel-probe"
        ),
        "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_SOLVER_COMMAND": (
            "private-solver-command sentinel-solver"
        ),
        "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_AGENT_COMMAND": (
            "private-agent-command sentinel-agent"
        ),
        "SKILLSBENCH_LOOPX_TURN_VALIDATION_COMMAND": (
            "private-validator-command sentinel-validator"
        ),
        "SKILLSBENCH_LOCAL_CODEX_PROXY_COMMAND": (
            "private-local-proxy-command sentinel-local-proxy"
        ),
    }
    env.update(private_values)
    env.update(
        {
            "SKILLSBENCH_ROUTE": "loopx-turn-agent-cli",
            "SKILLSBENCH_LOOPX_TURN_MAX_TURNS": "4",
            "SKILLSBENCH_LOOPX_TURN_PROGRESS_EXIT_CODE": "10",
            "SKILLSBENCH_LOOPX_TURN_TERMINAL_POLICY": "fixed-n",
            "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_AGENT_COMMAND_INSTRUMENTED": (
                "1"
            ),
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "turn-wiring"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    output = proc.stdout
    assert "remote_command_file_bridge_probe_command_configured=1" in output
    assert "remote_command_file_bridge_solver_command_configured=1" in output
    assert "remote_command_file_bridge_agent_command_configured=1" in output
    assert "remote_command_file_bridge_agent_command_instrumented=1" in output
    assert "local_codex_proxy_command_configured=1" in output
    assert "loopx_turn_validation_command_configured=1" in output
    assert "loopx_turn_max_turns=4" in output
    assert "loopx_turn_progress_exit_code=10" in output
    assert "loopx_turn_terminal_policy=fixed-n" in output
    assert "docker_proxy_host_recorded=false" in output
    assert "docker_proxy_host=" not in output
    assert env["SKILLSBENCH_DOCKER_PROXY_HOST"] not in output
    assert "private_runner_command_values_redacted=true" in output
    assert "runner_connectivity_preflight=required" in output
    assert "exact_host_codex_sandbox_preflight=required" in output
    for arg_name in (
        "--remote-command-file-bridge-probe-command",
        "--remote-command-file-bridge-solver-command",
        "--remote-command-file-bridge-agent-command",
        "--remote-command-file-bridge-agent-command-instrumented",
        "--local-forward-managed-command",
        "--loopx-turn-validation-command",
        "--loopx-turn-max-turns",
        "--loopx-turn-progress-exit-code",
        "--loopx-turn-terminal-policy",
    ):
        assert arg_name in output
    for private_value in private_values.values():
        assert private_value not in output
    assert "sentinel-" not in output


def test_launcher_dry_run_does_not_require_reachable_local_proxy(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_PROXY_HOST": "127.0.0.1",
            "SKILLSBENCH_LOCAL_CODEX_PROXY_PORT": "1",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "proxy-contract"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "skillsbench_local_proxy_endpoint_unreachable" not in proc.stderr
    assert "docker_proxy_host_recorded=false" in proc.stdout
    assert "proxy_port_coherence_guard=enforced" in proc.stdout
    remote_port = int(_dry_run_value(proc.stdout, "remote_proxy_port"))
    assert 20000 <= remote_port <= 59999
    assert "remote_proxy_port_mode=run_scoped" in proc.stdout
    for expected_arg in (
        f"--remote-forward 127.0.0.1:{remote_port}:127.0.0.1:1",
        f"--codex-reverse-proxy-port {remote_port}",
        f"--benchmark-egress-proxy-port {remote_port}",
        f"--container-forwarder-port {remote_port}",
    ):
        assert expected_arg in proc.stdout


def test_launcher_scopes_default_remote_proxy_port_to_run_identity(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)

    def launch(stamp: str) -> subprocess.CompletedProcess[str]:
        run_env = env | {"SKILLSBENCH_RUN_STAMP": stamp}
        return subprocess.run(
            [str(LAUNCHER), "--dry-run", "public-smoke-case", "port-ownership"],
            cwd=REPO_ROOT,
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

    first = launch("20260716T000000CST")
    repeated = launch("20260716T000000CST")
    second = launch("20260716T000001CST")

    first_port = _dry_run_value(first.stdout, "remote_proxy_port")
    assert _dry_run_value(repeated.stdout, "remote_proxy_port") == first_port
    assert _dry_run_value(second.stdout, "remote_proxy_port") != first_port
    assert "remote_proxy_port_mode=run_scoped" in first.stdout


def test_launcher_preserves_explicit_remote_proxy_port(tmp_path: Path) -> None:
    env = _base_env(tmp_path)

    proc = subprocess.run(
        [
            str(LAUNCHER),
            "--dry-run",
            "public-smoke-case",
            "port-ownership",
            "18181",
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "remote_proxy_port=18181" in proc.stdout
    assert "remote_proxy_port_mode=explicit" in proc.stdout
    assert "--remote-forward 127.0.0.1:18181:127.0.0.1:18180" in proc.stdout


def test_launcher_fails_before_batch_when_exact_host_sandbox_probe_fails(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_count = tmp_path / "ssh-call-count"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-G" ]; then exit 0; fi\n'
        f"count_file={call_count!s}\n"
        'count=0\n'
        'if [ -f "$count_file" ]; then count=$(cat "$count_file"); fi\n'
        'count=$((count + 1))\n'
        'printf "%s" "$count" > "$count_file"\n'
        'if [ "$count" -le 2 ]; then exit 0; fi\n'
        'exit 1\n',
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    proc = subprocess.run(
        [str(LAUNCHER), "public-smoke-case", "exact-host-preflight"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 3, proc
    payload = json.loads(proc.stderr)
    assert payload == {
        "error": "skillsbench_exact_host_codex_sandbox_preflight_failed",
        "failure_category": "transport_or_unknown",
        "ok": False,
        "raw_output_recorded": False,
        "remote_codex_bin_mode": "path_lookup",
        "remote_path_recorded": False,
        "sandbox_mode": "workspace-write",
        "schema_version": "skillsbench_exact_host_codex_sandbox_preflight_v0",
        "ssh_destination_recorded": False,
        "timeout_seconds": 30,
    }
    assert call_count.read_text(encoding="utf-8") == "3"
    assert "pid=" not in proc.stdout


def test_launcher_types_exact_host_sandbox_probe_timeout(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_count = tmp_path / "ssh-call-count"
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-G" ]; then exit 0; fi\n'
        f"count_file={call_count!s}\n"
        'count=0\n'
        'if [ -f "$count_file" ]; then count=$(cat "$count_file"); fi\n'
        'count=$((count + 1))\n'
        'printf "%s" "$count" > "$count_file"\n'
        'if [ "$count" -le 2 ]; then exit 0; fi\n'
        'exit 124\n',
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["SKILLSBENCH_EXACT_HOST_CODEX_SANDBOX_PREFLIGHT_TIMEOUT_SEC"] = "45"

    proc = subprocess.run(
        [str(LAUNCHER), "public-smoke-case", "exact-host-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 3, proc
    payload = json.loads(proc.stderr)
    assert payload["failure_category"] == "timeout"
    assert payload["timeout_seconds"] == 45
    assert payload["raw_output_recorded"] is False
    assert payload["remote_path_recorded"] is False
    assert payload["ssh_destination_recorded"] is False
    assert call_count.read_text(encoding="utf-8") == "3"
    assert "pid=" not in proc.stdout


def test_launcher_rejects_invalid_exact_host_sandbox_probe_timeout(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_EXACT_HOST_CODEX_SANDBOX_PREFLIGHT_TIMEOUT_SEC"] = "0"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "invalid-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_EXACT_HOST_CODEX_SANDBOX_PREFLIGHT_TIMEOUT_SEC "
        "must be a positive integer"
    ) in proc.stderr


def test_launcher_fails_before_supervisor_when_runner_connectivity_is_not_ready(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_SSH_OPTIONS"] = "GSSAPIAuthentication=yes"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_count = tmp_path / "ssh-call-count"
    fake_ssh = fake_bin / "ssh"
    fake_klist = fake_bin / "klist"
    fake_ssh.write_text(
        "#!/bin/sh\n"
        f"printf x >> {call_count!s}\n"
        "exit 255\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o755)
    fake_klist.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_klist.chmod(0o755)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

    proc = subprocess.run(
        [str(LAUNCHER), "public-smoke-case", "connectivity-preflight"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 3, proc
    assert json.loads(proc.stderr) == {
        "benchmark_job_launched": False,
        "gssapi_configured": True,
        "local_gssapi_ticket_state": "present",
        "ok": True,
        "profile_values_recorded": False,
        "raw_output_recorded": False,
        "reachable": False,
        "readiness_state": "remote_task_free_acceptance_failed",
        "remote_task_free_acceptance": False,
        "result": "transport_unavailable",
        "schema_version": "skillsbench_runner_connectivity_probe_v0",
        "task_free_connection_attempt_completed": True,
        "task_material_read": False,
    }
    assert call_count.read_text(encoding="utf-8") == "x"
    assert "pid=" not in proc.stdout


def test_launcher_split_control_is_opt_in_and_redacts_provider_values(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    private_local_codex = "/private/local/codex-sentinel"
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_LOCAL_CODEX_BIN": private_local_codex,
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "split-control"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    output = proc.stdout
    assert "local_codex_split_control=1" in output
    assert "local_codex_provider=reverse_channel" in output
    assert "local_codex_exec_timeout_sec=runner-default" in output
    assert "host_local_acp_codex_exec_preflight_attempts=3" in output
    assert "outer_timeout_sec=runner-default" in output
    assert "remote_codex_bin_mode=split_control_client" in output
    assert (
        "exact_host_codex_sandbox_preflight=split_control_not_applicable"
        in output
    )
    assert "private_runner_command_values_redacted=true" in output
    for arg_name in (
        "--codex-bridge",
        "--codex-bin",
        "--codex-remote-socket",
        "--codex-remote-client-path",
        "--codex-prompt-bridge-command",
        "--codex-participant-sandbox",
        "--local-codex-provider",
        "--host-local-acp-codex-exec-preflight",
        "--host-local-acp-codex-exec-preflight-attempts",
    ):
        assert arg_name in output
    assert private_local_codex not in output
    assert "codex_bridge_client" not in output
    assert "loopx-codex-" not in output
    assert "example.invalid" not in output


def test_launcher_wires_explicit_host_local_preflight_attempts(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_HOST_LOCAL_ACP_CODEX_EXEC_PREFLIGHT_ATTEMPTS": "2",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "preflight-attempts"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "host_local_acp_codex_exec_preflight_attempts=2" in proc.stdout
    assert "--host-local-acp-codex-exec-preflight-attempts" in proc.stdout


def test_launcher_rejects_invalid_host_local_preflight_attempts(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_HOST_LOCAL_ACP_CODEX_EXEC_PREFLIGHT_ATTEMPTS": "0",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "preflight-attempts"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_HOST_LOCAL_ACP_CODEX_EXEC_PREFLIGHT_ATTEMPTS must be "
        "a positive integer"
    ) in proc.stderr


def test_launcher_wires_explicit_local_codex_exec_timeout(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_LOCAL_CODEX_EXEC_TIMEOUT_SEC": "14400",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "exec-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "local_codex_exec_timeout_sec=14400" in proc.stdout
    assert "--local-codex-exec-timeout-sec" in proc.stdout


def test_launcher_wires_explicit_outer_timeout(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_OUTER_TIMEOUT_SEC": "21600",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "outer-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "outer_timeout_sec=21600" in proc.stdout
    assert "--outer-timeout-sec" in proc.stdout


def test_launcher_rejects_invalid_local_codex_exec_timeout(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_LOCAL_CODEX_EXEC_TIMEOUT_SEC"] = "0"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "exec-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_LOCAL_CODEX_EXEC_TIMEOUT_SEC must be a positive integer"
        in proc.stderr
    )
    assert "supervisor_command=" not in proc.stdout


def test_launcher_rejects_invalid_outer_timeout(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_OUTER_TIMEOUT_SEC"] = "0"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "outer-timeout"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "SKILLSBENCH_OUTER_TIMEOUT_SEC must be a positive integer" in proc.stderr
    assert "supervisor_command=" not in proc.stdout


def test_launcher_split_control_requires_workspace_write(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env.update(
        {
            "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL": "1",
            "SKILLSBENCH_LOCAL_CODEX_SANDBOX": "danger-full-access",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "split-control"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_LOCAL_CODEX_SPLIT_CONTROL requires "
        "SKILLSBENCH_LOCAL_CODEX_SANDBOX=workspace-write"
    ) in proc.stderr
    assert "supervisor_command=" not in proc.stdout


def test_turn_launcher_accepts_stability_policy(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    validator = "private-validator-command sentinel-validator"
    env.update(
        {
            "SKILLSBENCH_ROUTE": "loopx-turn-agent-cli",
            "SKILLSBENCH_LOOPX_TURN_VALIDATION_COMMAND": validator,
            "SKILLSBENCH_LOOPX_TURN_MAX_TURNS": "4",
            "SKILLSBENCH_LOOPX_TURN_TERMINAL_POLICY": "stability",
        }
    )

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "stability-wiring"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "loopx_turn_max_turns=4" in proc.stdout
    assert "loopx_turn_terminal_policy=stability" in proc.stdout
    assert validator not in proc.stdout


def test_instrumented_agent_bridge_requires_an_explicit_agent_command(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_AGENT_COMMAND_INSTRUMENTED"] = "1"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "turn-wiring"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_AGENT_COMMAND_INSTRUMENTED requires "
        "SKILLSBENCH_REMOTE_COMMAND_FILE_BRIDGE_AGENT_COMMAND"
    ) in proc.stderr


def test_turn_launcher_requires_an_independent_validator(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_ROUTE"] = "loopx-turn-agent-cli"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "turn-wiring"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_LOOPX_TURN_VALIDATION_COMMAND is required for "
        "loopx-turn-agent-cli"
    ) in proc.stderr


def test_launcher_allows_explicit_direct_benchmark_egress(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_BENCHMARK_EGRESS_PROXY_MODE"] = "off"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "direct-egress"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "benchmark_egress_proxy_mode=off" in proc.stdout
    assert "--benchmark-egress-proxy-mode off" in proc.stdout


def test_launcher_rejects_invalid_benchmark_egress_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_BENCHMARK_EGRESS_PROXY_MODE"] = "sometimes"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "direct-egress"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_BENCHMARK_EGRESS_PROXY_MODE must be require, auto, or off"
        in proc.stderr
    )


def test_launcher_wires_bounded_primary_pip_index_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_PIP_INDEX_MODE"] = "primary"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "primary-pip"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "docker_pip_index_mode=primary" in proc.stdout
    assert "--docker-pip-index-mode primary" in proc.stdout


def test_launcher_wires_bounded_primary_apt_source_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_APT_SOURCE_MODE"] = "primary"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "primary-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "docker_apt_source_mode=primary" in proc.stdout
    assert "--docker-apt-source-mode primary" in proc.stdout


def test_launcher_wires_bounded_proxy_compatible_apt_transport(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_APT_TRANSPORT_MODE"] = "proxy-compatible"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "proxy-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "docker_apt_transport_mode=proxy-compatible" in proc.stdout
    assert "--docker-apt-transport-mode proxy-compatible" in proc.stdout


def test_launcher_defaults_to_proxy_compatible_primary_sources_with_required_proxy(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "default-proxy-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "benchmark_egress_proxy_mode=require" in proc.stdout
    assert "docker_apt_source_mode=primary" in proc.stdout
    assert "docker_apt_transport_mode=proxy-compatible" in proc.stdout
    assert "docker_pip_index_mode=primary" in proc.stdout
    assert "--docker-apt-source-mode primary" in proc.stdout
    assert "--docker-apt-transport-mode proxy-compatible" in proc.stdout
    assert "--docker-pip-index-mode primary" in proc.stdout


def test_launcher_defaults_to_mirror_sources_and_standard_apt_when_proxy_is_off(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_BENCHMARK_EGRESS_PROXY_MODE"] = "off"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "no-proxy-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "benchmark_egress_proxy_mode=off" in proc.stdout
    assert "docker_apt_source_mode=mirror" in proc.stdout
    assert "docker_apt_transport_mode=default" in proc.stdout
    assert "docker_pip_index_mode=mirror" in proc.stdout
    assert "--docker-apt-source-mode mirror" in proc.stdout
    assert "--docker-apt-transport-mode default" in proc.stdout
    assert "--docker-pip-index-mode mirror" in proc.stdout


def test_launcher_preserves_explicit_package_source_overrides_with_required_proxy(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_APT_SOURCE_MODE"] = "mirror"
    env["SKILLSBENCH_DOCKER_APT_TRANSPORT_MODE"] = "default"
    env["SKILLSBENCH_DOCKER_PIP_INDEX_MODE"] = "mirror"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "explicit-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "benchmark_egress_proxy_mode=require" in proc.stdout
    assert "docker_apt_source_mode=mirror" in proc.stdout
    assert "docker_apt_transport_mode=default" in proc.stdout
    assert "docker_pip_index_mode=mirror" in proc.stdout
    assert "--docker-apt-source-mode mirror" in proc.stdout
    assert "--docker-apt-transport-mode default" in proc.stdout
    assert "--docker-pip-index-mode mirror" in proc.stdout


def test_launcher_rejects_unbounded_apt_transport_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_APT_TRANSPORT_MODE"] = "private-mode"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "invalid-transport"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_DOCKER_APT_TRANSPORT_MODE must be default or "
        "proxy-compatible"
    ) in proc.stderr


def test_launcher_rejects_unbounded_apt_source_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_APT_SOURCE_MODE"] = "private-url"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "invalid-apt"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "SKILLSBENCH_DOCKER_APT_SOURCE_MODE must be mirror or primary" in (
        proc.stderr
    )


def test_launcher_rejects_unbounded_pip_index_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_PIP_INDEX_MODE"] = "private-url"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "invalid-pip"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert "SKILLSBENCH_DOCKER_PIP_INDEX_MODE must be mirror or primary" in (
        proc.stderr
    )


def test_launcher_wires_bounded_no_isolation_pip_build_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_PIP_BUILD_MODE"] = "no-isolation"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "pip-build-mode"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "docker_pip_build_mode=no-isolation" in proc.stdout
    assert "--docker-pip-build-mode no-isolation" in proc.stdout


def test_launcher_rejects_unbounded_pip_build_mode(tmp_path: Path) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_DOCKER_PIP_BUILD_MODE"] = "arbitrary-flags"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "invalid-pip-build"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert proc.returncode == 2
    assert (
        "SKILLSBENCH_DOCKER_PIP_BUILD_MODE must be isolated or no-isolation"
        in proc.stderr
    )


def test_setup_only_launcher_enables_incremental_public_artifact_sync(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_SETUP_ONLY_PUBLIC_PREFLIGHT"] = "1"
    env["SKILLSBENCH_APPEND_HISTORY"] = "1"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "setup-progress"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "public_artifact_sync_interval_sec=30" in proc.stdout
    assert "exact_host_codex_sandbox_preflight=not_required" in proc.stdout
    assert "--public-artifact-sync-interval-sec 30" in proc.stdout
    assert "--setup-only-public-preflight" in proc.stdout
    assert "--append-history" not in proc.stdout


def test_formal_launcher_enables_incremental_public_artifact_sync(
    tmp_path: Path,
) -> None:
    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "live-progress"],
        cwd=REPO_ROOT,
        env=_base_env(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "setup_only_public_preflight=0" in proc.stdout
    assert "public_artifact_sync_interval_sec=30" in proc.stdout
    assert "--public-artifact-sync-interval-sec 30" in proc.stdout


def test_formal_launcher_can_disable_incremental_public_artifact_sync(
    tmp_path: Path,
) -> None:
    env = _base_env(tmp_path)
    env["SKILLSBENCH_PUBLIC_ARTIFACT_SYNC_INTERVAL_SEC"] = "0"

    proc = subprocess.run(
        [str(LAUNCHER), "--dry-run", "public-smoke-case", "no-live-progress"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True,
    )

    assert "public_artifact_sync_interval_sec=0" in proc.stdout
    assert "--public-artifact-sync-interval-sec 0" in proc.stdout
