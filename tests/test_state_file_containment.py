from __future__ import annotations

from pathlib import Path

import pytest

from loopx.state_refresh import resolve_goal_state


def _registry(project: Path) -> dict[str, object]:
    return {
        "goals": [
            {
                "id": "loopx-meta",
                "repo": str(project),
                "state_file": ".local/goals/loopx-meta/ACTIVE_GOAL_STATE.md",
            }
        ]
    }


def test_override_inside_project_is_allowed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state_file = project / ".local" / "goals" / "loopx-meta" / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("## Next Action\n", encoding="utf-8")

    goal, resolved_project, resolved = resolve_goal_state(
        registry=_registry(project),
        goal_id="loopx-meta",
        project_override=project,
        state_file_override=state_file,
    )

    assert goal is not None
    assert resolved_project == project.resolve()
    assert resolved == state_file.resolve()


def test_override_equal_to_registered_state_file_is_allowed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state_file = project / ".local" / "goals" / "loopx-meta" / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("## Next Action\n", encoding="utf-8")

    _, _, resolved = resolve_goal_state(
        registry=_registry(project),
        goal_id="loopx-meta",
        project_override=project,
        state_file_override=state_file,
    )

    assert resolved == state_file.resolve()


def test_override_outside_project_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("## Next Action\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes project root"):
        resolve_goal_state(
            registry=_registry(project),
            goal_id="loopx-meta",
            project_override=project,
            state_file_override=outside,
        )


def test_relative_override_escaping_project_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    with pytest.raises(ValueError, match="escapes project root"):
        resolve_goal_state(
            registry=_registry(project),
            goal_id="loopx-meta",
            project_override=project,
            state_file_override=Path("../outside.md"),
        )


def test_symlink_override_escaping_project_is_rejected(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("## Next Action\n", encoding="utf-8")
    inside = project / "inside.md"
    inside.symlink_to(outside)

    with pytest.raises(ValueError, match="escapes project root"):
        resolve_goal_state(
            registry=_registry(project),
            goal_id="loopx-meta",
            project_override=project,
            state_file_override=inside,
        )


def test_prefix_sibling_override_is_rejected(tmp_path: Path) -> None:
    """Containment must use path hierarchy, not string-prefix matching.

    A sibling directory whose name starts with the project directory name
    (``proj`` vs ``proj-evil``) would pass a naive ``startswith`` check after
    resolve, but must still be rejected by ``is_relative_to``.
    """

    project = tmp_path / "proj"
    project.mkdir()
    sibling = tmp_path / "proj-evil" / "ACTIVE_GOAL_STATE.md"
    sibling.parent.mkdir()
    sibling.write_text("## Next Action\n", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes project root"):
        resolve_goal_state(
            registry=_registry(project),
            goal_id="loopx-meta",
            project_override=project,
            state_file_override=sibling,
        )
