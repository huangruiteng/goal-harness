from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from loopx.cli import main
from loopx.configure_goal import configure_goal
from loopx.control_plane.work_items import task_lease as task_lease_module
from loopx.control_plane.work_items.task_lease import (
    TaskLeaseError,
    acquire_task_lease,
    inspect_task_lease,
    lease_is_active,
    read_lease,
    release_task_lease,
    task_lease_path,
)
from loopx.todos import add_goal_todo


GOAL_ID = "roster-safe-leases"
AGENT_A = "codex-worker-a"
AGENT_B = "codex-worker-b"
AGENT_C = "codex-worker-c"


def _write_fixture(tmp_path: Path, *, agents: list[str] | None = None) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "ACTIVE_GOAL_STATE.md"
    state.write_text(
        "\n".join(
            [
                "---",
                f"goal_id: {GOAL_ID}",
                "updated_at: 2026-08-23T00:00:00+00:00",
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
                            "registered_agents": list(agents or [AGENT_A, AGENT_B]),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry, state


def _add_open_todo(registry: Path, *, text: str) -> dict[str, Any]:
    return add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=text,
        task_class="advancement_task",
    )


def _acquire(
    registry: Path,
    runtime_root: Path,
    todo_id: str,
    *,
    owner: str,
    key: str,
    ttl_seconds: int = 600,
    write_scopes: list[str] | None = None,
) -> dict[str, Any]:
    return acquire_task_lease(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        todo_id=todo_id,
        owner=owner,
        idempotency_key=key,
        ttl_seconds=ttl_seconds,
        write_scopes=write_scopes,
    )


def _stored_agents(registry: Path) -> list[str]:
    payload = json.loads(registry.read_text(encoding="utf-8"))
    return list(payload["goals"][0]["coordination"]["registered_agents"])


def test_wholesale_roster_replace_does_not_drop_active_lease_protection(
    tmp_path: Path,
) -> None:
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    todo = _add_open_todo(registry, text="Hold this todo under an active lease.")
    acquired = _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_A, key="a-turn-1")
    lease_before = dict(acquired["lease"])

    replaced = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        registered_agents=[AGENT_B],
        execute=True,
    )

    assert replaced["written"] is True
    assert replaced["after"]["registered_agents"] == [AGENT_B]
    assert _stored_agents(registry) == [AGENT_B]
    warnings = replaced.get("active_lease_owner_warnings") or []
    assert warnings, replaced
    assert warnings[0]["owner"] == AGENT_A
    assert warnings[0]["todo_id"] == todo["todo_id"]

    with pytest.raises(TaskLeaseError) as steal:
        _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-1")
    assert steal.value.code == "todo_lease_conflict"

    persisted = read_lease(
        task_lease_path(
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
        )
    )
    assert persisted is not None
    assert lease_is_active(persisted) is True
    assert persisted["owner"] == AGENT_A
    assert persisted["idempotency_key"] == lease_before["idempotency_key"]
    assert persisted["version"] == lease_before["version"]

    inspected = inspect_task_lease(
        registry_path=registry,
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
    )
    assert inspected["active"] is True
    assert inspected["lease"]["owner"] == AGENT_A


def test_dropped_owner_lease_can_be_taken_only_after_release(
    tmp_path: Path,
) -> None:
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    todo = _add_open_todo(registry, text="Release then allow the remaining owner to acquire.")
    acquired = _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_A, key="a-turn-1")
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        registered_agents=[AGENT_B],
        execute=True,
    )

    with pytest.raises(TaskLeaseError) as steal:
        _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-1")
    assert steal.value.code == "todo_lease_conflict"

    released = release_task_lease(
        runtime_root=runtime_root,
        goal_id=GOAL_ID,
        todo_id=todo["todo_id"],
        owner=AGENT_A,
        idempotency_key="a-turn-1",
        expected_version=int(acquired["lease"]["version"]),
        registry_path=registry,
    )
    assert released["released"] is True

    taken = _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-2")
    assert taken["acquired"] is True
    assert taken["lease"]["owner"] == AGENT_B


def test_dropped_owner_lease_can_be_taken_only_after_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(task_lease_module, "now_utc", lambda: now)
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    todo = _add_open_todo(registry, text="Expire then allow the remaining owner to acquire.")
    _acquire(
        registry,
        runtime_root,
        todo["todo_id"],
        owner=AGENT_A,
        key="a-turn-1",
        ttl_seconds=60,
    )
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        registered_agents=[AGENT_B],
        execute=True,
    )

    with pytest.raises(TaskLeaseError) as steal:
        _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-1")
    assert steal.value.code == "todo_lease_conflict"

    monkeypatch.setattr(
        task_lease_module,
        "now_utc",
        lambda: now + timedelta(seconds=61),
    )
    taken = _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-2")
    assert taken["acquired"] is True
    assert taken["lease"]["owner"] == AGENT_B


def test_incremental_add_does_not_change_existing_owner_or_lease_state(
    tmp_path: Path,
) -> None:
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    todo_a = _add_open_todo(registry, text="A keeps this lease while C is added.")
    todo_b = _add_open_todo(registry, text="B keeps this lease while C is added.")
    lease_a = _acquire(
        registry,
        runtime_root,
        todo_a["todo_id"],
        owner=AGENT_A,
        key="a-turn-1",
        write_scopes=["docs/**"],
    )
    lease_b = _acquire(
        registry,
        runtime_root,
        todo_b["todo_id"],
        owner=AGENT_B,
        key="b-turn-1",
        write_scopes=["tests/**"],
    )
    agents_before = _stored_agents(registry)
    lease_a_before = dict(lease_a["lease"])
    lease_b_before = dict(lease_b["lease"])

    added = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        add_registered_agents=[AGENT_C],
        execute=True,
    )

    assert added["written"] is True
    assert added["after"]["registered_agents"] == [AGENT_A, AGENT_B, AGENT_C]
    assert added.get("active_lease_owner_warnings") in (None, [])
    assert _stored_agents(registry) == [AGENT_A, AGENT_B, AGENT_C]
    assert agents_before == [AGENT_A, AGENT_B]

    persisted_a = read_lease(
        task_lease_path(
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            todo_id=todo_a["todo_id"],
        )
    )
    persisted_b = read_lease(
        task_lease_path(
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            todo_id=todo_b["todo_id"],
        )
    )
    assert persisted_a == lease_a_before
    assert persisted_b == lease_b_before

    with pytest.raises(TaskLeaseError) as steal_a:
        _acquire(registry, runtime_root, todo_a["todo_id"], owner=AGENT_B, key="b-steal-a")
    assert steal_a.value.code == "todo_lease_conflict"
    with pytest.raises(TaskLeaseError) as steal_b:
        _acquire(registry, runtime_root, todo_b["todo_id"], owner=AGENT_A, key="a-steal-b")
    assert steal_b.value.code == "todo_lease_conflict"


def test_incremental_remove_keeps_active_lease_and_warns(
    tmp_path: Path,
) -> None:
    registry, _state = _write_fixture(tmp_path, agents=[AGENT_A, AGENT_B, AGENT_C])
    runtime_root = tmp_path / "runtime"
    todo = _add_open_todo(registry, text="Removing A from the roster must not wipe the lease.")
    acquired = _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_A, key="a-turn-1")

    removed = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        remove_registered_agents=[AGENT_A],
        execute=True,
    )

    assert removed["after"]["registered_agents"] == [AGENT_B, AGENT_C]
    warnings = removed.get("active_lease_owner_warnings") or []
    assert any(item["owner"] == AGENT_A for item in warnings), removed

    with pytest.raises(TaskLeaseError) as steal:
        _acquire(registry, runtime_root, todo["todo_id"], owner=AGENT_B, key="b-turn-1")
    assert steal.value.code == "todo_lease_conflict"
    persisted = read_lease(
        task_lease_path(
            runtime_root=runtime_root,
            goal_id=GOAL_ID,
            todo_id=todo["todo_id"],
        )
    )
    assert persisted is not None
    assert persisted["owner"] == AGENT_A
    assert persisted["version"] == acquired["lease"]["version"]


def test_new_acquire_still_requires_owner_on_roster(tmp_path: Path) -> None:
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    held = _add_open_todo(registry, text="A already holds this one.")
    free = _add_open_todo(registry, text="A cannot acquire a new todo after leaving the roster.")
    _acquire(registry, runtime_root, held["todo_id"], owner=AGENT_A, key="a-held")
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        registered_agents=[AGENT_B],
        execute=True,
    )

    with pytest.raises(TaskLeaseError) as error:
        _acquire(registry, runtime_root, free["todo_id"], owner=AGENT_A, key="a-new")
    assert error.value.code == "owner_not_registered"


def test_off_roster_owner_write_scope_still_conflicts(tmp_path: Path) -> None:
    registry, _state = _write_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    held = _add_open_todo(registry, text="A holds overlapping docs scope.")
    other = _add_open_todo(registry, text="B should not take overlapping docs scope.")
    _acquire(
        registry,
        runtime_root,
        held["todo_id"],
        owner=AGENT_A,
        key="a-docs",
        write_scopes=["docs/**"],
    )
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        registered_agents=[AGENT_B],
        execute=True,
    )

    with pytest.raises(TaskLeaseError) as error:
        _acquire(
            registry,
            runtime_root,
            other["todo_id"],
            owner=AGENT_B,
            key="b-docs",
            write_scopes=["docs/readme.md"],
        )
    assert error.value.code == "write_scope_conflict"


def test_configure_goal_rejects_combining_replace_with_incremental(
    tmp_path: Path,
) -> None:
    registry, _state = _write_fixture(tmp_path)

    with pytest.raises(ValueError, match="cannot be combined"):
        configure_goal(
            registry_path=registry,
            goal_id=GOAL_ID,
            registered_agents=[AGENT_B],
            add_registered_agents=[AGENT_C],
            execute=False,
        )


def test_configure_goal_cli_add_registered_agent(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, _state = _write_fixture(tmp_path)

    exit_code = main(
        [
            "--registry",
            str(registry),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--format",
            "json",
            "configure-goal",
            "--goal-id",
            GOAL_ID,
            "--add-registered-agent",
            AGENT_C,
            "--execute",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["written"] is True
    assert payload["after"]["registered_agents"] == [AGENT_A, AGENT_B, AGENT_C]
    assert _stored_agents(registry) == [AGENT_A, AGENT_B, AGENT_C]
