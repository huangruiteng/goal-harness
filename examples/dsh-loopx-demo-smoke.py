#!/usr/bin/env python3
"""Validate the public DSH × LoopX demo in an isolated temporary copy."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = REPO_ROOT / "examples" / "dsh-loopx-demo"
PRIVATE_MARKERS = tuple(
    "".join(parts)
    for parts in (
        ("/", "Users/"),
        (".local", "/"),
        ("lark", "office.com"),
        ("byte", "dance.com"),
        ("Author", "ization:"),
        ("BEGIN", " PRIVATE ", "KEY"),
    )
)


def main() -> int:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is required")

    required = (
        "README.md",
        "package.json",
        "package-lock.json",
        "reproduce-demo.sh",
        "src/cli.js",
        "test/cli.test.js",
    )
    for relative in required:
        path = DEMO_ROOT / relative
        if not path.is_file():
            raise AssertionError(f"missing demo file: {relative}")
        text = path.read_text(encoding="utf-8")
        for marker in PRIVATE_MARKERS:
            if marker in text:
                raise AssertionError(f"{relative}: private marker {marker!r}")

    lock = json.loads((DEMO_ROOT / "package-lock.json").read_text(encoding="utf-8"))
    packages = lock["packages"]
    resolved = [
        entry["resolved"]
        for entry in packages.values()
        if isinstance(entry, dict) and "resolved" in entry
    ]
    if not resolved or not all(url.startswith("https://registry.npmjs.org/") for url in resolved):
        raise AssertionError("demo lockfile must use only public npm registry URLs")

    with tempfile.TemporaryDirectory(prefix="loopx-dsh-demo-") as tmp:
        checkout = Path(tmp) / "demo"
        shutil.copytree(DEMO_ROOT, checkout)
        subprocess.run([npm, "ci", "--ignore-scripts"], cwd=checkout, check=True)
        subprocess.run([npm, "test"], cwd=checkout, check=True)

    print("dsh-loopx-demo-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
