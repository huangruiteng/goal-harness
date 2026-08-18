from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest

from loopx.capabilities.repository_change_window import (
    build_policy,
    evaluate_policy,
    git_hook_provider_status,
    install_git_hook_provider,
    list_pending_changes,
    record_pending_change,
    resolve_pending_change,
    run_git_hook_provider,
    uninstall_git_hook_provider,
    verify_pending_change,
)
from loopx.capabilities.repository_change_window.policy import (
    BlockedWindow,
    ChangeWindowPolicy,
    ChangeWindowPolicyError,
    Weekday,
    parse_local_time,
)
from loopx.cli import main


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    global_config = tmp_path / "empty-global-gitconfig"
    global_config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(tmp_path / "missing-system-gitconfig"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "LoopX Test")
    _git(repo, "config", "user.email", "loopx@example.invalid")
    _git(repo, "remote", "add", "origin", "git@github.com:example/change-window.git")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "base")
    return repo


def _weekday_policy():
    return build_policy(
        timezone_name="Asia/Shanghai",
        weekdays=["mon", "tue", "wed", "thu", "fri"],
        blocked_start="10:00",
        blocked_end="21:00",
    )


def test_policy_uses_typed_timezone_boundaries_and_internal_fake_clock() -> None:
    policy = _weekday_policy()

    before = evaluate_policy(
        policy,
        now=datetime.fromisoformat("2026-08-18T09:59:00+08:00"),
    )
    start = evaluate_policy(
        policy,
        now=datetime.fromisoformat("2026-08-18T10:00:00+08:00"),
    )
    end = evaluate_policy(
        policy,
        now=datetime.fromisoformat("2026-08-18T21:00:00+08:00"),
    )
    weekend = evaluate_policy(
        policy,
        now=datetime.fromisoformat("2026-08-22T12:00:00+08:00"),
    )

    assert before["allowed"] is True
    assert start["allowed"] is False
    assert start["next_eligible_at"] == "2026-08-18T21:00:00+08:00"
    assert end["allowed"] is True
    assert weekend["allowed"] is True

    overnight = build_policy(
        timezone_name="UTC",
        weekdays=["fri"],
        blocked_start="22:00",
        blocked_end="02:00",
    )
    assert (
        evaluate_policy(
            overnight,
            now=datetime.fromisoformat("2026-08-22T01:30:00+00:00"),
        )["allowed"]
        is False
    )
    assert (
        evaluate_policy(
            overnight,
            now=datetime.fromisoformat("2026-08-22T02:00:00+00:00"),
        )["allowed"]
        is True
    )

    with pytest.raises(ChangeWindowPolicyError, match="timezone-aware"):
        evaluate_policy(policy, now=datetime(2026, 8, 18, 12, 0))

    full_week = tuple(Weekday(day) for day in range(7))
    with pytest.raises(ChangeWindowPolicyError, match="eligible local minute"):
        ChangeWindowPolicy(
            timezone_name="UTC",
            blocked_windows=(
                BlockedWindow(
                    weekdays=full_week,
                    start_local=parse_local_time("00:00"),
                    end_local=parse_local_time("12:00"),
                ),
                BlockedWindow(
                    weekdays=full_week,
                    start_local=parse_local_time("12:00"),
                    end_local=parse_local_time("00:00"),
                ),
            ),
        )


def test_install_is_default_off_preserves_prior_hook_and_is_linked_worktree_shared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    prior_hooks = tmp_path / "prior-hooks"
    prior_hooks.mkdir()
    prior_hook = prior_hooks / "pre-commit"
    prior_hook.write_text(
        "#!/bin/sh\nprintf prior-hook-called > prior-hook.marker\n",
        encoding="utf-8",
    )
    prior_hook.chmod(0o755)
    _git(repo, "config", "--local", "core.hooksPath", str(prior_hooks))

    preview = install_git_hook_provider(repo_path=repo, policy=_weekday_policy())
    assert preview["dry_run"] is True
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == str(
        prior_hooks
    )
    assert git_hook_provider_status(repo_path=repo)["status"] == "not_installed"

    installed = install_git_hook_provider(
        repo_path=repo,
        policy=_weekday_policy(),
        execute=True,
    )
    assert installed["enabled"] is True
    assert installed["contains_personal_path"] is False
    assert str(tmp_path) not in json.dumps(installed, sort_keys=True)

    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-b", "feature/linked", str(linked))
    linked_status = git_hook_provider_status(
        repo_path=linked,
        now=datetime.fromisoformat("2026-08-22T12:00:00+08:00"),
    )
    assert linked_status["ok"] is True
    assert linked_status["repository_id"] == installed["repository_id"]
    assert linked_status["contains_personal_path"] is False

    allowed = run_git_hook_provider(
        repo_path=linked,
        runtime_root=runtime_root,
        event="pre-commit",
        now=datetime.fromisoformat("2026-08-22T12:00:00+08:00"),
    )
    assert allowed["status"] == "allowed"
    assert allowed["previous_hook_invoked"] is True
    assert (linked / "prior-hook.marker").read_text(
        encoding="utf-8"
    ) == "prior-hook-called"

    blocked = run_git_hook_provider(
        repo_path=linked,
        runtime_root=runtime_root,
        event="pre-commit",
        now=datetime.fromisoformat("2026-08-18T12:00:00+08:00"),
    )
    assert blocked["status"] == "blocked_by_policy"
    assert blocked["pending_change"]["changed"] is True
    assert list_pending_changes(runtime_root=runtime_root)["count"] == 1

    uninstall_preview = uninstall_git_hook_provider(repo_path=linked)
    assert uninstall_preview["dry_run"] is True
    assert git_hook_provider_status(repo_path=repo)["installed"] is True
    uninstalled = uninstall_git_hook_provider(repo_path=linked, execute=True)
    assert uninstalled["status"] == "uninstalled"
    assert _git(repo, "config", "--local", "--get", "core.hooksPath") == str(
        prior_hooks
    )
    assert prior_hook.is_file()


def test_pending_change_ledger_is_restart_safe_idempotent_and_path_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    decision = evaluate_policy(
        _weekday_policy(),
        now=datetime.fromisoformat("2026-08-18T12:00:00+08:00"),
    )
    with pytest.raises(ValueError, match="absolute paths"):
        record_pending_change(
            runtime_root=runtime_root,
            repo_path=repo,
            decision=decision,
            source="manual_cli",
            validation_refs=["artifact:/home/example/private.log"],
        )
    with pytest.raises(ValueError, match="credentials"):
        record_pending_change(
            runtime_root=runtime_root,
            repo_path=repo,
            decision=decision,
            source="manual_cli",
            validation_refs=["Bear" + "er example-credential"],
        )
    first = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        goal_id="example-goal",
        todo_id="todo_example123",
        write_scopes=["loopx/**", "tests/**"],
        validation_refs=["pytest:focused:passed"],
        execute=True,
        now=datetime(2026, 8, 18, 4, 0, tzinfo=timezone.utc),
    )
    repeated = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        goal_id="example-goal",
        todo_id="todo_example123",
        write_scopes=["loopx/**", "tests/**"],
        validation_refs=["pytest:focused:passed"],
        execute=True,
        now=datetime(2026, 8, 18, 4, 1, tzinfo=timezone.utc),
    )
    assert first["changed"] is True
    assert repeated["duplicate"] is True

    automatic_refresh = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision={**decision, "observed_at": "2026-08-18T12:01:00+08:00"},
        source="git_hook:pre-commit",
        execute=True,
    )
    assert automatic_refresh["record"]["change_id"] == first["record"]["change_id"]
    assert automatic_refresh["record"]["goal_id"] == "example-goal"
    assert automatic_refresh["record"]["todo_id"] == "todo_example123"
    assert automatic_refresh["record"]["write_scopes"] == ["loopx/**", "tests/**"]

    restarted_read = list_pending_changes(runtime_root=runtime_root)
    assert restarted_read["count"] == 1
    serialized_projection = json.dumps(restarted_read, sort_keys=True)
    assert str(tmp_path) not in serialized_projection
    assert '"contains_code": false' in serialized_projection
    change_id = first["record"]["change_id"]
    assert (
        verify_pending_change(
            runtime_root=runtime_root,
            change_id=change_id,
        )["status"]
        == "verified"
    )

    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    drifted = verify_pending_change(runtime_root=runtime_root, change_id=change_id)
    assert drifted["status"] == "drifted"
    assert any(
        item["check"] == "worktree_fingerprint" and item["status"] == "changed"
        for item in drifted["checks"]
    )
    refreshed = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        goal_id="example-goal",
        todo_id="todo_example123",
        write_scopes=["loopx/**", "tests/**"],
        validation_refs=["pytest:focused:passed"],
        execute=True,
    )
    assert refreshed["transition"] == "refreshed"
    assert refreshed["changed"] is True

    untracked = repo / "new.txt"
    untracked.write_text("first\n", encoding="utf-8")
    untracked_record = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        goal_id="example-goal",
        todo_id="todo_example123",
        execute=True,
    )
    untracked.write_text("second\n", encoding="utf-8")
    assert (
        verify_pending_change(
            runtime_root=runtime_root,
            change_id=untracked_record["record"]["change_id"],
        )["status"]
        == "drifted"
    )
    untracked.unlink()
    record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        goal_id="example-goal",
        todo_id="todo_example123",
        execute=True,
    )

    resolved = resolve_pending_change(
        runtime_root=runtime_root,
        change_id=change_id,
        resolution="merged",
        evidence="github:example/change-window#42",
        execute=True,
    )
    duplicate_resolution = resolve_pending_change(
        runtime_root=runtime_root,
        change_id=change_id,
        resolution="merged",
        evidence="github:example/change-window#42",
        execute=True,
    )
    assert resolved["changed"] is True
    assert duplicate_resolution["duplicate"] is True
    assert list_pending_changes(runtime_root=runtime_root, state="open")["count"] == 0
    assert (
        list_pending_changes(runtime_root=runtime_root, state="resolved")["count"] == 1
    )
    assert (
        verify_pending_change(runtime_root=runtime_root, change_id=change_id)["status"]
        == "unlocatable"
    )


def test_verify_detects_missing_branch_and_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    decision = {"allowed": False, "reason": "test_gate"}

    linked = tmp_path / "linked-missing"
    _git(repo, "worktree", "add", "-b", "feature/missing", str(linked))
    recorded = record_pending_change(
        runtime_root=runtime_root,
        repo_path=linked,
        decision=decision,
        source="manual_cli",
        execute=True,
    )
    change_id = recorded["record"]["change_id"]
    _git(repo, "worktree", "remove", "--force", str(linked))
    missing_worktree = verify_pending_change(
        runtime_root=runtime_root,
        change_id=change_id,
    )
    assert missing_worktree["status"] == "missing_worktree"

    branch_record = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision=decision,
        source="manual_cli",
        change_id="change_missingbranch123",
        execute=True,
    )
    _git(repo, "switch", "-c", "temporary-current")
    _git(repo, "branch", "-D", "main")
    missing_branch = verify_pending_change(
        runtime_root=runtime_root,
        change_id=branch_record["record"]["change_id"],
    )
    assert any(
        item["check"] == "branch" and item["status"] == "missing"
        for item in missing_branch["checks"]
    )


def test_verify_detects_branch_movement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    recorded = record_pending_change(
        runtime_root=runtime_root,
        repo_path=repo,
        decision={"allowed": False, "reason": "test_gate"},
        source="manual_cli",
        execute=True,
    )
    (repo / "tracked.txt").write_text("advanced\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "advance")

    result = verify_pending_change(
        runtime_root=runtime_root,
        change_id=recorded["record"]["change_id"],
    )
    assert result["status"] == "drifted"
    assert any(
        item["check"] == "branch_head"
        and item["status"] == "advanced_or_rewritten"
        and item["ok"] is False
        for item in result["checks"]
    )


def test_cli_preview_and_global_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repository(tmp_path, monkeypatch)
    runtime_root = tmp_path / "runtime"
    args = [
        "--runtime-root",
        str(runtime_root),
        "--format",
        "json",
        "change-window",
        "install",
        "--repo-path",
        str(repo),
    ]
    assert main(args) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["dry_run"] is True
    assert git_hook_provider_status(repo_path=repo)["installed"] is False

    assert main([*args, "--execute"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["status"] == "installed"
    assert (
        main(
            [
                "--runtime-root",
                str(runtime_root),
                "--format",
                "json",
                "change-window",
                "list",
            ]
        )
        == 0
    )
    listed = json.loads(capsys.readouterr().out)
    assert listed["changes"] == []
