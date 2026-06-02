export type ActionPacketInput = {
  goalId: string;
  title: string;
  summary: string;
  userTodoText?: string | null;
  todoBlocksGate?: boolean;
  operatorQuestion?: string | null;
  suggestedReply: string;
  gateFallbackDecision: string;
  boundary: string;
  durableRecordRule?: string | null;
  safePathLabel: string;
  command?: string | null;
  quotaShortLine?: string | null;
  authorityShortLine?: string | null;
};

export function buildActionPacket(input: ActionPacketInput) {
  const userActionLines = input.userTodoText
    ? [
      `用户待办：${compactPacketText(input.userTodoText)}`,
      ...(input.todoBlocksGate ? ["完成或明确暂缓用户待办后，再判断下面的 Gate。"] : []),
    ]
    : [
      "用户待办：无。",
    ];
  const gateLines = input.operatorQuestion
    ? [
      `Gate：${compactPacketText(input.operatorQuestion)}`,
      `建议回复：${input.todoBlocksGate ? `先说明用户待办是否已完成；完成后再回复：${input.suggestedReply}` : input.suggestedReply}`,
    ]
    : [
      `Gate：无用户 gate；${input.gateFallbackDecision}`,
    ];
  const stateLine = [
    compactPacketText(input.summary, 180),
    input.quotaShortLine ? `配额 ${input.quotaShortLine}` : null,
    input.authorityShortLine ? `权威源 ${input.authorityShortLine}` : null,
  ].filter(Boolean).join("；");

  return [
    "【Goal Harness Action Packet】",
    `目标：${input.goalId}`,
    `动作：${input.title}`,
    `状态：${stateLine}`,
    "",
    "【用户动作 / Gate】",
    ...userActionLines,
    ...gateLines,
    `边界：${compactPacketText(input.boundary, 220)}`,
    input.durableRecordRule,
    "",
    "【同意后给项目 Agent】",
    `只允许 safe path：${input.safePathLabel}`,
    input.command ? `命令：${input.command.replace(/\s+/g, " ").trim()}` : null,
    "要求：用中文回报 changed files、validation、next safe action；需要写入/生产/进一步授权时停下。",
  ].filter(Boolean).join("\n");
}

export function compactPacketText(value: string, maxLength = 260) {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength - 1)}…`;
}
