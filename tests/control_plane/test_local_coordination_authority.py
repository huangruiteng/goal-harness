from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from loopx.control_plane.coordination.local_authority import (
    LocalCoordinationAuthorityUnavailable,
    read_canonical_todos_if_promoted,
)
from loopx.control_plane.coordination.runtime_shadow import (
    build_todo_runtime_shadow_projection,
)
from loopx.control_plane.effect_runtime import effect_runtime_result
from loopx.control_plane.todos.active_state_editing import TODO_SECTION_HEADINGS
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


def _todo_read_model(todo_count: int) -> dict[str, object]:
    return {
        "schema_version": "loopx_todo_canonical_read_record_v0",
        "todo_count": todo_count,
    }


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
            "todo_read_model": _todo_read_model(1),
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
            "todo_read_model": _todo_read_model(1),
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


def test_real_shadow_projection_promotes_complete_complex_todo_semantics(
    tmp_path: Path,
) -> None:
    """Exercise builder -> shadow -> promotion -> production Todo list."""

    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    state_file = project / ".codex/goals/goal-a/ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text("# Goal\n", encoding="utf-8")
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
    complex_todo = {
        "schema_version": "todo_item_v0",
        "index": 7,
        "done": False,
        "text": "Qualify provider cutover on a complex Goal",
        "title": "Provider semantic parity",
        "todo_id": "todo_complex",
        "role": "agent",
        "status": "deferred",
        "priority": "P0",
        "archive_state": "active",
        "source_section": TODO_SECTION_HEADINGS["agent"],
        "task_class": "continuous_monitor",
        "action_kind": "monitor",
        "task_domain": "control_plane",
        "task_repository": "loopx",
        "continuation_policy": "continue_goal",
        "claimed_by": "agent-a",
        "excluded_agents": ["agent-b"],
        "resume_when": "material_change",
        "resume_ready": False,
        "cadence": "weekly",
        "next_due_at": "2026-09-07T09:00:00+08:00",
        "expires_at": "2026-10-01T00:00:00+08:00",
        "watch_only": True,
        "material_change": False,
        "material_change_generation": 4,
        "consecutive_no_change": 2,
        "max_no_change_before_replan": 3,
        "successor_todo_ids": ["todo_successor"],
        "note": "keep operator context",
        "evidence": "semantic fixture evidence",
        "updated_at": "2026-09-04T10:00:00+08:00",
    }
    successor = {
        "schema_version": "todo_item_v0",
        "index": 8,
        "done": True,
        "text": "Preserve completion semantics",
        "title": "Completion evidence",
        "todo_id": "todo_successor",
        "role": "agent",
        "status": "done",
        "priority": "P1",
        "archive_state": "active",
        "source_section": TODO_SECTION_HEADINGS["agent"],
        "completion_continuation": "no_followup",
        "completed_at": "2026-09-03T18:00:00+08:00",
        "completion_turn_key": "turn-complete",
    }
    projection = build_todo_runtime_shadow_projection(
        goal_id="goal-a",
        todos=[complex_todo, successor],
    )
    canonical_bytes = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    projection_sha256 = hashlib.sha256(canonical_bytes).hexdigest()

    bootstrap = effect_runtime_result(
        "coordination.runtime_shadow.bootstrap",
        {
            "schema_version": "loopx_coordination_runtime_shadow_bootstrap_v0",
            "runtime_root": str(runtime_root),
            "goal_id": "goal-a",
            "operation_id": "bootstrap:goal-a:complex",
            "source_version": "state:complex:0",
            "projection": projection,
        },
    )
    assert bootstrap["status"] == "applied"
    mirrored = effect_runtime_result(
        "coordination.runtime_shadow.commit",
        {
            "schema_version": "loopx_coordination_runtime_shadow_commit_v0",
            "runtime_root": str(runtime_root),
            "goal_id": "goal-a",
            "operation_id": "todo:goal-a:complex:qualify",
            "event_kind": "todo_update",
            "source_version": "state:complex:1",
            "projection": projection,
        },
    )
    assert mirrored["status"] == "applied"
    provider_revision = str(mirrored["provider_revision"])
    fence = {
        "schema_version": "loopx_legacy_coordination_writer_fence_v0",
        "state": "engaged",
        "goal_id": "goal-a",
        "fence_id": "legacy-writer-fence:goal-a:complex",
        "source_version": "state:complex:1",
        "source_projection_sha256": projection_sha256,
        "expected_shadow_provider_revision": provider_revision,
    }
    engaged = effect_runtime_result(
        "coordination.local_authority.legacy_writer_fence.engage",
        {
            "schema_version": "loopx_legacy_coordination_writer_fence_engage_request_v0",
            "runtime_root": str(runtime_root),
            "goal_id": "goal-a",
            "fence": fence,
        },
    )
    assert engaged["status"] == "applied"
    promoted = effect_runtime_result(
        "coordination.local_authority.promote",
        {
            "schema_version": "loopx_local_coordination_promotion_request_v0",
            "runtime_root": str(runtime_root),
            "goal_id": "goal-a",
            "operation_id": "promote:goal-a:complex",
            "expected_shadow_provider_revision": provider_revision,
            "expected_shadow_projection_sha256": projection_sha256,
            "minimum_operations": 1,
            "required_event_kinds": ["todo_update"],
            "writer_fence": fence,
        },
    )
    assert promoted["status"] == "applied"

    state_file.unlink()
    result = list_goal_todos(registry_path=registry_path, goal_id="goal-a")
    by_id = {item["todo_id"]: item for item in result["todos"]}
    for field in (
        "text",
        "title",
        "priority",
        "source_section",
        "archive_state",
        "continuation_policy",
        "resume_when",
        "cadence",
        "next_due_at",
        "expires_at",
        "watch_only",
        "material_change_generation",
        "successor_todo_ids",
        "note",
        "evidence",
    ):
        assert by_id["todo_complex"][field] == complex_todo[field]
    assert by_id["todo_successor"]["completed_at"] == successor["completed_at"]
    assert by_id["todo_successor"]["completion_continuation"] == "no_followup"
    assert result["authority_read"]["todo_read_model"]["todo_count"] == 2
