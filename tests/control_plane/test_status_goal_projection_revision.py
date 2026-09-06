"""Tests for the status goal-projection registry revision signal."""

from __future__ import annotations

from loopx.control_plane.status.collection import registry_activation_revision


def _registry(goals: list[dict[str, object]]) -> dict[str, object]:
    return {"goals": goals}


def test_registry_revision_is_stable_across_snapshots() -> None:
    goals = [
        {"id": "goal-a", "activation": {"schema_version": "loopx_goal_activation_v1", "state": "active"}},
        {"id": "goal-b", "activation": {"schema_version": "loopx_goal_activation_v1", "state": "stopped"}},
    ]
    first = registry_activation_revision(_registry(goals))
    second = registry_activation_revision(_registry(goals))
    assert first == second
    assert first.startswith("registry_activation_v1:")


def test_registry_revision_changes_when_activation_partition_changes() -> None:
    def with_state(state: str) -> dict[str, object]:
        return _registry([
            {"id": "goal-a", "activation": {"schema_version": "loopx_goal_activation_v1", "state": state}},
            {"id": "goal-b", "activation": {"schema_version": "loopx_goal_activation_v1", "state": "stopped"}},
        ])

    active = registry_activation_revision(with_state("active"))
    stopped = registry_activation_revision(with_state("stopped"))
    assert active != stopped


def test_registry_revision_ignores_goal_display_churn() -> None:
    base = _registry([
        {"id": "goal-a", "display_name": "alpha", "activation_state": "active"},
        {"id": "goal-b", "display_name": "beta", "activation_state": "stopped"},
    ])
    renamed = _registry([
        {"id": "goal-a", "display_name": "Alpha v2", "activation_state": "active"},
        {"id": "goal-b", "display_name": "Beta v2", "activation_state": "stopped"},
    ])
    assert registry_activation_revision(base) == registry_activation_revision(renamed)
