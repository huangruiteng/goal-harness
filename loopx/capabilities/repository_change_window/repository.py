from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


class RepositoryChangeWindowError(ValueError):
    """A fail-closed repository or pending-change contract error."""


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    root: Path
    common_dir: Path
    repository_id: str
    branch: str
    head_oid: str


def git(
    repo: Path,
    *args: str,
    check: bool = True,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        detail = (
            result.stderr.decode("utf-8", errors="replace").strip()
            or result.stdout.decode("utf-8", errors="replace").strip()
            or "git command failed"
        )
        raise RepositoryChangeWindowError(detail)
    return result


def git_text(repo: Path, *args: str, check: bool = True) -> str:
    return (
        git(repo, *args, check=check).stdout.decode("utf-8", errors="replace").strip()
    )


def repository_root(repo_path: str | Path) -> Path:
    requested = Path(repo_path).expanduser().resolve()
    return Path(git_text(requested, "rev-parse", "--show-toplevel")).resolve()


def repository_common_dir(repo: Path) -> Path:
    raw = Path(git_text(repo, "rev-parse", "--git-common-dir"))
    return (raw if raw.is_absolute() else repo / raw).resolve()


def _credential_free_remote(value: str) -> str | None:
    remote = str(value or "").strip()
    if not remote:
        return None
    scp_match = re.fullmatch(r"(?:[^@/:]+@)?([^/:]+):(.+)", remote)
    if scp_match and "://" not in remote:
        host = scp_match.group(1).lower()
        path = scp_match.group(2)
    else:
        parsed = urlsplit(remote)
        if not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        path = unquote(parsed.path).lstrip("/")
    normalized_path = path.removesuffix(".git").strip("/")
    if not normalized_path or any(char.isspace() for char in normalized_path):
        return None
    return f"git:{host}/{normalized_path}"


def repository_identity(repo: Path, common_dir: Path) -> str:
    remote = git_text(repo, "remote", "get-url", "origin", check=False)
    normalized = _credential_free_remote(remote)
    if normalized:
        return normalized
    digest = hashlib.sha256(str(common_dir).encode("utf-8")).hexdigest()[:20]
    return f"git-local:{digest}"


def resolve_repository_context(repo_path: str | Path) -> RepositoryContext:
    root = repository_root(repo_path)
    common_dir = repository_common_dir(root)
    branch = git_text(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if not branch:
        raise RepositoryChangeWindowError(
            "repository change tracking requires an attached local branch"
        )
    head_oid = git_text(root, "rev-parse", "--verify", "HEAD^{commit}")
    return RepositoryContext(
        root=root,
        common_dir=common_dir,
        repository_id=repository_identity(root, common_dir),
        branch=branch,
        head_oid=head_oid,
    )


def _digest_git_output(repo: Path, *args: str) -> str:
    return hashlib.sha256(git(repo, *args).stdout).hexdigest()


def _path_count(repo: Path, *args: str) -> int:
    output = git(repo, *args).stdout
    return len([item for item in output.split(b"\0") if item])


def _untracked_content_digest(repo: Path, names: bytes) -> str:
    paths = [os.fsdecode(item) for item in names.split(b"\0") if item]
    combined = hashlib.sha256(names)
    for offset in range(0, len(paths), 128):
        object_ids = git(
            repo,
            "hash-object",
            "--no-filters",
            "--",
            *paths[offset : offset + 128],
        ).stdout
        combined.update(b"\0")
        combined.update(object_ids)
    return combined.hexdigest()


def repository_change_fingerprint(context: RepositoryContext) -> dict[str, object]:
    repo = context.root
    staged_count = _path_count(
        repo,
        "diff",
        "--cached",
        "--name-only",
        "-z",
        "--no-ext-diff",
    )
    unstaged_count = _path_count(
        repo,
        "diff",
        "--name-only",
        "-z",
        "--no-ext-diff",
    )
    untracked_names = git(
        repo,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ).stdout
    untracked_count = len([item for item in untracked_names.split(b"\0") if item])
    combined = hashlib.sha256()
    for label, digest in (
        (
            "staged",
            _digest_git_output(
                repo,
                "diff",
                "--cached",
                "--binary",
                "--no-ext-diff",
            ),
        ),
        (
            "unstaged",
            _digest_git_output(repo, "diff", "--binary", "--no-ext-diff"),
        ),
        ("untracked_content", _untracked_content_digest(repo, untracked_names)),
    ):
        combined.update(label.encode("utf-8"))
        combined.update(b"\0")
        combined.update(digest.encode("ascii"))
        combined.update(b"\0")
    return {
        "schema_version": "repository_change_fingerprint_v0",
        "digest": combined.hexdigest(),
        "head_oid": context.head_oid,
        "staged_path_count": staged_count,
        "unstaged_path_count": unstaged_count,
        "untracked_path_count": untracked_count,
        "contains_diff_body": False,
        "contains_path_names": False,
    }
