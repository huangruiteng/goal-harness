from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from loopx import registry as registry_module


def run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_registry_git_probe_skips_git_when_discovery_has_no_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "project" / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    def unexpected_git(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        return subprocess.CompletedProcess(command, 128, "", "not a git repository")

    monkeypatch.setattr(registry_module.subprocess, "run", unexpected_git)

    assert registry_module._registry_git_probe(registry_path) == {
        "available": True,
        "probe_status": "ok",
        "inside_worktree": False,
        "tracked": False,
        "ignored": False,
        "worktree_root_recorded": False,
    }
    assert calls == []


def test_registry_git_probe_preserves_file_classification_inside_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.delenv("GIT_WORK_TREE", raising=False)
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "--quiet")
    (repo / ".gitignore").write_text("ignored.json\n", encoding="utf-8")
    tracked = repo / "tracked.json"
    ignored = repo / "ignored.json"
    untracked = repo / "untracked.json"
    for path in (tracked, ignored, untracked):
        path.write_text("{}\n", encoding="utf-8")
    run_git(repo, "add", "tracked.json")

    assert registry_module._registry_git_probe(tracked) == {
        "available": True,
        "probe_status": "ok",
        "inside_worktree": True,
        "tracked": True,
        "ignored": False,
        "worktree_root_recorded": False,
    }
    assert registry_module._registry_git_probe(ignored) == {
        "available": True,
        "probe_status": "ok",
        "inside_worktree": True,
        "tracked": False,
        "ignored": True,
        "worktree_root_recorded": False,
    }
    assert registry_module._registry_git_probe(untracked) == {
        "available": True,
        "probe_status": "ok",
        "inside_worktree": True,
        "tracked": False,
        "ignored": False,
        "worktree_root_recorded": False,
    }


def test_registry_git_probe_reports_unavailable_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(registry_module.shutil, "which", lambda _: None)

    def unexpected_git(*_: object, **__: object) -> None:
        raise AssertionError("non-Git fast path must not launch Git")

    monkeypatch.setattr(registry_module.subprocess, "run", unexpected_git)

    assert registry_module._registry_git_probe(registry_path) == {
        "available": False,
        "probe_status": "git_unavailable",
        "inside_worktree": False,
        "tracked": False,
        "ignored": False,
        "worktree_root_recorded": False,
    }
