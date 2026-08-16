#!/usr/bin/env python3
"""Thin repository-hygiene smoke for LoopX's own public checkout."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.contract import scan_public_boundary  # noqa: E402


REQUIRED_TRACKED_FILES = (
    "LICENSE",
    "CONTRIBUTING.md",
)
SECURITY_FILES = ("SECURITY.md", ".github/SECURITY.md")
ISSUE_TEMPLATE_DIR = ".github/ISSUE_TEMPLATE/"
PR_TEMPLATE = ".github/PULL_REQUEST_TEMPLATE.md"
RELEASE_TIMELINE = REPO_ROOT / "docs" / "product" / "release-readiness.md"
FIRST_PUBLIC_RELEASE = (0, 1, 3)
VERSION_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def tracked_files() -> set[str]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "repository-hygiene-smoke requires a git worktree: "
            f"{completed.stderr.strip() or 'git ls-files failed'}"
        )
    return {line for line in completed.stdout.split("\0") if line}


def validate_required_tracked_files(files: set[str]) -> None:
    missing = [name for name in REQUIRED_TRACKED_FILES if name not in files]
    if missing:
        raise AssertionError(f"missing tracked repository-hygiene files: {sorted(missing)}")
    if not any(name in files for name in SECURITY_FILES):
        raise AssertionError(
            "missing tracked security policy; expected one of "
            + ", ".join(SECURITY_FILES)
        )
    if PR_TEMPLATE not in files:
        raise AssertionError(f"missing tracked pull-request template: {PR_TEMPLATE}")
    issue_templates = [
        name
        for name in files
        if name.startswith(ISSUE_TEMPLATE_DIR)
        and name != f"{ISSUE_TEMPLATE_DIR}config.yml"
    ]
    if not issue_templates:
        raise AssertionError(f"missing tracked issue templates under {ISSUE_TEMPLATE_DIR}")


def validate_public_private_boundary() -> None:
    boundary = scan_public_boundary([REPO_ROOT], registry={})
    hits = list(boundary.get("hits") or [])
    if hits:
        detail = "\n".join(hits)
        raise AssertionError(f"public/private boundary violations:\n{detail}")
    if not boundary.get("ok"):
        raise AssertionError(
            f"public/private boundary scan failed: {boundary.get('ok')}"
        )


def release_tags() -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "tag", "--list", "--sort=version:refname", "v*"],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"cannot list git tags: {completed.stderr.strip()}")
    tags: list[str] = []
    for tag in completed.stdout.splitlines():
        match = VERSION_TAG_RE.match(tag.strip())
        if not match:
            continue
        version = tuple(int(part) for part in match.groups())
        if version >= FIRST_PUBLIC_RELEASE:
            tags.append(tag.strip())
    return tags


def validate_release_timeline() -> None:
    if not RELEASE_TIMELINE.is_file():
        raise AssertionError(f"missing release timeline: {RELEASE_TIMELINE.relative_to(REPO_ROOT)}")
    timeline = RELEASE_TIMELINE.read_text(encoding="utf-8")
    tags = release_tags()
    if not tags:
        if "on 20" not in timeline:
            raise AssertionError("release timeline has no dated version entries")
        return
    missing = [tag for tag in tags if f"`{tag}`" not in timeline]
    if missing:
        raise AssertionError(
            "release timeline is missing version entries: "
            + ", ".join(missing)
        )


def main() -> int:
    files = tracked_files()
    validate_required_tracked_files(files)
    validate_public_private_boundary()
    validate_release_timeline()
    print("repository-hygiene-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
