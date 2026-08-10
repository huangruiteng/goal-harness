#!/usr/bin/env python3
"""Smoke-test the local-only integration-branch CLI contract.

The fixture intentionally uses only a temporary local Git repository. It
proves that preview remains read-only, execution updates only the configured
local integration branch and ignored plan, source order is preserved, a
reviewed candidate can be adopted, and dirty/conflicting inputs fail closed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_BRANCH = "codex/local-integration"
SOURCES = ("feature-a", "fix-b")


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
    )


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo), *args], cwd=repo, check=check).stdout.strip()


def commit(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def run_cli(repo: Path, *args: str, check: bool = True) -> tuple[int, dict[str, Any]]:
    result = run(
        [
            sys.executable,
            "-m",
            "loopx.cli",
            "--format",
            "json",
            "integration-branch",
            *args,
        ],
        cwd=REPO_ROOT,
        check=False,
    )
    if check and result.returncode:
        raise AssertionError(
            f"integration-branch CLI failed rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result.returncode, json.loads(result.stdout)


def build_repository(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "LoopX Smoke")
    git(repo, "config", "user.email", "loopx-smoke@example.invalid")
    commit(repo, ".gitignore", ".loopx/\n", "ignore local LoopX state")
    commit(repo, "shared.txt", "base\n", "base")

    git(repo, "switch", "-c", "feature-a")
    commit(repo, "a.txt", "a1\n", "feature a")
    git(repo, "switch", "main")

    git(repo, "switch", "-c", "fix-b")
    commit(repo, "b.txt", "b1\n", "fix b")
    git(repo, "switch", "main")
    return repo


def configure_args(repo: Path, *, execute: bool) -> list[str]:
    args = [
        "configure",
        "--repo-path",
        str(repo),
        "--base-ref",
        "main",
        "--integration-branch",
        INTEGRATION_BRANCH,
    ]
    for source in SOURCES:
        args.extend(["--source-branch", source])
    if execute:
        args.append("--execute")
    return args


def sync_args(repo: Path, *, execute: bool, candidate_ref: str | None = None) -> list[str]:
    args = ["sync", "--repo-path", str(repo)]
    if candidate_ref:
        args.extend(["--candidate-ref", candidate_ref])
    if execute:
        args.append("--execute")
    return args


def assert_source_order(payload: dict[str, Any]) -> None:
    sources = payload["status_packet"]["plan"]["last_sync"]["sources"]
    assert [item["ref"] for item in sources] == list(SOURCES), sources


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        repo = build_repository(Path(temp_dir))
        main_head = git(repo, "rev-parse", "main")
        source_heads = {source: git(repo, "rev-parse", source) for source in SOURCES}
        assert git(repo, "remote") == ""

        # Configure previews without writing the ignored local plan.
        _, preview = run_cli(repo, *configure_args(repo, execute=False))
        plan_path = repo / ".loopx" / "integration-branch.json"
        assert preview["status"] == "preview", preview
        assert preview["executed"] is False, preview
        assert not plan_path.exists()
        assert git(repo, "branch", "--list", INTEGRATION_BRANCH) == ""

        _, configured = run_cli(repo, *configure_args(repo, execute=True))
        assert configured["status"] == "configured", configured
        assert configured["write_boundary"].startswith("local ignored plan only"), configured
        assert plan_path.is_file()
        assert git(repo, "check-ignore", "--quiet", ".loopx/integration-branch.json") == ""
        assert (
            git(repo, "ls-files", "--error-unmatch", ".loopx/integration-branch.json", check=False)
            == ""
        )

        _, initial_status = run_cli(repo, "status", "--repo-path", str(repo))
        assert initial_status["status"] == "drifted", initial_status
        assert initial_status["drift_reasons"] == [{"kind": "never_synced"}]

        # Preview builds an ephemeral candidate but does not publish a branch.
        _, sync_preview = run_cli(repo, *sync_args(repo, execute=False))
        assert sync_preview["status"] == "preview_ready", sync_preview
        assert sync_preview["updated"] is False, sync_preview
        assert git(repo, "branch", "--list", INTEGRATION_BRANCH) == ""

        _, initial_sync = run_cli(repo, *sync_args(repo, execute=True))
        integration_head = initial_sync["candidate_sha"]
        assert initial_sync["status"] == "synced", initial_sync
        assert initial_sync["updated"] is True, initial_sync
        assert_source_order(initial_sync)
        for source, source_head in source_heads.items():
            git(repo, "merge-base", "--is-ancestor", source_head, INTEGRATION_BRANCH)

        # Conflict must preserve the prior integration head. A separately
        # reviewed candidate containing every input can then be adopted.
        git(repo, "switch", "feature-a")
        commit(repo, "shared.txt", "from feature-a\n", "feature a conflict")
        git(repo, "switch", "fix-b")
        commit(repo, "shared.txt", "from fix-b\n", "fix b conflict")
        git(repo, "switch", "main")
        source_heads = {source: git(repo, "rev-parse", source) for source in SOURCES}

        conflict_rc, conflict = run_cli(repo, *sync_args(repo, execute=True), check=False)
        assert conflict_rc == 1, conflict
        assert conflict["status"] == "merge_failed", conflict
        assert conflict["integration_unchanged"] is True, conflict
        assert git(repo, "rev-parse", INTEGRATION_BRANCH) == integration_head

        git(repo, "switch", "-c", "reviewed-candidate", "main")
        git(repo, "merge", "--no-ff", "--no-edit", "feature-a")
        failed_merge = run(
            ["git", "-C", str(repo), "merge", "--no-ff", "--no-edit", "fix-b"],
            cwd=repo,
            check=False,
        )
        assert failed_merge.returncode != 0, failed_merge
        (repo / "shared.txt").write_text("reviewed resolution\n", encoding="utf-8")
        git(repo, "add", "shared.txt")
        git(repo, "commit", "--no-edit")
        reviewed_candidate = git(repo, "rev-parse", "HEAD")
        git(repo, "switch", "main")

        _, candidate_preview = run_cli(
            repo,
            *sync_args(repo, execute=False, candidate_ref=reviewed_candidate),
        )
        assert candidate_preview["candidate_source"] == "supplied", candidate_preview
        _, adopted = run_cli(
            repo,
            *sync_args(repo, execute=True, candidate_ref=reviewed_candidate),
        )
        assert adopted["status"] == "synced", adopted
        assert adopted["candidate_sha"] == reviewed_candidate, adopted
        assert_source_order(adopted)

        # Preview still remains read-only with a dirty checked-out integration
        # branch; execute fails before publishing a new integration head.
        source_worktree = Path(temp_dir) / "source-worktree"
        git(repo, "worktree", "add", str(source_worktree), "feature-a")
        latest_source = commit(source_worktree, "a.txt", "a2\n", "review update")
        git(repo, "switch", INTEGRATION_BRANCH)
        (repo / "shared.txt").write_text("local diagnostic only\n", encoding="utf-8")
        before_dirty_sync = git(repo, "rev-parse", INTEGRATION_BRANCH)

        _, dirty_preview = run_cli(repo, *sync_args(repo, execute=False))
        assert dirty_preview["status"] == "preview_ready", dirty_preview
        assert dirty_preview["updated"] is False, dirty_preview
        assert git(repo, "rev-parse", INTEGRATION_BRANCH) == before_dirty_sync

        dirty_rc, dirty = run_cli(repo, *sync_args(repo, execute=True), check=False)
        assert dirty_rc == 2, dirty
        assert dirty["status"] == "invalid_state", dirty
        assert "worktree is dirty" in dirty["error"], dirty
        assert git(repo, "rev-parse", INTEGRATION_BRANCH) == before_dirty_sync
        assert git(repo, "rev-parse", "feature-a") == latest_source
        assert git(repo, "rev-parse", "main") == main_head
        assert git(repo, "remote") == ""

    print("integration-branch-cli-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
