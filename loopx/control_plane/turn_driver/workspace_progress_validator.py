"""Independent bounded workspace-progress validation for Chat-started Turns."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

MAX_UNTRACKED_BYTES = 32 * 1024 * 1024
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _git_bytes(project: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=project,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            "workspace progress validation requires a readable Git worktree"
        )
    return completed.stdout


def workspace_progress_digest(project: Path) -> str:
    """Hash the reviewable Git workspace state without exposing its contents."""

    root = project.expanduser().resolve()
    digest = sha256()
    for args in (
        ("rev-parse", "HEAD"),
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        ("diff", "--binary", "--no-ext-diff"),
        ("diff", "--cached", "--binary", "--no-ext-diff"),
    ):
        digest.update(_git_bytes(root, *args))
        digest.update(b"\0")

    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    remaining = MAX_UNTRACKED_BYTES
    for raw_name in untracked.split(b"\0"):
        if not raw_name:
            continue
        digest.update(raw_name)
        path = root / raw_name.decode("utf-8", errors="surrogateescape")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(str(path.readlink()).encode("utf-8", errors="surrogateescape"))
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        digest.update(str(size).encode("ascii"))
        if remaining <= 0:
            continue
        with path.open("rb") as handle:
            content = handle.read(min(size, remaining))
        digest.update(content)
        remaining -= len(content)
    return "sha256:" + digest.hexdigest()


def validate_workspace_progress(project: Path, *, baseline_hash: str) -> bool:
    if _SHA256_RE.fullmatch(baseline_hash) is None:
        return False
    if workspace_progress_digest(project) == baseline_hash:
        return False
    for args in (("diff", "--check"), ("diff", "--cached", "--check")):
        checked = subprocess.run(
            ["git", *args],
            cwd=project.expanduser().resolve(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if checked.returncode != 0:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-hash", required=True)
    args = parser.parse_args(argv)
    # The Turn driver supplies the normalized result on stdin. Consume it so a
    # future pipe writer cannot block even though this validator needs only the
    # independently observed workspace state.
    sys.stdin.buffer.read()
    try:
        return (
            0
            if validate_workspace_progress(Path.cwd(), baseline_hash=args.baseline_hash)
            else 1
        )
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
