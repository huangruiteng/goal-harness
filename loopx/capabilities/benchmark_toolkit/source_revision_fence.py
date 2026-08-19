"""Fail-closed source revision admission for benchmark runs."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BENCHMARK_SOURCE_REVISION_FENCE_SCHEMA_VERSION = "benchmark_source_revision_fence_v0"
_FULL_GIT_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


class BenchmarkSourceRevisionFenceError(ValueError):
    """The source checkout or revision observation cannot be trusted."""


@dataclass(frozen=True)
class BenchmarkSourceRevisionFence:
    """Private exact evidence behind one source admission decision."""

    source_checkout: Path
    expected_revision: str
    local_revision: str
    observed_reference_revision: str
    source_clean: bool
    admitted: bool
    reason_code: str

    @property
    def local_matches_expected(self) -> bool:
        return self.local_revision == self.expected_revision

    @property
    def observed_reference_matches_expected(self) -> bool:
        return self.observed_reference_revision == self.expected_revision


def _normalize_revision(value: str, *, field: str) -> str:
    revision = str(value).strip().lower()
    if not _FULL_GIT_OBJECT_ID.fullmatch(revision):
        raise BenchmarkSourceRevisionFenceError(f"{field}_invalid")
    return revision


def _git_text(source: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "--no-optional-locks", "-C", str(source), *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise BenchmarkSourceRevisionFenceError(
            "source_revision_git_readback_failed"
        ) from exc
    if completed.returncode:
        raise BenchmarkSourceRevisionFenceError("source_revision_git_readback_failed")
    return completed.stdout.strip()


def inspect_benchmark_source_revision_fence(
    source_checkout: str | Path,
    *,
    expected_revision: str,
    observed_reference_revision: str,
) -> BenchmarkSourceRevisionFence:
    """Compare a clean local checkout with a pin and caller-observed ref head.

    The caller owns any network fetch or provider API read used to obtain
    ``observed_reference_revision``. This helper performs only local readback;
    it never fetches, checks out, installs, or launches a benchmark run.
    """

    requested = Path(source_checkout).expanduser()
    if requested.is_symlink():
        raise BenchmarkSourceRevisionFenceError("source_checkout_symlink_denied")
    try:
        source = requested.resolve(strict=True)
    except OSError as exc:
        raise BenchmarkSourceRevisionFenceError("source_checkout_missing") from exc
    if not source.is_dir():
        raise BenchmarkSourceRevisionFenceError("source_checkout_not_directory")

    expected = _normalize_revision(expected_revision, field="expected_revision")
    observed = _normalize_revision(
        observed_reference_revision,
        field="observed_reference_revision",
    )
    try:
        repository_root = Path(
            _git_text(source, "rev-parse", "--show-toplevel")
        ).resolve(strict=True)
    except OSError as exc:
        raise BenchmarkSourceRevisionFenceError(
            "source_checkout_root_unreadable"
        ) from exc
    if repository_root != source:
        raise BenchmarkSourceRevisionFenceError(
            "source_checkout_must_be_repository_root"
        )

    local = _normalize_revision(
        _git_text(source, "rev-parse", "HEAD"),
        field="local_revision",
    )
    source_clean = not bool(
        _git_text(source, "status", "--porcelain", "--untracked-files=all")
    )
    if not source_clean:
        admitted = False
        reason_code = "source_checkout_dirty"
    elif local != expected:
        admitted = False
        reason_code = "local_revision_mismatch"
    elif observed != expected:
        admitted = False
        reason_code = "observed_reference_revision_mismatch"
    else:
        admitted = True
        reason_code = "revision_fence_satisfied"

    return BenchmarkSourceRevisionFence(
        source_checkout=source,
        expected_revision=expected,
        local_revision=local,
        observed_reference_revision=observed,
        source_clean=source_clean,
        admitted=admitted,
        reason_code=reason_code,
    )


def compact_benchmark_source_revision_fence_receipt(
    fence: BenchmarkSourceRevisionFence,
) -> dict[str, Any]:
    """Return a public-safe decision receipt without paths or revisions."""

    return {
        "schema_version": BENCHMARK_SOURCE_REVISION_FENCE_SCHEMA_VERSION,
        "admitted": fence.admitted,
        "reason_code": fence.reason_code,
        "source_clean": fence.source_clean,
        "local_matches_expected": fence.local_matches_expected,
        "observed_reference_matches_expected": (
            fence.observed_reference_matches_expected
        ),
        "source_path_recorded": False,
        "revision_values_recorded": False,
        "network_access_performed": False,
        "write_performed": False,
    }
