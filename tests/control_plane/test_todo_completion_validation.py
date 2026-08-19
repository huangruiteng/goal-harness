from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

import pytest

import loopx.control_plane.todos.completion_validation as completion_validation_module
from loopx.status import parse_active_state_todos
from loopx.todos import add_goal_todo, complete_goal_todo, update_goal_todo

GOAL_ID = "todo-completion-validation"
AGENT = "codex-author"

_PASS_COMMAND = f'{shlex.quote(sys.executable)} -c "raise SystemExit(0)"'
_FAIL_COMMAND = f'{shlex.quote(sys.executable)} -c "raise SystemExit(1)"'
_SLEEP_COMMAND = f'{shlex.quote(sys.executable)} -c "import time; time.sleep(30)"'


def _write_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "\n".join(
            [
                "---",
                f"goal_id: {GOAL_ID}",
                "updated_at: 2026-08-12T00:00:00+00:00",
                "---",
                "",
                "## Agent Todo",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.global.json"
    registry.write_text(
        json.dumps(
            {
                "common_runtime_root": str(tmp_path / "runtime"),
                "goals": [
                    {
                        "id": GOAL_ID,
                        "domain": "harness_self_improvement",
                        "status": "active",
                        "repo": str(repo),
                        "state_file": state.name,
                        "adapter": {"kind": "harness_self_improvement"},
                        "coordination": {
                            "agent_model": "peer_v1",
                            "registered_agents": [AGENT],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state


def _agent_todo(state: Path, todo_id: str) -> dict:
    todos = parse_active_state_todos(state.read_text(encoding="utf-8"))
    return next(
        item
        for item in todos["agent_todos"]["items"]
        if item["todo_id"] == todo_id
    )


def _add_todo(
    registry: Path,
    *,
    validation_command: str | None = None,
    validation_command_json: str | None = None,
    validation_label: str | None = None,
    validation_timeout_seconds: int | None = None,
) -> dict:
    return add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text="Deliver one bounded change.",
        task_class="advancement_task",
        claimed_by=AGENT,
        validation_command=validation_command,
        validation_command_json=validation_command_json,
        validation_label=validation_label,
        validation_timeout_seconds=validation_timeout_seconds,
    )


def test_validation_command_declared_and_passing_commits_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(
        registry,
        validation_command=_PASS_COMMAND,
        validation_label="caller-declared smoke",
    )
    # Spy on the executor so the test fails if the gate is silently skipped.
    original_runner = completion_validation_module.run_caller_validation
    calls = {"count": 0}

    def counting_runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return original_runner(*args, **kwargs)

    monkeypatch.setattr(completion_validation_module, "run_caller_validation", counting_runner)

    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="validated completion",
    )
    assert calls["count"] == 1  # the gate actually ran the declared command
    assert result["ok"] is True
    assert result["changed"] is True
    assert "validation_blocked_completion" not in result
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "done"


def test_missing_validation_executable_returns_typed_receipt(
    tmp_path: Path,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(registry, validation_command="nonexistent-binary-xyz-12345")
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["status"] == "command_not_run"
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_malformed_validation_command_returns_typed_receipt(
    tmp_path: Path,
) -> None:
    registry, state = _write_fixture(tmp_path)
    # Unbalanced quote -> shlex.split raises ValueError -> typed receipt.
    todo = _add_todo(registry, validation_command="echo 'unbalanced")
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["status"] == "command_malformed"
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_validation_command_declared_and_failing_blocks_completion(
    tmp_path: Path,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(
        registry,
        validation_command=_FAIL_COMMAND,
        validation_label="caller-declared smoke",
    )
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    # Completion is blocked: nothing committed, evidence stays only a claim.
    assert result["ok"] is False
    assert result["completed"] is False
    assert result["changed"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["exit_code"] == 1
    assert receipt["command_label"] == "caller-declared smoke"
    # Privacy invariant preserved.
    assert receipt["stdout_captured"] is False
    assert receipt["stderr_captured"] is False
    assert receipt["local_path_captured"] is False
    # State is unchanged: the todo is still open.
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_no_validation_command_keeps_fast_path_unchanged(tmp_path: Path) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(registry)  # no validation_command declared
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="plain completion",
    )
    assert result["ok"] is True
    assert result["changed"] is True
    assert "validation_blocked_completion" not in result
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "done"


def test_validation_timeout_blocks_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        completion_validation_module, "_COMPLETION_VALIDATION_TIMEOUT_SECONDS", 0.5
    )
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(registry, validation_command=_SLEEP_COMMAND)
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["status"] == "timeout"
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_terminal_replay_short_circuits_before_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(registry, validation_command=_PASS_COMMAND)

    original_runner = completion_validation_module.run_caller_validation
    calls = {"count": 0}

    def counting_runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return original_runner(*args, **kwargs)

    monkeypatch.setattr(completion_validation_module, "run_caller_validation", counting_runner)

    first = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="validated completion",
    )
    assert first["ok"] is True
    assert calls["count"] == 1  # validation ran once on the real completion

    replay = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="duplicate completion",
    )
    # Replay short-circuits before the validation gate; the command is not re-run.
    assert calls["count"] == 1
    assert replay["ok"] is True


def test_per_todo_validation_timeout_overrides_default(tmp_path: Path) -> None:
    registry, state = _write_fixture(tmp_path)
    # A 1s per-todo timeout cuts the sleeping command off long before the 20s
    # module default, and the typed receipt reports the declared value.
    todo = _add_todo(
        registry,
        validation_command=_SLEEP_COMMAND,
        validation_timeout_seconds=1,
    )
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["status"] == "timeout"
    assert "timed out after 1s" in receipt["summary"]
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_validation_timeout_out_of_range_rejected(tmp_path: Path) -> None:
    registry, _state = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="1 and 29"):
        _add_todo(
            registry,
            validation_command=_PASS_COMMAND,
            validation_timeout_seconds=30,
        )


def test_validation_timeout_requires_validation_command(tmp_path: Path) -> None:
    registry, _state = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="requires --validation-command"):
        _add_todo(registry, validation_timeout_seconds=5)


def test_validation_command_json_passing_commits_completion(
    tmp_path: Path,
) -> None:
    registry, state = _write_fixture(tmp_path)
    pass_argv = json.dumps([sys.executable, "-c", "raise SystemExit(0)"])
    todo = _add_todo(
        registry,
        validation_command_json=pass_argv,
        validation_label="argv-form smoke",
    )
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="validated completion",
    )
    assert result["ok"] is True
    assert "validation_blocked_completion" not in result
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "done"


def test_validation_command_json_failing_blocks_completion(
    tmp_path: Path,
) -> None:
    registry, state = _write_fixture(tmp_path)
    fail_argv = json.dumps([sys.executable, "-c", "raise SystemExit(1)"])
    todo = _add_todo(registry, validation_command_json=fail_argv)
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["exit_code"] == 1
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_validation_command_forms_mutually_exclusive(tmp_path: Path) -> None:
    registry, _state = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="mutually exclusive"):
        _add_todo(
            registry,
            validation_command=_PASS_COMMAND,
            validation_command_json=json.dumps([sys.executable, "-c", "pass"]),
        )


@pytest.mark.parametrize(
    "payload",
    [
        "not json at all",
        '{"not":"a list"}',
        "[]",
        json.dumps([sys.executable, 123]),
        json.dumps([sys.executable, ""]),
    ],
)
def test_validation_command_json_must_be_nonempty_string_array(
    tmp_path: Path, payload: str
) -> None:
    registry, _state = _write_fixture(tmp_path)
    with pytest.raises(ValueError, match="must be a JSON string array"):
        _add_todo(registry, validation_command_json=payload)


def test_validation_timeout_works_with_command_json(tmp_path: Path) -> None:
    registry, state = _write_fixture(tmp_path)
    sleep_argv = json.dumps([sys.executable, "-c", "import time; time.sleep(30)"])
    todo = _add_todo(
        registry,
        validation_command_json=sleep_argv,
        validation_timeout_seconds=1,
    )
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    receipt = result["validation"]
    assert receipt["status"] == "timeout"
    assert "timed out after 1s" in receipt["summary"]
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_corrupted_argv_declaration_fails_closed(tmp_path: Path) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(
        registry,
        validation_command_json=json.dumps(
            [sys.executable, "-c", "raise SystemExit(0)"]
        ),
    )
    # Corrupt the persisted argv declaration in place; completion must run the
    # gate and fail closed as a malformed command, never silently skip it.
    text = state.read_text(encoding="utf-8")
    corrupted, substitutions = re.subn(
        r"validation_command_argv=\S+",
        "validation_command_argv=%5Bbroken",
        text,
    )
    assert substitutions == 1
    state.write_text(corrupted, encoding="utf-8")
    result = complete_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        agent_id=AGENT,
        evidence="claim of completion",
    )
    assert result["ok"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["status"] == "command_malformed"
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_empty_argv_declaration_reports_neutral_message(
    tmp_path: Path,
) -> None:
    # An argv declaration collapsing to [] (e.g. corrupted on disk) surfaces
    # the form-neutral empty-command error inside the malformed receipt.
    registry, _state = _write_fixture(tmp_path)
    receipt = completion_validation_module._run_declared_completion_validation(
        validation_command=None,
        validation_argv=[],
        validation_label=None,
        validation_timeout_seconds=None,
        registry_path=registry,
        goal_id=GOAL_ID,
    )
    assert receipt is not None
    assert receipt["status"] == "command_malformed"
    assert "validation command must not be empty" in receipt["summary"]


def _user_todo(state: Path, todo_id: str) -> dict:
    todos = parse_active_state_todos(state.read_text(encoding="utf-8"))
    return next(
        item
        for item in todos["user_todos"]["items"]
        if item["todo_id"] == todo_id
    )


def _spy_validation_runner(monkeypatch: pytest.MonkeyPatch) -> dict:
    original_runner = completion_validation_module.run_caller_validation
    calls = {"count": 0}

    def counting_runner(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return original_runner(*args, **kwargs)

    monkeypatch.setattr(
        completion_validation_module, "run_caller_validation", counting_runner
    )
    return calls


def test_user_todo_update_done_runs_declared_validation_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="user",
        text="Operator-recorded outcome.",
        task_class="user_action",
        validation_command=_FAIL_COMMAND,
        validation_label="caller-declared smoke",
    )
    calls = _spy_validation_runner(monkeypatch)
    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        status="done",
        evidence="claim of completion",
    )
    # The declared command ran once and blocked the update: nothing committed.
    assert calls["count"] == 1
    assert result["ok"] is False
    assert result["changed"] is False
    assert result["validation_blocked_completion"] is True
    receipt = result["validation"]
    assert receipt["passed"] is False
    assert receipt["exit_code"] == 1
    assert receipt["stdout_captured"] is False
    assert _user_todo(state, str(todo["todo_id"]))["status"] == "open"


def test_user_todo_update_done_without_declaration_keeps_fast_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="user",
        text="Operator-recorded outcome.",
        task_class="user_action",
    )
    calls = _spy_validation_runner(monkeypatch)
    result = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        status="done",
    )
    assert calls["count"] == 0
    assert result["ok"] is True
    assert "validation_blocked_completion" not in result
    assert _user_todo(state, str(todo["todo_id"]))["status"] == "done"


def test_repeated_done_update_does_not_rerun_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="user",
        text="Operator-recorded outcome.",
        task_class="user_action",
        validation_command=_PASS_COMMAND,
    )
    calls = _spy_validation_runner(monkeypatch)
    first = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        status="done",
        evidence="validated completion",
    )
    assert first["ok"] is True
    assert calls["count"] == 1  # the passing command ran once via the update gate
    assert _user_todo(state, str(todo["todo_id"]))["status"] == "done"

    second = update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=str(todo["todo_id"]),
        status="done",
        note="re-acknowledged",
    )
    # Already-completed short-circuit: the command is not re-run.
    assert second["ok"] is True
    assert calls["count"] == 1
    assert _user_todo(state, str(todo["todo_id"]))["status"] == "done"


def test_agent_todo_update_done_keeps_guard_error_without_running_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, state = _write_fixture(tmp_path)
    todo = _add_todo(registry, validation_command=_FAIL_COMMAND)
    calls = _spy_validation_runner(monkeypatch)
    with pytest.raises(ValueError, match="must use complete_goal_todo"):
        update_goal_todo(
            registry_path=registry,
            goal_id=GOAL_ID,
            todo_id=str(todo["todo_id"]),
            status="done",
        )
    # The gate never runs for agent sections; the pre-existing guard fires.
    assert calls["count"] == 0
    assert _agent_todo(state, str(todo["todo_id"]))["status"] == "open"
