from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.experiments.planner_worker.contract import (
    AdapterTurn,
    PLANNER_WORKER_PLAN_SCHEMA_VERSION,
    PLANNER_WORKER_STEP_SCHEMA_VERSION,
    ValidationResult,
)
from loopx.experiments.planner_worker.runtime import (
    WorkspaceChange,
    run_planner_worker_once,
)
from loopx.experiments.planner_worker.traex import (
    GitWorkspaceObserver,
    SubprocessValidationRunner,
)


def executable_plan() -> dict:
    return {
        "schema_version": PLANNER_WORKER_PLAN_SCHEMA_VERSION,
        "plan_id": "runtime-plan",
        "objective": "Update one fixture.",
        "steps": [
            {
                "schema_version": PLANNER_WORKER_STEP_SCHEMA_VERSION,
                "step_id": "edit-fixture",
                "planner_order": 1,
                "role": "worker",
                "target_files": ["result.txt"],
                "action_kind": "edit",
                "recommended_executor": "cheap_worker",
                "worker_model_tier": "cheap",
                "worker_autonomy": "bounded",
                "worker_ready": True,
                "worker_blockers": [],
                "context_budget": {
                    "max_files": 1,
                    "max_bytes_per_file": 4096,
                    "allow_extra_files": False,
                },
                "research_summary": "The fixture contains one stale value.",
                "implementation_notes": "Replace the stale value.",
                "instruction": "Write expected to result.txt.",
                "depends_on": [],
                "validation_commands": ["python3 verify.py"],
                "done_criteria": ["verify.py exits zero"],
                "escalation_policy": "Stop if result.txt is outside the workspace.",
                "verification": "Run python3 verify.py.",
            }
        ],
    }


class FakePlanner:
    def __init__(self, plan: dict) -> None:
        self.output_plan = plan
        self.calls = 0

    def plan(self, *, prompt: str, model_route: dict[str, str], cwd: Path) -> AdapterTurn:
        self.calls += 1
        assert model_route["model"] == "gpt-5.5"
        return AdapterTurn(
            output_text=json.dumps(self.output_plan),
            usage={"input_tokens": 100, "output_tokens": 40},
            usage_complete=True,
        )


class FixtureWorker:
    def __init__(
        self,
        *,
        expected_model: str = "deepseek-v4-flash",
        extra_file: str | None = None,
    ) -> None:
        self.calls = 0
        self.model_routes: list[dict[str, str]] = []
        self.expected_model = expected_model
        self.extra_file = extra_file

    def execute(self, *, prompt: str, model_route: dict[str, str], cwd: Path) -> AdapterTurn:
        self.calls += 1
        self.model_routes.append(model_route)
        assert model_route["model"] == self.expected_model
        assert "Do not re-plan the whole task" in prompt
        (cwd / "result.txt").write_text("expected\n", encoding="utf-8")
        if self.extra_file:
            (cwd / self.extra_file).write_text("outside scope\n", encoding="utf-8")
        return AdapterTurn(
            output_text="updated result.txt",
            usage={"input_tokens": 60, "output_tokens": 20},
            usage_complete=True,
        )


def fixture_validation(command: str, cwd: Path) -> ValidationResult:
    passed = command == "python3 verify.py" and (cwd / "result.txt").read_text(
        encoding="utf-8"
    ) == "expected\n"
    return ValidationResult(command=command, passed=passed, exit_code=0 if passed else 1)


class FixtureWorkspaceObserver:
    def __init__(self) -> None:
        self.before: dict[str, bytes] = {}

    def _snapshot(self, cwd: Path) -> dict[str, bytes]:
        return {
            path.relative_to(cwd).as_posix(): path.read_bytes()
            for path in cwd.rglob("*")
            if path.is_file() and ".git" not in path.parts
        }

    def assert_clean(self, cwd: Path) -> None:
        self.before = self._snapshot(cwd)

    def changed_files(self, cwd: Path) -> dict[str, WorkspaceChange]:
        after = self._snapshot(cwd)
        changed = {
            path
            for path in {*self.before, *after}
            if self.before.get(path) != after.get(path)
        }
        return {
            path: {
                "size": len(after[path]) if path in after else None,
                "file_type": "regular" if path in after else "deleted",
            }
            for path in sorted(changed)
        }


def test_runtime_executes_selected_step_validates_and_emits_receipt(tmp_path: Path) -> None:
    planner = FakePlanner(executable_plan())
    worker = FixtureWorker()

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=planner,
        worker=worker,
        validation_runner=fixture_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert planner.calls == 1
    assert worker.calls == 1
    assert worker.model_routes == [{"model": "deepseek-v4-flash", "effort": "medium"}]
    assert receipt["schema_version"] == "planner_worker_receipt_v0"
    assert receipt["status"] == "completed"
    assert receipt["plan_id"] == "runtime-plan"
    assert receipt["step_id"] == "edit-fixture"
    assert receipt["executor"] == "cheap_worker"
    assert receipt["model_route"]["model"] == "deepseek-v4-flash"
    assert receipt["validation"] == [
        {"command": "python3 verify.py", "passed": True, "exit_code": 0}
    ]
    assert receipt["usage"] == {
        "complete": True,
        "input_tokens": 160,
        "output_tokens": 60,
        "total_tokens": 220,
    }
    assert receipt["cost"] == {
        "complete": False,
        "amount": None,
        "currency": None,
        "reason": "model pricing was not supplied",
    }


def test_runtime_validation_failure_cannot_report_delivery_success(tmp_path: Path) -> None:
    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=FixtureWorker(),
        validation_runner=lambda command, cwd: ValidationResult(
            command=command,
            passed=False,
            exit_code=1,
        ),
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"][0]["passed"] is False


def test_runtime_strong_step_uses_strong_model_route(tmp_path: Path) -> None:
    plan = executable_plan()
    plan["steps"][0]["recommended_executor"] = "strong_worker"
    plan["steps"][0]["worker_model_tier"] = "strong"
    worker = FixtureWorker(expected_model="gpt-5.5")

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=worker,
        validation_runner=fixture_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "completed"
    assert receipt["executor"] == "strong_worker"
    assert receipt["model_route"]["model"] == "gpt-5.5"


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("not_ready", "blocked"),
        ("blocker", "blocked"),
        ("planner_only", "planner_required"),
        ("dependency", "waiting_dependencies"),
    ],
)
def test_runtime_ineligible_step_does_not_call_worker(
    tmp_path: Path,
    case: str,
    expected_status: str,
) -> None:
    plan = executable_plan()
    if case == "not_ready":
        plan["steps"][0]["worker_ready"] = False
    elif case == "blocker":
        plan["steps"][0]["worker_ready"] = False
        plan["steps"][0]["worker_blockers"] = ["Planner needs one missing symbol."]
    elif case == "planner_only":
        plan["steps"][0]["recommended_executor"] = "planner_only"
        plan["steps"][0]["worker_model_tier"] = "none"
        plan["steps"][0]["worker_ready"] = False
    else:
        dependency = {
            **plan["steps"][0],
            "step_id": "inspect-first",
            "planner_order": 2,
            "recommended_executor": "planner_only",
            "worker_model_tier": "none",
            "worker_ready": False,
        }
        plan["steps"][0]["planner_order"] = 1
        plan["steps"][0]["depends_on"] = ["inspect-first"]
        plan["steps"].append(dependency)
    worker = FixtureWorker()

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=worker,
        validation_runner=fixture_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert worker.calls == 0
    assert receipt["status"] == expected_status
    assert receipt["step_id"] == "edit-fixture"
    assert receipt["validation"] == []


def test_runtime_rejects_worker_changes_outside_plan_scope(tmp_path: Path) -> None:
    worker = FixtureWorker(extra_file="unplanned.txt")

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=worker,
        validation_runner=fixture_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"] == []
    assert "unplanned.txt" in receipt["write_scope"]["violations"]


def test_runtime_rejects_unapproved_planner_validation_before_worker(
    tmp_path: Path,
) -> None:
    worker = FixtureWorker()

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=worker,
        validation_runner=fixture_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 approved.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert worker.calls == 0
    assert receipt["status"] == "failed"
    assert "did not approve" in receipt["reason"]


@pytest.mark.parametrize("symlink_kind", ["file", "directory"])
def test_runtime_rejects_preexisting_symlink_escape_before_worker(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    import os
    import subprocess

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_result = outside / "result.txt"
    outside_result.write_text("outside\n", encoding="utf-8")
    plan = executable_plan()
    if symlink_kind == "file":
        os.symlink(outside_result, workspace / "result.txt")
    else:
        os.symlink(outside, workspace / "linked")
        plan["steps"][0]["target_files"] = ["linked/result.txt"]
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "--", "."], cwd=workspace, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=workspace,
        check=True,
    )

    class EscapingWorker:
        def __init__(self) -> None:
            self.calls = 0

        def execute(
            self,
            *,
            prompt: str,
            model_route: dict[str, str],
            cwd: Path,
        ) -> AdapterTurn:
            self.calls += 1
            target = "result.txt" if symlink_kind == "file" else "linked/result.txt"
            (cwd / target).write_text("escaped\n", encoding="utf-8")
            return AdapterTurn(output_text="wrote target", usage={}, usage_complete=False)

    worker = EscapingWorker()
    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=workspace,
        planner=FakePlanner(plan),
        worker=worker,
        validation_runner=lambda command, cwd: ValidationResult(
            command=command,
            passed=True,
            exit_code=0,
        ),
        workspace_observer=GitWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert worker.calls == 0
    assert outside_result.read_text(encoding="utf-8") == "outside\n"
    assert receipt["status"] == "failed"
    assert receipt["write_scope"]["passed"] is False
    assert any(
        violation.endswith(":resolved_outside_workspace")
        for violation in receipt["write_scope"]["violations"]
    )


def test_runtime_revalidates_target_path_after_worker(tmp_path: Path) -> None:
    import os

    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")

    class SymlinkWorker:
        def execute(
            self,
            *,
            prompt: str,
            model_route: dict[str, str],
            cwd: Path,
        ) -> AdapterTurn:
            os.symlink(outside, cwd / "result.txt")
            return AdapterTurn(output_text="linked target", usage={}, usage_complete=False)

    receipt = run_planner_worker_once(
        objective="Create one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=SymlinkWorker(),
        validation_runner=lambda command, cwd: ValidationResult(
            command=command,
            passed=True,
            exit_code=0,
        ),
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"] == []
    assert receipt["write_scope"]["passed"] is False
    assert "result.txt:resolved_outside_workspace" in receipt["write_scope"]["violations"]


def test_runtime_rejects_extra_symlink_when_extra_files_are_allowed(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "result.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "result.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    plan = executable_plan()
    plan["steps"][0]["context_budget"]["allow_extra_files"] = True
    plan["steps"][0]["context_budget"]["max_files"] = 2

    class ExtraSymlinkWorker:
        def execute(
            self,
            *,
            prompt: str,
            model_route: dict[str, str],
            cwd: Path,
        ) -> AdapterTurn:
            (cwd / "result.txt").write_text("expected\n", encoding="utf-8")
            os.symlink(outside, cwd / "extra-link")
            return AdapterTurn(
                output_text="updated fixture", usage={}, usage_complete=False
            )

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=ExtraSymlinkWorker(),
        validation_runner=fixture_validation,
        workspace_observer=GitWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"] == []
    assert receipt["write_scope"]["unsupported_paths"] == ["extra-link"]
    assert (
        "extra-link:unsupported_file_type:symlink"
        in receipt["write_scope"]["violations"]
    )


def test_runtime_audits_validation_changes_before_success(tmp_path: Path) -> None:
    def mutating_validation(command: str, cwd: Path) -> ValidationResult:
        (cwd / "validation-side-effect.txt").write_text("dirty\n", encoding="utf-8")
        return ValidationResult(command=command, passed=True, exit_code=0)

    receipt = run_planner_worker_once(
        objective="Update one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(executable_plan()),
        worker=FixtureWorker(),
        validation_runner=mutating_validation,
        workspace_observer=FixtureWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["validation"] == [
        {"command": "python3 verify.py", "passed": True, "exit_code": 0}
    ]
    assert receipt["write_scope"]["changed_files"]["validation-side-effect.txt"] == {
        "size": len("dirty\n"),
        "file_type": "regular",
    }
    assert "validation-side-effect.txt" in receipt["write_scope"]["violations"]


@pytest.mark.parametrize(
    "command",
    [
        "/tmp/python3 verify.py",
        "python3 -c 'print(1)'",
        "sh verify.sh",
    ],
)
def test_subprocess_validation_rejects_unbounded_command_shapes(
    tmp_path: Path,
    command: str,
) -> None:
    result = SubprocessValidationRunner(
        timeout_seconds=1,
        approved_commands=frozenset({command}),
    )(command, tmp_path)

    assert result.passed is False
    assert result.exit_code is None


def test_git_workspace_observer_detects_ignored_private_state_change(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("private.txt\n", encoding="utf-8")
    (tmp_path / "private.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    (tmp_path / "private.txt").write_text("after\n", encoding="utf-8")

    assert observer.changed_files(tmp_path) == {
        "private.txt": {"size": len("after\n"), "file_type": "regular"}
    }


def test_git_workspace_observer_detects_file_mode_change(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("unchanged\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    tracked.chmod(0o755)

    assert observer.changed_files(tmp_path) == {
        "tracked.txt": {"size": len("unchanged\n"), "file_type": "regular"}
    }


def test_git_workspace_observer_detects_directory_mode_change(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "tracked.txt").write_text("unchanged\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "pkg/tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    current_mode = package.stat().st_mode & 0o777
    package.chmod(0o755 if current_mode != 0o755 else 0o700)

    assert observer.changed_files(tmp_path) == {
        "pkg": {"size": None, "file_type": "directory"}
    }


def test_git_workspace_observer_reports_new_directory_by_leaf_file(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    nested = tmp_path / "new" / "result.txt"
    nested.parent.mkdir()
    nested.write_text("created\n", encoding="utf-8")

    assert observer.changed_files(tmp_path) == {
        "new/result.txt": {"size": len("created\n"), "file_type": "regular"}
    }


def test_git_workspace_observer_detects_worktree_mode_change(
    tmp_path: Path,
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    current_mode = tmp_path.stat().st_mode & 0o777
    tmp_path.chmod(0o755 if current_mode != 0o755 else 0o700)

    assert observer.changed_files(tmp_path) == {
        ".": {"size": None, "file_type": "directory"}
    }


def test_git_workspace_observer_detects_fifo_without_blocking(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    observer = GitWorkspaceObserver()
    observer.assert_clean(tmp_path)

    os.mkfifo(tmp_path / "worker.fifo")

    assert observer.changed_files(tmp_path) == {
        "worker.fifo": {"size": None, "file_type": "special"}
    }


def test_git_workspace_observer_detects_unix_socket() -> None:
    import errno
    import socket
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory(prefix="lx-pw-", dir="/tmp") as tmp:
        short_path = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=short_path, check=True)
        (short_path / "tracked.txt").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", "tracked.txt"], cwd=short_path, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=LoopX Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=short_path,
            check=True,
        )
        observer = GitWorkspaceObserver()
        observer.assert_clean(short_path)

        worker_socket = socket.socket(socket.AF_UNIX)
        try:
            try:
                worker_socket.bind(str(short_path / "worker.sock"))
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EPERM}:
                    pytest.skip("sandbox does not permit creating Unix sockets")
                raise
            assert observer.changed_files(short_path) == {
                "worker.sock": {"size": None, "file_type": "special"}
            }
        finally:
            worker_socket.close()


def test_runtime_rejects_special_file_even_when_planner_targets_it(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "--", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=LoopX Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    plan = executable_plan()
    plan["steps"][0]["target_files"] = ["worker.fifo"]
    validation_calls: list[str] = []

    class FifoWorker:
        def execute(
            self,
            *,
            prompt: str,
            model_route: dict[str, str],
            cwd: Path,
        ) -> AdapterTurn:
            os.mkfifo(cwd / "worker.fifo")
            return AdapterTurn(
                output_text="created fifo",
                usage={},
                usage_complete=False,
            )

    def validation(command: str, cwd: Path) -> ValidationResult:
        validation_calls.append(command)
        return ValidationResult(command=command, passed=True, exit_code=0)

    receipt = run_planner_worker_once(
        objective="Create one fixture.",
        task_instruction="Use the Planner result.",
        cwd=tmp_path,
        planner=FakePlanner(plan),
        worker=FifoWorker(),
        validation_runner=validation,
        workspace_observer=GitWorkspaceObserver(),
        approved_validation_commands={"python3 verify.py"},
        model_routes={
            "planner": {"model": "gpt-5.5", "effort": "high"},
            "cheap_worker": {"model": "deepseek-v4-flash", "effort": "medium"},
            "strong_worker": {"model": "gpt-5.5", "effort": "high"},
        },
    )

    assert receipt["status"] == "failed"
    assert receipt["write_scope"]["passed"] is False
    assert receipt["write_scope"]["unsupported_paths"] == ["worker.fifo"]
    assert receipt["validation"] == []
    assert validation_calls == []
