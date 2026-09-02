from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from loopx.cli_commands import todo as todo_command
from loopx.cli_commands import task_lease as task_lease_command
from loopx.control_plane import effect_runtime
from loopx.control_plane.coordination.runtime_shadow import (
    RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
    RUNTIME_SHADOW_METHOD,
    build_todo_runtime_shadow_projection,
    dispatch_coordination_runtime_shadow,
    load_task_lease_runtime_shadow_records,
    resolve_coordination_runtime_shadow_config,
)


def _dispatch(
    tmp_path: Path,
    goal: dict[str, object],
    runtime_invoker,
) -> dict[str, object]:
    return dispatch_coordination_runtime_shadow(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        operation_id="todo:goal-a:todo_one:v1",
        event_kind="todo_claim",
        source_version="state:1",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=runtime_invoker,
    )


def test_runtime_shadow_is_zero_call_default_off(tmp_path: Path) -> None:
    calls: list[object] = []

    result = _dispatch(tmp_path, {"id": "goal-a"}, lambda *args: calls.append(args))

    assert result["status"] == "disabled"
    assert result["reason_code"] == "configuration_absent"
    assert result["primary_writeback_preserved"] is True
    assert result["decision_read_from_shadow"] is False
    assert calls == []


def test_runtime_shadow_requires_complete_explicit_file_opt_in(tmp_path: Path) -> None:
    calls: list[object] = []
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": "wrong",
                "provider": "file_v0",
            }
        },
    }

    result = _dispatch(tmp_path, goal, lambda *args: calls.append(args))

    assert result["status"] == "disabled"
    assert result["reason_code"] == "schema_mismatch"
    assert calls == []
    assert resolve_coordination_runtime_shadow_config(goal).enabled is False


def test_runtime_shadow_dispatches_exact_typed_request_after_opt_in(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def invoke(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_coordination_runtime_shadow_result_v0",
            "status": "applied",
            "primary_writeback_preserved": True,
            "decision_read_from_shadow": False,
        }

    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }
    result = _dispatch(tmp_path, goal, invoke)

    assert result["status"] == "applied"
    assert captured["method"] == RUNTIME_SHADOW_METHOD
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["runtime_root"] == str(tmp_path.resolve())
    assert params["operation_id"] == "todo:goal-a:todo_one:v1"


def test_runtime_shadow_failure_never_changes_primary_truth(tmp_path: Path) -> None:
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }

    def fail(*_args) -> object:
        raise RuntimeError("runtime unavailable")

    result = _dispatch(tmp_path, goal, fail)

    assert result["status"] == "failed"
    assert result["reason_code"] == "shadow_runtime_unavailable"
    assert result["primary_writeback_preserved"] is True
    assert result["decision_read_from_shadow"] is False


def test_todo_projection_is_compact_stable_and_excludes_private_fields() -> None:
    projection = build_todo_runtime_shadow_projection(
        goal_id="goal-a",
        todos=[
            {
                "todo_id": "todo_b",
                "role": "agent",
                "status": "open",
                "claimed_by": "agent-a",
                "note": "private narrative must not enter coordination",
                "evidence": "large evidence must stay in its owning ledger",
            },
            {
                "todo_id": "todo_a",
                "role": "user",
                "status": "done",
                "successor_todo_ids": ["todo_b"],
            },
            {"status": "open"},
        ],
    )

    assert [item["todo_id"] for item in projection["todos"]] == [
        "todo_a",
        "todo_b",
    ]
    assert "note" not in projection["todos"][1]
    assert "evidence" not in projection["todos"][1]
    assert projection["leases"] == []


def test_committed_todo_hook_has_no_default_output_or_runtime_call(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        todo_command,
        "load_registry",
        lambda _path: {"goals": [{"id": "goal-a"}]},
    )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("default-off hook must not build or dispatch")

    monkeypatch.setattr(todo_command, "list_goal_todos", unexpected)
    monkeypatch.setattr(todo_command, "dispatch_coordination_runtime_shadow", unexpected)
    result = todo_command._mirror_committed_todo_runtime_shadow(
        {
            "ok": True,
            "dry_run": False,
            "changed": True,
            "updated_at": "2026-09-03T07:00:00+08:00",
            "rollout_event": {"event_id": "event-a"},
        },
        args=Namespace(
            goal_id="goal-a",
            todo_command="update",
            project=None,
            state_file=None,
        ),
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
    )

    assert result is None


def test_committed_todo_hook_dispatches_after_explicit_opt_in(
    monkeypatch,
    tmp_path: Path,
) -> None:
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }
    monkeypatch.setattr(
        todo_command,
        "load_registry",
        lambda _path: {"goals": [goal]},
    )
    monkeypatch.setattr(todo_command, "resolve_runtime_root", lambda *_args: tmp_path)
    monkeypatch.setattr(
        todo_command,
        "list_goal_todos",
        lambda **_kwargs: {
            "todos": [{"todo_id": "todo_one", "role": "agent", "status": "done"}]
        },
    )
    captured: dict[str, object] = {}

    def dispatch(**kwargs):
        captured.update(kwargs)
        return {"status": "applied"}

    monkeypatch.setattr(todo_command, "dispatch_coordination_runtime_shadow", dispatch)
    result = todo_command._mirror_committed_todo_runtime_shadow(
        {
            "ok": True,
            "dry_run": False,
            "changed": True,
            "updated_at": "2026-09-03T07:00:00+08:00",
            "rollout_event": {"event_id": "event-a"},
        },
        args=Namespace(
            goal_id="goal-a",
            todo_command="complete",
            project=None,
            state_file=None,
        ),
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
    )

    assert result == {"status": "applied"}
    assert captured["operation_id"] == "todo-shadow:event-a"
    assert captured["event_kind"] == "todo_complete"
    assert captured["projection"]["todos"] == [
        {"todo_id": "todo_one", "role": "agent", "status": "done"}
    ]


def test_committed_todo_hook_reaches_the_file_shadow_through_typescript(
    monkeypatch,
    tmp_path: Path,
) -> None:
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }
    monkeypatch.setattr(
        todo_command,
        "load_registry",
        lambda _path: {"goals": [goal]},
    )
    monkeypatch.setattr(
        todo_command,
        "resolve_runtime_root",
        lambda *_args: tmp_path / "state",
    )
    monkeypatch.setattr(
        todo_command,
        "list_goal_todos",
        lambda **_kwargs: {
            "todos": [
                {
                    "todo_id": "todo_one",
                    "role": "agent",
                    "status": "open",
                    "claimed_by": "agent-a",
                }
            ]
        },
    )
    monkeypatch.setattr(
        effect_runtime,
        "_runtime_dir",
        lambda: tmp_path / "effect-runtime",
    )

    try:
        result = todo_command._mirror_committed_todo_runtime_shadow(
            {
                "ok": True,
                "dry_run": False,
                "changed": True,
                "updated_at": "2026-09-03T07:30:00+08:00",
                "rollout_event": {"event_id": "event-real-runtime"},
            },
            args=Namespace(
                goal_id="goal-a",
                todo_command="claim",
                project=None,
                state_file=None,
            ),
            registry_path=tmp_path / "registry.json",
            runtime_root_arg=None,
        )
    finally:
        effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)

    assert result is not None
    assert result["status"] == "applied"
    assert result["decision_read_from_shadow"] is False
    assert result["parity"]["receipt_matches"] is True
    assert result["parity"]["projection_readback"]["verified"] is True


def test_lease_projection_reads_compact_terminal_records(tmp_path: Path) -> None:
    lease_dir = tmp_path / "goals" / "goal-a" / "task-leases"
    lease_dir.mkdir(parents=True)
    (lease_dir / "todo_b.json").write_text(
        '{"schema_version":"task_lease_v0","goal_id":"goal-a",'
        '"todo_id":"todo_b","owner":"agent-a","version":2,'
        '"lease_epoch":1,"status":"released","released_at":"later",'
        '"idempotency_key":"must-not-enter-projection"}',
        encoding="utf-8",
    )

    records = load_task_lease_runtime_shadow_records(
        runtime_root=tmp_path,
        goal_id="goal-a",
    )

    assert records == [
        {
            "todo_id": "todo_b",
            "owner": "agent-a",
            "version": 2,
            "lease_epoch": 1,
            "released_at": "later",
            "status": "released",
        }
    ]


def test_committed_task_lease_hook_dispatches_full_coordination_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }
    monkeypatch.setattr(
        task_lease_command,
        "load_registry",
        lambda _path: {"goals": [goal]},
    )
    monkeypatch.setattr(
        task_lease_command,
        "list_goal_todos",
        lambda **_kwargs: {
            "todos": [{"todo_id": "todo_one", "role": "agent", "status": "open"}]
        },
    )
    monkeypatch.setattr(
        task_lease_command,
        "load_task_lease_runtime_shadow_records",
        lambda **_kwargs: [
            {
                "todo_id": "todo_one",
                "owner": "agent-a",
                "version": 1,
                "lease_epoch": 1,
                "status": "active",
            }
        ],
    )
    captured: dict[str, object] = {}

    def dispatch(**kwargs):
        captured.update(kwargs)
        return {"status": "applied"}

    monkeypatch.setattr(
        task_lease_command,
        "dispatch_coordination_runtime_shadow",
        dispatch,
    )
    result = task_lease_command._mirror_committed_task_lease_runtime_shadow(
        {
            "ok": True,
            "lease": {
                "todo_id": "todo_one",
                "updated_at": "2026-09-03T07:05:00Z",
            },
        },
        args=Namespace(
            goal_id="goal-a",
            todo_id="todo_one",
            task_lease_command="acquire",
            idempotency_key="acquire-1",
        ),
        registry_path=tmp_path / "registry.json",
        runtime_root_arg=None,
        runtime_root=tmp_path,
    )

    assert result == {"status": "applied"}
    assert captured["operation_id"] == (
        "task-lease-shadow:acquire:goal-a:todo_one:acquire-1"
    )
    assert captured["event_kind"] == "task_lease_acquire"
    assert captured["projection"]["leases"] == [
        {
            "todo_id": "todo_one",
            "owner": "agent-a",
            "version": 1,
            "lease_epoch": 1,
            "status": "active",
        }
    ]


def test_committed_task_lease_hook_reaches_file_shadow_through_typescript(
    monkeypatch,
    tmp_path: Path,
) -> None:
    goal = {
        "id": "goal-a",
        "coordination": {
            "runtime_shadow": {
                "enabled": True,
                "schema_version": RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
                "provider": "file_v0",
            }
        },
    }
    monkeypatch.setattr(
        task_lease_command,
        "load_registry",
        lambda _path: {"goals": [goal]},
    )
    monkeypatch.setattr(
        task_lease_command,
        "list_goal_todos",
        lambda **_kwargs: {
            "todos": [{"todo_id": "todo_one", "role": "agent", "status": "open"}]
        },
    )
    lease_dir = tmp_path / "state" / "goals" / "goal-a" / "task-leases"
    lease_dir.mkdir(parents=True)
    (lease_dir / "todo_one.json").write_text(
        '{"todo_id":"todo_one","owner":"agent-a","version":1,'
        '"lease_epoch":1,"updated_at":"2026-09-03T07:35:00Z",'
        '"status":"active"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        effect_runtime,
        "_runtime_dir",
        lambda: tmp_path / "effect-runtime",
    )

    try:
        result = task_lease_command._mirror_committed_task_lease_runtime_shadow(
            {
                "ok": True,
                "lease": {
                    "todo_id": "todo_one",
                    "updated_at": "2026-09-03T07:35:00Z",
                },
            },
            args=Namespace(
                goal_id="goal-a",
                todo_id="todo_one",
                task_lease_command="acquire",
                idempotency_key="lease-real-runtime",
            ),
            registry_path=tmp_path / "registry.json",
            runtime_root_arg=None,
            runtime_root=tmp_path / "state",
        )
    finally:
        effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)

    assert result is not None
    assert result["status"] == "applied"
    assert result["decision_read_from_shadow"] is False
    assert result["parity"]["receipt_matches"] is True
    assert result["parity"]["projection_readback"]["verified"] is True
