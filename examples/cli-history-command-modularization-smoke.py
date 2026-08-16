#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loopx.cli", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def assert_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"expected to find {needle!r} in output:\n{text}")


def assert_not_contains(text: str, needle: str) -> None:
    if needle in text:
        raise AssertionError(f"did not expect to find {needle!r} in output:\n{text}")


def main() -> int:
    cli_source = (ROOT / "loopx" / "cli.py").read_text(encoding="utf-8")
    init_source = (ROOT / "loopx" / "cli_commands" / "__init__.py").read_text(
        encoding="utf-8"
    )
    history_source = (ROOT / "loopx" / "cli_commands" / "history.py").read_text(
        encoding="utf-8"
    )

    if "history_parser = sub.add_parser" in cli_source:
        raise AssertionError("history parser registration leaked back into loopx/cli.py")
    assert_contains(cli_source, "register_history_command(sub)")
    assert_contains(cli_source, "handle_history_command(")
    assert_contains(init_source, "register_history_command")
    assert_contains(init_source, "handle_history_command")
    assert_not_contains(history_source, "append_active_user_assisted_pilot")
    assert_contains(history_source, "render_index_duplicate_repair_markdown")

    help_result = run_cli("history", "--help")
    if help_result.returncode != 0:
        raise AssertionError(help_result.stderr or help_result.stdout)
    assert_not_contains(help_result.stdout, "append-active-user-assisted-pilot")
    assert_contains(help_result.stdout, "repair-index-duplicates")
    assert_contains(help_result.stdout, "rebuild-index-collisions")
    assert_not_contains(help_result.stdout, "--active-user-pilot-json")

    print("cli-history-command-modularization-smoke: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
