#!/usr/bin/env python3
"""Smoke-test the dashboard Review Packet contract.

The dashboard owns the operator-facing packet text. This smoke keeps a
public-safe fixture for the planned opt-in path and checks the source still
orders the human question, local gate dry-run, and project-agent command
sections correctly.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PAGE = REPO_ROOT / "apps/dashboard/src/views/dashboard-page.tsx"
STATUS_CONTRACT = REPO_ROOT / "docs/status-data-contract.md"


def command_block(command: str) -> str:
    return "\n".join(["```bash", command, "```"])


def multiline_command(*lines: str) -> str:
    return "\n".join(lines)


def assert_order(text: str, labels: list[str]) -> None:
    positions = [text.index(label) for label in labels]
    assert positions == sorted(positions), (labels, positions, text)


def source_between(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def build_sanitized_controller_packet() -> str:
    goal_id = "planned-main-control"
    operator_gate_draft = multiline_command(
        "goal-harness \\",
        "  --registry ./examples/registry.example.json \\",
        "  --runtime-root ./tmp/runtime \\",
        "  operator-gate \\",
        f"  --goal-id {goal_id} \\",
        "  --decision approve \\",
        "  --reason-summary '同意先做 read-only map dry-run，不授权写入或生产动作' \\",
        "  --dry-run",
    )
    project_agent_command = multiline_command(
        "goal-harness \\",
        "  --registry ./examples/registry.example.json \\",
        "  --runtime-root ./tmp/runtime \\",
        "  read-only-map \\",
        f"  --goal-id {goal_id} \\",
        "  --dry-run",
    )
    return "\n".join(
        [
            "【Goal Harness Review Packet】",
            f"目标：{goal_id}",
            "类型：Controller",
            "链接：https://example.invalid/review",
            "摘要：planned opt-in review fixture",
            "权威源：public-safe fixture",
            "配额：eligible",
            "",
            "【人只需判断】",
            "问题：是否允许目标项目进入 read-only/controller opt-in？",
            "回复：同意先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "边界：这只授权项目 Agent 预览 dry-run 路径；不写 operator gate、run history、write-control、实验控制或生产动作。",
            "",
            "【用户本地 Gate 记录草稿】",
            "用途：人确认后，由用户或主控先 dry-run 预览 durable operator gate；不要把它当作项目 Agent 执行命令。",
            command_block(operator_gate_draft),
            "",
            "【给项目 Agent】",
            "转发条件：只有用户已经明确同意 read-only/controller dry-run 后，才把本段发给项目 Agent。",
            "执行边界：只执行下面只读或 dry-run 项目路径；不要运行用户本地 Gate 记录草稿。",
            "停止条件：需要真实 approval、write-control、run history append、生产动作或命令失败时，停下等明确授权。",
            "",
            command_block(project_agent_command),
            "",
            "回报：用中文说明 changed files、validation 和 next safe action。",
        ]
    )


def main() -> int:
    source = DASHBOARD_PAGE.read_text(encoding="utf-8")
    contract = STATUS_CONTRACT.read_text(encoding="utf-8")
    controller_contract = source_between(
        contract,
        "For controller opt-in packets",
        "`status=read_only_project_map`",
    )
    assert "the dashboard/operator view owns the human decision" in contract
    assert "the project-agent command is only the after-approval dry-run execution path" in contract
    assert "复制后直接发给对应项目 Agent；人只补一句判断。" not in source
    assert "Operator Review Packet" in source
    assert "先在 dashboard/operator view 做判断；同意后再把 packet 作为项目 Agent 的执行上下文。" in source
    assert "项目 Agent 只有在 approval 后才回报 changed files、validation 和 next safe action。" in source
    assert "转发条件：只有用户已经明确同意 read-only/controller dry-run 后，才把本段发给项目 Agent。" in source
    assert "执行边界：只执行下面只读或 dry-run 项目路径；不要运行用户本地 Gate 记录草稿。" in source
    assert "停止条件：需要真实 approval、write-control、run history append、生产动作或命令失败时，停下等明确授权。" in source
    assert_order(
        controller_contract,
        [
            "operator question must appear before any",
            "local gate preview must appear before any",
            "project-agent command",
        ],
    )

    packet_builder = source_between(source, "function buildReviewPacket", "function ReviewLinkPanel")
    assert_order(packet_builder, ["【人只需判断】", "【用户本地 Gate 记录草稿】", "【给项目 Agent】"])

    controller_prompt = source_between(source, "if (kind === \"controller\")", "if (kind === \"codex\")")
    assert "是否允许目标项目进入 read-only/controller opt-in？" in controller_prompt
    assert "同意先做 read-only map dry-run / 暂不同意 + 一句话原因。" in controller_prompt
    assert "不写 operator gate、run history、write-control、实验控制或生产动作" in controller_prompt

    gate_builder = source_between(source, "function buildOperatorGateDryRunCommand", "function buildOperatorTransitionPreview")
    assert "operator-gate" in gate_builder
    assert "--decision approve" in gate_builder
    assert "同意先做 read-only map dry-run，不授权写入或生产动作" in gate_builder
    assert "--dry-run" in gate_builder

    read_only_builder = source_between(source, "function buildReadOnlyMapDryRunCommand", "function buildRefreshStateDryRunCommand")
    assert "read-only-map" in read_only_builder
    assert "--dry-run" in read_only_builder

    quota_state_labels = source_between(source, "const quotaStateLabel", "function quotaVariant")
    assert "Throttled" in quota_state_labels
    assert "本窗口配额已用完" in quota_state_labels

    user_action_builder = source_between(source, "function buildUserActionSummaryItems", "function UserActionSummary")
    assert "const quota = row.queueItem?.quota ?? row.goal.quota;" in user_action_builder
    assert "const quotaState = quota?.state ?? \"waiting\";" in user_action_builder
    assert "decision.waitingOn === \"codex\" && quotaState === \"throttled\"" in user_action_builder
    assert_order(
        user_action_builder,
        [
            "if (decision.waitingOn === \"external_evidence\")",
            "decision.waitingOn === \"codex\" && quotaState === \"throttled\"",
            "if (decision.waitingOn === \"codex\")",
        ],
    )

    packet = build_sanitized_controller_packet()
    assert_order(
        packet,
        [
            "问题：是否允许目标项目进入 read-only/controller opt-in？",
            "【用户本地 Gate 记录草稿】",
            "operator-gate",
            "【给项目 Agent】",
            "转发条件",
            "执行边界",
            "停止条件",
            "read-only-map",
        ],
    )
    assert packet.count("operator-gate") == 1, packet
    assert packet.count("read-only-map") == 1, packet
    assert "不要把它当作项目 Agent 执行命令" in packet
    assert "不授权写入或生产动作" in packet
    print("review-packet-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
