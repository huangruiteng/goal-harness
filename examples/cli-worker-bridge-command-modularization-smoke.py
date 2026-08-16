#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "loopx" / "cli.py"
MODULE = ROOT / "loopx" / "cli_commands" / "worker_bridge.py"
INIT = ROOT / "loopx" / "cli_commands" / "__init__.py"


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        input=stdin,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_success(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode != 0:
        raise AssertionError(
            f"expected success, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    return result.stdout


def main() -> None:
    cli_source = CLI.read_text(encoding="utf-8")
    module_source = MODULE.read_text(encoding="utf-8")
    init_source = INIT.read_text(encoding="utf-8")

    forbidden_cli_markers = [
        "worker_bridge_parser = sub.add_parser",
        "worker_bridge_sub = worker_bridge_parser.add_subparsers",
        "build_worker_bridge_install_contract(",
        "observe_active_user_intervention_feed(",
        'if args.command == "worker-bridge":',
    ]
    for marker in forbidden_cli_markers:
        require(marker not in cli_source, f"worker-bridge marker leaked into cli.py: {marker}")

    for marker in (
        "register_worker_bridge_commands",
        "handle_worker_bridge_command",
        "WORKER_BRIDGE_COMMANDS",
        "append_worker_bridge_counter_trace_row(",
    ):
        require(marker in module_source, f"worker-bridge command module missing {marker}")
    require("register_worker_bridge_commands" in init_source, "__init__ did not export worker bridge registration")
    require("handle_worker_bridge_command" in init_source, "__init__ did not export worker bridge handler")

    help_text = require_success(run_cli("worker-bridge", "active-user-observe", "--help"))
    for option in ("--feed-jsonl", "--observation-json", "--counter-trace-json"):
        require(option in help_text, f"active-user-observe help omitted {option}")

    contract_payload = json.loads(
        require_success(run_cli("worker-bridge", "contract", "--format", "json"))
    )
    require(contract_payload.get("ok") is True, "worker bridge contract should be ok")
    require(
        contract_payload.get("schema_version")
        == "loopx_worker_bridge_install_contract_v0",
        "contract schema changed",
    )

    with tempfile.TemporaryDirectory(prefix="loopx-worker-bridge-cli-") as tmp:
        root = Path(tmp)
        before = require_success(
            run_cli(
                "worker-bridge",
                "active-user-intervention",
                "--seq",
                "0",
                "--message",
                "before worker start",
                "--before-worker-start",
                "--jsonl",
            )
        ).strip()
        after = require_success(
            run_cli(
                "worker-bridge",
                "active-user-intervention",
                "--seq",
                "2",
                "--message",
                "after worker start",
                "--jsonl",
            )
        ).strip()
        feed_path = root / "feed.jsonl"
        observation_path = root / "observation.json"
        counter_trace_path = root / "counter-trace.jsonl"
        feed_path.write_text(before + "\n" + after + "\n", encoding="utf-8")

        observe_payload = json.loads(
            require_success(
                run_cli(
                    "worker-bridge",
                    "active-user-observe",
                    "--feed-jsonl",
                    str(feed_path),
                    "--worker-start-seq",
                    "1",
                    "--observation-json",
                    str(observation_path),
                    "--counter-trace-json",
                    str(counter_trace_path),
                    "--format",
                    "json",
                )
            )
        )
        require(observe_payload.get("ok") is True, "active-user-observe should succeed")
        require(observe_payload.get("observation_written") is True, "observation writeback missing")
        require(observe_payload.get("counter_trace_written") is True, "counter trace writeback missing")

    print("cli-worker-bridge-command-modularization-smoke: ok")


if __name__ == "__main__":
    main()
