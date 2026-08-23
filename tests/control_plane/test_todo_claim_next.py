from __future__ import annotations

from multiprocessing import get_context
from pathlib import Path
from typing import Any

from loopx.control_plane.testing.canary_harness import write_fixture_registry
from loopx.control_plane.todos.active_state_todo_parser import parse_active_state_todos
from loopx.control_plane.todos.claim_next import (
    CLAIM_NEXT_EMPTY_REASON,
    claim_next_goal_todo,
    select_claimable_todo,
    todo_is_claimable,
)
from loopx.control_plane.work_items.task_lease import acquire_task_lease
from loopx.todos import add_goal_todo, update_goal_todo


GOAL_ID = "todo-claim-next"
AGENT_A = "codex-worker-a"
AGENT_B = "codex-worker-b"
AGENT_C = "codex-worker-c"
AGENT_D = "codex-worker-d"
AGENTS = (AGENT_A, AGENT_B, AGENT_C, AGENT_D)


def _write_fixture(tmp_path: Path, *, agents: tuple[str, ...] = AGENTS) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    state_file = project / ".codex" / "goals" / GOAL_ID / "ACTIVE_GOAL_STATE.md"
    registry_path = project / ".loopx" / "registry.json"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        "\n".join(
            [
                "---",
                "status: active",
                "updated_at: 2026-08-23T00:00:00+00:00",
                "---",
                "",
                "# Active Goal State",
                "",
                "## Objective",
                "",
                "Exercise atomic claim-next.",
                "",
                "## Agent Todo",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_fixture_registry(
        project=project,
        runtime_root=runtime,
        registry_path=registry_path,
        goal_id=GOAL_ID,
        domain="todo-claim-next-fixture",
        adapter_kind="generic_project_goal_v0",
        registered_agents=agents,
        quota_allowed_slots=None,
    )
    return registry_path, state_file, runtime


def _add_open_unclaimed(registry: Path, *, text: str) -> dict[str, Any]:
    return add_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        role="agent",
        text=text,
        task_class="advancement_task",
    )


def _parsed_agent_items(state_file: Path) -> list[dict[str, Any]]:
    fields = parse_active_state_todos(state_file.read_text(encoding="utf-8"), item_limit=None)
    return list((fields.get("agent_todos") or {}).get("items") or [])


def _claim_next_worker(payload: tuple[str, str]) -> dict[str, Any]:
    registry_path, agent_id = payload
    return claim_next_goal_todo(
        registry_path=Path(registry_path),
        goal_id=GOAL_ID,
        agent_id=agent_id,
    )


def test_claim_next_assigns_unique_todos_under_real_concurrency(tmp_path: Path) -> None:
    registry, _state, _runtime = _write_fixture(tmp_path)
    added = [
        _add_open_unclaimed(registry, text=f"Deliver unique slice {index}.")
        for index in range(4)
    ]
    added_ids = {item["todo_id"] for item in added}
    assert len(added_ids) == 4

    ctx = get_context("spawn")
    with ctx.Pool(processes=4) as pool:
        results = pool.map(
            _claim_next_worker,
            [(str(registry), agent_id) for agent_id in AGENTS],
        )

    claimed_ids = [payload["todo_id"] for payload in results]
    claimants = [payload["claimed_by"] for payload in results]
    assert all(payload["ok"] is True and payload["claimed"] is True for payload in results)
    assert len(set(claimed_ids)) == 4, claimed_ids
    assert set(claimed_ids) == added_ids
    assert set(claimants) == set(AGENTS)
    empty = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_A,
    )
    assert empty["ok"] is True
    assert empty["claimed"] is False
    assert empty["empty_reason"] == CLAIM_NEXT_EMPTY_REASON
    assert empty["todo_id"] is None


def test_same_agent_does_not_reselect_an_already_claimed_todo(tmp_path: Path) -> None:
    registry, _state, _runtime = _write_fixture(tmp_path, agents=(AGENT_A,))
    first = _add_open_unclaimed(registry, text="First unique slice.")
    second = _add_open_unclaimed(registry, text="Second unique slice.")
    claimed_first = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_A,
    )
    claimed_second = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_A,
    )
    assert claimed_first["todo_id"] == first["todo_id"]
    assert claimed_second["todo_id"] == second["todo_id"]
    assert claimed_first["claimed_by"] == AGENT_A
    assert claimed_second["claimed_by"] == AGENT_A


def test_claim_next_optional_lease_attaches_to_the_claimed_todo(tmp_path: Path) -> None:
    registry, _state, _runtime = _write_fixture(tmp_path, agents=(AGENT_A,))
    added = _add_open_unclaimed(registry, text="Lease this slice after claim.")
    payload = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_A,
        acquire_lease=True,
    )
    assert payload["ok"] is True
    assert payload["todo_id"] == added["todo_id"]
    lease = payload["task_lease"]["lease"]
    assert lease["owner"] == AGENT_A
    assert lease["todo_id"] == added["todo_id"]


def test_claim_next_returns_empty_when_no_work_is_available(tmp_path: Path) -> None:
    registry, _state, _runtime = _write_fixture(tmp_path, agents=(AGENT_A,))
    payload = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_A,
    )
    assert payload["ok"] is True
    assert payload["claimed"] is False
    assert payload["empty_reason"] == CLAIM_NEXT_EMPTY_REASON
    assert payload["todo_id"] is None
    assert payload["command"] == "claim-next"


def test_claimed_or_leased_todos_are_not_selected(tmp_path: Path) -> None:
    registry, state, runtime = _write_fixture(tmp_path, agents=(AGENT_A, AGENT_B))
    claimed = _add_open_unclaimed(registry, text="Already owned slice.")
    leased = _add_open_unclaimed(registry, text="Hard-leased slice.")
    free = _add_open_unclaimed(registry, text="Free runnable slice.")
    update_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        todo_id=claimed["todo_id"],
        claimed_by=AGENT_A,
        agent_id=AGENT_A,
        claim_only=True,
    )
    acquire_task_lease(
        registry_path=registry,
        runtime_root=runtime,
        goal_id=GOAL_ID,
        todo_id=leased["todo_id"],
        owner=AGENT_A,
        idempotency_key="lease-owned-by-a",
    )
    payload = claim_next_goal_todo(
        registry_path=registry,
        goal_id=GOAL_ID,
        agent_id=AGENT_B,
    )
    assert payload["ok"] is True
    assert payload["claimed"] is True
    assert payload["todo_id"] == free["todo_id"]
    assert payload["claimed_by"] == AGENT_B
    items = {item["todo_id"]: item for item in _parsed_agent_items(state)}
    assert items[claimed["todo_id"]]["claimed_by"] == AGENT_A
    assert items[leased["todo_id"]].get("claimed_by") in {None, ""}
    assert items[free["todo_id"]]["claimed_by"] == AGENT_B


def test_todo_is_claimable_rejects_claimed_and_leased_items() -> None:
    leased_ids = {"todo_leaseditem01"}
    assert todo_is_claimable(
        {"todo_id": "todo_freeitem0001", "claimed_by": None},
        leased_todo_ids=leased_ids,
    )
    assert not todo_is_claimable(
        {"todo_id": "todo_claimeditem1", "claimed_by": AGENT_A},
        leased_todo_ids=leased_ids,
    )
    assert not todo_is_claimable(
        {"todo_id": "todo_leaseditem01", "claimed_by": None},
        leased_todo_ids=leased_ids,
    )


def test_select_claimable_todo_follows_selected_todo_order() -> None:
    items = [
        {
            "todo_id": "todo_lateritem001",
            "index": 2,
            "priority": "P1",
            "status": "open",
            "task_class": "advancement_task",
            "text": "Later slice.",
        },
        {
            "todo_id": "todo_firstitem001",
            "index": 1,
            "priority": "P0",
            "status": "open",
            "task_class": "advancement_task",
            "text": "First slice.",
        },
        {
            "todo_id": "todo_claimeditem1",
            "index": 0,
            "priority": "P0",
            "status": "open",
            "task_class": "advancement_task",
            "claimed_by": AGENT_A,
            "text": "Already claimed.",
        },
    ]
    selected = select_claimable_todo(
        items,
        agent_id=AGENT_B,
        task_class="advancement_task",
        leased_todo_ids=set(),
    )
    assert selected is not None
    assert selected["todo_id"] == "todo_firstitem001"


def test_claim_next_cli_empty_result_is_ok(tmp_path: Path) -> None:
    from loopx.control_plane.testing.canary_harness import run_json_cli_result

    registry, _state, _runtime = _write_fixture(tmp_path, agents=(AGENT_A,))
    returncode, payload = run_json_cli_result(
        "todo",
        "claim-next",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_A,
        registry_path=registry,
    )
    assert returncode == 0, payload
    assert payload["ok"] is True
    assert payload["claimed"] is False
    assert payload["empty_reason"] == CLAIM_NEXT_EMPTY_REASON


def test_claim_next_cli_claims_next_todo(tmp_path: Path) -> None:
    from loopx.control_plane.testing.canary_harness import run_json_cli

    registry, _state, _runtime = _write_fixture(tmp_path, agents=(AGENT_A, AGENT_B))
    first = _add_open_unclaimed(registry, text="First runnable slice.")
    second = _add_open_unclaimed(registry, text="Second runnable slice.")
    payload = run_json_cli(
        "todo",
        "claim-next",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_A,
        registry_path=registry,
        include_returncode=False,
    )
    assert payload["ok"] is True
    assert payload["claimed"] is True
    assert payload["todo_id"] == first["todo_id"]
    assert payload["claimed_by"] == AGENT_A
    next_payload = run_json_cli(
        "todo",
        "claim-next",
        "--goal-id",
        GOAL_ID,
        "--agent-id",
        AGENT_B,
        registry_path=registry,
        include_returncode=False,
    )
    assert next_payload["todo_id"] == second["todo_id"]
    assert next_payload["claimed_by"] == AGENT_B
