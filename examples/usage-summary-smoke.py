#!/usr/bin/env python3
"""Smoke-test public-safe usage summary proxy fields."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.status import collect_status  # noqa: E402


FORBIDDEN_USAGE_KEYS = {
    "token_count",
    "tokens",
    "thread_count",
    "threads",
    "raw_thread_logs",
    "raw_session_path",
    "session_transcript",
}


def write_registry(root: Path) -> Path:
    project = root / "project"
    runtime = root / "runtime"
    registry_path = project / ".goal-harness" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    goals = []
    for goal_id in ("project-a", "project-b"):
        state_file = f".codex/goals/{goal_id}/ACTIVE_GOAL_STATE.md"
        (project / Path(state_file).parent).mkdir(parents=True, exist_ok=True)
        (project / state_file).write_text(
            "---\nstatus: active\nupdated_at: 2026-01-01T00:00:00+00:00\n---\n"
            f"\n# {goal_id}\n\n## Next Action\n\n- Continue one public-safe step.\n",
            encoding="utf-8",
        )
        goals.append(
            {
                "id": goal_id,
                "domain": "usage-summary-fixture",
                "status": "active",
                "repo": str(project),
                "state_file": state_file,
                "adapter": {"kind": "fixture_adapter_v0", "status": "connected-read-only"},
            }
        )
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": goals,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path


def append_run(
    runtime: Path,
    *,
    goal_id: str,
    generated_at: datetime,
    classification: str,
    quota_event: dict[str, Any] | None = None,
) -> None:
    run_dir = runtime / "goals" / goal_id / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.isoformat().replace("+00:00", "Z").replace(":", "-")
    json_path = run_dir / f"{stamp}-{classification}.json"
    markdown_path = run_dir / f"{stamp}-{classification}.md"
    record: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "goal_id": goal_id,
        "classification": classification,
        "recommended_action": "fixture action",
        "health_check": "fixture health",
    }
    if quota_event:
        record["quota_event"] = quota_event
    json_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text("# Fixture run\n", encoding="utf-8")
    with (run_dir / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    **record,
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                },
                sort_keys=True,
            )
            + "\n"
        )


def assert_no_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in FORBIDDEN_USAGE_KEYS, key
            assert_no_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_forbidden_keys(child)


def main() -> int:
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="goal-harness-usage-summary-") as tmp:
        root = Path(tmp)
        registry_path = write_registry(root)
        runtime = root / "runtime"
        append_run(runtime, goal_id="project-a", generated_at=now - timedelta(hours=1), classification="state_refreshed")
        append_run(runtime, goal_id="project-a", generated_at=now - timedelta(minutes=30), classification="quota_slot_spent")
        append_run(runtime, goal_id="project-b", generated_at=now - timedelta(hours=2), classification="read_only_project_map")
        append_run(
            runtime,
            goal_id="project-b",
            generated_at=now - timedelta(hours=3),
            classification="quota_slot_spent",
            quota_event={"event_type": "quota_slot_spent", "source": "heartbeat", "slots": 2},
        )
        append_run(runtime, goal_id="project-b", generated_at=now - timedelta(days=8), classification="state_refreshed")

        payload = collect_status(
            registry_path=registry_path,
            runtime_root_override=str(runtime),
            scan_roots=[root / "project"],
            limit=20,
        )
        usage = payload["usage_summary"]
        totals = usage["totals"]
        assert usage["available"] is True, usage
        assert usage["source"] == "run_history", usage
        assert usage["sample_run_count"] == 5, usage
        assert totals["runs_24h"] == 4, totals
        assert totals["runs_7d"] == 4, totals
        assert totals["quota_spend_slots_24h"] == 3, totals
        assert totals["quota_spend_slots_7d"] == 3, totals
        assert totals["automation_run_count_24h"] == 2, totals
        assert totals["automation_run_count_7d"] == 2, totals

        goals = {goal["goal_id"]: goal for goal in usage["goals"]}
        assert goals["project-a"]["runs_24h"] == 2, goals
        assert goals["project-b"]["runs_24h"] == 2, goals
        assert goals["project-a"]["project_share_24h"] == 0.5, goals
        assert goals["project-b"]["project_share_24h"] == 0.5, goals
        assert_no_forbidden_keys(usage)

    print("usage-summary smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
