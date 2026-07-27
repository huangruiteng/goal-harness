from __future__ import annotations

from pathlib import Path

from examples.control_plane.todo_lifecycle_fixtures import (
    GOAL_ID,
    run_cli,
    write_fixture,
)


def test_fixture_cli_runner_restores_cwd_and_returns_json(tmp_path: Path) -> None:
    registry_path, _ = write_fixture(tmp_path)
    original_cwd = Path.cwd()

    payload = run_cli(
        registry_path,
        "todo",
        "add",
        "--goal-id",
        GOAL_ID,
        "--role",
        "agent",
        "--text",
        "Exercise the fixture CLI runner.",
        "--task-class",
        "advancement_task",
    )

    assert payload["ok"] is True
    assert Path.cwd() == original_cwd
