from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from loopx.cli_commands import todo as todo_command
from loopx.cli_commands import task_lease as task_lease_command
from loopx.control_plane import effect_runtime
from loopx.control_plane.coordination.runtime_shadow import (
    RUNTIME_SHADOW_BOOTSTRAP_METHOD,
    RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA_VERSION,
    RUNTIME_SHADOW_CONFIG_SCHEMA_VERSION,
    RUNTIME_SHADOW_METHOD,
    RUNTIME_SHADOW_ROLLBACK_METHOD,
    RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA_VERSION,
    bootstrap_coordination_runtime_shadow,
    build_todo_runtime_shadow_projection,
    dispatch_coordination_runtime_shadow,
    inspect_coordination_runtime_shadow,
    load_task_lease_runtime_shadow_records,
    qualify_coordination_runtime_shadow,
    read_coordination_runtime_shadow_todo_candidate,
    resolve_coordination_runtime_shadow_config,
    rollback_coordination_runtime_shadow,
)


def test_runtime_shadow_todo_read_candidate_is_default_off_and_typed(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    disabled = read_coordination_runtime_shadow_todo_candidate(
        goal={"id": "goal-a"},
        runtime_root=tmp_path,
        goal_id="goal-a",
        todo_id="todo_one",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=lambda *args: calls.append(args),
    )
    assert disabled["status"] == "disabled"
    assert disabled["read_candidate_qualified"] is False
    assert disabled["decision_read_from_shadow"] is False
    assert calls == []

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

    def invoke(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {
            "schema_version": "loopx_coordination_runtime_shadow_todo_read_result_v0",
            "status": "matched",
            "todo_id": "todo_one",
            "todo": {"todo_id": "todo_one", "status": "open"},
            "read_candidate_qualified": True,
            "decision_read_from_shadow": False,
        }

    matched = read_coordination_runtime_shadow_todo_candidate(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        todo_id="todo_one",
        projection={
            "schema_version": "projection_v0",
            "goal_id": "goal-a",
            "todos": [{"todo_id": "todo_one", "status": "open"}],
        },
        runtime_invoker=invoke,
    )
    assert matched["status"] == "matched"
    assert matched["read_candidate_qualified"] is True
    assert calls[0][0] == "coordination.runtime_shadow.todo_read_candidate"
    assert calls[0][1]["todo_id"] == "todo_one"


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


def test_runtime_shadow_bootstrap_is_explicit_default_off_and_typed(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    disabled = bootstrap_coordination_runtime_shadow(
        goal={"id": "goal-a"},
        runtime_root=tmp_path,
        goal_id="goal-a",
        operation_id="bootstrap:goal-a:state-1",
        source_version="state:1",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=lambda *args: calls.append(args),
    )
    assert disabled["status"] == "disabled"
    assert disabled["decision_read_from_shadow"] is False
    assert calls == []

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

    def invoke(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {
            "schema_version": "loopx_coordination_runtime_shadow_bootstrap_result_v0",
            "status": "applied",
            "bootstrap_receipts_empty": True,
            "decision_read_from_shadow": False,
        }

    applied = bootstrap_coordination_runtime_shadow(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        operation_id="bootstrap:goal-a:state-1",
        source_version="state:1",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=invoke,
    )
    assert applied["status"] == "applied"
    method, params = calls[-1]
    assert method == RUNTIME_SHADOW_BOOTSTRAP_METHOD
    assert params["schema_version"] == RUNTIME_SHADOW_BOOTSTRAP_REQUEST_SCHEMA_VERSION
    assert params["source_version"] == "state:1"


def test_runtime_shadow_rollback_is_explicit_default_off_and_revision_fenced(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    disabled = rollback_coordination_runtime_shadow(
        goal={"id": "goal-a"},
        runtime_root=tmp_path,
        goal_id="goal-a",
        operation_id="rollback:goal-a:file-revision-1",
        expected_provider_revision="file:revision-1",
        runtime_invoker=lambda *args: calls.append(args),
    )
    assert disabled["status"] == "disabled"
    assert calls == []

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

    def invoke(method: str, params: dict[str, object]) -> dict[str, object]:
        calls.append((method, params))
        return {
            "schema_version": "loopx_coordination_runtime_shadow_rollback_result_v0",
            "status": "applied",
            "active_shadow_removed": True,
            "archive_retained": True,
            "decision_read_from_shadow": False,
        }

    applied = rollback_coordination_runtime_shadow(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        operation_id="rollback:goal-a:file-revision-1",
        expected_provider_revision="file:revision-1",
        runtime_invoker=invoke,
    )

    assert applied["status"] == "applied"
    method, params = calls[-1]
    assert method == RUNTIME_SHADOW_ROLLBACK_METHOD
    assert params["schema_version"] == RUNTIME_SHADOW_ROLLBACK_REQUEST_SCHEMA_VERSION
    assert params["expected_provider_revision"] == "file:revision-1"


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


def test_runtime_shadow_inspection_is_default_off_and_forwards_compact_projection(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    disabled = inspect_coordination_runtime_shadow(
        goal={"id": "goal-a"},
        runtime_root=tmp_path,
        goal_id="goal-a",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=lambda *args: calls.append(args),
    )
    assert disabled["status"] == "disabled"
    assert disabled["decision_read_from_shadow"] is False
    assert calls == []

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
    captured: dict[str, object] = {}

    def inspect(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_coordination_runtime_shadow_inspection_v0",
            "status": "matched",
            "parity_matches": True,
            "bootstrap_required": False,
            "decision_read_from_shadow": False,
        }

    matched = inspect_coordination_runtime_shadow(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        projection={"schema_version": "projection_v0", "todos": []},
        runtime_invoker=inspect,
    )
    assert matched["status"] == "matched"
    assert matched["decision_read_from_shadow"] is False
    assert captured["method"] == "coordination.runtime_shadow.inspect"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["runtime_root"] == str(tmp_path.resolve())
    assert params["projection"] == {
        "schema_version": "projection_v0",
        "todos": [],
    }


def test_runtime_shadow_qualification_is_default_off_and_forwards_policy(
    tmp_path: Path,
) -> None:
    calls: list[tuple[object, ...]] = []
    disabled = qualify_coordination_runtime_shadow(
        goal={"id": "goal-a"},
        runtime_root=tmp_path,
        goal_id="goal-a",
        projection={"schema_version": "projection_v0", "todos": []},
        minimum_operations=3,
        required_event_kinds=["todo_claim"],
        runtime_invoker=lambda *args: calls.append(args),
    )
    assert disabled["status"] == "disabled"
    assert disabled["qualified"] is False
    assert calls == []

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
    captured: dict[str, object] = {}

    def qualify(method: str, params: dict[str, object]) -> dict[str, object]:
        captured["method"] = method
        captured["params"] = params
        return {
            "schema_version": "loopx_coordination_runtime_shadow_qualification_v0",
            "status": "qualified",
            "qualified": True,
            "decision_read_from_shadow": False,
        }

    result = qualify_coordination_runtime_shadow(
        goal=goal,
        runtime_root=tmp_path,
        goal_id="goal-a",
        projection={"schema_version": "projection_v0", "todos": []},
        minimum_operations=5,
        required_event_kinds=["todo_claim", "task_lease_acquire"],
        runtime_invoker=qualify,
    )
    assert result["status"] == "qualified"
    assert result["decision_read_from_shadow"] is False
    assert captured["method"] == "coordination.runtime_shadow.qualify"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["minimum_operations"] == 5
    assert params["required_event_kinds"] == [
        "todo_claim",
        "task_lease_acquire",
    ]


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
    monkeypatch.setattr(
        todo_command, "dispatch_coordination_runtime_shadow", unexpected
    )
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


def test_runtime_shadow_inspection_reaches_file_store_through_typescript(
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
    projection = {
        "schema_version": "projection_v0",
        "goal_id": "goal-a",
        "todos": [{"todo_id": "todo_one", "status": "open"}],
        "leases": [],
    }
    runtime_root = tmp_path / "state"
    monkeypatch.setattr(
        effect_runtime,
        "_runtime_dir",
        lambda: tmp_path / "effect-runtime",
    )

    try:
        before = inspect_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id="goal-a",
            projection=projection,
        )
        applied = dispatch_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id="goal-a",
            operation_id="todo-shadow:event-inspect",
            event_kind="todo_update",
            source_version="state:1",
            projection=projection,
        )
        after = inspect_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id="goal-a",
            projection=projection,
        )
    finally:
        effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)

    assert before["status"] == "missing"
    assert before["bootstrap_required"] is True
    assert applied["status"] == "applied"
    assert after["status"] == "matched"
    assert after["parity_matches"] is True
    assert after["decision_read_from_shadow"] is False


def test_runtime_shadow_qualification_reaches_file_store_through_typescript(
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
    projection = {
        "schema_version": "projection_v0",
        "goal_id": "goal-a",
        "todos": [{"todo_id": "todo_one", "status": "open"}],
        "leases": [],
    }
    runtime_root = tmp_path / "state"
    monkeypatch.setattr(
        effect_runtime,
        "_runtime_dir",
        lambda: tmp_path / "effect-runtime",
    )

    try:
        bootstrap = bootstrap_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id="goal-a",
            operation_id="bootstrap:goal-a:state-0",
            source_version="state:0",
            projection=projection,
        )
        for index, event_kind in enumerate(
            ("todo_claim", "task_lease_acquire", "todo_complete"),
            start=1,
        ):
            result = dispatch_coordination_runtime_shadow(
                goal=goal,
                runtime_root=runtime_root,
                goal_id="goal-a",
                operation_id=f"shadow:goal-a:{index}",
                event_kind=event_kind,
                source_version=f"state:{index}",
                projection=projection,
            )
            assert result["status"] == "applied"
        qualified = qualify_coordination_runtime_shadow(
            goal=goal,
            runtime_root=runtime_root,
            goal_id="goal-a",
            projection=projection,
            minimum_operations=3,
            required_event_kinds=["todo_claim", "task_lease_acquire"],
        )
    finally:
        effect_runtime.effect_runtime_result("runtime.shutdown", {}, retry_safe=False)

    assert bootstrap["status"] == "applied"
    assert qualified["status"] == "qualified"
    assert qualified["qualified"] is True
    assert qualified["evidence"]["operation_count"] == 3
    assert qualified["decision_read_from_shadow"] is False


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
