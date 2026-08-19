from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from loopx.capabilities.benchmark_toolkit import (
    BENCHMARK_SOURCE_REVISION_FENCE_SCHEMA_VERSION,
    BenchmarkSourceRevisionFenceError,
    compact_benchmark_source_revision_fence_receipt,
    inspect_benchmark_source_revision_fence,
)


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "source"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "benchmark@example.invalid")
    _git(repository, "config", "user.name", "Benchmark Fixture")
    (repository / "README.md").write_text("first\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "fixture")
    return repository, _git(repository, "rev-parse", "HEAD")


def test_source_revision_fence_admits_exact_clean_revision(tmp_path: Path) -> None:
    repository, revision = _repository(tmp_path)

    fence = inspect_benchmark_source_revision_fence(
        repository,
        expected_revision=revision,
        observed_reference_revision=revision,
    )
    receipt = compact_benchmark_source_revision_fence_receipt(fence)

    assert fence.admitted is True
    assert receipt == {
        "schema_version": BENCHMARK_SOURCE_REVISION_FENCE_SCHEMA_VERSION,
        "admitted": True,
        "reason_code": "revision_fence_satisfied",
        "source_clean": True,
        "local_matches_expected": True,
        "observed_reference_matches_expected": True,
        "source_path_recorded": False,
        "revision_values_recorded": False,
        "network_access_performed": False,
        "write_performed": False,
    }
    rendered = json.dumps(receipt, sort_keys=True)
    assert str(repository) not in rendered
    assert revision not in rendered


def test_source_revision_fence_rejects_dirty_checkout(tmp_path: Path) -> None:
    repository, revision = _repository(tmp_path)
    (repository / "local-note.txt").write_text("untracked\n", encoding="utf-8")

    fence = inspect_benchmark_source_revision_fence(
        repository,
        expected_revision=revision,
        observed_reference_revision=revision,
    )

    assert fence.admitted is False
    assert fence.reason_code == "source_checkout_dirty"
    assert fence.source_clean is False


def test_source_revision_fence_distinguishes_local_and_reference_drift(
    tmp_path: Path,
) -> None:
    repository, first = _repository(tmp_path)
    (repository / "README.md").write_text("second\n", encoding="utf-8")
    _git(repository, "commit", "-am", "second")
    second = _git(repository, "rev-parse", "HEAD")

    local_drift = inspect_benchmark_source_revision_fence(
        repository,
        expected_revision=first,
        observed_reference_revision=first,
    )
    assert local_drift.reason_code == "local_revision_mismatch"

    _git(repository, "reset", "--hard", first)
    reference_drift = inspect_benchmark_source_revision_fence(
        repository,
        expected_revision=first,
        observed_reference_revision=second,
    )
    assert reference_drift.reason_code == "observed_reference_revision_mismatch"
    assert reference_drift.local_matches_expected is True
    assert reference_drift.observed_reference_matches_expected is False


def test_source_revision_fence_cli_is_fail_closed(tmp_path: Path) -> None:
    repository, revision = _repository(tmp_path)
    command = [
        sys.executable,
        "-m",
        "loopx.cli",
        "--format",
        "json",
        "benchmark",
        "source-revision-fence",
        "--source-checkout",
        str(repository),
        "--expected-revision",
        revision,
        "--observed-reference-revision",
        "f" * 40,
        "--require-admitted",
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["reason_code"] == "observed_reference_revision_mismatch"
    assert str(repository) not in completed.stdout
    assert revision not in completed.stdout


def test_source_revision_fence_rejects_invalid_identity(tmp_path: Path) -> None:
    repository, revision = _repository(tmp_path)

    with pytest.raises(
        BenchmarkSourceRevisionFenceError,
        match="observed_reference_revision_invalid",
    ):
        inspect_benchmark_source_revision_fence(
            repository,
            expected_revision=revision,
            observed_reference_revision="main",
        )
