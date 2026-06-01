#!/usr/bin/env python3
"""Run the public dependency-free smoke scripts.

This is intentionally a tiny examples runner, not a test framework. Keep
`goal-harness check` focused on contract health and call this explicitly when
example behavior needs coverage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = REPO_ROOT / "examples"


def main() -> int:
    smoke_scripts = sorted(EXAMPLES_DIR.glob("*-smoke.py"))
    if not smoke_scripts:
        print("no smoke scripts found")
        return 0

    for script in smoke_scripts:
        label = script.relative_to(REPO_ROOT)
        print(f"==> {label}", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"{label} failed with exit code {result.returncode}", file=sys.stderr)
            return result.returncode

    print(f"ok: {len(smoke_scripts)} smoke script(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
