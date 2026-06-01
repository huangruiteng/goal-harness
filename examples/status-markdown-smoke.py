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


OLD_PLANNED_ACTION = "先审阅 Goal Harness operator gate；同意后再发送项目 agent 命令"
NEW_PLANNED_ACTION = "先在 Goal Harness 完成 operator 判断；同意后项目 Agent 只执行 read-only map dry-run"
APPROVED_ACTION = "把已批准的 agent_command 发给目标项目 agent；这不是写权限授权"
APPROVED_COMMAND = "goal-harness read-only-map --goal-id planned-main-control --dry-run"
REJECTED_ACTION = "保持 goal 在 gate 状态，修改 handoff 后再请求 operator 判断"
DEFERRED_ACTION = "保持 goal 在 gate 状态，先补齐要求的证据后再请求判断"


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


def append_operator_gate_fixture(
    root: Path,
    *,
    decision: str,
    generated_at: str,
    recommended_action: str,
) -> None:
    run_dir = root / "runtime" / "goals" / "planned-main-control" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    compact_time = generated_at.replace("-", "").replace(":", "")
    json_path = run_dir / f"{compact_time}-operator-gate.json"
    markdown_path = run_dir / f"{compact_time}-operator-gate.md"
    operator_gate = {
        "recorded_at": generated_at,
        "gate": "read_only_map_opt_in",
        "decision": decision,
        "operator_question": "是否同意 `planned-main-control` 先执行 read-only map opt-in？",
        "reason_summary": f"{decision} fixture reason",
    }
    if decision == "approve":
        operator_gate["agent_command"] = APPROVED_COMMAND
    classification = {
        "approve": "operator_gate_approved",
        "reject": "operator_gate_rejected",
        "defer": "operator_gate_deferred",
    }[decision]
    record = {
        "generated_at": generated_at,
        "goal_id": "planned-main-control",
        "classification": classification,
        "recommended_action": recommended_action,
        "health_check": (
            f"fixture operator_gate decision={decision}; "
            f"agent_command {1 if decision == 'approve' else 0}/1"
        ),
        "operator_gate": operator_gate,
    }
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text("# Fixture operator gate approval\n", encoding="utf-8")
    with (run_dir / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    **record,
                    "json_path": str(json_path),
                    "markdown_path": str(markdown_path),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def collect_fixture_status(root: Path, registry_path: Path) -> tuple[dict, str]:
    payload = collect_status(
        registry_path=registry_path,
        runtime_root_override=str(root / "runtime"),
        scan_roots=[root / "project"],
        limit=3,
    )
    return payload, render_status_markdown(payload)


def assert_operator_gate_waits_for_user(payload: dict, markdown: str, *, status: str, action: str) -> None:
    items = payload["attention_queue"]["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["goal_id"] == "planned-main-control", item
    assert item["status"] == status, item
    assert item["waiting_on"] == "user_or_controller", item
    assert item["recommended_action"] == action, item
    assert "agent_command" not in item, item
    assert "operator_question" in item, item
    assert "agent_command:" not in markdown, markdown
    assert "operator_gate_dry_run" not in markdown, markdown


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="goal-harness-status-smoke-") as tmp:
        root = Path(tmp)
        registry_path = write_planned_registry(root)
        payload, markdown = collect_fixture_status(root, registry_path)
        append_operator_gate_fixture(
            root,
            decision="approve",
            generated_at="2026-01-01T00:01:00+00:00",
            recommended_action=APPROVED_ACTION,
        )
        approved_payload, approved_markdown = collect_fixture_status(root, registry_path)
        append_operator_gate_fixture(
            root,
            decision="reject",
            generated_at="2026-01-01T00:02:00+00:00",
            recommended_action=REJECTED_ACTION,
        )
        rejected_payload, rejected_markdown = collect_fixture_status(root, registry_path)
        append_operator_gate_fixture(
            root,
            decision="defer",
            generated_at="2026-01-01T00:03:00+00:00",
            recommended_action=DEFERRED_ACTION,
        )
        deferred_payload, deferred_markdown = collect_fixture_status(root, registry_path)

    items = payload["attention_queue"]["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["goal_id"] == "planned-main-control", item
    assert item["waiting_on"] == "user_or_controller", item
    assert item["recommended_action"] == NEW_PLANNED_ACTION, item
    assert item["agent_command"] == "goal-harness read-only-map --goal-id planned-main-control --dry-run", item
    assert "operator_gate_dry_run" not in item, item
    assert OLD_PLANNED_ACTION not in json.dumps(payload, ensure_ascii=False), payload
    assert OLD_PLANNED_ACTION not in markdown, markdown
    assert NEW_PLANNED_ACTION in markdown, markdown

    gate_index = markdown.index("operator_gate_dry_run")
    agent_index = markdown.index("agent_command")
    assert gate_index < agent_index, markdown
    assert "<public-safe reason>" in markdown, markdown

    approved_items = approved_payload["attention_queue"]["items"]
    assert len(approved_items) == 1, approved_items
    approved_item = approved_items[0]
    assert approved_item["goal_id"] == "planned-main-control", approved_item
    assert approved_item["status"] == "operator_gate_approved", approved_item
    assert approved_item["waiting_on"] == "codex", approved_item
    assert approved_item["recommended_action"] == APPROVED_ACTION, approved_item
    assert approved_item["agent_command"] == APPROVED_COMMAND, approved_item
    assert "operator_question" not in approved_item, approved_item
    assert "operator_gate_dry_run" not in approved_markdown, approved_markdown
    assert f"agent_command: `{APPROVED_COMMAND}`" in approved_markdown, approved_markdown
    assert_operator_gate_waits_for_user(
        rejected_payload,
        rejected_markdown,
        status="operator_gate_rejected",
        action=REJECTED_ACTION,
    )
    assert_operator_gate_waits_for_user(
        deferred_payload,
        deferred_markdown,
        status="operator_gate_deferred",
        action=DEFERRED_ACTION,
    )
    print("status-markdown-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
