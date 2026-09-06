#!/usr/bin/env python3
"""Embed an exact public Git snapshot in the signed desktop distribution.

Never collect a developer's whole working directory or private local state.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


def build(root: Path) -> None:
    destination = root / "apps/desktop/loopx-control-plane/runtime"
    destination.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    archive = destination / "runtime-source.tar.gz"
    subprocess.run([
        "git", "archive", "--format=tar.gz", f"--output={archive}", revision,
        "loopx", "scripts", "skills", "docs", "man", "examples", "apps/presentation",
        ".github", "README.md", "LICENSE", "pyproject.toml",
    ], cwd=root, check=True)
    identity = {
        "schema_version": "desktop_runtime_bundle_v1",
        "source_revision": revision,
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    (destination / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    print(f"Prepared exact desktop runtime: {revision[:12]}")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
