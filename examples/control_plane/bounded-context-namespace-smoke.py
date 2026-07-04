#!/usr/bin/env python3
"""Guard repo-local control-plane code against legacy projection shims."""

from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_IMPORT = "loopx.projections"
LEGACY_PACKAGE_PREFIX = "loopx/projections/"


def tracked_text_files() -> list[Path]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-files",
            "*.py",
            "*.md",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [
        REPO_ROOT / line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and (REPO_ROOT / line.strip()).exists()
    ]


def tracked_files() -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def assert_no_tracked_legacy_projection_package() -> None:
    offenders = [
        path
        for path in tracked_files()
        if path.startswith(LEGACY_PACKAGE_PREFIX)
        and (REPO_ROOT / path).exists()
    ]
    assert offenders == [], (
        "legacy loopx/projections shims should not be kept for repo-local code; "
        "move implementations to loopx.control_plane.<bounded_context>",
        offenders,
    )


def assert_repo_local_imports_use_bounded_contexts() -> None:
    offenders: list[str] = []
    for path in tracked_text_files():
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        if LEGACY_IMPORT in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], {
        "legacy_import": LEGACY_IMPORT,
        "offenders": offenders[:20],
        "offender_count": len(offenders),
    }


def main() -> int:
    assert_no_tracked_legacy_projection_package()
    assert_repo_local_imports_use_bounded_contexts()
    print("bounded-context-namespace-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
