from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.history import collect_history


def _write_history_fixture(
    tmp_path: Path,
    runs_by_goal: dict[str, list[dict[str, Any]]],
) -> tuple[Path, Path]:
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}\n", encoding="utf-8")
    runtime_root = tmp_path / "runtime"

    for goal_id, runs in runs_by_goal.items():
        runs_dir = runtime_root / "goals" / goal_id / "runs"
        runs_dir.mkdir(parents=True)
        rows = []
        for position, run in enumerate(runs):
            row = dict(run)
            row.setdefault("json_path", f"artifacts/{goal_id}-{position}.json")
            row.setdefault("markdown_path", f"artifacts/{goal_id}-{position}.md")
            rows.append(json.dumps(row))
        (runs_dir / "index.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    return registry_path, runtime_root


def test_collect_history_orders_goal_runs_by_utc_instant(tmp_path: Path) -> None:
    registry_path, runtime_root = _write_history_fixture(
        tmp_path,
        {
            "goal-a": [
                {
                    "classification": "offset-earlier",
                    "generated_at": "2026-08-19T00:30:00+08:00",
                    "agent_id": "agent-a",
                    "agent_vision": {"agent_id": "agent-a", "revision": "earlier"},
                },
                {
                    "classification": "utc-later",
                    "generated_at": "2026-08-18T17:00:00Z",
                    "agent_id": "agent-a",
                    "agent_vision": {"agent_id": "agent-a", "revision": "later"},
                },
            ]
        },
    )

    history = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-a",
        limit=10,
    )

    goal = history["goals"][0]
    assert [run["classification"] for run in goal["latest_runs"]] == [
        "utc-later",
        "offset-earlier",
    ]
    assert goal["latest_status_run"]["classification"] == "utc-later"
    semantic_agent = goal["semantic_history"]["agents"][0]
    assert semantic_agent["latest_agent_vision_run"]["classification"] == "utc-later"


def test_collect_history_orders_runs_across_goals_by_utc_instant(
    tmp_path: Path,
) -> None:
    registry_path, runtime_root = _write_history_fixture(
        tmp_path,
        {
            "goal-a": [
                {
                    "classification": "offset-earlier",
                    "generated_at": "2026-08-19T00:30:00+08:00",
                }
            ],
            "goal-b": [
                {
                    "classification": "utc-later",
                    "generated_at": "2026-08-18T17:00:00Z",
                }
            ],
        },
    )

    history = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=None,
        limit=1,
    )

    assert [run["classification"] for run in history["runs"]] == ["utc-later"]


def test_collect_history_keeps_invalid_legacy_timestamps_below_valid_runs(
    tmp_path: Path,
) -> None:
    registry_path, runtime_root = _write_history_fixture(
        tmp_path,
        {
            "goal-a": [
                {
                    "classification": "malformed",
                    "generated_at": "not-a-time",
                },
                {
                    "classification": "overflow",
                    "generated_at": "0001-01-01T00:00:00+14:00",
                },
                {
                    "classification": "same-instant-z",
                    "generated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "classification": "same-instant-offset",
                    "generated_at": "2026-01-01T08:00:00+08:00",
                },
                {
                    "classification": "missing",
                    "generated_at": None,
                },
            ]
        },
    )

    history = collect_history(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id="goal-a",
        limit=10,
    )

    classifications = [
        run["classification"] for run in history["goals"][0]["latest_runs"]
    ]
    assert classifications == [
        "same-instant-offset",
        "same-instant-z",
        "malformed",
        "overflow",
        "missing",
    ]
