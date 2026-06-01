#!/usr/bin/env python3
"""Smoke-test agent-facing Markdown status hints.

This stays dependency-free and uses the public status collector against a
temporary planned read-only-map goal.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from goal_harness.status import collect_status, render_status_markdown  # noqa: E402


def write_planned_registry(root: Path) -> Path:
    project = root / "project"
    runtime = root / "runtime"
    goal_id = "planned-main-control"
    state_file = f".codex/goals/{goal_id}/ACTIVE_GOAL_STATE.md"
    registry_path = project / ".goal-harness" / "registry.json"

    (project / Path(state_file).parent).mkdir(parents=True, exist_ok=True)
    (project / state_file).write_text(
        "---\n"
        "status: planned-high-complexity\n"
        "updated_at: 2026-01-01T00:00:00+00:00\n"
        "---\n\n"
        "# Planned Main Control\n",
        encoding="utf-8",
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": "2026-01-01T00:00:00+00:00",
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": goal_id,
                        "domain": "complex-project",
                        "status": "planned-high-complexity",
                        "repo": str(project),
                        "state_file": state_file,
                        "adapter": {
                            "kind": "complex_project_read_only_map_v0",
                            "status": "planned",
                        },
                        "authority_sources": [],
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="goal-harness-status-smoke-") as tmp:
        root = Path(tmp)
        registry_path = write_planned_registry(root)
        payload = collect_status(
            registry_path=registry_path,
            runtime_root_override=str(root / "runtime"),
            scan_roots=[root / "project"],
            limit=3,
        )
        markdown = render_status_markdown(payload)

    items = payload["attention_queue"]["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["goal_id"] == "planned-main-control", item
    assert item["waiting_on"] == "user_or_controller", item
    assert item["agent_command"] == "goal-harness read-only-map --goal-id planned-main-control --dry-run", item
    assert "operator_gate_dry_run" not in item, item

    gate_index = markdown.index("operator_gate_dry_run")
    agent_index = markdown.index("agent_command")
    assert gate_index < agent_index, markdown
    assert "<public-safe reason>" in markdown, markdown
    print("status-markdown-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
