from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.control_plane.coordination.legacy_writer_fence import (
    LegacyCoordinationWriterFenced,
    legacy_coordination_writer_fence_path,
    require_legacy_coordination_write_allowed,
)


def test_missing_fence_preserves_default_without_starting_typescript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "loopx.control_plane.coordination.legacy_writer_fence.effect_runtime_result",
        lambda *_args, **_kwargs: pytest.fail("default path must not start runtime"),
    )

    require_legacy_coordination_write_allowed(
        runtime_root=tmp_path,
        goal_id="goal-a",
    )


def test_present_fence_delegates_to_typescript_and_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = legacy_coordination_writer_fence_path(
        runtime_root=tmp_path,
        goal_id="goal-a",
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"state": "present"}), encoding="utf-8")
    captured: dict[str, object] = {}

    def invoke(method: str, params: dict[str, object]) -> dict[str, object]:
        captured.update(method=method, params=params)
        return {
            "status": "blocked",
            "reason_code": "legacy_coordination_writer_fenced",
            "authority_mode": "file_v0",
        }

    monkeypatch.setattr(
        "loopx.control_plane.coordination.legacy_writer_fence.effect_runtime_result",
        invoke,
    )

    with pytest.raises(LegacyCoordinationWriterFenced) as exc_info:
        require_legacy_coordination_write_allowed(
            runtime_root=tmp_path,
            goal_id="goal-a",
        )

    assert exc_info.value.code == "legacy_coordination_writer_fenced"
    assert captured["method"] == "coordination.local_authority.legacy_write_check"
