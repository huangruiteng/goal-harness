#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from loopx import status as status_module  # noqa: E402
from loopx.control_plane.runtime import public_safety as public_safety_read_model  # noqa: E402
from loopx.control_plane.runtime import session_runtime as session_runtime_read_model  # noqa: E402
from loopx.control_plane.work_items import project_asset as project_asset_read_model  # noqa: E402
from loopx.session_runtime import SESSION_RUNTIME_READONLY_PROJECTION_SCHEMA_VERSION  # noqa: E402


def assert_status_uses_direct_read_models() -> None:
    assert status_module.public_safe_compact_text is public_safety_read_model.public_safe_compact_text
    assert status_module.public_safe_compact_list is public_safety_read_model.public_safe_compact_list
    assert (
        status_module.compact_session_runtime_readonly_projection
        is session_runtime_read_model.compact_session_runtime_readonly_projection
    )
    assert (
        status_module.compact_session_runtime_projection_from_run
        is session_runtime_read_model.compact_session_runtime_projection_from_run
    )


def assert_public_safe_text_parity() -> None:
    assert status_module.public_safe_compact_text("  keep\nthis  value ") == "keep this value"
    assert project_asset_read_model.project_asset_public_safe_compact_text(
        "  keep\nthis  value "
    ) == "keep this value"
    assert status_module.public_safe_compact_text("") is None

    local_path = "/" + "tmp" + "/loopx-public-boundary-probe.json"
    secret_like_text = "tok" + "en" + "=" + ("x" * 12)
    assert status_module.public_safe_compact_text(local_path) is None
    assert project_asset_read_model.project_asset_public_safe_compact_text(local_path) is None
    assert status_module.public_safe_compact_text(secret_like_text) is None
    assert project_asset_read_model.project_asset_public_safe_compact_text(secret_like_text) is None


def assert_public_safe_list_parity() -> None:
    local_path = "/" + "tmp" + "/loopx-public-boundary-probe.json"
    values = ["first", local_path, "second", "third"]
    expected = ["first", "second"]
    assert status_module.public_safe_compact_list(values, limit=2) == expected
    assert public_safety_read_model.public_safe_compact_list(values, limit=2) == expected
    assert status_module.public_safe_compact_list("single", limit=4) == ["single"]


def assert_session_runtime_defaults() -> None:
    local_path = "/" + "tmp" + "/session-runtime-probe.json"
    projection = {
        "schema_version": SESSION_RUNTIME_READONLY_PROJECTION_SCHEMA_VERSION,
        "goal_id": "loopx-meta",
        "source": {
            "host_kind": "codex",
            "latest_fact_at": "2026-07-05T12:00:00Z",
            "source_refs": {
                "todos": ["todo_1", "todo_2"],
            },
        },
        "boundary": {
            "raw_material_key_names": ["safe-key", local_path],
            "raw_logs_copied": False,
        },
        "first_screen": {
            "waiting_on": "codex",
            "latest_blocker": local_path,
            "recommended_action": "  continue\nvalidated seam  ",
            "agent_can_continue": True,
        },
        "work_lane_contract": {"lane": "advancement_task", "must_attempt_work": True},
        "attention_item": {"kind": "todo", "title": "  Public\nTitle  "},
    }

    compact = status_module.compact_session_runtime_readonly_projection(projection)
    assert compact == {
        "schema_version": SESSION_RUNTIME_READONLY_PROJECTION_SCHEMA_VERSION,
        "mode": "read_only",
        "goal_id": "loopx-meta",
        "source": {
            "host_kind": "codex",
            "latest_fact_at": "2026-07-05T12:00:00Z",
            "source_ref_counts": {"todos": 2},
        },
        "boundary": {
            "raw_logs_copied": False,
            "raw_material_key_names": ["safe-key"],
        },
        "first_screen": {
            "waiting_on": "codex",
            "recommended_action": "continue validated seam",
            "agent_can_continue": True,
        },
        "work_lane_contract": {
            "lane": "advancement_task",
            "must_attempt_work": True,
        },
        "attention_item": {"kind": "todo", "title": "Public Title"},
    }
    assert status_module.compact_session_runtime_projection_from_run(
        {"session_runtime_readonly_projection": projection}
    ) == compact


def main() -> None:
    assert_status_uses_direct_read_models()
    assert_public_safe_text_parity()
    assert_public_safe_list_parity()
    assert_session_runtime_defaults()


if __name__ == "__main__":
    main()
