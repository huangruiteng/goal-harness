#!/usr/bin/env python3
"""Smoke-test public run-id owner control for SkillsBench supervisors."""

from __future__ import annotations

import importlib.util
import json
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "skillsbench_reverse_tunnel_supervisor.py"


def load_supervisor() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "skillsbench_reverse_tunnel_supervisor",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def public_payload(
    supervisor: ModuleType,
    control_id: str,
    *,
    terminal: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": supervisor.SCHEMA_VERSION,
        "owner_control": {
            "schema_version": supervisor.OWNER_CONTROL_SCHEMA_VERSION,
            "enabled": True,
            "state": "listening",
            "control_id": control_id,
            "request_basename": supervisor.OWNER_STOP_REQUEST_BASENAME,
            "raw_request_recorded": False,
            "raw_path_recorded": False,
            "pid_read": False,
            "process_table_read": False,
        },
        "public_liveness": {
            "terminal": terminal,
            "process_alive": not terminal,
        },
    }


def write_public(
    supervisor: ModuleType,
    root: Path,
    run_name: str,
    control_id: str,
    *,
    terminal: bool = False,
) -> Path:
    run_dir = root / run_name
    run_dir.mkdir(parents=True)
    public_path = run_dir / "supervisor.public.json"
    public_path.write_text(
        json.dumps(
            public_payload(supervisor, control_id, terminal=terminal),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return public_path


def assert_receipt_boundary(receipt: dict[str, object], root: Path) -> None:
    assert receipt["raw_path_recorded"] is False, receipt
    assert receipt["raw_request_recorded"] is False, receipt
    assert receipt["pid_read"] is False, receipt
    assert receipt["process_table_read"] is False, receipt
    assert str(root) not in json.dumps(receipt, sort_keys=True), receipt


def write_fake_ssh(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import signal
import sys
import time

args = sys.argv[1:]
if "-R" in args:
    running = True
    def stop(_sig, _frame):
        global running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        time.sleep(0.05)
    raise SystemExit(0)

remote_command = args[-1] if args else ""
if "LOOPX_REVERSE_TUNNEL_PROBE" in remote_command:
    print("HTTP/1.1 200 Connection Established")
    raise SystemExit(0)
if "owner-stop-long-run" in remote_command:
    running = True
    def stop(_sig, _frame):
        global running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        time.sleep(0.05)
    raise SystemExit(0)
print('{"ok": true}')
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def assert_live_stop_integration(supervisor: ModuleType) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        run_dir = root / "integration-run"
        run_dir.mkdir()
        public_path = run_dir / "supervisor.public.json"
        fake_ssh = root / "ssh"
        write_fake_ssh(fake_ssh)
        supervisor_proc = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                "--ssh-bin",
                str(fake_ssh),
                "--ssh-destination",
                "opaque-host.example",
                "--remote-command",
                "owner-stop-long-run",
                "--public-output-path",
                str(public_path),
                "--owner-control-id",
                "integration-run",
                "--tunnel-ready-timeout-sec",
                "5",
                "--probe-interval-sec",
                "0.05",
                "--tunnel-health-interval-sec",
                "0",
                "--run-timeout-sec",
                "30",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if public_path.exists():
                public = json.loads(public_path.read_text(encoding="utf-8"))
                liveness = public.get("public_liveness", {})
                if liveness.get("state") == "running":
                    break
            time.sleep(0.05)
        else:
            supervisor_proc.terminate()
            supervisor_proc.wait(timeout=5)
            raise AssertionError("supervisor did not reach running state")

        stop_proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "stop",
                "--run-root",
                str(root),
                "--control-id",
                "integration-run",
                "--wait-timeout-sec",
                "10",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        stdout, stderr = supervisor_proc.communicate(timeout=10)
        assert stop_proc.returncode == 0, stop_proc.stderr or stop_proc.stdout
        receipt = json.loads(stop_proc.stdout)
        assert receipt["status"] == "terminal_observed", receipt
        assert_receipt_boundary(receipt, root)
        assert supervisor_proc.returncode == 128 + signal.SIGTERM, stderr or stdout

        public = json.loads(public_path.read_text(encoding="utf-8"))
        assert public["first_blocker"] == "supervisor_owner_stop_requested", public
        assert public["owner_control"]["state"] == "accepted", public
        assert public["owner_control"]["accepted_request_count"] == 1, public
        assert public["public_liveness"]["terminal"] is True, public
        assert public["public_liveness"]["process_alive"] is False, public
        assert public["terminal_closeout"]["reason_code"] == (
            "supervisor_owner_stop_requested"
        ), public
        assert "signal_name" not in public["terminal_closeout"], public
        assert str(root) not in json.dumps(public, sort_keys=True), public


def main() -> None:
    supervisor = load_supervisor()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        public_path = write_public(supervisor, root, "run-a", "run-a")

        rc, receipt = supervisor.request_owner_stop(
            [
                "--run-root",
                str(root),
                "--control-id",
                "run-a",
                "--wait-timeout-sec",
                "0",
            ]
        )
        assert rc == 0, receipt
        assert receipt["status"] == "requested", receipt
        assert receipt["matched_supervisor_count"] == 1, receipt
        assert receipt["active_supervisor_count"] == 1, receipt
        assert receipt["request_written"] is True, receipt
        assert_receipt_boundary(receipt, root)

        request_path = public_path.with_name(
            supervisor.OWNER_STOP_REQUEST_BASENAME
        )
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert request == {
            "schema_version": supervisor.OWNER_STOP_REQUEST_SCHEMA_VERSION,
            "control_id": "run-a",
            "action": "terminate",
            "requested_at": request["requested_at"],
        }, request

        args = SimpleNamespace(
            owner_control_id="run-a",
            public_output_path=str(public_path),
        )
        contract = supervisor._owner_control_public_contract(args)
        assert supervisor._poll_owner_stop_request(args, contract) is True
        assert contract["state"] == "accepted", contract
        assert contract["accepted_request_count"] == 1, contract
        assert request_path.exists() is False

        public_path.write_text(
            json.dumps(
                public_payload(supervisor, "run-a", terminal=True),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        rc, receipt = supervisor.request_owner_stop(
            [
                "--run-root",
                str(root),
                "--control-id",
                "run-a",
            ]
        )
        assert rc == 0, receipt
        assert receipt["status"] == "already_terminal", receipt
        assert receipt["request_written"] is False, receipt
        assert_receipt_boundary(receipt, root)

        invalid_path = write_public(supervisor, root, "run-b", "run-b")
        invalid_args = SimpleNamespace(
            owner_control_id="run-b",
            public_output_path=str(invalid_path),
        )
        invalid_contract = supervisor._owner_control_public_contract(invalid_args)
        invalid_request = invalid_path.with_name(
            supervisor.OWNER_STOP_REQUEST_BASENAME
        )
        invalid_request.write_text(
            json.dumps(
                {
                    "schema_version": supervisor.OWNER_STOP_REQUEST_SCHEMA_VERSION,
                    "control_id": "another-run",
                    "action": "terminate",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        assert (
            supervisor._poll_owner_stop_request(invalid_args, invalid_contract)
            is False
        )
        assert invalid_contract["state"] == "invalid_request_ignored"
        assert invalid_contract["invalid_request_count"] == 1
        assert invalid_request.exists() is False

        write_public(supervisor, root, "collision-a", "collision")
        write_public(supervisor, root, "collision-b", "collision")
        rc, receipt = supervisor.request_owner_stop(
            [
                "--run-root",
                str(root),
                "--control-id",
                "collision",
                "--wait-timeout-sec",
                "0",
            ]
        )
        assert rc == 3, receipt
        assert receipt["status"] == "ambiguous_active_supervisor", receipt
        assert receipt["active_supervisor_count"] == 2, receipt
        assert_receipt_boundary(receipt, root)

        write_public(supervisor, root, "cli-run", "cli-run")
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "stop",
                "--run-root",
                str(root),
                "--control-id",
                "cli-run",
                "--wait-timeout-sec",
                "0",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0, proc.stderr
        cli_receipt = json.loads(proc.stdout)
        assert cli_receipt["status"] == "requested", cli_receipt
        assert_receipt_boundary(cli_receipt, root)

    assert_live_stop_integration(supervisor)
    print("skillsbench supervisor owner control smoke: ok")


if __name__ == "__main__":
    main()
