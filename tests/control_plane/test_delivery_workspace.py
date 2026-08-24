from __future__ import annotations

import json
from pathlib import Path

from loopx.control_plane.agents.workspace_guard import (
    build_delivery_workspace_guard,
    capture_delivery_workspace,
    delivery_workspace_identity,
    delivery_workspace_repository,
)


def test_gitless_single_agent_workspace_uses_stable_goal_identity(
    tmp_path: Path,
) -> None:
    project = tmp_path / "plain-project"
    project.mkdir()

    snapshot = capture_delivery_workspace(
        project,
        local_goal_id="plain-goal",
        local_project_root=project,
    )

    assert snapshot == {
        "schema_version": "delivery_workspace_v1",
        "workspace_identity": "loopx:plain-goal",
        "identity_kind": "local_goal",
        "task_repository": None,
        "repository_source": "goal_id_fallback",
        "workspace_kind": "local_goal_workspace",
        "peer_independent_worktree_required": False,
    }
    assert str(project) not in json.dumps(snapshot)
    assert delivery_workspace_identity(snapshot) == "loopx:plain-goal"
    assert delivery_workspace_repository(snapshot) is None
    assert build_delivery_workspace_guard(
        {"delivery_workspace": snapshot},
        current_path=tmp_path,
    ) is None


def test_gitless_workspace_fails_closed_outside_goal_or_for_peer_writes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "plain-project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()

    assert capture_delivery_workspace(
        outside,
        local_goal_id="plain-goal",
        local_project_root=project,
    ) is None
    assert capture_delivery_workspace(
        project,
        local_goal_id="plain-goal",
        local_project_root=project,
        peer_independent_worktree_required=True,
    ) is None


def test_legacy_git_workspace_remains_accepted() -> None:
    legacy = {
        "schema_version": "delivery_workspace_v0",
        "task_repository": "git:github.com/example/loopx",
        "repository_source": "current_git_origin",
        "workspace_kind": "canonical_checkout",
        "peer_independent_worktree_required": False,
    }

    assert delivery_workspace_identity(legacy) == "git:github.com/example/loopx"
    assert delivery_workspace_repository(legacy) == "git:github.com/example/loopx"
