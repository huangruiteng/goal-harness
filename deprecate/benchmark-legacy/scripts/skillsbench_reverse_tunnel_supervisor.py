#!/usr/bin/env python3
"""Hold a reverse-tunnel session while running a remote SkillsBench command.

This helper is intentionally local-side: the remote benchmark host cannot
create an ``ssh -R`` tunnel back to itself. The launcher owns the tunnel process,
probes the remote loopback proxy through SSH, runs one remote command, and then
cleans the tunnel up. Public output records only lifecycle status and compact
counts. It is created when the supervisor starts, refreshed atomically while
the remote command is running, and finalized on every exit path; raw SSH
destinations, remote commands, proxy URLs, and command output are private.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.benchmark_core.remote_closeout import (  # noqa: E402
    build_remote_benchmark_closeout_contract,
    closeout_remote_benchmark_batch,
)
from loopx.benchmark_core.lifecycle import (  # noqa: E402
    build_benchmark_live_worker_phase,
    compact_benchmark_live_worker_phase,
)


SCHEMA_VERSION = "skillsbench_reverse_tunnel_supervisor_v0"
PUBLIC_LIVENESS_SCHEMA_VERSION = "skillsbench_supervisor_public_liveness_v0"
ACTIVE_PHASE_SCHEMA_VERSION = "skillsbench_supervisor_active_phase_v0"
TERMINAL_CLOSEOUT_SCHEMA_VERSION = "skillsbench_supervisor_terminal_closeout_v0"
OWNER_CONTROL_SCHEMA_VERSION = "skillsbench_supervisor_owner_control_v0"
OWNER_STOP_REQUEST_SCHEMA_VERSION = "skillsbench_supervisor_owner_stop_request_v0"
OWNER_STOP_RECEIPT_SCHEMA_VERSION = "skillsbench_supervisor_owner_stop_receipt_v0"
OWNER_STOP_REQUEST_BASENAME = "supervisor.stop.request.json"
PUBLIC_LIVENESS_INTERVAL_SEC = 30.0
DEFAULT_REMOTE_FORWARD = "127.0.0.1:18180:127.0.0.1:18180"
DEFAULT_TEST_HOST = "chatgpt.com"
DEFAULT_TEST_PORT = 443
BRIDGE_HELPER = (
    Path(__file__).resolve().with_name("skillsbench_reverse_channel_bridge.py")
)
PROXY_PORT_FIELDS = (
    "codex_reverse_proxy_port",
    "benchmark_egress_proxy_port",
    "container_forwarder_port",
)


class _SupervisorTerminationSignal(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(signal.Signals(signum).name)


def _valid_owner_control_id(value: str) -> bool:
    return bool(
        value
        and len(value) <= 240
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _owner_stop_request_path(public_output_path: str | None) -> Path | None:
    if not public_output_path:
        return None
    return Path(public_output_path).expanduser().with_name(
        OWNER_STOP_REQUEST_BASENAME
    )


def _owner_control_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    control_id = str(getattr(args, "owner_control_id", "") or "")
    enabled = bool(control_id and args.public_output_path)
    return {
        "schema_version": OWNER_CONTROL_SCHEMA_VERSION,
        "enabled": enabled,
        "state": "listening" if enabled else "disabled",
        "control_id": control_id if enabled else None,
        "request_basename": OWNER_STOP_REQUEST_BASENAME if enabled else None,
        "request_poll_count": 0,
        "accepted_request_count": 0,
        "invalid_request_count": 0,
        "raw_request_recorded": False,
        "raw_path_recorded": False,
        "pid_read": False,
        "process_table_read": False,
    }


def _prepare_owner_control(
    args: argparse.Namespace,
    contract: dict[str, Any],
) -> None:
    if contract.get("enabled") is not True:
        return
    request_path = _owner_stop_request_path(args.public_output_path)
    if request_path is None:
        return
    try:
        request_path.unlink(missing_ok=True)
    except OSError:
        contract["state"] = "request_cleanup_failed"
        contract["request_cleanup_error"] = True


def _poll_owner_stop_request(
    args: argparse.Namespace,
    contract: dict[str, Any],
) -> bool:
    if contract.get("enabled") is not True:
        return False
    request_path = _owner_stop_request_path(args.public_output_path)
    if request_path is None:
        return False
    contract["request_poll_count"] = int(contract["request_poll_count"]) + 1
    if not request_path.exists():
        return False

    request: Any = None
    try:
        if request_path.is_symlink() or request_path.stat().st_size > 4096:
            raise ValueError("unsafe owner stop request")
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        contract["state"] = "invalid_request_ignored"
        contract["invalid_request_count"] = int(contract["invalid_request_count"]) + 1
        try:
            request_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    valid = (
        isinstance(request, Mapping)
        and request.get("schema_version") == OWNER_STOP_REQUEST_SCHEMA_VERSION
        and request.get("action") == "terminate"
        and request.get("control_id") == contract.get("control_id")
    )
    if not valid:
        contract["state"] = "invalid_request_ignored"
        contract["invalid_request_count"] = int(contract["invalid_request_count"]) + 1
        try:
            request_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    contract["state"] = "accepted"
    contract["accepted_request_count"] = int(contract["accepted_request_count"]) + 1
    contract["accepted_action"] = "terminate"
    contract["accepted_at"] = _utc_timestamp(time.time())
    try:
        request_path.unlink(missing_ok=True)
    except OSError:
        contract["accepted_request_cleanup_error"] = True
    return True


def _host_kind(value: str) -> str:
    normalized = value.strip("[]").lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return "loopback"
    if normalized.startswith("10.") or normalized.startswith("192.168."):
        return "private"
    if normalized.startswith("172."):
        try:
            second_octet = int(normalized.split(".", 2)[1])
        except (IndexError, ValueError):
            second_octet = -1
        if 16 <= second_octet <= 31:
            return "private"
    return "public_or_unknown"


def _parse_remote_forward(value: str) -> dict[str, Any]:
    parts = value.split(":")
    if len(parts) != 4:
        raise ValueError(
            "--remote-forward must use host:port:host:port form, "
            "for example 127.0.0.1:18180:127.0.0.1:18180"
        )
    remote_host, remote_port, local_host, local_port = parts
    return {
        "remote_host": remote_host,
        "remote_port": int(remote_port),
        "local_host": local_host,
        "local_port": int(local_port),
    }


def _forward_public_contract(remote_forward: str) -> dict[str, Any]:
    parsed = _parse_remote_forward(remote_forward)
    return {
        "remote_host_kind": _host_kind(parsed["remote_host"]),
        "remote_port": parsed["remote_port"],
        "local_host_kind": _host_kind(parsed["local_host"]),
        "local_port": parsed["local_port"],
        "raw_forward_recorded": False,
    }


def _proxy_port_coherence_public_contract(
    args: argparse.Namespace,
) -> dict[str, Any]:
    declared = {
        field: getattr(args, field, None)
        for field in PROXY_PORT_FIELDS
        if getattr(args, field, None) is not None
    }
    contract: dict[str, Any] = {
        "schema_version": "skillsbench_proxy_port_coherence_v0",
        "state": "not_requested",
        "guard_enforced": False,
        "declared_surface_count": len(declared),
        "expected_surface_count": len(PROXY_PORT_FIELDS),
        "raw_command_read": False,
        "raw_command_recorded": False,
    }
    if not declared:
        return contract
    if len(declared) != len(PROXY_PORT_FIELDS):
        missing = [
            "--" + field.replace("_", "-")
            for field in PROXY_PORT_FIELDS
            if field not in declared
        ]
        raise ValueError(
            "proxy port coherence declarations are all-or-none; missing "
            + ", ".join(missing)
        )

    remote_port = _parse_remote_forward(args.remote_forward)["remote_port"]
    ports = [remote_port, *(int(declared[field]) for field in PROXY_PORT_FIELDS)]
    if any(port < 1 or port > 65535 for port in ports):
        raise ValueError("proxy port coherence declarations must be valid TCP ports")
    if len(set(ports)) != 1:
        raise ValueError(
            "--remote-forward remote port, --codex-reverse-proxy-port, "
            "--benchmark-egress-proxy-port, and --container-forwarder-port "
            "must match"
        )
    contract.update(
        {
            "state": "coherent",
            "guard_enforced": True,
            "coherent_port": remote_port,
        }
    )
    return contract


def _local_forward_dependency_public_contract(
    args: argparse.Namespace,
) -> dict[str, Any]:
    parsed = _parse_remote_forward(args.remote_forward)
    configured = bool(args.local_forward_managed_command)
    return {
        "schema_version": "skillsbench_local_forward_dependency_v0",
        "configured": configured,
        "state": "not_started" if configured else "not_requested",
        "local_host_kind": _host_kind(parsed["local_host"]),
        "local_port": parsed["local_port"],
        "managed_command_configured": configured,
        "managed_process_owned": False,
        "start_attempt_count": 0,
        "start_success_count": 0,
        "restart_attempt_limit": max(
            0,
            int(args.local_forward_restart_attempts),
        ),
        "restart_attempt_count": 0,
        "restart_success_count": 0,
        "failure_count": 0,
        "last_status": "not_started" if configured else "not_requested",
        "raw_command_recorded": False,
        "raw_output_recorded": False,
    }


def _local_forward_endpoint_ready(args: argparse.Namespace) -> bool:
    parsed = _parse_remote_forward(args.remote_forward)
    try:
        with socket.create_connection(
            (parsed["local_host"], parsed["local_port"]),
            timeout=max(0.05, float(args.local_forward_probe_timeout_sec)),
        ):
            return True
    except OSError:
        return False


def _wait_for_local_forward_endpoint(
    args: argparse.Namespace,
    proc: subprocess.Popen[Any],
) -> tuple[bool, str]:
    deadline = time.monotonic() + max(
        0.1,
        float(args.local_forward_ready_timeout_sec),
    )
    while time.monotonic() < deadline:
        if _local_forward_endpoint_ready(args):
            return True, "ready"
        if proc.poll() is not None:
            return False, "managed_process_exited_before_ready"
        time.sleep(0.05)
    return False, "endpoint_ready_timeout"


def _start_local_forward_dependency(
    args: argparse.Namespace,
    dependency: dict[str, Any],
    *,
    previous_proc: subprocess.Popen[Any] | None,
    restart: bool,
) -> tuple[subprocess.Popen[Any] | None, bool]:
    if previous_proc is not None:
        _stop_process_group(previous_proc, grace_sec=1.0)
    counter = "restart_attempt_count" if restart else "start_attempt_count"
    dependency[counter] = int(dependency[counter]) + 1
    dependency["state"] = "restarting" if restart else "starting"
    try:
        command = shlex.split(args.local_forward_managed_command)
    except ValueError:
        command = []
    if not command:
        dependency["failure_count"] = int(dependency["failure_count"]) + 1
        dependency["last_status"] = "managed_command_invalid"
        dependency["state"] = "failed"
        return None, False
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        dependency["failure_count"] = int(dependency["failure_count"]) + 1
        dependency["last_status"] = (
            f"managed_process_launch_failed_{type(exc).__name__[:40]}"
        )
        dependency["state"] = "failed"
        return None, False
    dependency["managed_process_owned"] = True
    ready, status = _wait_for_local_forward_endpoint(args, proc)
    dependency["last_status"] = status
    if not ready:
        dependency["failure_count"] = int(dependency["failure_count"]) + 1
        dependency["state"] = "failed"
        _stop_process_group(proc, grace_sec=1.0)
        return None, False
    success_counter = "restart_success_count" if restart else "start_success_count"
    dependency[success_counter] = int(dependency[success_counter]) + 1
    dependency["state"] = "recovered" if restart else "ready"
    return proc, True


def _ssh_base_command(args: argparse.Namespace) -> list[str]:
    command = [
        args.ssh_bin,
        "-x",
        "-T",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ControlPersist=no",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ServerAliveInterval={max(1, int(args.server_alive_interval_sec))}",
        "-o",
        f"ServerAliveCountMax={max(1, int(args.server_alive_count_max))}",
    ]
    for option in args.ssh_option or []:
        command.extend(["-o", option])
    return command


def _json_bridge_requested(args: argparse.Namespace) -> bool:
    return bool(
        args.json_bridge
        or args.json_bridge_command
        or args.json_remote_socket
        or args.json_remote_client_path
    )


def _codex_bridge_requested(args: argparse.Namespace) -> bool:
    return bool(
        args.codex_bridge
        or args.codex_remote_socket
        or args.codex_remote_client_path
        or args.codex_prompt_bridge_command
    )


def _codex_bridge_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enabled": _codex_bridge_requested(args),
        "server_started": False,
        "local_socket_ready": False,
        "reverse_socket_forward_requested": bool(args.codex_remote_socket),
        "remote_socket_ready": False,
        "remote_client_materialized": False,
        "participant_probe_requested": bool(args.codex_participant_sandbox),
        "participant_probe_passed": False,
        "participant_sandbox": args.codex_participant_sandbox or "not_requested",
        "raw_codex_command_recorded": False,
        "raw_prompt_bridge_command_recorded": False,
        "raw_socket_paths_recorded": False,
        "raw_client_path_recorded": False,
        "raw_probe_output_recorded": False,
        "remote_socket_cleanup": _remote_codex_socket_cleanup_public_contract(args),
    }


def _json_bridge_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "enabled": _json_bridge_requested(args),
        "server_started": False,
        "local_socket_ready": False,
        "reverse_socket_forward_requested": bool(args.json_remote_socket),
        "remote_socket_ready": False,
        "remote_client_materialized": False,
        "probe_policy": args.json_bridge_probe_policy,
        "sandbox_env_probe_deferred": (
            args.json_bridge_probe_policy == "sandbox-env-deferred"
        ),
        "sandbox_env_probe_defer_reason": (
            "benchflow_ai_addr_ai_port_available_only_inside_task_sandbox"
            if args.json_bridge_probe_policy == "sandbox-env-deferred"
            else ""
        ),
        "raw_bridge_command_recorded": False,
        "raw_socket_paths_recorded": False,
        "raw_client_path_recorded": False,
        "raw_probe_output_recorded": False,
        "remote_socket_cleanup": _remote_json_socket_cleanup_public_contract(args),
    }


def _resolved_json_local_socket(
    args: argparse.Namespace,
    runtime_dir: Path,
) -> Path:
    if args.json_local_socket:
        return Path(args.json_local_socket).expanduser()
    return runtime_dir / "json-bridge.sock"


def _resolved_codex_local_socket(
    args: argparse.Namespace,
    runtime_dir: Path,
) -> Path:
    if args.codex_local_socket:
        return Path(args.codex_local_socket).expanduser()
    return runtime_dir / "codex-bridge.sock"


def _cleanup_stale_local_forward(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requested": bool(args.cleanup_stale_local_forward),
        "matched_count": 0,
        "terminated_count": 0,
        "raw_process_args_recorded": False,
    }
    if not args.cleanup_stale_local_forward:
        return payload
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        payload["first_blocker"] = "stale_forward_scan_failed"
        return payload

    current_pid = os.getpid()
    candidates: list[int] = []
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        if (
            args.ssh_destination in command
            and args.remote_forward in command
            and " -R " in f" {command} "
        ):
            candidates.append(pid)
    payload["matched_count"] = len(candidates)
    for pid in candidates:
        try:
            os.kill(pid, signal.SIGTERM)
            payload["terminated_count"] = int(payload["terminated_count"]) + 1
        except (OSError, ProcessLookupError):
            continue
    if candidates:
        time.sleep(0.2)
    return payload


def _start_json_bridge_server(
    args: argparse.Namespace,
    *,
    socket_path: Path,
) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE_HELPER),
            "serve-json",
            "--socket",
            str(socket_path),
            "--bridge-command",
            args.json_bridge_command,
            "--timeout-sec",
            str(max(1.0, float(args.json_server_timeout_sec))),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


def _start_codex_bridge_server(
    args: argparse.Namespace,
    *,
    socket_path: Path,
) -> subprocess.Popen[Any]:
    command = [
        sys.executable,
        str(BRIDGE_HELPER),
        "serve-codex",
        "--socket",
        str(socket_path),
        "--codex-bin",
        args.codex_bin,
        "--timeout-sec",
        str(max(1.0, float(args.codex_server_timeout_sec))),
        "--first-action-timeout-sec",
        str(max(0.0, float(args.codex_first_action_timeout_sec))),
        "--bridge-idle-timeout-sec",
        str(max(0.0, float(args.codex_bridge_idle_timeout_sec))),
    ]
    if args.codex_prompt_bridge_command:
        command.extend(["--prompt-bridge-command", args.codex_prompt_bridge_command])
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


def _probe_local_socket(
    socket_path: Path, *, timeout_sec: float, interval_sec: float
) -> bool:
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    while time.monotonic() < deadline:
        if socket_path.exists():
            return True
        time.sleep(max(0.05, float(interval_sec)))
    return False


def _probe_local_json_socket(args: argparse.Namespace, socket_path: Path) -> bool:
    return _probe_local_socket(
        socket_path,
        timeout_sec=args.json_socket_ready_timeout_sec,
        interval_sec=args.probe_interval_sec,
    )


def _probe_local_codex_socket(args: argparse.Namespace, socket_path: Path) -> bool:
    return _probe_local_socket(
        socket_path,
        timeout_sec=args.codex_socket_ready_timeout_sec,
        interval_sec=args.probe_interval_sec,
    )


def _run_remote_shell_command(
    args: argparse.Namespace,
    command: str,
    *,
    timeout_sec: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_ssh_base_command(args), args.ssh_destination, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(1.0, float(timeout_sec)),
        check=False,
    )


def _probe_remote_json_socket(args: argparse.Namespace) -> bool:
    command = "test -S " + shlex.quote(args.json_remote_socket)
    try:
        proc = _run_remote_shell_command(
            args,
            command,
            timeout_sec=args.json_socket_ready_timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _probe_remote_codex_socket(args: argparse.Namespace) -> bool:
    command = "test -S " + shlex.quote(args.codex_remote_socket)
    try:
        proc = _run_remote_shell_command(
            args,
            command,
            timeout_sec=args.codex_socket_ready_timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _remote_codex_socket_cleanup_public_contract(
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "requested": bool(_codex_bridge_requested(args) and args.codex_remote_socket),
        "attempted": False,
        "ok": False,
        "raw_socket_paths_recorded": False,
        "raw_output_recorded": False,
    }


def _remote_json_socket_cleanup_public_contract(
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "requested": bool(_json_bridge_requested(args) and args.json_remote_socket),
        "attempted": False,
        "ok": False,
        "raw_socket_paths_recorded": False,
        "raw_output_recorded": False,
    }


def _cleanup_remote_socket(
    args: argparse.Namespace,
    *,
    socket_path: str,
    payload: dict[str, Any],
    blocker_prefix: str,
) -> dict[str, Any]:
    if not payload["requested"]:
        return payload
    payload["attempted"] = True
    command = "rm -f -- " + shlex.quote(socket_path)
    try:
        proc = _run_remote_shell_command(
            args,
            command,
            timeout_sec=args.remote_setup_timeout_sec,
        )
    except subprocess.TimeoutExpired:
        payload["first_blocker"] = f"{blocker_prefix}_timeout"
        return payload
    except OSError:
        payload["first_blocker"] = f"{blocker_prefix}_launch_failed"
        return payload
    payload["exit_code"] = proc.returncode
    payload["stdout_size_bucket"] = _size_bucket(proc.stdout or "")
    payload["stderr_size_bucket"] = _size_bucket(proc.stderr or "")
    payload["ok"] = proc.returncode == 0
    if proc.returncode != 0:
        payload["first_blocker"] = f"{blocker_prefix}_exit_nonzero"
    return payload


def _cleanup_remote_codex_socket(args: argparse.Namespace) -> dict[str, Any]:
    return _cleanup_remote_socket(
        args,
        socket_path=args.codex_remote_socket,
        payload=_remote_codex_socket_cleanup_public_contract(args),
        blocker_prefix="codex_bridge_remote_socket_cleanup",
    )


def _cleanup_remote_json_socket(args: argparse.Namespace) -> dict[str, Any]:
    return _cleanup_remote_socket(
        args,
        socket_path=args.json_remote_socket,
        payload=_remote_json_socket_cleanup_public_contract(args),
        blocker_prefix="json_bridge_remote_socket_cleanup",
    )


def _materialize_remote_bridge_client(
    args: argparse.Namespace,
    runtime_dir: Path,
    *,
    kind: str,
    remote_socket: str,
    remote_path: str,
) -> bool:
    local_client = runtime_dir / f"{kind}-bridge-client"
    try:
        subprocess.run(
            [
                sys.executable,
                str(BRIDGE_HELPER),
                "write-client",
                "--kind",
                kind,
                "--socket",
                remote_socket,
                "--output",
                str(local_client),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=max(1.0, float(args.remote_setup_timeout_sec)),
            check=True,
        )
        client_text = local_client.read_text(encoding="utf-8")
        remote_parent = os.path.dirname(remote_path) or "."
        remote_command = (
            "umask 077; mkdir -p "
            + shlex.quote(remote_parent)
            + "; cat > "
            + shlex.quote(remote_path)
            + "; chmod 700 "
            + shlex.quote(remote_path)
        )
        proc = subprocess.run(
            [*_ssh_base_command(args), args.ssh_destination, remote_command],
            input=client_text,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=max(1.0, float(args.remote_setup_timeout_sec)),
            check=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _materialize_remote_json_client(
    args: argparse.Namespace, runtime_dir: Path
) -> bool:
    return _materialize_remote_bridge_client(
        args,
        runtime_dir,
        kind="json",
        remote_socket=args.json_remote_socket,
        remote_path=args.json_remote_client_path,
    )


def _materialize_remote_codex_client(
    args: argparse.Namespace, runtime_dir: Path
) -> bool:
    return _materialize_remote_bridge_client(
        args,
        runtime_dir,
        kind="codex",
        remote_socket=args.codex_remote_socket,
        remote_path=args.codex_remote_client_path,
    )


def _probe_remote_codex_participant(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "requested": bool(args.codex_participant_sandbox),
        "passed": False,
        "sandbox": args.codex_participant_sandbox or "not_requested",
        "raw_output_recorded": False,
        "raw_command_recorded": False,
        "raw_paths_recorded": False,
        "credential_values_recorded": False,
    }
    if not payload["requested"]:
        return payload
    command = " ".join(
        [
            shlex.quote(args.codex_remote_client_path),
            "sandbox",
            "-c",
            shlex.quote(f'sandbox_mode="{args.codex_participant_sandbox}"'),
            "--",
            "true",
            ">/dev/null",
            "2>&1",
        ]
    )
    try:
        proc = _run_remote_shell_command(
            args,
            command,
            timeout_sec=args.codex_participant_probe_timeout_sec,
        )
    except subprocess.TimeoutExpired:
        payload["first_blocker"] = "codex_bridge_participant_probe_timeout"
        return payload
    except OSError:
        payload["first_blocker"] = "codex_bridge_participant_probe_launch_failed"
        return payload
    payload["exit_code"] = proc.returncode
    payload["passed"] = proc.returncode == 0
    if proc.returncode != 0:
        payload["first_blocker"] = "codex_bridge_participant_probe_exit_nonzero"
    return payload


def _render_remote_command(args: argparse.Namespace) -> str:
    command = args.remote_command
    if _codex_bridge_requested(args):
        command = command.replace(
            "{codex_bridge_client}",
            shlex.quote(args.codex_remote_client_path),
        )
    if _json_bridge_requested(args):
        command = command.replace(
            "{json_bridge_client}",
            shlex.quote(args.json_remote_client_path),
        )
    return command


def _remote_json_bridge_env_prefix(args: argparse.Namespace) -> str:
    if not _json_bridge_requested(args):
        return ""
    assignments = {
        "LOOPX_SKILLSBENCH_JSON_BRIDGE_CLIENT": args.json_remote_client_path,
        "LOOPX_REVERSE_JSON_TIMEOUT_SEC": str(int(args.json_server_timeout_sec)),
    }
    return " ".join(
        f"{name}={shlex.quote(value)}" for name, value in assignments.items()
    )


def _remote_command_with_bridge_env(args: argparse.Namespace) -> str:
    rendered = _render_remote_command(args)
    prefix = _remote_json_bridge_env_prefix(args)
    if not prefix:
        return rendered
    return prefix + " " + rendered


def _tunnel_command(
    args: argparse.Namespace,
    *,
    json_local_socket: Path | None = None,
    codex_local_socket: Path | None = None,
) -> list[str]:
    keepalive = max(1, int(args.keepalive_interval_sec))
    remote_keepalive = (
        f"while true; do sleep {keepalive}; "
        "echo loopx_reverse_tunnel_keepalive >&2; done"
    )
    command = [
        *_ssh_base_command(args),
        "-o",
        "ExitOnForwardFailure=yes",
    ]
    if _json_bridge_requested(args) and json_local_socket is not None:
        command.extend(
            [
                "-o",
                "StreamLocalBindUnlink=yes",
                "-R",
                f"{args.json_remote_socket}:{json_local_socket}",
            ]
        )
    if _codex_bridge_requested(args) and codex_local_socket is not None:
        command.extend(
            [
                "-o",
                "StreamLocalBindUnlink=yes",
                "-R",
                f"{args.codex_remote_socket}:{codex_local_socket}",
            ]
        )
    command.extend(
        [
            "-R",
            args.remote_forward,
            args.ssh_destination,
            remote_keepalive,
        ]
    )
    return command


def _probe_command(
    args: argparse.Namespace,
    *,
    timeout_sec: float | None = None,
) -> str:
    parsed = _parse_remote_forward(args.remote_forward)
    timeout = max(
        0.01,
        min(
            float(args.probe_timeout_sec),
            float(timeout_sec)
            if timeout_sec is not None
            else float(args.probe_timeout_sec),
        ),
    )
    code = (
        "# LOOPX_REVERSE_TUNNEL_PROBE\n"
        "import socket, sys\n"
        f"proxy_host = {parsed['remote_host']!r}\n"
        f"proxy_port = {parsed['remote_port']!r}\n"
        f"test_host = {args.test_host!r}\n"
        f"test_port = {int(args.test_port)!r}\n"
        f"timeout = {timeout!r}\n"
        "sock = socket.create_connection((proxy_host, proxy_port), timeout)\n"
        "sock.settimeout(timeout)\n"
        "request = (\n"
        "    f'CONNECT {test_host}:{test_port} HTTP/1.1\\r\\n'\n"
        "    f'Host: {test_host}:{test_port}\\r\\n'\n"
        "    'Proxy-Connection: close\\r\\n\\r\\n'\n"
        ")\n"
        "sock.sendall(request.encode('ascii'))\n"
        "response = sock.recv(256).decode('iso-8859-1', errors='replace')\n"
        "sock.close()\n"
        "print(response.splitlines()[0] if response.splitlines() else '')\n"
    )
    return "python3 -c " + shlex.quote(code)


def _run_remote_probe(
    args: argparse.Namespace,
    *,
    timeout_sec: float | None = None,
) -> tuple[bool, str]:
    probe_timeout = max(0.01, float(args.probe_timeout_sec))
    command_timeout = (
        max(0.01, float(timeout_sec))
        if timeout_sec is not None
        else probe_timeout + 5.0
    )
    command = [
        *_ssh_base_command(args),
        args.ssh_destination,
        _probe_command(args, timeout_sec=command_timeout),
    ]
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=command_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "probe_timeout"
    except OSError:
        return False, "probe_launch_failed"
    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if proc.returncode == 0 and " 200 " in f" {output} ":
        return True, "http_connect_ready"
    if " 407 " in f" {output} ":
        return False, "proxy_auth_required"
    if proc.returncode == 255:
        return False, "ssh_transport_unavailable"
    if proc.returncode != 0:
        return False, "probe_exit_nonzero"
    return False, "proxy_connect_rejected"


def _start_tunnel_process(
    args: argparse.Namespace,
    *,
    json_local_socket: Path | None = None,
    codex_local_socket: Path | None = None,
) -> subprocess.Popen[Any]:
    return subprocess.Popen(
        _tunnel_command(
            args,
            json_local_socket=json_local_socket,
            codex_local_socket=codex_local_socket,
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )


def _wait_for_tunnel_ready(
    args: argparse.Namespace,
    tunnel_proc: subprocess.Popen[Any],
    *,
    timeout_sec: float,
    remote_proc: subprocess.Popen[Any] | None = None,
    run_deadline: float | None = None,
) -> tuple[bool, str, int]:
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    status = "not_started"
    attempts = 0
    while time.monotonic() < deadline:
        if remote_proc is not None and remote_proc.poll() is not None:
            return False, "remote_command_completed", attempts
        if run_deadline is not None and time.monotonic() >= run_deadline:
            return False, "run_deadline_exceeded", attempts
        if tunnel_proc.poll() is not None:
            return False, "tunnel_process_exited", attempts
        now = time.monotonic()
        probe_budget = max(0.01, deadline - now)
        if run_deadline is not None:
            probe_budget = max(0.01, min(probe_budget, run_deadline - now))
        ready, status = _run_remote_probe(args, timeout_sec=probe_budget)
        attempts += 1
        if run_deadline is not None and time.monotonic() >= run_deadline:
            return False, "run_deadline_exceeded", attempts
        if remote_proc is not None and remote_proc.poll() is not None:
            return False, "remote_command_completed", attempts
        if tunnel_proc.poll() is not None:
            return False, "tunnel_process_exited", attempts
        if time.monotonic() >= deadline:
            return False, status, attempts
        if ready:
            return True, status, attempts
        time.sleep(max(0.1, float(args.probe_interval_sec)))
    return False, status, attempts


def _tunnel_liveness_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    interval_sec = max(0.0, float(args.tunnel_health_interval_sec))
    enabled = bool(interval_sec > 0 and args.remote_command)
    return {
        "schema_version": "skillsbench_reverse_tunnel_liveness_v0",
        "enabled": enabled,
        "state": "not_started" if enabled else "disabled",
        "health_interval_sec": interval_sec,
        "failure_threshold": max(1, int(args.tunnel_health_failure_threshold)),
        "reconnect_attempt_limit": max(0, int(args.tunnel_reconnect_attempts)),
        "health_probe_attempt_count": 0,
        "health_probe_success_count": 0,
        "health_probe_failure_count": 0,
        "health_probe_inconclusive_count": 0,
        "max_consecutive_failure_count": 0,
        "max_consecutive_inconclusive_count": 0,
        "reconnect_attempt_count": 0,
        "reconnect_success_count": 0,
        "reconnect_failure_count": 0,
        "last_probe_status": "not_started",
        "raw_probe_output_recorded": False,
    }


def _stop_process_group(proc: subprocess.Popen[Any], *, grace_sec: float = 5.0) -> str:
    if proc.poll() is not None:
        return "already_exited"
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already_exited"
    except OSError:
        try:
            proc.terminate()
        except OSError:
            pass
    deadline = time.monotonic() + max(0.0, grace_sec)
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        return "killed"
    return "terminated"


def _write_private_log(
    path: str | None,
    *,
    stdout_text: str,
    stderr_text: str,
) -> bool:
    if not path:
        return False
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        (f"# stdout\n{stdout_text}\n# stderr\n{stderr_text}\n"),
        encoding="utf-8",
    )
    return True


def _utc_timestamp(epoch_seconds: float) -> str:
    return (
        datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _write_public_checkpoint(
    path: str | None,
    payload: dict[str, Any],
    *,
    state: str,
    started_at: float,
    heartbeat_count: int,
    terminal: bool,
    observed_at: float | None = None,
) -> None:
    now = time.time() if observed_at is None else observed_at
    payload["duration_sec"] = round(max(0.0, now - started_at), 3)
    if terminal:
        active_phase = payload.get("active_phase")
        active_phase = active_phase if isinstance(active_phase, dict) else {}
        live_worker_phase = compact_benchmark_live_worker_phase(
            active_phase.get("benchmark_live_worker_phase")
        )
        phase_ready = live_worker_phase.get("phase_ready")
        if live_worker_phase and isinstance(phase_ready, dict):
            terminal_disposition = {
                "succeeded": "completed",
                "failed": "failed",
            }.get(state, "ended_unresolved")
            active_phase["benchmark_live_worker_phase"] = (
                build_benchmark_live_worker_phase(
                    runtime_preparing=phase_ready.get("runtime_preparing") is True,
                    worker_prepared=phase_ready.get("worker_prepared") is True,
                    worker_running=phase_ready.get("worker_running") is True,
                    agent_active=phase_ready.get("agent_active") is True,
                    terminal_disposition=terminal_disposition,
                )
            )
    payload["public_liveness"] = {
        "schema_version": PUBLIC_LIVENESS_SCHEMA_VERSION,
        "state": state,
        "terminal": terminal,
        "process_alive": not terminal,
        "heartbeat_count": max(1, int(heartbeat_count)),
        "update_interval_sec": PUBLIC_LIVENESS_INTERVAL_SEC,
        "started_at": _utc_timestamp(started_at),
        "observed_at": _utc_timestamp(now),
        "elapsed_sec": payload["duration_sec"],
        "raw_task_text_recorded": False,
        "raw_logs_recorded": False,
        "raw_trajectory_recorded": False,
        "raw_verifier_output_recorded": False,
        "local_paths_recorded": False,
    }
    if not path:
        return
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    closeout = payload.get("terminal_closeout")
    if isinstance(closeout, Mapping):
        closeout_target = target.with_name("supervisor_closeout.compact.json")
        closeout_temporary = closeout_target.with_name(
            f".{closeout_target.name}.{os.getpid()}.tmp"
        )
        try:
            closeout_temporary.write_text(
                json.dumps(closeout, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            closeout_temporary.replace(closeout_target)
        finally:
            closeout_temporary.unlink(missing_ok=True)


def _public_artifact_sync_requested(args: argparse.Namespace) -> bool:
    return bool(
        args.remote_public_artifact_root
        or args.remote_public_artifact_glob
        or args.local_public_artifact_dir
    )


def _public_artifact_sync_contract(args: argparse.Namespace) -> dict[str, Any]:
    return build_remote_benchmark_closeout_contract(
        requested=_public_artifact_sync_requested(args),
        ledger_requested=bool(args.local_run_ledger_path),
        aggregate_requested=bool(args.local_current_aggregate_path),
        ledger_catchup_requested=bool(args.local_ledger_catchup_root),
    )


def _incremental_public_artifact_sync_contract(
    args: argparse.Namespace,
) -> dict[str, Any]:
    interval_sec = max(0.0, float(args.public_artifact_sync_interval_sec))
    return {
        "enabled": interval_sec > 0.0,
        "interval_sec": interval_sec,
        "attempt_count": 0,
        "success_count": 0,
        "failure_count": 0,
        "last_status": "not_run",
        "raw_paths_recorded": False,
        "raw_artifacts_recorded": False,
    }


def _active_phase_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": ACTIVE_PHASE_SCHEMA_VERSION,
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
    if not args.local_public_artifact_dir:
        return contract

    root = Path(args.local_public_artifact_dir).expanduser()
    if not root.is_dir() or root.is_symlink():
        return contract

    selected_phase: dict[str, Any] = {}
    selected_sequence = -1
    receipt_count = 0
    for path in sorted(root.rglob("runner_prerequisites.public.json")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_size > int(args.public_artifact_max_bytes):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping):
            continue
        phase = compact_benchmark_live_worker_phase(
            payload.get("benchmark_live_worker_phase")
        )
        if not phase:
            continue
        receipt_count += 1
        sequence = payload.get("benchflow_lifecycle_receipt_sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            sequence = 0
        if sequence >= selected_sequence:
            selected_phase = phase
            selected_sequence = sequence

    contract["receipt_count"] = receipt_count
    if not selected_phase:
        return contract
    contract.update(
        state="observed",
        receipt_sequence=selected_sequence,
        benchmark_live_worker_phase=selected_phase,
        public_artifact_read=True,
    )
    return contract


def _record_incremental_public_artifact_sync(
    contract: dict[str, Any],
    result: Mapping[str, Any],
) -> None:
    contract["attempt_count"] = int(contract["attempt_count"]) + 1
    if result.get("ok") is True:
        contract["success_count"] = int(contract["success_count"]) + 1
        contract["last_status"] = "passed"
    else:
        contract["failure_count"] = int(contract["failure_count"]) + 1
        contract["last_status"] = str(result.get("first_blocker") or "sync_failed")[
            :120
        ]


def _sync_remote_public_artifacts(
    args: argparse.Namespace,
    *,
    include_local_closeout: bool = True,
) -> dict[str, Any]:
    return closeout_remote_benchmark_batch(
        run_remote_command=lambda command, timeout: _run_remote_shell_command(
            args,
            command,
            timeout_sec=timeout,
        ),
        remote_root=args.remote_public_artifact_root,
        artifact_globs=list(args.remote_public_artifact_glob or []),
        local_public_artifact_dir=args.local_public_artifact_dir,
        adapter_kind=args.public_artifact_adapter_kind,
        max_bytes=args.public_artifact_max_bytes,
        sync_timeout_sec=args.public_artifact_sync_timeout_sec,
        ledger_path=args.local_run_ledger_path if include_local_closeout else "",
        run_group_id=args.local_run_group_id,
        aggregate_path=(
            args.local_current_aggregate_path if include_local_closeout else ""
        ),
        canonical_case_ids_file=args.local_canonical_case_ids_file,
        benchmark_id=args.local_benchmark_id,
        target_lane_id=args.local_target_lane_id,
        target_run_group_contains=list(args.local_target_run_group_contains or []),
        target_backfill_run_group_contains=list(
            args.local_target_backfill_run_group_contains or []
        ),
        ledger_catchup_root=(
            args.local_ledger_catchup_root if include_local_closeout else ""
        ),
        ledger_catchup_run_group_contains=list(
            args.local_ledger_catchup_run_group_contains or []
        ),
        repo_root=REPO_ROOT,
    )


def _size_bucket(value: str) -> str:
    size = len(value.encode("utf-8", errors="replace"))
    if size <= 0:
        return "empty"
    if size < 200:
        return "1_199"
    if size < 1000:
        return "200_999"
    if size < 5000:
        return "1000_4999"
    return "5000_plus"


def _remote_command_failure_subtype(stderr_text: str) -> str:
    """Classify stable entry failures without projecting remote stderr."""
    normalized = stderr_text.lower()
    if "loopx_runner_source_git_head_mismatch" in normalized:
        return "runner_source_git_head_mismatch"
    if "loopx_runner_source_git_head_unknown" in normalized:
        return "runner_source_git_head_unknown"
    if "unrecognized arguments:" in normalized:
        return "cli_argument_incompatible"
    if "usage:" in normalized and ": error:" in normalized:
        return "cli_argument_error"
    if (
        "can't open file" in normalized
        and "no such file or directory" in normalized
    ):
        return "remote_entrypoint_missing"
    if "skillsbenchsetuppreflightblocked" in normalized:
        return "setup_preflight_blocked"
    return "unclassified"


def _remote_failure_cleanup_public_contract(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "requested": bool(args.remote_failure_cleanup_pattern),
        "attempted": False,
        "trigger": "not_run",
        "include_docker": bool(args.remote_failure_cleanup_include_docker),
        "raw_pattern_recorded": False,
        "raw_output_recorded": False,
    }


def _remote_failure_cleanup_command(args: argparse.Namespace) -> str:
    code = r"""
import json
import os
import signal
import subprocess
import sys
import time

pattern = sys.argv[1]
include_docker = sys.argv[2] == "1"
self_pid = os.getpid()
self_pgid = os.getpgrp()
parent_pid = os.getppid()
ancestors = {parent_pid}
cursor = parent_pid
while cursor > 1:
    try:
        with open(f"/proc/{cursor}/stat", "r", encoding="utf-8", errors="replace") as handle:
            parts = handle.read().split()
        cursor = int(parts[3])
    except Exception:
        break
    ancestors.add(cursor)


def matching_pids():
    matches = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == self_pid or pid in ancestors:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        command = raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")
        if pattern not in command:
            continue
        try:
            if os.getpgid(pid) == self_pgid:
                continue
        except OSError:
            pass
        matches.append(pid)
    return sorted(set(matches))


term_targets = matching_pids()
term_sent = 0
for pid in term_targets:
    try:
        os.kill(pid, signal.SIGTERM)
        term_sent += 1
    except OSError:
        pass

time.sleep(1.0)
kill_targets = matching_pids()
kill_sent = 0
for pid in kill_targets:
    try:
        os.kill(pid, signal.SIGKILL)
        kill_sent += 1
    except OSError:
        pass

alive_after = matching_pids()
docker_status = "not_requested"
docker_matched = 0
docker_removed = 0
if include_docker:
    docker_status = "ok"
    try:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
        names = [
            line.strip()
            for line in (ps.stdout or "").splitlines()
            if line.strip() and pattern in line.strip()
        ]
        docker_matched = len(names)
        for name in names:
            rm = subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
                check=False,
            )
            if rm.returncode == 0:
                docker_removed += 1
    except FileNotFoundError:
        docker_status = "docker_unavailable"
    except Exception:
        docker_status = "docker_cleanup_failed"

print(json.dumps({
    "matched_count": len(term_targets),
    "term_sent_count": term_sent,
    "kill_sent_count": kill_sent,
    "alive_after_count": len(alive_after),
    "docker_status": docker_status,
    "docker_matched_count": docker_matched,
    "docker_removed_count": docker_removed,
}, sort_keys=True))
"""
    include_docker = "1" if args.remote_failure_cleanup_include_docker else "0"
    return (
        "# LOOPX_REMOTE_FAILURE_CLEANUP\n"
        + "python3 - "
        + shlex.quote(args.remote_failure_cleanup_pattern)
        + " "
        + include_docker
        + " <<'PY'\n"
        + code.strip()
        + "\nPY"
    )


def _run_remote_failure_cleanup(
    args: argparse.Namespace,
    *,
    trigger: str,
) -> dict[str, Any]:
    payload = _remote_failure_cleanup_public_contract(args)
    payload["trigger"] = trigger
    if not args.remote_failure_cleanup_pattern:
        return payload
    payload["attempted"] = True
    try:
        proc = _run_remote_shell_command(
            args,
            _remote_failure_cleanup_command(args),
            timeout_sec=args.remote_failure_cleanup_timeout_sec,
        )
    except subprocess.TimeoutExpired:
        payload["first_blocker"] = "remote_failure_cleanup_timeout"
        return payload
    except OSError:
        payload["first_blocker"] = "remote_failure_cleanup_launch_failed"
        return payload

    stdout_text = proc.stdout or ""
    stderr_text = proc.stderr or ""
    payload["exit_code"] = proc.returncode
    payload["stdout_size_bucket"] = _size_bucket(stdout_text)
    payload["stderr_size_bucket"] = _size_bucket(stderr_text)
    if proc.returncode != 0:
        payload["first_blocker"] = "remote_failure_cleanup_exit_nonzero"
        return payload
    try:
        parsed = json.loads(stdout_text.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        payload["first_blocker"] = "remote_failure_cleanup_result_missing"
        return payload
    if not isinstance(parsed, dict):
        payload["first_blocker"] = "remote_failure_cleanup_result_invalid"
        return payload
    for key in (
        "matched_count",
        "term_sent_count",
        "kill_sent_count",
        "alive_after_count",
        "docker_matched_count",
        "docker_removed_count",
    ):
        try:
            payload[key] = int(parsed.get(key, 0))
        except (TypeError, ValueError):
            payload[key] = 0
    payload["docker_status"] = str(parsed.get("docker_status", "unknown"))[:80]
    return payload


def _initial_public_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "tunnel_started": False,
        "tunnel_ready": False,
        "probe_attempt_count": 0,
        "probe_status": "not_started",
        "remote_command_requested": bool(args.remote_command),
        "raw_ssh_destination_recorded": False,
        "raw_remote_command_recorded": False,
        "raw_probe_output_recorded": False,
        "raw_remote_output_recorded": False,
        "private_log_written": False,
        "remote_forward": _forward_public_contract(args.remote_forward),
        "proxy_port_coherence": dict(args.proxy_port_coherence),
        "local_forward_dependency": (
            _local_forward_dependency_public_contract(args)
        ),
        "json_bridge": _json_bridge_public_contract(args),
        "codex_bridge": _codex_bridge_public_contract(args),
        "remote_failure_cleanup": _remote_failure_cleanup_public_contract(args),
        "public_artifact_sync": _public_artifact_sync_contract(args),
        "incremental_public_artifact_sync": (
            _incremental_public_artifact_sync_contract(args)
        ),
        "tunnel_liveness": _tunnel_liveness_public_contract(args),
        "owner_control": _owner_control_public_contract(args),
    }


def _owner_stop_receipt(
    *,
    control_id: str,
    status: str,
    matched_supervisor_count: int,
    active_supervisor_count: int,
    terminal_supervisor_count: int,
    request_written: bool = False,
    terminal_observed: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": OWNER_STOP_RECEIPT_SCHEMA_VERSION,
        "ok": status in {"requested", "already_terminal", "terminal_observed"},
        "status": status,
        "control_id": control_id,
        "matched_supervisor_count": matched_supervisor_count,
        "active_supervisor_count": active_supervisor_count,
        "terminal_supervisor_count": terminal_supervisor_count,
        "request_written": request_written,
        "terminal_observed": terminal_observed,
        "raw_path_recorded": False,
        "raw_request_recorded": False,
        "pid_read": False,
        "process_table_read": False,
    }


def request_owner_stop(argv: list[str]) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(
        prog="skillsbench_reverse_tunnel_supervisor.py stop",
        description=(
            "Request cooperative terminal closeout for one owned SkillsBench "
            "supervisor by public control id."
        ),
    )
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--control-id", required=True)
    parser.add_argument("--wait-timeout-sec", type=float, default=30.0)
    args = parser.parse_args(argv)
    control_id = str(args.control_id)
    if not _valid_owner_control_id(control_id):
        parser.error("--control-id must be a bounded public-safe identifier")

    run_root = Path(args.run_root).expanduser()
    if not run_root.is_dir() or run_root.is_symlink():
        return 2, _owner_stop_receipt(
            control_id=control_id,
            status="run_root_unavailable",
            matched_supervisor_count=0,
            active_supervisor_count=0,
            terminal_supervisor_count=0,
        )

    matches: list[tuple[Path, dict[str, Any]]] = []
    for public_path in run_root.rglob("supervisor.public.json"):
        if public_path.is_symlink() or not public_path.is_file():
            continue
        try:
            loaded = json.loads(public_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(loaded, dict):
            continue
        owner_control = loaded.get("owner_control")
        if (
            isinstance(owner_control, Mapping)
            and owner_control.get("schema_version") == OWNER_CONTROL_SCHEMA_VERSION
            and owner_control.get("enabled") is True
            and owner_control.get("control_id") == control_id
        ):
            matches.append((public_path, loaded))

    active = [
        item
        for item in matches
        if isinstance(item[1].get("public_liveness"), Mapping)
        and item[1]["public_liveness"].get("terminal") is not True
        and item[1]["public_liveness"].get("process_alive") is True
    ]
    terminal = [
        item
        for item in matches
        if isinstance(item[1].get("public_liveness"), Mapping)
        and item[1]["public_liveness"].get("terminal") is True
    ]
    counts = {
        "matched_supervisor_count": len(matches),
        "active_supervisor_count": len(active),
        "terminal_supervisor_count": len(terminal),
    }
    if not active:
        status = "already_terminal" if terminal else "supervisor_not_found"
        return (0 if terminal else 2), _owner_stop_receipt(
            control_id=control_id,
            status=status,
            **counts,
        )
    if len(active) != 1:
        return 3, _owner_stop_receipt(
            control_id=control_id,
            status="ambiguous_active_supervisor",
            **counts,
        )

    public_path = active[0][0]
    request_path = public_path.with_name(OWNER_STOP_REQUEST_BASENAME)
    request = {
        "schema_version": OWNER_STOP_REQUEST_SCHEMA_VERSION,
        "control_id": control_id,
        "action": "terminate",
        "requested_at": _utc_timestamp(time.time()),
    }
    temporary = request_path.with_name(f".{request_path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(request, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(request_path)
    finally:
        temporary.unlink(missing_ok=True)

    wait_timeout_sec = max(0.0, float(args.wait_timeout_sec))
    if wait_timeout_sec == 0.0:
        return 0, _owner_stop_receipt(
            control_id=control_id,
            status="requested",
            request_written=True,
            **counts,
        )

    deadline = time.monotonic() + wait_timeout_sec
    while time.monotonic() < deadline:
        try:
            latest = json.loads(public_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            latest = {}
        liveness = latest.get("public_liveness") if isinstance(latest, dict) else {}
        if isinstance(liveness, Mapping) and liveness.get("terminal") is True:
            return 0, _owner_stop_receipt(
                control_id=control_id,
                status="terminal_observed",
                request_written=True,
                terminal_observed=True,
                **counts,
            )
        time.sleep(0.1)

    return 4, _owner_stop_receipt(
        control_id=control_id,
        status="request_pending",
        request_written=True,
        **counts,
    )


def _last_public_liveness_contract(path: str | None) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "schema_version": "skillsbench_supervisor_previous_liveness_v0",
        "status": "unavailable",
        "state": "unknown",
        "terminal": False,
        "process_alive": False,
        "heartbeat_count": 0,
        "elapsed_sec": 0.0,
        "last_known_tunnel_ready": False,
        "raw_task_text_read": False,
        "raw_logs_read": False,
        "raw_trajectory_read": False,
        "raw_verifier_output_read": False,
        "local_paths_recorded": False,
    }
    if not path:
        return contract
    try:
        loaded = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return contract
    if not isinstance(loaded, Mapping):
        return contract
    liveness = loaded.get("public_liveness")
    if not isinstance(liveness, Mapping):
        return contract

    state = str(liveness.get("state") or "unknown")
    if state not in {"starting", "running", "succeeded", "failed"}:
        state = "unknown"
    try:
        heartbeat_count = max(0, int(liveness.get("heartbeat_count", 0)))
    except (TypeError, ValueError):
        heartbeat_count = 0
    try:
        elapsed_sec = max(0.0, float(liveness.get("elapsed_sec", 0.0)))
    except (TypeError, ValueError):
        elapsed_sec = 0.0
    contract.update(
        {
            "status": "read",
            "state": state,
            "terminal": bool(liveness.get("terminal")),
            "process_alive": bool(liveness.get("process_alive")),
            "heartbeat_count": heartbeat_count,
            "elapsed_sec": elapsed_sec,
            "last_known_tunnel_ready": bool(loaded.get("tunnel_ready")),
        }
    )
    return contract


def _last_public_checkpoint(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        loaded = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(loaded, Mapping):
        return {}
    if loaded.get("schema_version") != SCHEMA_VERSION:
        return {}
    return dict(loaded)


def _terminal_artifact_presence(args: argparse.Namespace) -> dict[str, Any]:
    contract = {
        "status": "unavailable",
        "benchmark_compact_present": False,
        "controller_trace_present": False,
        "public_artifact_read": False,
        "raw_artifacts_read": False,
        "local_paths_recorded": False,
    }
    if not args.local_public_artifact_dir:
        return contract
    root = Path(args.local_public_artifact_dir).expanduser()
    if not root.is_dir() or root.is_symlink():
        return contract
    basenames: set[str] = set()
    for path in root.rglob("*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        basenames.add(path.name)
    contract.update(
        status="observed",
        benchmark_compact_present="benchmark_run.compact.json" in basenames,
        controller_trace_present="loopx_controller_trace.public.json" in basenames,
        public_artifact_read=True,
    )
    return contract


def _terminal_closeout_contract(
    args: argparse.Namespace,
    *,
    trigger: str,
    signal_name: str = "",
) -> dict[str, Any]:
    artifacts = _terminal_artifact_presence(args)
    benchmark_compact_present = bool(artifacts["benchmark_compact_present"])
    contract = {
        "schema_version": TERMINAL_CLOSEOUT_SCHEMA_VERSION,
        "status": "complete",
        "disposition": (
            "defer_to_benchmark_compact"
            if benchmark_compact_present
            else "typed_exclusion"
        ),
        "reason_code": trigger,
        "benchmark_compact_present": benchmark_compact_present,
        "controller_trace_present": bool(artifacts["controller_trace_present"]),
        "official_score_countable": None if benchmark_compact_present else False,
        "retry_recommended": False,
        "rotation_allowed": True,
        "public_artifact_read": bool(artifacts["public_artifact_read"]),
        "raw_artifacts_read": False,
        "raw_task_text_read": False,
        "raw_logs_read": False,
        "raw_trajectory_read": False,
        "raw_verifier_output_read": False,
        "local_paths_recorded": False,
    }
    if signal_name:
        contract["signal_name"] = signal_name
    return contract


def _termination_public_artifact_sync(
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not _public_artifact_sync_requested(args):
        return _public_artifact_sync_contract(args)
    try:
        return _sync_remote_public_artifacts(args)
    except Exception as exc:
        contract = _public_artifact_sync_contract(args)
        contract.update(
            attempted=True,
            ok=False,
            first_blocker="termination_public_artifact_sync_failed",
            error_type=type(exc).__name__[:80],
        )
        return contract


def _finalize_unhandled_supervisor_failure(
    args: argparse.Namespace,
    exc: Exception,
) -> dict[str, Any]:
    previous = _last_public_liveness_contract(args.public_output_path)
    now = time.time()
    started_at = now - float(previous["elapsed_sec"])
    payload = _last_public_checkpoint(args.public_output_path)
    if not payload:
        try:
            payload = _initial_public_payload(args)
        except Exception as payload_exc:
            payload = {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "tunnel_started": False,
                "tunnel_ready": False,
                "remote_command_requested": bool(args.remote_command),
                "raw_ssh_destination_recorded": False,
                "raw_remote_command_recorded": False,
                "raw_probe_output_recorded": False,
                "raw_remote_output_recorded": False,
                "private_log_written": False,
                "fallback_payload_error_type": type(payload_exc).__name__[:80],
            }
    payload["ok"] = False
    termination_signal = (
        exc.signum if isinstance(exc, _SupervisorTerminationSignal) else None
    )
    payload["first_blocker"] = (
        "supervisor_termination_signal"
        if termination_signal is not None
        else "supervisor_unhandled_exception"
    )
    payload["supervisor_error_type"] = type(exc).__name__[:80]
    payload["public_terminal_fallback"] = {
        "schema_version": "skillsbench_supervisor_terminal_fallback_v0",
        "triggered": True,
        "trigger": payload["first_blocker"],
        "previous_liveness": previous,
        "exception_message_recorded": False,
        "raw_task_text_recorded": False,
        "raw_logs_recorded": False,
        "raw_trajectory_recorded": False,
        "raw_verifier_output_recorded": False,
        "local_paths_recorded": False,
    }
    if termination_signal is not None:
        signal_name = signal.Signals(termination_signal).name
        payload["public_terminal_fallback"]["signal_name"] = signal_name
    else:
        signal_name = ""
    try:
        payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
            args,
            trigger=str(payload["first_blocker"]),
        )
    except Exception as cleanup_exc:
        cleanup = _remote_failure_cleanup_public_contract(args)
        cleanup["trigger"] = str(payload["first_blocker"])
        cleanup["first_blocker"] = "remote_failure_cleanup_failed"
        cleanup["error_type"] = type(cleanup_exc).__name__[:80]
        payload["remote_failure_cleanup"] = cleanup
    payload["public_artifact_sync"] = _termination_public_artifact_sync(args)
    payload["terminal_closeout"] = _terminal_closeout_contract(
        args,
        trigger=str(payload["first_blocker"]),
        signal_name=signal_name,
    )
    _write_public_checkpoint(
        args.public_output_path,
        payload,
        state="failed",
        started_at=started_at,
        heartbeat_count=int(previous["heartbeat_count"]) + 1,
        terminal=True,
        observed_at=now,
    )
    return payload


def run_supervisor(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    started_at = time.time()
    payload = _initial_public_payload(args)
    _prepare_owner_control(args, payload["owner_control"])
    public_heartbeat_count = 0

    def checkpoint(state: str, *, terminal: bool = False) -> None:
        nonlocal public_heartbeat_count
        public_heartbeat_count += 1
        payload["active_phase"] = _active_phase_public_contract(args)
        _write_public_checkpoint(
            args.public_output_path,
            payload,
            state=state,
            started_at=started_at,
            heartbeat_count=public_heartbeat_count,
            terminal=terminal,
        )

    checkpoint("starting")

    tunnel_proc: subprocess.Popen[Any] | None = None
    local_forward_proc: subprocess.Popen[Any] | None = None
    json_bridge_proc: subprocess.Popen[Any] | None = None
    codex_bridge_proc: subprocess.Popen[Any] | None = None
    runtime_dir_obj: tempfile.TemporaryDirectory[str] | None = None
    json_local_socket: Path | None = None
    codex_local_socket: Path | None = None

    def finish(returncode: int) -> tuple[int, dict[str, Any]]:
        payload["duration_sec"] = round(max(0.0, time.time() - started_at), 3)
        if tunnel_proc is not None:
            payload["tunnel_cleanup_status"] = _stop_process_group(
                tunnel_proc,
                grace_sec=1.0,
            )
            if tunnel_proc.returncode is not None:
                payload["tunnel_exit_code"] = tunnel_proc.returncode
        if local_forward_proc is not None:
            dependency = payload["local_forward_dependency"]
            dependency["managed_process_cleanup_status"] = _stop_process_group(
                local_forward_proc,
                grace_sec=1.0,
            )
            if local_forward_proc.returncode is not None:
                dependency["managed_process_exit_code"] = (
                    local_forward_proc.returncode
                )
        if json_bridge_proc is not None:
            payload["json_bridge"]["server_cleanup_status"] = _stop_process_group(
                json_bridge_proc,
                grace_sec=1.0,
            )
            if json_bridge_proc.returncode is not None:
                payload["json_bridge"]["server_exit_code"] = json_bridge_proc.returncode
        if codex_bridge_proc is not None:
            payload["codex_bridge"]["server_cleanup_status"] = _stop_process_group(
                codex_bridge_proc,
                grace_sec=1.0,
            )
            if codex_bridge_proc.returncode is not None:
                payload["codex_bridge"]["server_exit_code"] = codex_bridge_proc.returncode
        if runtime_dir_obj is not None:
            runtime_dir_obj.cleanup()
        checkpoint(
            "succeeded" if returncode == 0 and payload.get("ok") is True else "failed",
            terminal=True,
        )
        return returncode, payload

    try:
        payload["stale_forward_cleanup"] = _cleanup_stale_local_forward(args)
        local_dependency = payload["local_forward_dependency"]
        if local_dependency["configured"]:
            if _local_forward_endpoint_ready(args):
                local_dependency["state"] = "external_ready"
                local_dependency["last_status"] = "ready"
            else:
                local_forward_proc, local_forward_ready = (
                    _start_local_forward_dependency(
                        args,
                        local_dependency,
                        previous_proc=None,
                        restart=False,
                    )
                )
                if not local_forward_ready:
                    payload["first_blocker"] = (
                        "local_forward_dependency_unavailable"
                    )
                    return finish(2)
        runtime_dir_obj = tempfile.TemporaryDirectory(
            prefix="loopx-rt-",
            dir="/tmp",
        )
        runtime_dir = Path(runtime_dir_obj.name)
        if _json_bridge_requested(args):
            json_bridge_payload = payload["json_bridge"]
            json_local_socket = _resolved_json_local_socket(args, runtime_dir)
            try:
                json_bridge_proc = _start_json_bridge_server(
                    args,
                    socket_path=json_local_socket,
                )
                json_bridge_payload["server_started"] = True
            except OSError as exc:
                payload["first_blocker"] = "json_bridge_server_launch_failed"
                json_bridge_payload["server_error_type"] = type(exc).__name__[:80]
                return finish(2)

            if not _probe_local_json_socket(args, json_local_socket):
                payload["first_blocker"] = "json_bridge_local_socket_not_ready"
                return finish(2)
            if json_bridge_proc.poll() is not None:
                payload["first_blocker"] = "json_bridge_server_exited_before_ready"
                json_bridge_payload["server_exit_code"] = json_bridge_proc.returncode
                return finish(2)
            json_bridge_payload["local_socket_ready"] = True
            json_bridge_payload["remote_socket_cleanup"] = _cleanup_remote_json_socket(
                args
            )
            if not json_bridge_payload["remote_socket_cleanup"].get("ok"):
                payload["first_blocker"] = json_bridge_payload[
                    "remote_socket_cleanup"
                ].get(
                    "first_blocker",
                    "json_bridge_remote_socket_cleanup_failed",
                )
                return finish(2)

        if _codex_bridge_requested(args):
            codex_bridge_payload = payload["codex_bridge"]
            codex_local_socket = _resolved_codex_local_socket(args, runtime_dir)
            try:
                codex_bridge_proc = _start_codex_bridge_server(
                    args,
                    socket_path=codex_local_socket,
                )
                codex_bridge_payload["server_started"] = True
            except OSError as exc:
                payload["first_blocker"] = "codex_bridge_server_launch_failed"
                codex_bridge_payload["server_error_type"] = type(exc).__name__[:80]
                return finish(2)

            if not _probe_local_codex_socket(args, codex_local_socket):
                payload["first_blocker"] = "codex_bridge_local_socket_not_ready"
                return finish(2)
            if codex_bridge_proc.poll() is not None:
                payload["first_blocker"] = "codex_bridge_server_exited_before_ready"
                codex_bridge_payload["server_exit_code"] = codex_bridge_proc.returncode
                return finish(2)
            codex_bridge_payload["local_socket_ready"] = True
            codex_bridge_payload["remote_socket_cleanup"] = (
                _cleanup_remote_codex_socket(args)
            )
            if not codex_bridge_payload["remote_socket_cleanup"].get("ok"):
                payload["first_blocker"] = codex_bridge_payload[
                    "remote_socket_cleanup"
                ].get(
                    "first_blocker",
                    "codex_bridge_remote_socket_cleanup_failed",
                )
                return finish(2)

        tunnel_proc = _start_tunnel_process(
            args,
            json_local_socket=json_local_socket,
            codex_local_socket=codex_local_socket,
        )
        payload["tunnel_started"] = True
    except OSError as exc:
        payload["first_blocker"] = "reverse_tunnel_launch_failed"
        payload["tunnel_error_type"] = type(exc).__name__[:80]
        return finish(2)

    ready, status, probe_attempts = _wait_for_tunnel_ready(
        args,
        tunnel_proc,
        timeout_sec=args.tunnel_ready_timeout_sec,
    )
    payload["probe_attempt_count"] = probe_attempts
    payload["probe_status"] = status
    payload["tunnel_ready"] = ready
    if status == "tunnel_process_exited":
        liveness = payload["tunnel_liveness"]
        for _attempt in range(int(liveness["reconnect_attempt_limit"])):
            liveness["reconnect_attempt_count"] = (
                int(liveness["reconnect_attempt_count"]) + 1
            )
            try:
                tunnel_proc = _start_tunnel_process(
                    args,
                    json_local_socket=json_local_socket,
                    codex_local_socket=codex_local_socket,
                )
            except OSError as exc:
                liveness["last_probe_status"] = (
                    f"reconnect_launch_failed_{type(exc).__name__[:40]}"
                )
                liveness["reconnect_failure_count"] = (
                    int(liveness["reconnect_failure_count"]) + 1
                )
                continue
            ready, status, reconnect_probes = _wait_for_tunnel_ready(
                args,
                tunnel_proc,
                timeout_sec=args.tunnel_reconnect_ready_timeout_sec,
            )
            payload["probe_attempt_count"] = (
                int(payload["probe_attempt_count"]) + reconnect_probes
            )
            payload["probe_status"] = status
            payload["tunnel_ready"] = ready
            liveness["last_probe_status"] = status
            if ready:
                liveness["reconnect_success_count"] = (
                    int(liveness["reconnect_success_count"]) + 1
                )
                liveness["state"] = "reconnected"
                break
            liveness["reconnect_failure_count"] = (
                int(liveness["reconnect_failure_count"]) + 1
            )
        if not ready:
            liveness["state"] = "failed"
            payload["first_blocker"] = (
                "reverse_tunnel_process_exited_before_ready"
            )
            payload["tunnel_exit_code"] = tunnel_proc.returncode
            return finish(2)

    if payload["tunnel_ready"] is not True:
        payload["first_blocker"] = "reverse_tunnel_probe_not_ready"
        return finish(2)

    if _json_bridge_requested(args):
        json_bridge_payload = payload["json_bridge"]
        if not _probe_remote_json_socket(args):
            payload["first_blocker"] = "json_bridge_remote_socket_not_ready"
            return finish(2)
        json_bridge_payload["remote_socket_ready"] = True
        assert runtime_dir_obj is not None
        if not _materialize_remote_json_client(args, Path(runtime_dir_obj.name)):
            payload["first_blocker"] = "json_bridge_remote_client_materialize_failed"
            return finish(2)
        json_bridge_payload["remote_client_materialized"] = True
        json_bridge_payload["remote_command_placeholder_supported"] = (
            "{json_bridge_client}" in args.remote_command
        )

    if _codex_bridge_requested(args):
        codex_bridge_payload = payload["codex_bridge"]
        if not _probe_remote_codex_socket(args):
            payload["first_blocker"] = "codex_bridge_remote_socket_not_ready"
            return finish(2)
        codex_bridge_payload["remote_socket_ready"] = True
        assert runtime_dir_obj is not None
        if not _materialize_remote_codex_client(args, Path(runtime_dir_obj.name)):
            payload["first_blocker"] = "codex_bridge_remote_client_materialize_failed"
            return finish(2)
        codex_bridge_payload["remote_client_materialized"] = True
        codex_bridge_payload["remote_command_placeholder_supported"] = (
            "{codex_bridge_client}" in args.remote_command
        )
        participant_probe = _probe_remote_codex_participant(args)
        codex_bridge_payload["participant_probe"] = participant_probe
        codex_bridge_payload["participant_probe_passed"] = bool(
            participant_probe["passed"]
        )
        if participant_probe["requested"] and not participant_probe["passed"]:
            payload["first_blocker"] = participant_probe.get(
                "first_blocker",
                "codex_bridge_participant_probe_failed",
            )
            return finish(2)

    if args.preflight_only or not args.remote_command:
        payload["ok"] = True
        return finish(0)

    command = [
        *_ssh_base_command(args),
        args.ssh_destination,
        _remote_command_with_bridge_env(args),
    ]
    assert runtime_dir_obj is not None
    runtime_dir = Path(runtime_dir_obj.name)
    stdout_path = runtime_dir / "remote-command.stdout"
    stderr_path = runtime_dir / "remote-command.stderr"
    remote_proc: subprocess.Popen[Any] | None = None
    remote_command_timed_out = False
    tunnel_liveness_failed = False
    liveness = payload["tunnel_liveness"]
    try:
        with (
            stdout_path.open("w", encoding="utf-8") as stdout_handle,
            stderr_path.open("w", encoding="utf-8") as stderr_handle,
        ):
            remote_proc = subprocess.Popen(
                command,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                start_new_session=True,
            )
            run_deadline = time.monotonic() + max(1.0, float(args.run_timeout_sec))
            health_interval = max(0.0, float(args.tunnel_health_interval_sec))
            next_health_probe = time.monotonic() + health_interval
            incremental_sync = payload["incremental_public_artifact_sync"]
            incremental_sync_interval = float(incremental_sync["interval_sec"])
            next_incremental_sync = (
                time.monotonic() + incremental_sync_interval
                if incremental_sync["enabled"]
                else float("inf")
            )
            consecutive_failures = 0
            consecutive_inconclusive = 0
            if liveness["enabled"] and liveness["state"] != "reconnected":
                liveness["state"] = "healthy"
            checkpoint("running")
            next_public_checkpoint = (
                time.monotonic() + PUBLIC_LIVENESS_INTERVAL_SEC
            )

            while remote_proc.poll() is None:
                if _poll_owner_stop_request(args, payload["owner_control"]):
                    checkpoint("running")
                    raise _SupervisorTerminationSignal(signal.SIGTERM)
                now = time.monotonic()
                if now >= run_deadline:
                    remote_command_timed_out = True
                    _stop_process_group(remote_proc, grace_sec=1.0)
                    break
                if now >= next_incremental_sync:
                    _record_incremental_public_artifact_sync(
                        incremental_sync,
                        _sync_remote_public_artifacts(
                            args,
                            include_local_closeout=False,
                        ),
                    )
                    next_incremental_sync = time.monotonic() + incremental_sync_interval
                    if remote_proc.poll() is not None:
                        break
                    now = time.monotonic()
                if now >= next_public_checkpoint:
                    checkpoint("running")
                    next_public_checkpoint = (
                        time.monotonic() + PUBLIC_LIVENESS_INTERVAL_SEC
                    )
                if not liveness["enabled"] or now < next_health_probe:
                    time.sleep(0.1)
                    continue

                if tunnel_proc.poll() is not None:
                    health_ready = False
                    health_status = "tunnel_process_exited"
                else:
                    health_ready, health_status = _run_remote_probe(
                        args,
                        timeout_sec=max(0.01, run_deadline - now),
                    )
                    payload["probe_attempt_count"] = (
                        int(payload["probe_attempt_count"]) + 1
                    )
                liveness["health_probe_attempt_count"] = (
                    int(liveness["health_probe_attempt_count"]) + 1
                )
                liveness["last_probe_status"] = health_status
                if time.monotonic() >= run_deadline:
                    remote_command_timed_out = True
                    _stop_process_group(remote_proc, grace_sec=1.0)
                    break
                if remote_proc.poll() is not None:
                    break
                if health_ready:
                    liveness["health_probe_success_count"] = (
                        int(liveness["health_probe_success_count"]) + 1
                    )
                    consecutive_failures = 0
                    consecutive_inconclusive = 0
                    if liveness["state"] != "reconnected":
                        liveness["state"] = "healthy"
                    next_health_probe = time.monotonic() + health_interval
                    continue

                local_dependency = payload["local_forward_dependency"]
                if (
                    local_dependency["configured"]
                    and tunnel_proc.poll() is None
                    and not _local_forward_endpoint_ready(args)
                ):
                    liveness["health_probe_failure_count"] = (
                        int(liveness["health_probe_failure_count"]) + 1
                    )
                    consecutive_failures += 1
                    liveness["max_consecutive_failure_count"] = max(
                        int(liveness["max_consecutive_failure_count"]),
                        consecutive_failures,
                    )
                    recovered_local_dependency = False
                    for _attempt in range(
                        int(local_dependency["restart_attempt_limit"])
                    ):
                        local_forward_proc, recovered_local_dependency = (
                            _start_local_forward_dependency(
                                args,
                                local_dependency,
                                previous_proc=local_forward_proc,
                                restart=True,
                            )
                        )
                        if recovered_local_dependency:
                            break
                    if recovered_local_dependency:
                        liveness["last_probe_status"] = (
                            "local_forward_dependency_recovered"
                        )
                        liveness["state"] = "degraded"
                        consecutive_failures = 0
                        consecutive_inconclusive = 0
                        next_health_probe = time.monotonic()
                        continue
                    liveness["state"] = "failed"
                    liveness["last_probe_status"] = (
                        "local_forward_dependency_unrecoverable"
                    )
                    tunnel_liveness_failed = True
                    _stop_process_group(remote_proc, grace_sec=1.0)
                    break

                if (
                    health_status == "ssh_transport_unavailable"
                    and tunnel_proc.poll() is None
                ):
                    liveness["health_probe_inconclusive_count"] = (
                        int(liveness["health_probe_inconclusive_count"]) + 1
                    )
                    consecutive_inconclusive += 1
                    liveness["max_consecutive_inconclusive_count"] = max(
                        int(liveness["max_consecutive_inconclusive_count"]),
                        consecutive_inconclusive,
                    )
                    liveness["state"] = "degraded"
                    next_health_probe = time.monotonic() + health_interval
                    continue

                consecutive_inconclusive = 0
                liveness["health_probe_failure_count"] = (
                    int(liveness["health_probe_failure_count"]) + 1
                )
                consecutive_failures += 1
                if health_status == "tunnel_process_exited":
                    consecutive_failures = max(
                        consecutive_failures,
                        int(liveness["failure_threshold"]),
                    )
                liveness["max_consecutive_failure_count"] = max(
                    int(liveness["max_consecutive_failure_count"]),
                    consecutive_failures,
                )
                if consecutive_failures < int(liveness["failure_threshold"]):
                    liveness["state"] = "degraded"
                    next_health_probe = time.monotonic() + health_interval
                    continue

                if tunnel_proc.poll() is None:
                    liveness["health_probe_inconclusive_count"] = (
                        int(liveness["health_probe_inconclusive_count"]) + 1
                    )
                    consecutive_inconclusive += 1
                    liveness["max_consecutive_inconclusive_count"] = max(
                        int(liveness["max_consecutive_inconclusive_count"]),
                        consecutive_inconclusive,
                    )
                    consecutive_failures = 0
                    liveness["state"] = "degraded"
                    liveness["last_probe_status"] = (
                        "new_connect_admission_inconclusive_tunnel_preserved"
                    )
                    next_health_probe = time.monotonic() + health_interval
                    continue

                recovered = False
                for _attempt in range(int(liveness["reconnect_attempt_limit"])):
                    liveness["reconnect_attempt_count"] = (
                        int(liveness["reconnect_attempt_count"]) + 1
                    )
                    try:
                        tunnel_proc = _start_tunnel_process(
                            args,
                            json_local_socket=json_local_socket,
                            codex_local_socket=codex_local_socket,
                        )
                    except OSError as exc:
                        liveness["last_probe_status"] = (
                            f"reconnect_launch_failed_{type(exc).__name__[:40]}"
                        )
                        liveness["reconnect_failure_count"] = (
                            int(liveness["reconnect_failure_count"]) + 1
                        )
                        continue
                    reconnect_ready, reconnect_status, reconnect_probes = (
                        _wait_for_tunnel_ready(
                            args,
                            tunnel_proc,
                            timeout_sec=args.tunnel_reconnect_ready_timeout_sec,
                            remote_proc=remote_proc,
                            run_deadline=run_deadline,
                        )
                    )
                    payload["probe_attempt_count"] = (
                        int(payload["probe_attempt_count"]) + reconnect_probes
                    )
                    liveness["last_probe_status"] = reconnect_status
                    if reconnect_status == "remote_command_completed":
                        recovered = True
                        break
                    if reconnect_status == "run_deadline_exceeded":
                        remote_command_timed_out = True
                        _stop_process_group(remote_proc, grace_sec=1.0)
                        break
                    if reconnect_ready:
                        liveness["reconnect_success_count"] = (
                            int(liveness["reconnect_success_count"]) + 1
                        )
                        liveness["state"] = "reconnected"
                        consecutive_failures = 0
                        consecutive_inconclusive = 0
                        recovered = True
                        break
                    liveness["reconnect_failure_count"] = (
                        int(liveness["reconnect_failure_count"]) + 1
                    )
                if remote_command_timed_out:
                    break
                if not recovered:
                    liveness["state"] = "failed"
                    tunnel_liveness_failed = True
                    _stop_process_group(remote_proc, grace_sec=1.0)
                    break
                next_health_probe = time.monotonic() + health_interval

            remote_proc.wait(timeout=2.0)

        stdout_text = stdout_path.read_text(encoding="utf-8")
        stderr_text = stderr_path.read_text(encoding="utf-8")
        payload["remote_command_exit_code"] = remote_proc.returncode
        payload["remote_stdout_size_bucket"] = _size_bucket(stdout_text)
        payload["remote_stderr_size_bucket"] = _size_bucket(stderr_text)
        payload["private_log_written"] = _write_private_log(
            args.private_log_path,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
        )
        if remote_command_timed_out:
            payload["remote_command_timeout"] = True
            payload["first_blocker"] = "remote_command_timeout"
            payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
                args,
                trigger="remote_command_timeout",
            )
            return finish(124)
        if tunnel_liveness_failed:
            payload["tunnel_ready"] = False
            payload["first_blocker"] = "reverse_tunnel_liveness_unrecoverable"
            payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
                args,
                trigger="reverse_tunnel_liveness_unrecoverable",
            )
            return finish(75)
        payload["public_artifact_sync"] = _sync_remote_public_artifacts(args)
        sync_ok = (
            not _public_artifact_sync_requested(args)
            or payload["public_artifact_sync"].get("ok") is True
        )
        payload["ok"] = remote_proc.returncode == 0 and sync_ok
        if remote_proc.returncode != 0:
            payload["first_blocker"] = "remote_command_exit_nonzero"
            payload["remote_command_failure_subtype"] = (
                _remote_command_failure_subtype(stderr_text)
            )
            payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
                args,
                trigger="remote_command_exit_nonzero",
            )
        elif not sync_ok:
            payload["first_blocker"] = str(
                payload["public_artifact_sync"].get("first_blocker")
                or "public_artifact_sync_failed"
            )
        return finish(
            0
            if remote_proc.returncode == 0 and sync_ok
            else remote_proc.returncode or 3
        )
    except _SupervisorTerminationSignal as exc:
        if remote_proc is not None:
            _stop_process_group(remote_proc, grace_sec=1.0)
        owner_stop_requested = (
            payload.get("owner_control", {}).get("state") == "accepted"
        )
        trigger = (
            "supervisor_owner_stop_requested"
            if owner_stop_requested
            else "supervisor_termination_signal"
        )
        payload["ok"] = False
        payload["first_blocker"] = trigger
        payload["supervisor_error_type"] = type(exc).__name__[:80]
        try:
            payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
                args,
                trigger=trigger,
            )
        except Exception as cleanup_exc:
            cleanup = _remote_failure_cleanup_public_contract(args)
            cleanup["trigger"] = trigger
            cleanup["first_blocker"] = "remote_failure_cleanup_failed"
            cleanup["error_type"] = type(cleanup_exc).__name__[:80]
            payload["remote_failure_cleanup"] = cleanup
        payload["public_artifact_sync"] = _termination_public_artifact_sync(args)
        payload["terminal_closeout"] = _terminal_closeout_contract(
            args,
            trigger=trigger,
            signal_name=(
                "" if owner_stop_requested else signal.Signals(exc.signum).name
            ),
        )
        payload["public_terminal_fallback"] = {
            "schema_version": "skillsbench_supervisor_terminal_fallback_v0",
            "triggered": True,
            "trigger": trigger,
            "exception_message_recorded": False,
            "raw_task_text_recorded": False,
            "raw_logs_recorded": False,
            "raw_trajectory_recorded": False,
            "raw_verifier_output_recorded": False,
            "local_paths_recorded": False,
        }
        if not owner_stop_requested:
            payload["public_terminal_fallback"]["signal_name"] = signal.Signals(
                exc.signum
            ).name
        return finish(128 + exc.signum)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if remote_proc is not None:
            _stop_process_group(remote_proc, grace_sec=1.0)
        payload["first_blocker"] = "remote_command_monitor_failed"
        payload["remote_command_monitor_error_type"] = type(exc).__name__[:80]
        payload["remote_failure_cleanup"] = _run_remote_failure_cleanup(
            args,
            trigger="remote_command_monitor_failed",
        )
        return finish(3)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-bin", default="ssh")
    parser.add_argument("--ssh-destination", required=True)
    parser.add_argument(
        "--ssh-option",
        action="append",
        default=[],
        help="Additional -o option for every ssh invocation, e.g. ConnectTimeout=10.",
    )
    parser.add_argument("--server-alive-interval-sec", type=int, default=30)
    parser.add_argument("--server-alive-count-max", type=int, default=3)
    parser.add_argument("--remote-forward", default=DEFAULT_REMOTE_FORWARD)
    parser.add_argument(
        "--codex-reverse-proxy-port",
        type=int,
        default=None,
        help=(
            "Structured declaration of the remote Codex reverse-proxy port. "
            "Must match the other proxy port declarations and --remote-forward."
        ),
    )
    parser.add_argument(
        "--benchmark-egress-proxy-port",
        type=int,
        default=None,
        help=(
            "Structured declaration of the benchmark egress-proxy port. "
            "Must match the other proxy port declarations and --remote-forward."
        ),
    )
    parser.add_argument(
        "--container-forwarder-port",
        type=int,
        default=None,
        help=(
            "Structured declaration of the container forwarder listen port. "
            "Must match the other proxy port declarations and --remote-forward."
        ),
    )
    parser.add_argument(
        "--local-forward-managed-command",
        default="",
        help=(
            "Optional private foreground command that owns the local endpoint "
            "targeted by --remote-forward. The supervisor starts it when the "
            "endpoint is absent and restarts it after bounded liveness failure; "
            "the raw command and output are never written publicly."
        ),
    )
    parser.add_argument(
        "--local-forward-probe-timeout-sec",
        type=float,
        default=1.0,
        help="TCP probe timeout for the managed local-forward endpoint.",
    )
    parser.add_argument(
        "--local-forward-ready-timeout-sec",
        type=float,
        default=10.0,
        help="Readiness budget after starting the managed local-forward command.",
    )
    parser.add_argument(
        "--local-forward-restart-attempts",
        type=int,
        default=2,
        help="Bounded managed local-forward restarts after endpoint loss.",
    )
    parser.add_argument("--test-host", default=DEFAULT_TEST_HOST)
    parser.add_argument("--test-port", type=int, default=DEFAULT_TEST_PORT)
    parser.add_argument("--probe-timeout-sec", type=float, default=8.0)
    parser.add_argument("--probe-interval-sec", type=float, default=1.0)
    parser.add_argument("--tunnel-ready-timeout-sec", type=float, default=30.0)
    parser.add_argument("--keepalive-interval-sec", type=int, default=20)
    parser.add_argument(
        "--tunnel-health-interval-sec",
        type=float,
        default=30.0,
        help=(
            "Interval for CONNECT probes while the remote command is running; "
            "set to 0 to disable ongoing liveness checks."
        ),
    )
    parser.add_argument(
        "--tunnel-health-failure-threshold",
        type=int,
        default=2,
        help="Consecutive failed health probes before bounded tunnel reconnect.",
    )
    parser.add_argument(
        "--tunnel-reconnect-attempts",
        type=int,
        default=2,
        help="Maximum tunnel restart attempts after sustained liveness failure.",
    )
    parser.add_argument(
        "--tunnel-reconnect-ready-timeout-sec",
        type=float,
        default=30.0,
        help="Readiness budget for each restarted tunnel.",
    )
    parser.add_argument("--run-timeout-sec", type=float, default=7200.0)
    parser.add_argument(
        "--remote-failure-cleanup-pattern",
        default="",
        help=(
            "Private remote process/container name substring to clean up after "
            "a nonzero or timed-out remote command. Public output records "
            "counts only, never the pattern."
        ),
    )
    parser.add_argument(
        "--remote-failure-cleanup-include-docker",
        action="store_true",
        help=(
            "Also remove running Docker containers whose names contain the "
            "private cleanup pattern. Public output records counts only."
        ),
    )
    parser.add_argument(
        "--remote-failure-cleanup-timeout-sec",
        type=float,
        default=60.0,
        help="Timeout for the private remote failure cleanup command.",
    )
    parser.add_argument(
        "--cleanup-stale-local-forward",
        action="store_true",
        help=(
            "Before launching, terminate matching local ssh -R processes for "
            "the same destination and remote-forward. Public output records "
            "counts only."
        ),
    )
    parser.add_argument(
        "--json-bridge",
        action="store_true",
        help=(
            "Hold a per-run JSON reverse-channel bridge alongside the TCP "
            "reverse tunnel."
        ),
    )
    parser.add_argument(
        "--json-bridge-command",
        default="",
        help=(
            "Private local command executed by the JSON bridge server for "
            "sandbox command/file requests. Not written to public output."
        ),
    )
    parser.add_argument(
        "--json-local-socket",
        default="",
        help=(
            "Optional local Unix socket path for the JSON bridge server. "
            "Omit to use a per-run temporary socket."
        ),
    )
    parser.add_argument(
        "--json-remote-socket",
        default="",
        help=(
            "Remote Unix socket path exposed through ssh -R for the JSON "
            "bridge. The raw path is not written to public output."
        ),
    )
    parser.add_argument(
        "--json-remote-client-path",
        default="",
        help=(
            "Remote path where the JSON bridge client script is materialized. "
            "Use {json_bridge_client} inside --remote-command to inject it."
        ),
    )
    parser.add_argument("--json-server-timeout-sec", type=float, default=7200.0)
    parser.add_argument("--json-socket-ready-timeout-sec", type=float, default=15.0)
    parser.add_argument("--remote-setup-timeout-sec", type=float, default=30.0)
    parser.add_argument(
        "--json-bridge-probe-policy",
        choices=("sandbox-env-deferred", "socket-only"),
        default="sandbox-env-deferred",
        help=(
            "Pre-case readiness policy. sandbox-env-deferred avoids probing "
            "AI_ADDR/AI_PORT before the BenchFlow task sandbox exists; socket-only "
            "checks only the local/remote bridge socket and client lifecycle."
        ),
    )
    parser.add_argument(
        "--codex-bridge",
        action="store_true",
        help=(
            "Hold an opt-in local Codex reverse-channel provider alongside the "
            "TCP reverse tunnel."
        ),
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Local Codex executable used by the reverse-channel server.",
    )
    parser.add_argument(
        "--codex-local-socket",
        default="",
        help=(
            "Optional local Unix socket path for the Codex bridge server. "
            "Omit to use a per-run temporary socket."
        ),
    )
    parser.add_argument(
        "--codex-remote-socket",
        default="",
        help=(
            "Remote Unix socket exposed through ssh -R for the Codex bridge. "
            "The raw path is not written to public output."
        ),
    )
    parser.add_argument(
        "--codex-remote-client-path",
        default="",
        help=(
            "Remote path where the Codex bridge client is materialized. "
            "Use {codex_bridge_client} inside --remote-command to inject it."
        ),
    )
    parser.add_argument(
        "--codex-prompt-bridge-command",
        default="",
        help=(
            "Private local command used to execute scored sandbox operations "
            "on the remote participant host. Not written to public output."
        ),
    )
    parser.add_argument("--codex-server-timeout-sec", type=float, default=7200.0)
    parser.add_argument("--codex-socket-ready-timeout-sec", type=float, default=15.0)
    parser.add_argument(
        "--codex-participant-sandbox",
        choices=("read-only", "workspace-write"),
        default="",
        help=(
            "Fixed sandbox used by the task-free participant probe. "
            "Split-control benchmark launches must use workspace-write."
        ),
    )
    parser.add_argument(
        "--codex-participant-probe-timeout-sec",
        type=float,
        default=60.0,
    )
    parser.add_argument(
        "--codex-first-action-timeout-sec",
        type=float,
        default=180.0,
    )
    parser.add_argument(
        "--codex-bridge-idle-timeout-sec",
        type=float,
        default=0.0,
    )
    parser.add_argument("--remote-command", default="")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--remote-public-artifact-root",
        default="",
        help=(
            "Private remote root for post-run compact/public artifact collection. "
            "The path is never written to public output."
        ),
    )
    parser.add_argument(
        "--remote-public-artifact-glob",
        action="append",
        default=[],
        help=(
            "Relative compact/public artifact glob below the private remote root. "
            "May be repeated; raw artifacts are rejected before transport."
        ),
    )
    parser.add_argument(
        "--local-public-artifact-dir",
        default="",
        help=(
            "Private local destination for synchronized compact/public artifacts. "
            "The path is never written to public output."
        ),
    )
    parser.add_argument(
        "--public-artifact-adapter-kind",
        default="skillsbench",
    )
    parser.add_argument(
        "--public-artifact-max-bytes",
        type=int,
        default=2 * 1024 * 1024,
    )
    parser.add_argument(
        "--public-artifact-sync-timeout-sec",
        type=float,
        default=60.0,
    )
    parser.add_argument(
        "--public-artifact-sync-interval-sec",
        type=float,
        default=0.0,
        help=(
            "Optional interval for syncing bounded public artifacts while the "
            "remote command is still running. Zero disables incremental sync."
        ),
    )
    parser.add_argument(
        "--local-run-ledger-path",
        default="",
        help=(
            "Optional private local ledger updated from synchronized compact runs. "
            "The path is never written to public output."
        ),
    )
    parser.add_argument("--local-run-group-id", default="")
    parser.add_argument(
        "--local-ledger-catchup-root",
        default="",
        help=(
            "Optional local public artifact root laid out as "
            "<run-group-id>/**/benchmark_run.compact.json. Missing terminal rows "
            "are upserted before aggregation; raw artifacts are never read."
        ),
    )
    parser.add_argument(
        "--local-ledger-catchup-run-group-contains",
        action="append",
        default=[],
        help=(
            "Optional substring filter for catch-up run-group directories. "
            "May be repeated."
        ),
    )
    parser.add_argument("--local-current-aggregate-path", default="")
    parser.add_argument("--local-canonical-case-ids-file", default="")
    parser.add_argument("--local-benchmark-id", default="skillsbench@1.1")
    parser.add_argument("--local-target-lane-id", default="")
    parser.add_argument(
        "--local-target-run-group-contains",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--local-target-backfill-run-group-contains",
        action="append",
        default=[],
    )
    parser.add_argument(
        "--private-log-path",
        default=None,
        help="Optional private stdout/stderr capture for the remote command.",
    )
    parser.add_argument(
        "--public-output-path",
        default=None,
        help="Optional path for compact public-safe supervisor JSON.",
    )
    parser.add_argument(
        "--owner-control-id",
        default="",
        help=(
            "Public-safe run id that enables cooperative owner stop requests "
            "through the supervisor public-output directory."
        ),
    )
    args = parser.parse_args(argv)
    if args.owner_control_id:
        if not _valid_owner_control_id(args.owner_control_id):
            parser.error("--owner-control-id must be a bounded public-safe identifier")
        if not args.public_output_path:
            parser.error("--owner-control-id requires --public-output-path")
    try:
        args.proxy_port_coherence = _proxy_port_coherence_public_contract(args)
    except ValueError as exc:
        parser.error(str(exc))
    if _json_bridge_requested(args):
        args.json_bridge = True
        missing = [
            name
            for name in (
                "json_bridge_command",
                "json_remote_socket",
                "json_remote_client_path",
            )
            if not getattr(args, name)
        ]
        if missing:
            parser.error(
                "--json-bridge requires "
                + ", ".join("--" + item.replace("_", "-") for item in missing)
            )
    if _codex_bridge_requested(args):
        args.codex_bridge = True
        missing = [
            name
            for name in (
                "codex_remote_socket",
                "codex_remote_client_path",
                "codex_prompt_bridge_command",
                "codex_participant_sandbox",
            )
            if not getattr(args, name)
        ]
        if missing:
            parser.error(
                "--codex-bridge requires "
                + ", ".join("--" + item.replace("_", "-") for item in missing)
            )
    if _public_artifact_sync_requested(args):
        missing = []
        if not args.remote_public_artifact_root:
            missing.append("--remote-public-artifact-root")
        if not args.remote_public_artifact_glob:
            missing.append("--remote-public-artifact-glob")
        if not args.local_public_artifact_dir:
            missing.append("--local-public-artifact-dir")
        if missing:
            parser.error("artifact sync requires " + ", ".join(missing))
        for pattern in args.remote_public_artifact_glob:
            parts = Path(pattern).parts
            if Path(pattern).is_absolute() or ".." in parts:
                parser.error(
                    "--remote-public-artifact-glob must be relative and bounded"
                )
    if (
        args.public_artifact_sync_interval_sec > 0
        and not _public_artifact_sync_requested(args)
    ):
        parser.error("--public-artifact-sync-interval-sec requires artifact sync")
    if args.local_run_ledger_path and not _public_artifact_sync_requested(args):
        parser.error("--local-run-ledger-path requires artifact sync")
    if args.local_ledger_catchup_root and not args.local_run_ledger_path:
        parser.error("--local-ledger-catchup-root requires --local-run-ledger-path")
    if args.local_current_aggregate_path:
        if not args.local_run_ledger_path or not args.local_canonical_case_ids_file:
            parser.error(
                "--local-current-aggregate-path requires --local-run-ledger-path "
                "and --local-canonical-case-ids-file"
            )
    return args


def main(argv: list[str] | None = None) -> int:
    resolved_argv = list(sys.argv[1:] if argv is None else argv)
    if resolved_argv[:1] == ["stop"]:
        rc, receipt = request_owner_stop(resolved_argv[1:])
        sys.stdout.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        return rc

    args = parse_args(resolved_argv)
    previous_signal_handlers: dict[int, Any] = {}

    def request_terminal_closeout(signum: int, _frame: Any) -> None:
        raise _SupervisorTerminationSignal(signum)

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        previous_signal_handlers[signum] = signal.signal(
            signum,
            request_terminal_closeout,
        )
    try:
        rc, payload = run_supervisor(args)
    except Exception as exc:
        payload = _finalize_unhandled_supervisor_failure(args, exc)
        rc = (
            128 + exc.signum
            if isinstance(exc, _SupervisorTerminationSignal)
            else 70
        )
        sys.stderr.write(
            "skillsbench supervisor failed unexpectedly: "
            f"{type(exc).__name__}\n"
        )
    finally:
        for signum, previous_handler in previous_signal_handlers.items():
            signal.signal(signum, previous_handler)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(text)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
