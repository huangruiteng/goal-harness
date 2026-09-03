from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.coordination.local_authority import (
    LocalCoordinationAuthorityUnavailable,
    read_canonical_todos_if_promoted,
)
from loopx.control_plane.coordination.legacy_writer_fence import (
    legacy_coordination_writer_fence_path,
)
from loopx.todos import list_goal_todos


def _engage_fence(runtime_root: Path, goal_id: str = "goal-a") -> None:
    path = legacy_coordination_writer_fence_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"state": "engaged"}), encoding="utf-8")


def test_absent_fence_preserves_legacy_path_without_starting_typescript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority.effect_runtime_result",
        lambda *_args, **_kwargs: pytest.fail("pre-cutover read must stay legacy"),
    )
    assert read_canonical_todos_if_promoted(
        runtime_root=tmp_path,
        goal_id="goal-a",
    ) is None


def test_engaged_fence_reads_typescript_provider_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _engage_fence(tmp_path)
    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority.effect_runtime_result",
        lambda method, params: {
            "status": "loaded",
            "todos": [{"todo_id": "todo_a", "role": "agent", "status": "open"}],
            "provider_revision": "file:1",
            "cursor": "1",
            "source_authority": "file_v0",
            "decision_read_from_provider": True,
            "legacy_fallback_used": False,
        },
    )
    result = read_canonical_todos_if_promoted(
        runtime_root=tmp_path,
        goal_id="goal-a",
    )
    assert result is not None
    assert result["todos"][0]["todo_id"] == "todo_a"


def test_engaged_fence_never_falls_back_when_provider_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _engage_fence(tmp_path)
    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority.effect_runtime_result",
        lambda method, params: {
            "status": "missing",
            "source_authority": "file_v0",
            "decision_read_from_provider": True,
            "legacy_fallback_used": False,
        },
    )
    with pytest.raises(LocalCoordinationAuthorityUnavailable) as exc_info:
        read_canonical_todos_if_promoted(runtime_root=tmp_path, goal_id="goal-a")
    assert exc_info.value.code == "local_authority_todo_list_unavailable"


def test_todo_list_uses_provider_after_cutover_even_when_markdown_disagrees(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    state_file = project / ".codex/goals/goal-a/ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        "# Goal\n\n## Agent Todos\n\n- [ ] stale Markdown Todo <!-- loopx:todo todo_id=todo_stale status=open -->\n",
        encoding="utf-8",
    )
    runtime_root = tmp_path / "runtime"
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "common_runtime_root": str(runtime_root),
                "goals": [
                    {
                        "id": "goal-a",
                        "status": "active",
                        "repo": str(project),
                        "state_file": ".codex/goals/goal-a/ACTIVE_GOAL_STATE.md",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _engage_fence(runtime_root)
    state_file.unlink()
    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority.effect_runtime_result",
        lambda method, params: {
            "status": "loaded",
            "todos": [
                {
                    "todo_id": "todo_provider",
                    "role": "agent",
                    "status": "open",
                    "text": "provider Todo",
                }
            ],
            "provider_revision": "file:2",
            "cursor": "2",
            "source_authority": "file_v0",
            "decision_read_from_provider": True,
            "legacy_fallback_used": False,
        },
    )

    result = list_goal_todos(registry_path=registry_path, goal_id="goal-a")

    assert result["source"] == "file_authority"
    assert [item["todo_id"] for item in result["todos"]] == ["todo_provider"]
    assert result["authority_read"]["legacy_fallback_used"] is False
