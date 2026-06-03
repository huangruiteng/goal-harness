#!/usr/bin/env python3
"""Smoke-test the CLI-visible Review Packet formatter."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GOAL_ID = "planned-main-control"
APPROVED_COMMAND = f"goal-harness read-only-map --goal-id {GOAL_ID} --dry-run"


def write_planned_registry(root: Path) -> Path:
    project = root / "project"
    runtime = root / "runtime"
    state_file = f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
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
                        "id": GOAL_ID,
                        "domain": "complex-project",
                        "status": "planned-high-complexity",
                        "repo": str(project),
                        "state_file": state_file,
                        "adapter": {
                            "kind": "complex_project_read_only_map_v0",
                            "status": "planned",
                        },
                    }
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return registry_path


def append_operator_gate_approval_fixture(root: Path) -> None:
    run_dir = root / "runtime" / "goals" / GOAL_ID / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    generated_at = "2026-01-01T00:01:00+00:00"
    compact_time = generated_at.replace("-", "").replace(":", "")
    json_path = run_dir / f"{compact_time}-operator-gate.json"
    markdown_path = run_dir / f"{compact_time}-operator-gate.md"
    record = {
        "generated_at": generated_at,
        "goal_id": GOAL_ID,
        "classification": "operator_gate_approved",
        "recommended_action": "把已批准的 agent_command 发给目标项目 agent；这不是写权限授权",
        "health_check": "fixture operator_gate decision=approve; agent_command 1/1",
        "operator_gate": {
            "recorded_at": generated_at,
            "gate": "read_only_map_opt_in",
            "decision": "approve",
            "operator_question": f"是否同意 `{GOAL_ID}` 先执行 read-only map opt-in？",
            "reason_summary": f"同意 {GOAL_ID} 先做 read-only map dry-run，不授权写入或生产动作",
            "agent_command": APPROVED_COMMAND,
        },
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


def run_cli(root: Path, registry_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "goal_harness.cli",
            "--registry",
            str(registry_path),
            "--runtime-root",
            str(root / "runtime"),
            *args,
        ],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def assert_order(text: str, labels: list[str]) -> None:
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions), (labels, positions, text)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="goal-harness-review-packet-") as tmp:
        root = Path(tmp)
        registry_path = write_planned_registry(root)
        run_dir = root / "runtime" / "goals" / GOAL_ID / "runs"
        markdown_result = run_cli(
            root,
            registry_path,
            "review-packet",
            "--goal-id",
            GOAL_ID,
            "--review-url",
            "https://example.invalid/review",
            "--scan-root",
            str(root / "project"),
        )
        packet = markdown_result.stdout
        assert "【Goal Harness Review Packet】" in packet, packet
        assert "类型：Controller" in packet, packet
        assert f"建议判断：同意 {GOAL_ID} 先做 read-only map dry-run；不授权写入或生产动作。" in packet, packet
        assert f"回复：同意 {GOAL_ID} 先做 read-only map dry-run / 暂不同意 + 一句话原因。" in packet, packet
        assert f"--reason-summary '同意 {GOAL_ID} 先做 read-only map dry-run，不授权写入或生产动作'" in packet, packet
        assert "【用户本地 Gate 记录草稿】" in packet, packet
        assert "记录规则：保留 --dry-run 只预览；确认写入 durable operator gate 时再删除 --dry-run。" in packet, packet
        assert "reject / defer 与一句 public-safe 原因" in packet, packet
        assert "operator-gate" in packet, packet
        assert "【给项目 Agent】" in packet, packet
        assert f"目标校验：本段只适用于 goal_id=`{GOAL_ID}`；如果与你当前 active goal 或 registry entry 不一致，停止并回报目标不匹配。" in packet, packet
        assert "上下文规则：本段只携带最小当前指令" in packet, packet
        assert "不要从旧聊天或旧 packet 拼当前状态" in packet, packet
        assert "转发条件：只有用户已经明确同意 read-only/controller dry-run 后，才把本段发给项目 Agent。" in packet, packet
        assert "执行边界：只执行下面只读或 dry-run 项目路径；不要运行用户本地 Gate 记录草稿。" in packet, packet
        assert "停止条件：需要真实 approval、write-control、run history append、生产动作或命令失败时，停下等明确授权。" in packet, packet
        assert "read-only-map" in packet, packet
        assert_order(
            packet,
            ["【人只需判断】", "【用户本地 Gate 记录草稿】", "operator-gate", "【给项目 Agent】", "目标校验", "read-only-map"],
        )
        assert not run_dir.exists(), "review-packet must not write runtime runs"

        json_result = run_cli(
            root,
            registry_path,
            "--format",
            "json",
            "review-packet",
            "--goal-id",
            GOAL_ID,
            "--scan-root",
            str(root / "project"),
        )
        payload = json.loads(json_result.stdout)
        assert payload["ok"] is True, payload
        assert payload["kind"] == "controller", payload
        assert payload["operator_gate_dry_run_command"], payload
        assert payload["operator_gate_decision_commands"]["approve"] == payload["operator_gate_dry_run_command"], payload
        assert "--decision reject" in payload["operator_gate_decision_commands"]["reject"], payload
        assert "<public-safe-reason>" in payload["operator_gate_decision_commands"]["reject"], payload
        assert "--decision defer" in payload["operator_gate_decision_commands"]["defer"], payload
        assert "<public-safe-condition>" in payload["operator_gate_decision_commands"]["defer"], payload
        assert payload["project_agent_command"], payload
        assert "转发条件" in payload["packet"], payload
        assert not run_dir.exists(), "json review-packet must not write runtime runs"

        append_operator_gate_approval_fixture(root)
        before_files = sorted(path.name for path in run_dir.iterdir())
        approved_markdown_result = run_cli(
            root,
            registry_path,
            "review-packet",
            "--goal-id",
            GOAL_ID,
            "--scan-root",
            str(root / "project"),
        )
        approved_packet = approved_markdown_result.stdout
        assert "类型：Codex" in approved_packet, approved_packet
        assert "问题：operator gate 已批准；是否把短交接发给目标项目 Agent？" in approved_packet, approved_packet
        assert "建议判断：直接转发给项目 Agent；不追加写权限、主控接管或生产动作授权。" in approved_packet, approved_packet
        assert "回复：转发下方【给项目 Agent】即可。" in approved_packet, approved_packet
        assert "这只是执行已批准的只读/dry-run agent_command" in approved_packet, approved_packet
        assert "【用户本地 Gate 记录草稿】" not in approved_packet, approved_packet
        assert "上下文规则：本段只携带最小当前指令" in approved_packet, approved_packet
        assert "不要从旧聊天或旧 packet 拼当前状态" in approved_packet, approved_packet
        assert "转发条件：operator gate 已记录为 approve；本段只用于把已批准的 agent_command 交给目标项目 Agent。" in approved_packet, approved_packet
        assert "执行边界：只执行下面命令；这是只读/dry-run 执行，不是写权限、主控接管或生产动作授权。" in approved_packet, approved_packet
        assert "停止条件：命令失败，或需要写入、run history append、生产动作、更高权限时，停下并用中文回报结果。" in approved_packet, approved_packet
        assert APPROVED_COMMAND in approved_packet, approved_packet
        assert_order(
            approved_packet,
            ["【人只需判断】", "operator gate 已批准", "【给项目 Agent】", "operator gate 已记录为 approve", APPROVED_COMMAND],
        )

        approved_json_result = run_cli(
            root,
            registry_path,
            "--format",
            "json",
            "review-packet",
            "--goal-id",
            GOAL_ID,
            "--scan-root",
            str(root / "project"),
        )
        approved_payload = json.loads(approved_json_result.stdout)
        assert approved_payload["ok"] is True, approved_payload
        assert approved_payload["kind"] == "codex", approved_payload
        assert approved_payload["operator_gate_approved_handoff"] is True, approved_payload
        assert approved_payload["project_agent_command"] == APPROVED_COMMAND, approved_payload
        assert approved_payload["project_agent_handoff"], approved_payload
        assert "operator gate 已记录为 approve" in approved_payload["project_agent_handoff"], approved_payload
        assert "不要从旧聊天或旧 packet 拼当前状态" in approved_payload["project_agent_handoff"], approved_payload
        assert approved_payload["operator_gate_dry_run_command"] is None, approved_payload
        assert approved_payload["operator_gate_decision_commands"] == {}, approved_payload
        after_files = sorted(path.name for path in run_dir.iterdir())
        assert after_files == before_files, "approved review-packet must not write runtime runs"

    print("review-packet-cli-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
