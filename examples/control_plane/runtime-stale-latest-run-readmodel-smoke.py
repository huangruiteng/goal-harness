#!/usr/bin/env python3
"""Smoke-test stale latest-run freshness as a runtime read model."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.control_plane.goals.active_state_metadata import parse_state_frontmatter  # noqa: E402
from loopx.control_plane.runtime.stale_latest_run import (  # noqa: E402
    stale_latest_run_projection_warning,
)


AGENT_LANE_PROGRESS_SCOPE = "agent_lane"


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def resolve_goal_local_path(raw: Any, goal: dict[str, Any]) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    if path.is_absolute():
        return path
    repo = goal.get("repo")
    return (Path(str(repo)) if repo else Path.cwd()) / path


def state_text(updated_at: str, body: str) -> str:
    return (
        "---\n"
        "status: active\n"
        f"updated_at: {updated_at}\n"
        "---\n\n"
        "# Active State\n\n"
        f"{body}\n"
    )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def warning_for(goal: dict[str, Any], current_run: dict[str, Any]) -> dict[str, Any] | None:
    return stale_latest_run_projection_warning(
        goal,
        current_run,
        agent_lane_progress_scope=AGENT_LANE_PROGRESS_SCOPE,
        resolve_goal_local_path=resolve_goal_local_path,
        parse_state_frontmatter=parse_state_frontmatter,
        parse_timestamp=parse_timestamp,
    )


def base_goal(project: Path, state_file: str, runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": "runtime-freshness",
        "registry_member": True,
        "repo": str(project),
        "state_file": state_file,
        "latest_runs": runs or [],
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="loopx-runtime-stale-latest-run-") as tmp:
        project = Path(tmp) / "project"
        state_file = ".codex/goals/runtime-freshness/ACTIVE_GOAL_STATE.md"
        state_path = project / state_file
        state_path.parent.mkdir(parents=True, exist_ok=True)

        old_text = state_text("2026-01-01T00:01:00+00:00", "old snapshot")
        active_text = state_text("2026-01-01T00:03:00+00:00", "new active state")
        state_path.write_text(active_text, encoding="utf-8")
        stale_status_run = {
            "classification": "state_refreshed",
            "generated_at": "2026-01-01T00:02:00+00:00",
            "state": {
                "sha256_16": digest(old_text),
                "frontmatter": {"updated_at": "2026-01-01T00:01:00+00:00"},
            },
        }

        warning = warning_for(base_goal(project, state_file), stale_status_run)
        assert warning is not None, warning
        assert warning["requires_refresh_state"] is True, warning
        assert warning["active_state_updated_at"] == "2026-01-01T00:03:00+00:00", warning
        assert warning["latest_run_generated_at"] == "2026-01-01T00:02:00+00:00", warning
        assert "active_state_updated_after_latest_run" in warning["reason"], warning
        assert "active_state_updated_after_latest_run_snapshot" in warning["reason"], warning
        assert "active_state_digest_differs_from_latest_run_snapshot" in warning["reason"], warning

        agent_lane_current = {
            "classification": "side_lane_refresh",
            "generated_at": "2026-01-01T00:03:30+00:00",
            "progress_scope": AGENT_LANE_PROGRESS_SCOPE,
            "state": {
                "sha256_16": digest(active_text),
                "frontmatter": {"updated_at": "2026-01-01T00:03:00+00:00"},
            },
        }
        assert warning_for(base_goal(project, state_file, [agent_lane_current]), stale_status_run) is None

        agent_lane_stale = {
            "classification": "side_lane_old_refresh",
            "generated_at": "2026-01-01T00:02:30+00:00",
            "progress_scope": AGENT_LANE_PROGRESS_SCOPE,
            "state": {
                "sha256_16": digest(old_text),
                "frontmatter": {"updated_at": "2026-01-01T00:01:00+00:00"},
            },
        }
        stale_lane_warning = warning_for(base_goal(project, state_file, [agent_lane_stale]), stale_status_run)
        assert stale_lane_warning is not None, stale_lane_warning
        assert stale_lane_warning["requires_refresh_state"] is True, stale_lane_warning

        non_registry_goal = base_goal(project, state_file)
        non_registry_goal["registry_member"] = False
        assert warning_for(non_registry_goal, stale_status_run) is None

    print("runtime-stale-latest-run-readmodel-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
