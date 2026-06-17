#!/usr/bin/env python3
"""Regression for the first modular CLI command seam.

This protects the initial extraction from ``goal_harness.cli`` into
``goal_harness.cli_commands``. The old public invocation should keep working
while command registration/handling moves behind a small module contract.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from goal_harness.cli_commands import handle_doctor_command, register_doctor_command

    assert callable(register_doctor_command)
    assert callable(handle_doctor_command)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--format",
            "json",
            "doctor",
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict), payload
    assert payload.get("ok") is True, payload
    assert "checks" in payload, payload
    print("cli-command-module-contract-regression ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
