#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "loopx" / "cli.py"
MODULE = ROOT / "demo" / "multi_agent_cli.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
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

    require("multi_agent.py" not in cli_source, "cli.py should not embed multi-agent module details")
    require(
        '("multi-agent", "demo.multi_agent_cli", "register_multi_agent_commands")'
        in cli_source,
        "cli.py did not register the source-checkout multi-agent demo",
    )
    require(
        "from demo.multi_agent_cli import handle_multi_agent_command" in cli_source,
        "cli.py did not dispatch the source-checkout multi-agent demo",
    )

    for marker in (
        "register_multi_agent_commands",
        "handle_multi_agent_command",
        "build_visible_multi_agent_payload_from_spec",
        "execute_visible_multi_agent_launcher",
        "generic_multi_agent_launch_spec_v0",
        "--auto-wake",
    ):
        require(marker in module_source, f"multi-agent module missing {marker}")

    help_text = require_success(run_cli("multi-agent", "launch", "--help"))
    for option in (
        "--spec",
        "--execute",
        "--workspace",
        "--attach",
        "--auto-wake",
        "--codex-trust-workspace",
    ):
        require(option in help_text, f"multi-agent launch help omitted {option}")

    print("cli-multi-agent-command-modularization-smoke: ok")


if __name__ == "__main__":
    main()
