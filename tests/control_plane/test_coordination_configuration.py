from __future__ import annotations

from loopx.control_plane.coordination.configuration import normalize_goal_write_scope


def test_goal_write_scope_normalization_preserves_configuration_semantics() -> None:
    assert normalize_goal_write_scope(None) is None
    assert normalize_goal_write_scope([]) == []
    assert normalize_goal_write_scope(
        [" docs/**, tests/** ", "docs/**", "src/**;generated/**", ""]
    ) == ["docs/**", "tests/**", "src/**;generated/**"]
