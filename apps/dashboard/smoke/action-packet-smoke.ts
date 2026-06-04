import { buildActionPacket, buildApprovedAgentHandoff } from "../src/data/action-packet.js";

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

const packet = buildActionPacket({
  goalId: "premium-ui-ai-search-rec-migration",
  title: "Review or authorize",
  summary: "production still blocked; owner/SOP snapshot has 9 blockers, but only two user todos are open",
  userTodoText: "Read the core Lark document section 8 first. Focus on 当前结论 and the Nacos diff 快速锚点 / Diff Anchors table.",
  agentTodoText: "Run the read-only map dry-run after the owner todo is resolved; stop before writes.",
  todoBlocksGate: true,
  operatorQuestion: "是否同意 premium-ui 迁移在 owner/SOP review 后继续推进？",
  suggestedReply: "同意继续 safe-local/offline 路径 / 暂不同意 + 一句话原因。",
  gateFallbackDecision: "同意继续 safe-local/offline 路径；不授权写入或生产动作。",
  boundary: "不要执行 Nacos 写入、Prem metadata upsert、workflow creation 或生产状态变化。",
  durableRecordRule: "记录规则：先用 operator-gate dry-run 预览；确认写入时去掉 --dry-run。",
  safePathLabel: "Read-only map dry-run",
  command: "goal-harness read-only-map --goal-id premium-ui-ai-search-rec-migration --dry-run",
  quotaShortLine: "Operator gate; 0/1440 slots",
  authorityShortLine: "default entries 10/10; topic 10; materials 6; owner review 1; stale 1; risk medium",
  projectOwner: "user_or_controller",
  projectGate: "owner_sop_review",
  projectNextAction: "Project asset says the owner/SOP review is the current authority.",
  projectStopCondition: "Stop before write-control or production mutation.",
  projectAssetSource: "project_asset",
});

assert(packet.includes("【GH Packet】"), "missing packet title");
assert(packet.includes("【用户/Gate】"), "missing user action section");
assert(packet.includes("Quota：Operator gate; 0/1440 slots"), "missing compact quota context");
assert(packet.includes("Authority：default entries 10/10; topic 10; materials 6; owner review 1; stale 1; risk medium"), "missing compact authority/material context");
assert(packet.includes("Project Asset：Owner=user_or_controller；Gate=owner_sop_review"), "missing project-asset owner/gate");
assert(packet.includes("Next：Project asset says the owner/SOP review is the current authority."), "missing project-asset next action");
assert(packet.includes("Stop：Stop before write-control or production mutation."), "missing project-asset stop condition");
assert(packet.includes("待办：Read the core Lark document section 8 first."), "missing first user todo");
assert(packet.includes("先处理/暂缓再判 gate"), "missing todo-before-gate cue");
assert(packet.includes("Gate：是否同意 premium-ui 迁移"), "missing gate question");
assert(packet.includes("【给项目 Agent】"), "missing project-agent handoff section");
assert(packet.includes("待办：Run the read-only map dry-run after the owner todo is resolved; stop before writes."), "missing first agent todo");
assert(packet.includes("路径：Read-only map dry-run"), "missing safe path");
assert(packet.includes("上下文：只信当前 state/status/history 与命令输出"), "missing agent context rule");
assert(packet.includes("不授权写入或生产动作") || packet.includes("不要执行 Nacos 写入"), "missing safety boundary");
assert(packet.length > 600 && packet.length < 1200, `unexpected packet length: ${packet.length}`);
assert(
  packet.indexOf("【用户/Gate】") < packet.indexOf("【给项目 Agent】"),
  "user action section must precede project-agent handoff",
);

const approvedHandoff = buildApprovedAgentHandoff({
  goalId: "planned-main-control",
  command: "goal-harness read-only-map --goal-id planned-main-control --dry-run --approved",
  agentTodoText: "Run the read-only map dry-run after owner todo resolution.",
  projectNextAction: "Approved project asset next action.",
  projectStopCondition: "Stop if execution needs write authority.",
  projectAssetSource: "project_asset",
});

assert(approvedHandoff.includes("目标校验：本段只适用于 goal_id=`planned-main-control`"), "missing target guard");
assert(approvedHandoff.includes("上下文规则：本段只携带最小当前指令"), "missing compact context rule");
assert(approvedHandoff.includes("Project Asset Next：Approved project asset next action."), "missing approved project-asset next action");
assert(approvedHandoff.includes("Project Asset Stop：Stop if execution needs write authority."), "missing approved project-asset stop condition");
assert(approvedHandoff.includes("Agent 待办：Run the read-only map dry-run after owner todo resolution."), "missing approved agent todo");
assert(approvedHandoff.includes("operator gate 已记录为 approve"), "missing approved forwarding condition");
assert(approvedHandoff.includes("只执行下面命令"), "missing execution boundary");
assert(approvedHandoff.includes("goal-harness read-only-map --goal-id planned-main-control --dry-run --approved"), "missing approved command");
assert(!approvedHandoff.includes("【GH Packet】"), "handoff-only payload must not include packet wrapper");
assert(!approvedHandoff.includes("【用户/Gate】"), "handoff-only payload must not include user gate wrapper");
assert(!approvedHandoff.includes("建议："), "handoff-only payload must not include human suggestion text");

const legacyFallbackPacket = buildActionPacket({
  goalId: "legacy-status-only",
  title: "Legacy status",
  summary: "raw status says continue but no project_asset is present",
  userTodoText: null,
  agentTodoText: "Inspect status only; do not treat raw fields as owner-approved state.",
  todoBlocksGate: false,
  operatorQuestion: null,
  suggestedReply: "保持 status inspection；补 project_asset 后再恢复 delivery。",
  gateFallbackDecision: "保持 status inspection；补 project_asset 后再恢复 delivery。",
  boundary: "This is a legacy/raw fallback; do not infer owner, gate, or stop condition authority.",
  safePathLabel: "Legacy status inspection",
  command: "goal-harness status --goal-id legacy-status-only",
  projectNextAction: "Continue from raw status field.",
  projectStopCondition: "Stop before any delivery claim.",
  projectAssetSource: "legacy_raw_fallback",
});

assert(legacyFallbackPacket.includes("Project Asset：legacy/raw fallback"), "missing legacy/raw fallback source");
assert(legacyFallbackPacket.includes("Owner/Gate/Stop 未确认"), "missing fallback untrusted-owner cue");
assert(legacyFallbackPacket.includes("Fallback Next：Continue from raw status field."), "missing fallback next label");
assert(legacyFallbackPacket.includes("Fallback Stop：Stop before any delivery claim."), "missing fallback stop label");
assert(!legacyFallbackPacket.includes("Project Asset：Owner="), "fallback packet must not claim owner/gate authority");

const focusWaitPacket = buildActionPacket({
  goalId: "focus-wait-owner-blocker",
  title: "Focus wait owner blocker",
  summary: "quiet until owner evidence, a clean baseline, or external eval changes",
  userTodoText: "Provide new owner evidence, a clean baseline, or external eval before delivery resumes.",
  agentTodoText: "只检查当前 state/status/history；保持 focus_wait 并用中文回报仍在等待什么。",
  todoBlocksGate: false,
  operatorQuestion: null,
  suggestedReply: "继续保持 focus wait；有新 owner evidence、clean baseline 或外部 eval 后再恢复 delivery。",
  gateFallbackDecision: "继续保持 focus wait；有新 owner evidence、clean baseline 或外部 eval 后再恢复 delivery。",
  boundary: "这不是 delivery approval；项目 Agent 只做 status/history inspection，不执行交付路径、写入、reward append 或生产动作。",
  safePathLabel: "Status/history inspection only",
  command: "goal-harness --registry ./examples/registry.example.json --runtime-root ./tmp/runtime status --goal-id focus-wait-owner-blocker",
});

assert(focusWaitPacket.includes("目标：focus-wait-owner-blocker"), "missing focus-wait goal id");
assert(focusWaitPacket.includes("待办：Provide new owner evidence"), "missing owner blocker unlock condition");
assert(focusWaitPacket.includes("Gate：无；建议：继续保持 focus wait"), "missing focus-wait fallback decision");
assert(focusWaitPacket.includes("Status/history inspection only"), "missing status/history-only safe path");
assert(focusWaitPacket.includes("保持 focus_wait"), "missing agent focus-wait boundary");
assert(!focusWaitPacket.includes("operator-gate"), "focus-wait packet must not draft an operator gate");
assert(!focusWaitPacket.includes("read-only-map"), "focus-wait packet must not expose a delivery map command");

console.log(`action-packet smoke ok (${packet.length} chars, handoff ${approvedHandoff.length} chars, legacy ${legacyFallbackPacket.length} chars, focus ${focusWaitPacket.length} chars)`);
