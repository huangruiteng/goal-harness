#!/usr/bin/env python3
"""Smoke-test the dashboard operator action packet contract.

The dashboard owns the operator-facing packet text. This smoke keeps a
public-safe fixture for the planned opt-in path and checks the source keeps the
copyable packet short and human-facing. The longer local gate dry-run remains
available as an advanced/debug path, not as the default copied packet.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PAGE = REPO_ROOT / "apps/dashboard/src/views/dashboard-page.tsx"
ACTION_PACKET = REPO_ROOT / "apps/dashboard/src/data/action-packet.ts"
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
            "【Goal Harness Action Packet】",
            f"目标：{goal_id}",
            "动作：Review controller opt-in",
            "状态：planned opt-in review fixture；配额 Operator gate; 0/1440 slots；权威源 default entries 10/10; topic 10; risk medium",
            "",
            "【用户动作 / Gate】",
            "用户待办：无。",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            f"建议回复：同意 {goal_id} 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "边界：这只授权项目 Agent 预览 dry-run 路径；不写 operator gate、run history、write-control、实验控制或生产动作。",
            "记录规则：如需持久记录本次判断，先用本地 operator-gate dry-run 预览；确认写入时去掉 --dry-run；拒绝/暂缓用 reject/defer + public-safe 原因。",
            "",
            "【同意后给项目 Agent】",
            "只允许 safe path：Read-only map dry-run",
            f"命令：{project_agent_command.replace(chr(10), ' ')}",
            "要求：用中文回报 changed files、validation、next safe action；需要写入/生产/进一步授权时停下。",
        ]
    )


def build_sanitized_controller_packet_with_user_todo() -> str:
    goal_id = "planned-main-control"
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
            "【Goal Harness Action Packet】",
            f"目标：{goal_id}",
            "动作：Review or authorize",
            "状态：planned opt-in review fixture",
            "",
            "【用户动作 / Gate】",
            "用户待办：Read the owner review worksheet first.",
            "完成或明确暂缓用户待办后，再判断下面的 Gate。",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            f"建议回复：先说明用户待办是否已完成；完成后再回复：同意 {goal_id} 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "边界：这只授权项目 Agent 预览 dry-run 路径；不写 operator gate、run history、write-control、实验控制或生产动作。",
            "记录规则：如需持久记录本次判断，先用本地 operator-gate dry-run 预览；确认写入时去掉 --dry-run；拒绝/暂缓用 reject/defer + public-safe 原因。",
            "",
            "【同意后给项目 Agent】",
            "只允许 safe path：Read-only map dry-run",
            f"命令：{project_agent_command.replace(chr(10), ' ')}",
            "要求：用中文回报 changed files、validation、next safe action；需要写入/生产/进一步授权时停下。",
        ]
    )


def main() -> int:
    source = DASHBOARD_PAGE.read_text(encoding="utf-8")
    action_packet_source = ACTION_PACKET.read_text(encoding="utf-8")
    contract = STATUS_CONTRACT.read_text(encoding="utf-8")
    controller_contract = source_between(
        contract,
        "For controller opt-in packets",
        "`status=read_only_project_map`",
    )
    assert "the dashboard/operator view owns the human decision" in contract
    assert "the project-agent command is only the after-approval dry-run execution path" in contract
    assert "复制后直接发给对应项目 Agent；人只补一句判断。" not in source
    assert "【Goal Harness Action Packet】" in action_packet_source
    assert "【用户动作 / Gate】" in action_packet_source
    assert "Copy action packet for" in source
    assert "需要写入/生产/进一步授权时停下" in action_packet_source
    assert "input.command ? `命令：" in action_packet_source
    assert_order(
        controller_contract,
        [
            "operator question must appear before any",
            "local gate preview must appear before any",
            "project-agent command",
        ],
    )

    packet_builder = source_between(source, "function buildHumanFriendlyActionPacket", "function readinessVariant")
    assert "return buildActionPacket({" in packet_builder
    assert_order(action_packet_source, ["【Goal Harness Action Packet】", "【用户动作 / Gate】", "【同意后给项目 Agent】"])
    assert "operatorGateDraftCommand" not in packet_builder
    assert "用户待办：" in action_packet_source
    assert "Gate：" in action_packet_source
    assert "先说明用户待办是否已完成" in action_packet_source

    controller_prompt = source_between(source, "if (kind === \"controller\")", "if (kind === \"codex\")")
    assert "是否允许目标项目进入 read-only/controller opt-in？" in controller_prompt
    assert "同意先做 read-only map dry-run / 暂不同意 + 一句话原因。" in controller_prompt
    assert "不写 operator gate、run history、write-control、实验控制或生产动作" in controller_prompt

    controller_reply = source_between(source, "function controllerReplyLine", "function suggestedDecisionLine")
    assert "同意 ${goalId} 先做 read-only map dry-run / 暂不同意 + 一句话原因。" in controller_reply
    assert "同意 ${goalId} 先做 read-only map dry-run，不授权写入或生产动作" in controller_reply
    record_rule = source_between(source, "function durableOperatorGateRecordRule", "function suggestedDecisionLine")
    assert "记录规则：如需持久记录本次判断" in record_rule
    assert "operator-gate dry-run 预览" in record_rule
    assert "reject/defer + public-safe 原因" in record_rule
    assert "durableOperatorGateRecordRule(item.kind)" in packet_builder

    gate_builder = source_between(source, "function buildOperatorGateDryRunCommand", "function buildOperatorDecision")
    assert "operator-gate" in gate_builder
    assert "--decision approve" in gate_builder
    assert "controllerApprovalReason(goalId)" in gate_builder
    assert "--dry-run" in gate_builder

    read_only_builder = source_between(source, "function buildReadOnlyMapDryRunCommand", "function buildRefreshStateDryRunCommand")
    assert "read-only-map" in read_only_builder
    assert "--dry-run" in read_only_builder

    quota_state_labels = source_between(source, "const quotaStateLabel", "function quotaVariant")
    assert "Throttled" in quota_state_labels
    assert "本窗口配额已用完" in quota_state_labels

    user_action_builder = source_between(source, "function buildUserActionSummaryItems", "function UserActionSummary")
    assert "const projectAsset = row.queueItem?.project_asset;" in user_action_builder
    assert "const quota = projectAsset?.quota ?? row.queueItem?.quota ?? row.goal.quota;" in user_action_builder
    assert "todosFromProjectAssetSummary(projectAsset?.user_todos" in user_action_builder
    assert "const nextAction = projectAsset?.next_action ?? decision.action;" in user_action_builder
    assert "const stopCondition = projectAsset?.stop_condition ?? handoffCondition ?? decision.action;" in user_action_builder
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
    user_action_summary = source_between(source, "function UserActionSummary", "function OperatorDecisionPanel")
    assert "buildHumanFriendlyActionPacket({ item, registry, runtimeRoot })" in user_action_summary
    assert "aria-label={`Copy action packet for ${item.goalId}`}" in user_action_summary
    assert "const primaryOperatorGate" not in user_action_summary
    assert "Needs decision" not in user_action_summary
    assert "blocksGate={Boolean(item.operatorQuestion && firstOpenTodo(item.userTodos))}" in user_action_summary
    assert "先做用户待办" in source
    assert "完成或明确暂缓这个用户待办后，再审批下面的 gate。" in source

    packet = build_sanitized_controller_packet()
    assert_order(
        packet,
        [
            "【用户动作 / Gate】",
            "Gate：是否允许目标项目进入 read-only/controller opt-in？",
            "建议回复：同意 planned-main-control 先做 read-only map dry-run / 暂不同意 + 一句话原因。",
            "记录规则：如需持久记录本次判断",
            "【同意后给项目 Agent】",
            "read-only-map",
            "需要写入/生产/进一步授权时停下",
        ],
    )
    assert "operator-gate dry-run 预览" in packet, packet
    assert "operator-gate \\" not in packet, packet
    assert packet.count("read-only-map") == 1, packet
    assert len(packet.splitlines()) <= 21, packet
    assert "不写 operator gate、run history、write-control、实验控制或生产动作" in packet

    packet_with_todo = build_sanitized_controller_packet_with_user_todo()
    assert_order(
        packet_with_todo,
        [
            "【用户动作 / Gate】",
            "用户待办：",
            "完成或明确暂缓用户待办后",
            "Gate：",
            "建议回复：先说明用户待办是否已完成",
            "【同意后给项目 Agent】",
        ],
    )
    assert "Read the owner review worksheet first." in packet_with_todo
    assert "operator-gate \\" not in packet_with_todo, packet_with_todo
    assert len(packet_with_todo.splitlines()) <= 22, packet_with_todo
    print("review-packet-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
