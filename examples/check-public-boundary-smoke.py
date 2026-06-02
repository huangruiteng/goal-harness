#!/usr/bin/env python3
"""Smoke-test check behavior in a fresh directory with no project registry."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    home = cwd / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env.pop("GOAL_HARNESS_REGISTRY", None)
    return subprocess.run(
        [sys.executable, "-m", "goal_harness.cli", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        implicit = run_cli(root, "--format", "json", "check", "--scan-root", str(REPO_ROOT))
        if implicit.returncode != 0:
            raise AssertionError(implicit.stderr or implicit.stdout)
        payload = json.loads(implicit.stdout)
        if not payload.get("ok"):
            raise AssertionError(payload)
        warnings = payload.get("warnings") or []
        if not any("registry file does not exist" in str(item) for item in warnings):
            raise AssertionError(payload)

        explicit = run_cli(
            root,
            "--registry",
            str(root / "missing-registry.json"),
            "--format",
            "json",
            "check",
            "--scan-root",
            str(REPO_ROOT),
        )
        if explicit.returncode == 0:
            raise AssertionError(explicit.stdout)
        explicit_payload = json.loads(explicit.stdout)
        if explicit_payload.get("ok"):
            raise AssertionError(explicit_payload)

    print("check-public-boundary-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
