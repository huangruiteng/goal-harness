#!/usr/bin/env python3
"""Smoke-test agent-facing status and quota hints.

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
from goal_harness.quota import build_quota_should_run, render_quota_should_run_markdown  # noqa: E402


OLD_PLANNED_ACTION = "先审阅 Goal Harness operator gate；同意后再发送项目 agent 命令"
NEW_PLANNED_ACTION = "先在 Goal Harness 完成 operator 判断；同意后项目 Agent 只执行 read-only map dry-run"
APPROVED_ACTION = "把已批准的 agent_command 发给目标项目 agent；这不是写权限授权"
APPROVED_COMMAND = "goal-harness read-only-map --goal-id planned-main-control --dry-run"
REJECTED_ACTION = "保持 goal 在 gate 状态，修改 handoff 后再请求 operator 判断"
DEFERRED_ACTION = "保持 goal 在 gate 状态，先补齐要求的证据后再请求判断"
REGISTRY_OVERRIDE_STATUS = "owner_sop_review_pending"
REGISTRY_OVERRIDE_ACTION = "请先完成 owner/SOP 判断；未决前不要让项目 agent 继续推进"
REGISTRY_OVERRIDE_QUESTION = "是否同意 owner/SOP review 完成后继续推进？"
REGISTRY_OVERRIDE_HANDOFF = "owner/SOP decision recorded"


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


def append_quota_slot_spend_fixture(root: Path, *, generated_at: str) -> None:
    run_dir = root / "runtime" / "goals" / "planned-main-control" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    compact_time = generated_at.replace("-", "").replace(":", "")
    json_path = run_dir / f"{compact_time}-quota-slot-spent.json"
    markdown_path = run_dir / f"{compact_time}-quota-slot-spent.md"
    record = {
        "generated_at": generated_at,
        "goal_id": "planned-main-control",
        "classification": "quota_slot_spent",
        "recommended_action": "account for one automatic heartbeat slot",
        "health_check": "fixture quota slot spend event",
        "quota_event": {
            "event_type": "quota_slot_spent",
            "source": "heartbeat",
            "slots": 1,
        },
    }
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text("# Fixture quota slot spend\n", encoding="utf-8")
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


def append_state_refreshed_fixture(root: Path, *, generated_at: str) -> None:
    run_dir = root / "runtime" / "goals" / "planned-main-control" / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    compact_time = generated_at.replace("-", "").replace(":", "")
    json_path = run_dir / f"{compact_time}-state-refreshed.json"
    markdown_path = run_dir / f"{compact_time}-state-refreshed.md"
    record = {
        "generated_at": generated_at,
        "goal_id": "planned-main-control",
        "classification": "state_refreshed",
        "recommended_action": "inspect refreshed active goal state and continue",
        "health_check": "fixture state refresh",
    }
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text("# Fixture state refresh\n", encoding="utf-8")
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


def set_registry_attention_override(registry_path: Path) -> None:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["goals"][0].update(
        {
            "waiting_on": "user_or_controller",
            "attention_status": REGISTRY_OVERRIDE_STATUS,
            "recommended_action": REGISTRY_OVERRIDE_ACTION,
            "operator_question": REGISTRY_OVERRIDE_QUESTION,
            "next_handoff_condition": REGISTRY_OVERRIDE_HANDOFF,
        }
    )
    registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def assert_quota_should_run(payload: dict, *, expected: bool, state: str, waiting_on: str) -> dict:
    quota_payload = build_quota_should_run(payload, goal_id="planned-main-control")
    quota_markdown = render_quota_should_run_markdown(quota_payload)
    assert quota_payload["should_run"] is expected, quota_payload
    assert quota_payload["state"] == state, quota_payload
    assert quota_payload["waiting_on"] == waiting_on, quota_payload
    if expected:
        assert quota_payload["decision"] == "run", quota_payload
        assert quota_payload["agent_command"] == APPROVED_COMMAND, quota_payload
        assert f"agent_command: `{APPROVED_COMMAND}`" in quota_markdown, quota_markdown
    else:
        assert quota_payload["decision"] == "skip", quota_payload
        assert quota_payload["reason"] == "human or target-controller gate must clear before spending compute", quota_payload
        assert "agent_command" not in quota_payload, quota_payload
        assert "agent_command:" not in quota_markdown, quota_markdown
    return quota_payload


def assert_planned_preview_is_not_runnable(payload: dict, markdown: str) -> None:
    items = payload["attention_queue"]["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["goal_id"] == "planned-main-control", item
    assert item["waiting_on"] == "user_or_controller", item
    assert item["recommended_action"] == NEW_PLANNED_ACTION, item
    assert item["agent_command"] == APPROVED_COMMAND, item
    assert "operator_gate_dry_run" not in item, item
    assert OLD_PLANNED_ACTION not in json.dumps(payload, ensure_ascii=False), payload
    assert OLD_PLANNED_ACTION not in markdown, markdown
    assert NEW_PLANNED_ACTION in markdown, markdown

    gate_index = markdown.index("operator_gate_dry_run")
    agent_index = markdown.index("agent_command")
    assert gate_index < agent_index, markdown
    assert "<public-safe reason>" in markdown, markdown

    quota_payload = assert_quota_should_run(
        payload,
        expected=False,
        state="operator_gate",
        waiting_on="user_or_controller",
    )
    assert quota_payload["status"] == "planned-high-complexity", quota_payload


def assert_registry_attention_override(payload: dict, markdown: str) -> None:
    items = payload["attention_queue"]["items"]
    assert len(items) == 1, items
    item = items[0]
    assert item["goal_id"] == "planned-main-control", item
    assert item["status"] == REGISTRY_OVERRIDE_STATUS, item
    assert item["waiting_on"] == "user_or_controller", item
    assert item["source"] == "registry", item
    assert item["recommended_action"] == REGISTRY_OVERRIDE_ACTION, item
    assert item["operator_question"] == REGISTRY_OVERRIDE_QUESTION, item
    assert item["next_handoff_condition"] == REGISTRY_OVERRIDE_HANDOFF, item
    assert "agent_command" not in item, item
    assert REGISTRY_OVERRIDE_STATUS in markdown, markdown
    assert REGISTRY_OVERRIDE_ACTION in markdown, markdown
    assert "state_refreshed" in json.dumps(payload["run_history"], ensure_ascii=False), payload
    assert_quota_should_run(
        payload,
        expected=False,
        state="operator_gate",
        waiting_on="user_or_controller",
    )


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
        append_quota_slot_spend_fixture(root, generated_at="2026-01-01T00:01:30+00:00")
        post_spend_payload, post_spend_markdown = collect_fixture_status(root, registry_path)
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
    with tempfile.TemporaryDirectory(prefix="goal-harness-status-registry-override-smoke-") as tmp:
        root = Path(tmp)
        registry_path = write_planned_registry(root)
        append_state_refreshed_fixture(root, generated_at="2026-01-01T00:04:00+00:00")
        set_registry_attention_override(registry_path)
        override_payload, override_markdown = collect_fixture_status(root, registry_path)

    assert_planned_preview_is_not_runnable(payload, markdown)
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
    assert_quota_should_run(
        approved_payload,
        expected=True,
        state="eligible",
        waiting_on="codex",
    )
    post_spend_items = post_spend_payload["attention_queue"]["items"]
    assert len(post_spend_items) == 1, post_spend_items
    post_spend_item = post_spend_items[0]
    assert post_spend_item["status"] == "operator_gate_approved", post_spend_item
    assert post_spend_item["recommended_action"] == APPROVED_ACTION, post_spend_item
    assert "quota_slot_spent" in json.dumps(post_spend_payload["run_history"], ensure_ascii=False), post_spend_payload
    assert "quota_slot_spent" not in post_spend_markdown.split("## Run History")[0], post_spend_markdown
    assert_operator_gate_waits_for_user(
        rejected_payload,
        rejected_markdown,
        status="operator_gate_rejected",
        action=REJECTED_ACTION,
    )
    assert_quota_should_run(
        rejected_payload,
        expected=False,
        state="operator_gate",
        waiting_on="user_or_controller",
    )
    assert_operator_gate_waits_for_user(
        deferred_payload,
        deferred_markdown,
        status="operator_gate_deferred",
        action=DEFERRED_ACTION,
    )
    assert_quota_should_run(
        deferred_payload,
        expected=False,
        state="operator_gate",
        waiting_on="user_or_controller",
    )
    assert_registry_attention_override(override_payload, override_markdown)
    print("status-markdown-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
