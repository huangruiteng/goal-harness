"""Default-off counterfactual: run unchanged against the pre-claim base too."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.todos import add_goal_todo, list_goal_todos, update_goal_todo


@pytest.mark.parametrize("with_note", [False, True])
def test_unpromoted_claim_retains_markdown_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_note: bool
) -> None:
    state = tmp_path / "ACTIVE_GOAL_STATE.md"
    state.write_text("# Goal\n\n## Agent Todo\n\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "common_runtime_root": str(runtime),
        "goals": [{"id": "goal-a", "status": "active", "repo": str(tmp_path),
                   "state_file": state.name, "coordination": {
                       "registered_agents": ["agent-a", "agent-b"],
                   }}],
    }), encoding="utf-8")
    created = add_goal_todo(registry_path=registry, goal_id="goal-a", role="agent",
                            text="Claim through the unchanged Markdown path")
    monkeypatch.setattr(
        "loopx.control_plane.coordination.local_authority.effect_runtime_result",
        lambda *_args, **_kwargs: pytest.fail("unpromoted call must not enter provider runtime"),
    )
    request = dict(registry_path=registry, goal_id="goal-a", todo_id=created["todo_id"],
                   claimed_by="agent-a", agent_id="agent-a", claim_only=True)
    if with_note:
        request["note"] = "legacy combined claim remains supported"
    before = state.read_bytes()
    preview = update_goal_todo(**request, dry_run=True)
    assert preview["ok"] is True
    assert preview["changed"] is True
    assert state.read_bytes() == before
    claimed = update_goal_todo(**request)
    assert claimed["ok"] is True
    assert claimed["changed"] is True
    assert claimed["mutation_authority"]["command"] == "claim"
    assert "source_authority" not in claimed
    todos = list_goal_todos(registry_path=registry, goal_id="goal-a")["todos"]
    todo = next(item for item in todos if item["todo_id"] == created["todo_id"])
    assert todo["claimed_by"] == "agent-a"
    if with_note:
        assert todo["note"] == request["note"]
    after = state.read_bytes()
    assert update_goal_todo(**request)["changed"] is False
    assert state.read_bytes() == after
    assert not (runtime / "authority" / "file-v0").exists()
