import { useEffect, useMemo, useRef, useState, type ClipboardEvent as ReactClipboardEvent } from "react";
import { AlertCircle, Bot, CalendarClock, ListPlus, MessageCircleQuestion, Paperclip, Plus, Send, X } from "lucide-react";

import {
  applyTypedAction,
  cancelTypedAction,
  ChatApiError,
  configureGoalChannelAutoNotify,
  fetchGoalContexts,
  fetchGoalChannelTargets,
  fetchLarkConnections,
  listTypedActions,
  previewTypedAction,
  setupGoalChannel,
  transitionTypedAction,
  type GoalRepositoryContext,
  type LarkGoalConnection,
  type TypedActionProposal,
} from "../../data/chat";

import { ChannelHeader } from "./channel-header";
import { ChannelTimeline } from "./channel-timeline";
import { ContextDrawer } from "./context-drawer";
import { GoalSidebar } from "./goal-sidebar";
import { GoalTasksView } from "./goal-tasks-view";
import { LarkSettingsPage } from "./lark-settings-page";
import { MarkdownText } from "./markdown";
import type {
  PersonalWorkspaceCallbacks,
  WorkspaceAgentOption,
  WorkspaceActionPreview,
  WorkspaceActionPreviewRequest,
  WorkspaceDrawerSelection,
  WorkspaceGoal,
  WorkspaceGoalTab,
  WorkspaceImageAttachment,
  WorkspaceModel,
  WorkspaceRun,
  WorkspaceSystemHealth,
  WorkspaceTimelineItem,
} from "./personal-workspace-model";
import { goalTitleFor, workspaceHomeLaneForGoal, workspaceSessionStatusLabel } from "./personal-workspace-model";
import { routeWorkspaceInput } from "./personal-workspace-router";
import { WorkspaceShell } from "./workspace-shell";
import "./personal-workspace.css";

export function sanitizeTaskDraftFromReply(reply: string): string {
  const nextStepMatch = reply.match(/(?:下一步|建议|行动项|待办)[：:\s]*([^\n]+)/u);
  let candidate = nextStepMatch ? nextStepMatch[1] : reply;
  candidate = candidate
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#*~_>]/g, "")
    .replace(/^[-*•\d+.\s]+/u, "")
    .replace(/^(好的|没问题|收到|建议如下|任务如下|分析如下|结论[：:])[\s，,：:]*/u, "");
  const lines = candidate.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const firstLine = lines[0] || candidate;
  const normalized = firstLine.replace(/\s+/gu, " ").trim();
  return Array.from(normalized).slice(0, 120).join("");
}

function dedupeProposals(proposals: WorkspaceActionPreview[]): WorkspaceActionPreview[] {
  const latest = new Map<string, WorkspaceActionPreview>();
  proposals.forEach((proposal) => {
    const subject = proposal.fields.find((field) => field.label === "todo id")?.value ?? "";
    const key = [proposal.actionKind, proposal.goalId ?? "", subject, proposal.title].join(":");
    latest.set(key, proposal);
  });
  return [...latest.values()];
}

const activeHomeLanes = [
  { description: "等待你的决定、授权或补充信息", key: "needs_you", label: "需要你" },
  { description: "Agent 正在推进并持续回传进展", key: "running", label: "执行中" },
  { description: "持续监控，出现变化时再提醒你", key: "observing", label: "观察中" },
  { description: "已经安排，等待时间或前置条件", key: "scheduled", label: "已安排" },
] as const;

function activityTimeLabel(value?: string) {
  if (!value) return "等待首次活动";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  const today = new Date();
  const time = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(parsed);
  if (parsed.toDateString() === today.toDateString()) return `今天 ${time}`;
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(parsed);
}

function ManagerHomeBoard({
  goals,
  onSelectGoal,
  systemHealth,
}: {
  goals: WorkspaceGoal[];
  onSelectGoal: (goalId: string) => void;
  systemHealth?: WorkspaceSystemHealth;
}) {
  const active = Object.fromEntries(activeHomeLanes.map((lane) => [lane.key, [] as WorkspaceGoal[]])) as Record<(typeof activeHomeLanes)[number]["key"], WorkspaceGoal[]>;
  const history: WorkspaceGoal[] = [];
  const stopped: WorkspaceGoal[] = [];
  goals.forEach((goal) => {
    const lane = workspaceHomeLaneForGoal(goal);
    if (lane === "history") history.push(goal);
    else if (lane === "stopped") stopped.push(goal);
    else active[lane].push(goal);
  });
  const goalCard = (goal: WorkspaceGoal) => (
    <button className="personal-home-goal-card" data-goal-state={goal.state} key={goal.goalId} onClick={() => onSelectGoal(goal.goalId)} type="button">
      <span className="personal-home-goal-meta"><i />{goal.agentLabel ?? goal.agentId}</span>
      <strong>{goal.title}</strong>
      <p>{goal.needsYou ?? goal.nextSentence}</p>
      <footer><span>{goal.state}</span><small title={goal.latestActivity}>{goal.latestActivity ? activityTimeLabel(goal.latestActivity) : goal.agentTodos.length ? `${goal.agentTodos.length} 个 Task` : "尚无活动"}</small></footer>
    </button>
  );
  return (
    <section aria-label="Goal 工作区" className="personal-home-board">
      {systemHealth && (!systemHealth.ok || systemHealth.issues.length > 0 || systemHealth.freshnessWarning) ? (
        <div className="personal-system-health-banner" role="alert">
          <div className="personal-system-health-header">
            <AlertCircle size={15} />
            <strong>系统健康：{systemHealth.summary}</strong>
            {systemHealth.freshnessWarning ? <small>（{systemHealth.freshnessWarning}）</small> : null}
          </div>
          {systemHealth.issues.length > 0 ? (
            <ul className="personal-system-health-issues">
              {systemHealth.issues.map((issue, idx) => (
                <li key={idx}>{issue}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="personal-home-lanes">
        {activeHomeLanes.map((lane) => (
          <section className={`personal-home-lane is-${lane.key}`} data-testid={`personal-home-lane-${lane.key}`} key={lane.key}>
            <header><span><i />{lane.label}</span><b>{active[lane.key].length}</b></header>
            <p>{lane.description}</p>
            <div className="personal-home-lane-list">
              {active[lane.key].length ? active[lane.key].map(goalCard) : <span className="personal-home-empty">当前没有</span>}
            </div>
          </section>
        ))}
      </div>
      <details className="personal-home-history">
        <summary><span>历史</span><b>{history.length}</b><small>已完成的 Goal</small></summary>
        <div>{history.length ? history.map(goalCard) : <span className="personal-home-empty">还没有已完成的 Goal</span>}</div>
      </details>
      {stopped.length ? (
        <details className="personal-home-history is-stopped">
          <summary><span>已停止</span><b>{stopped.length}</b><small>保留状态，可随时恢复</small></summary>
          <div>{stopped.map(goalCard)}</div>
        </details>
      ) : null}
    </section>
  );
}

function ManagerConversationTray({
  agentLabel,
  messages,
  onClose,
  onDraftTask,
  onOpenConversation,
  title,
}: {
  agentLabel?: string;
  messages: Array<Extract<WorkspaceTimelineItem, { kind: "message" }>['message']>;
  onClose?: () => void;
  onDraftTask?: (text: string) => void;
  onOpenConversation: () => void;
  title?: string;
}) {
  const latestUserIndex = messages.reduce((latest, message, index) => message.role === "user" ? index : latest, 0);
  const latestExchange = messages.slice(Math.max(0, latestUserIndex));
  const visibleMessages = latestExchange.slice(-3);
  const latestAssistantMessage = visibleMessages.filter((item) => item.role === "assistant" && !item.pending).at(-1);

  useEffect(() => {
    if (!onClose) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <aside aria-label="对话回执" className="personal-manager-conversation-tray">
      <header>
        <span>
          <Bot size={16} />
          <strong>{title ?? "管家对话"}</strong>
          <small>{messages.at(-1)?.pending ? "正在回复" : "刚刚"}</small>
        </span>
        <div className="personal-manager-conversation-actions">
          {onDraftTask && latestAssistantMessage ? (
            <button
              className="personal-manager-conversation-btn"
              onClick={() => onDraftTask(latestAssistantMessage.text)}
              title="将 Agent 最新回复转为 Task 草稿"
              type="button"
            >
              <ListPlus size={13} />
              <span>转为 Task</span>
            </button>
          ) : null}
          <button className="personal-manager-conversation-link" onClick={onOpenConversation} type="button">查看完整对话</button>
          {onClose ? (
            <button
              aria-label="关闭对话回执"
              className="personal-manager-conversation-close"
              onClick={onClose}
              title="关闭对话回执"
              type="button"
            >
              <X size={14} />
            </button>
          ) : null}
        </div>
      </header>
      <div aria-live="polite" className="personal-manager-conversation-messages">
        {visibleMessages.map((message) => (
          <article className={`is-${message.role}`} key={message.id}>
            <strong>{message.role === "user" ? "你" : message.agentLabel ?? agentLabel ?? "LoopX 管家"}</strong>
            <div className="personal-manager-conversation-bubble">
              {message.role === "user" ? <p>{message.text}</p> : <MarkdownText text={message.text} />}
              {message.pending ? <small>正在整理…</small> : null}
            </div>
          </article>
        ))}
      </div>
    </aside>
  );
}

function SessionRecordHeader({ onClose, onOpenDetails, run }: {
  onClose: () => void;
  onOpenDetails: () => void;
  run: WorkspaceRun;
}) {
  return (
    <section aria-label="执行 Session 运行记录" className="personal-session-record">
      <header>
        <span><Bot size={17} />执行 Session · 运行记录</span>
        <button aria-label="退出运行记录" onClick={onClose} type="button"><X size={15} /></button>
      </header>
      <div>
        <strong>{run.title}</strong>
        <p>当前时间线已切换到这次 Session 的消息与 Turn 记录。</p>
      </div>
      <dl>
        <div><dt>Agent</dt><dd>{run.agentLabel}</dd></div>
        <div><dt>状态</dt><dd>{workspaceSessionStatusLabel(run.sessionStatus ?? run.status)}</dd></div>
        <div><dt>Session</dt><dd title={run.sessionId}>{run.sessionId}</dd></div>
      </dl>
      <button className="personal-secondary-action" onClick={onOpenDetails} type="button">Session 详情</button>
    </section>
  );
}

function defaultTimeline(model: WorkspaceModel, selectedGoalId: string | null): WorkspaceTimelineItem[] {  const items: WorkspaceTimelineItem[] = [];
  if (selectedGoalId === null) {
    model.userTodos.slice(0, 4).forEach((attention) => items.push({
      attention: { ...attention, goalTitle: attention.goalTitle ?? goalTitleFor(model, attention.goalId) },
      id: `attention:${attention.todoId}`,
      kind: "attention",
    }));
    model.goals.filter((goal) => workspaceHomeLaneForGoal(goal) === "running").slice(0, 4).forEach((goal) => items.push({
      id: `run:${goal.goalId}`,
      kind: "run",
      run: {
        agentId: goal.agentId,
        agentLabel: goal.agentLabel ?? goal.agentId,
        completedSteps: goal.agentTodos.filter((todo) => todo.done).length,
        goalId: goal.goalId,
        goalTitle: goal.title,
        latestActivity: goal.agentSentence,
        runId: `goal:${goal.goalId}`,
        status: "running",
        title: goal.nextSentence,
        totalSteps: goal.agentTodos.length || 1,
      },
    }));
    return items;
  }
  const goal = model.goals.find((candidate) => candidate.goalId === selectedGoalId);
  if (!goal) return items;
  if (goal.needsYou) {
    items.push({
      attention: {
        blocking: goal.needsYouBlocking ?? false,
        goalId: goal.goalId,
        goalTitle: goal.title,
        text: goal.needsYou,
        todoId: `${goal.goalId}:attention`,
      },
      id: `attention:${goal.goalId}`,
      kind: "attention",
    });
  }
  items.push({
    id: `run:${goal.goalId}`,
    kind: "run",
    run: {
      agentId: goal.agentId,
      agentLabel: goal.agentLabel ?? goal.agentId,
      completedSteps: goal.agentTodos.filter((todo) => todo.done).length,
      goalId: goal.goalId,
      goalTitle: goal.title,
      latestActivity: goal.agentSentence,
      runId: `goal:${goal.goalId}`,
      status: goal.state === "推进中" ? "running" : goal.state === "需修复" ? "failed" : "waiting",
      title: goal.nextSentence,
      totalSteps: goal.agentTodos.length || 1,
    },
  });
  goal.agentTodos.filter((todo) => todo.taskClass === "continuous_monitor").forEach((todo) => {
    const monitorRun = model.timeline?.find((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> =>
      item.kind === "run"
      && item.run.goalId === goal.goalId
      && item.run.todoId === todo.todoId
      && Boolean(item.run.sessionId));
    items.push({
    id: `schedule:${goal.goalId}:${todo.todoId}`,
    kind: "schedule",
    schedule: {
      agentId: goal.agentId,
      executionHistory: monitorRun ? [{
        label: monitorRun.run.latestActivity || monitorRun.run.title,
        runId: monitorRun.run.runId,
        status: monitorRun.run.status === "waiting" || monitorRun.run.status === "queued" ? "running" : monitorRun.run.status,
        timestamp: goal.latestActivity || "最近活动",
      }] : [],
      goalId: goal.goalId,
      label: todo.text,
      schedule: todo.evidence ?? "由 LoopX continuous_monitor Todo 驱动",
      scheduleId: todo.todoId,
      scheduleKind: "monitor",
      sessionId: monitorRun?.run.sessionId,
      status: todo.done || todo.status === "paused" ? "paused" : "active",
      stopCondition: "Goal 完成或 owner 停止",
      target: todo.text,
      timezone: "Asia/Shanghai",
    },
    });
  });
  const heartbeatProposal = model.timeline?.find((item): item is Extract<WorkspaceTimelineItem, { kind: "proposal" }> =>
    item.kind === "proposal" && item.proposal.actionKind === "heartbeat.bind" && item.proposal.goalId === goal.goalId);
  if (heartbeatProposal) {
    const field = (label: string) => heartbeatProposal.proposal.fields.find((item) => item.label === label)?.value;
    items.push({
      id: `schedule:${goal.goalId}:heartbeat`,
      kind: "schedule",
      schedule: {
        agentId: goal.agentId,
        executionHistory: [],
        goalId: goal.goalId,
        label: `推进 ${goal.title}`,
        nextRunAt: "等待宿主调度确认",
        notificationRule: field("notification policy") ?? "仅在需要你时通知",
        schedule: field("cadence") ?? "由 heartbeat-prompt 生命周期驱动",
        scheduleId: `${goal.goalId}:heartbeat`,
        scheduleKind: "heartbeat",
        status: heartbeatProposal.proposal.status === "applied" ? "active" : "draft",
        stopCondition: field("stop condition") ?? "Goal 完成或 owner 停止",
        timezone: field("timezone") ?? "Asia/Shanghai",
      },
    });
  }
  return items;
}

function proposalStatus(status: TypedActionProposal["status"]): WorkspaceActionPreview["status"] {
  if (status === "preview_ready") return "ready";
  if (status === "cancelled") return "draft";
  if (status === "failed") return "error";
  return status;
}

function proposalFields(parameters: Record<string, unknown>) {
  const fieldLabels: Record<string, string> = {
    agent_id: "Agent",
    completion_criteria: "完成标准",
    execution_boundary: "执行边界",
    goal_id: "Goal ID",
    operation: "操作",
    reason: "原因",
    initial_todos: "首个任务",
    objective: "目标",
    permission: "权限",
    stop_condition: "停止条件",
    title: "标题",
    workspace_ref: "执行工作区",
  };
  const priority = ["title", "objective", "completion_criteria", "execution_boundary", "permission", "agent_id", "workspace_ref", "initial_todos", "heartbeat", "stop_condition", "goal_id"];
  return Object.entries(parameters)
    .sort(([left], [right]) => {
      const leftIndex = priority.indexOf(left);
      const rightIndex = priority.indexOf(right);
      return (leftIndex < 0 ? priority.length : leftIndex) - (rightIndex < 0 ? priority.length : rightIndex);
    })
    .slice(0, 10)
    .map(([label, value]) => ({
    label: fieldLabels[label] ?? label.replaceAll("_", " "),
    value: label === "workspace_ref"
      ? value === "current"
        ? "当前本地工作区（未绑定 Repository）"
        : `${String(value ?? "当前工作区")}（仅提供执行环境，不会自动关联仓库）`
      : Array.isArray(value) ? value.join(" · ") : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value ?? "—"),
    }));
}

function workspaceProposal(proposal: TypedActionProposal): WorkspaceActionPreview {
  const lifecycleOperation = proposal.action_kind === "goal.lifecycle"
    && (proposal.normalized_parameters.operation === "stop" || proposal.normalized_parameters.operation === "resume")
    ? proposal.normalized_parameters.operation
    : undefined;
  return {
    actionKind: proposal.action_kind,
    fields: proposalFields(proposal.normalized_parameters),
    goalId: typeof proposal.normalized_parameters.goal_id === "string" ? proposal.normalized_parameters.goal_id : undefined,
    impact: proposal.action_kind === "goal.create"
      ? "确认后会创建 Goal 和首个 Todo，并让选定 Agent 开始首轮推进。"
      : proposal.action_kind === "goal.lifecycle" && lifecycleOperation === "stop"
        ? "确认后会停止自动推进，并将 Goal 移入折叠的「已停止」列表；历史、Todo 和证据都会保留，可随时恢复。"
        : proposal.action_kind === "goal.lifecycle"
          ? "确认后会恢复 Goal 的自动调度资格并移回 Active Goals；实际执行仍受 quota、Gate 和 Todo 约束。"
      : proposal.permission_classification === "protected"
      ? "该操作需要通过受保护的 LoopX 写入服务完成。"
      : "确认后会调用规范 LoopX 服务写入状态。",
    previewId: proposal.proposal_id,
    lifecycleOperation,
    gate: proposal.gate ? {
      kind: String(proposal.gate.kind ?? "protected_action"),
      nextAction: typeof proposal.gate.next_action === "string" ? proposal.gate.next_action : undefined,
      summary: String(proposal.gate.summary ?? "需要宿主确认"),
    } : undefined,
    primaryLabel: proposal.action_kind === "goal.create" ? "创建 Goal 并开始首轮"
      : proposal.action_kind === "goal.lifecycle" && lifecycleOperation === "stop"
        ? "停止 Goal"
        : proposal.action_kind === "goal.lifecycle"
          ? "恢复 Goal"
      : proposal.action_kind === "todo.create" && proposal.normalized_parameters.start_execution === true
        ? "创建任务并开始执行"
        : "确认并应用",
    status: proposalStatus(proposal.status),
    title: proposal.summary,
  };
}

function compactGoalSlug(value: string) {
  const ascii = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 42);
  if (ascii) return ascii;
  let hash = 2_166_136_261;
  for (const character of value) {
    hash ^= character.codePointAt(0) ?? 0;
    hash = Math.imul(hash, 16_777_619);
  }
  return `goal-${(hash >>> 0).toString(36)}`;
}

function goalTitleFromMessage(message: string) {
  const quoted = message.match(/[「“"]([^」”"]{2,80})[」”"]/u)?.[1];
  if (quoted) return quoted.trim();
  return message
    .replace(/^(请|帮我|我想|给我|创建|新建|设置)+/u, "")
    .replace(/(一个|新的)?\s*(goal|目标)/giu, "")
    .replace(/[，。！？].*$/u, "")
    .trim()
    .slice(0, 80) || "新的个人 Goal";
}

function structuredFieldFromMessage(message: string, labels: string[]) {
  for (const line of message.split(/\r?\n/u)) {
    const trimmed = line.trim();
    for (const label of labels) {
      const match = trimmed.match(new RegExp(`^${label.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")}\\s*[：:]\\s*(.*)$`, "u"));
      if (match?.[1]?.trim()) return match[1].trim();
    }
  }
  return "";
}

function structuredGoalIntentFromMessage(message: string) {
  const target = structuredFieldFromMessage(message, ["目标"]);
  const completion = structuredFieldFromMessage(message, ["完成标准"]);
  const boundary = structuredFieldFromMessage(message, ["执行边界（可选）", "执行边界", "边界"]);
  const title = (target || goalTitleFromMessage(message)).split(/[。；;\n]/u)[0].trim().slice(0, 80) || "新的个人 Goal";
  const objective = [target || title, completion ? `完成标准：${completion}` : "", boundary ? `执行边界：${boundary}` : ""]
    .filter(Boolean)
    .join("\n");
  const readOnly = /(只读|不调用外部工具|不修改(?:仓库|代码|状态)|read.?only)/iu.test(boundary || message);
  return {
    completionCriteria: completion,
    executionBoundary: boundary,
    initialTodos: completion ? [`按完成标准推进：${completion}`] : [],
    objective,
    permission: readOnly ? "read_only" : "workspace_write_on_confirmation",
    title,
  };
}

function cadenceFromMessage(message: string) {
  const minutes = message.match(/每\s*(\d{1,3})\s*分钟/u)?.[1];
  if (minutes) return `${minutes}m`;
  const hours = message.match(/每\s*(\d{1,2})\s*小时/u)?.[1];
  if (hours) return `${hours}h`;
  if (/每小时/u.test(message)) return "1h";
  if (/每天|每日|早上|上午/u.test(message)) return "1d";
  return "1d";
}

function unsupportedCalendarScheduleReason(message: string) {
  if (/(每周|星期|周[一二三四五六日天]|\d{1,2}\s*[：:]\s*\d{2})/u.test(message)) {
    return "当前定时检查不支持精确到星期或时刻的日历计划。请改用固定间隔，例如“每 30 分钟”“每 2 小时”或“每天”；草稿已保留，没有生成待确认操作。";
  }
  return null;
}

function monitorTargetFromMessage(message: string) {
  return structuredFieldFromMessage(message, ["检查内容", "监控内容", "目标"])
    || message.replace(/^(为当前 Goal )?(添加|配置|创建)?\s*(定时检查|监控)[：:]?/u, "").split(/\r?\n/u)[0].trim()
    || "检查当前 Goal 的阻塞、进度与新产出";
}

function stopConditionFromMessage(message: string) {
  if (/(mr|pr).{0,8}(合并|merge)/iu.test(message)) return "pr_merged";
  if (/发布完成|上线完成/u.test(message)) return "release_complete";
  return "goal_complete";
}

function mentionedAgent(message: string, agents: WorkspaceAgentOption[]) {
  const normalized = message.toLowerCase();
  return agents.find((agent) =>
    normalized.includes(agent.agentId.toLowerCase()) || normalized.includes(agent.label.toLowerCase()));
}

function todoTextFromMessage(message: string) {
  const titled = structuredFieldFromMessage(message, ["标题", "任务标题", "Todo 标题"]);
  const content = structuredFieldFromMessage(message, ["内容", "任务内容", "Todo 内容"]);
  if (titled) return [titled, content].filter(Boolean).join("：").slice(0, 400);
  const quoted = message.match(/[「“"]([^」”"]{2,200})[」”"]/u)?.[1];
  if (quoted) return quoted.trim();
  return message
    .replace(/^(请|帮我|给我|为当前 Goal |新增|新建|创建|添加|加上|加一个|记一个)+/u, "")
    .replace(/^(一个\s*)?(普通\s*)?(todo|待办|任务)(?:\s*到\s*Tasks?)?[：:\s]*/iu, "")
    .replace(/[。；;，,]\s*(?:不要|不需要|无需|禁止|别|暂不).{0,80}(?:heartbeat|心跳|定时|监控|执行).*$/iu, "")
    .replace(/[，,]\s*(并且|然后|再)?\s*(交给|分配给|让).+$/u, "")
    .replace(/\s*(交给|分配给|让)\s+.+$/u, "")
    .trim()
    .slice(0, 400) || "推进当前 Goal 的下一项工作";
}

const acceptedImageTypes = new Set(["image/png", "image/jpeg", "image/webp", "image/gif"]);
const maxImageAttachmentBytes = 5 * 1024 * 1024;
const maxImageAttachmentCount = 4;

function readImageAttachment(file: File): Promise<WorkspaceImageAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`无法读取图片 ${file.name}`));
    reader.onload = () => resolve({
      dataUrl: String(reader.result ?? ""),
      id: crypto.randomUUID(),
      mimeType: file.type,
      name: file.name,
      size: file.size,
    });
    reader.readAsDataURL(file);
  });
}

export function PersonalWorkspacePage({
  agents = [{ agentId: "codex", available: true, capability: "代码与项目执行", label: "Codex" }],
  callbacks = {},
  model,
  ownerLabel,
  selectedAgentId: controlledAgentId,
  selectedGoalId: controlledGoalId,
}: {
  agents?: WorkspaceAgentOption[];
  callbacks?: PersonalWorkspaceCallbacks;
  model: WorkspaceModel;
  ownerLabel?: string;
  selectedAgentId?: string;
  selectedGoalId?: string | null;
}) {
  const [localGoalId, setLocalGoalId] = useState<string | null>(controlledGoalId ?? null);
  const [localAgentId, setLocalAgentId] = useState(controlledAgentId ?? agents.find((agent) => agent.available)?.agentId ?? "codex");
  const [selection, setSelection] = useState<WorkspaceDrawerSelection | null>(null);
  const [activeSessionRun, setActiveSessionRun] = useState<WorkspaceRun | null>(null);
  const [proposals, setProposals] = useState<Record<string, WorkspaceActionPreview>>({});
  const [selectedGoalTab, setSelectedGoalTab] = useState<WorkspaceGoalTab>("chat");
  const [managerChatOpen, setManagerChatOpen] = useState(false);
  const [managerConversationReceiptVisible, setManagerConversationReceiptVisible] = useState(false);
  const [goalConversationReceiptVisible, setGoalConversationReceiptVisible] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>(() => {
    try {
      const raw = window.sessionStorage.getItem("loopx-pw-composer-drafts");
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? parsed as Record<string, string>
        : {};
    } catch {
      return {};
    }
  });
  const [sending, setSending] = useState(false);
  const [imageAttachments, setImageAttachments] = useState<WorkspaceImageAttachment[]>([]);
  const [imageAttachmentError, setImageAttachmentError] = useState<string | null>(null);
  const [actionFeedback, setActionFeedback] = useState<string | null>(null);
  const [refreshState, setRefreshState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [sessionProposalIds, setSessionProposalIds] = useState<string[]>([]);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [theme, setTheme] = useState<"brutal" | "paper">(() => {
    try {
      return window.localStorage.getItem("loopx-pw-theme") === "brutal" ? "brutal" : "paper";
    } catch {
      return "paper";
    }
  });
  const [goalContexts, setGoalContexts] = useState<Record<string, GoalRepositoryContext>>({});
  const [larkConnections, setLarkConnections] = useState<LarkGoalConnection[]>([]);
  const digestInitRef = useRef(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const channelScrollRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [digest, setDigest] = useState<{ attention: number; done: number; failed: number } | null>(null);
  const selectedGoalId = controlledGoalId === undefined ? localGoalId : controlledGoalId;
  const selectedAgentId = controlledAgentId ?? localAgentId;
  const composerDraftKey = `${selectedGoalId ?? "manager"}:${selectedAgentId}`;
  const composer = drafts[composerDraftKey] ?? "";
  useEffect(() => {
    setImageAttachments([]);
    setImageAttachmentError(null);
  }, [composerDraftKey]);
  function setComposerDraft(key: string, value: string) {
    setDrafts((current) => {
      const next = { ...current };
      if (value) {
        next[key] = value;
      } else {
        delete next[key];
      }
      try {
        window.sessionStorage.setItem("loopx-pw-composer-drafts", JSON.stringify(next));
      } catch {
        // Storage may be unavailable (private mode); drafts simply stay in memory.
      }
      return next;
    });
  }
  function setComposer(value: string) {
    setComposerDraft(composerDraftKey, value);
  }
  function fillQuickPrompt(text: string) {
    const existing = drafts[composerDraftKey]?.trimEnd();
    setComposer(existing ? `${existing}\n${text}` : text);
    window.requestAnimationFrame(() => composerRef.current?.focus());
  }
  useEffect(() => {
    const el = composerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [composer]);
  const workspaceGoals = useMemo(() => model.goals.map((goal) => {
    const repository = goalContexts[goal.goalId];
    return repository ? {
      ...goal,
      repository: {
        branch: repository.branch,
        identity: repository.identity,
        label: repository.label,
        readOnly: true as const,
      },
    } : goal;
  }), [goalContexts, model.goals]);
  const managerNeedsYouCount = useMemo(
    () => workspaceGoals.filter((goal) => workspaceHomeLaneForGoal(goal) === "needs_you").length,
    [workspaceGoals],
  );
  const managerBlockingCount = useMemo(
    () => workspaceGoals.filter((goal) =>
      workspaceHomeLaneForGoal(goal) === "needs_you"
      && (goal.needsYouBlocking || goal.state === "等你")
    ).length,
    [workspaceGoals],
  );
  const selectedGoal = workspaceGoals.find((goal) => goal.goalId === selectedGoalId) ?? null;
  const notificationSettingsOpen = selection?.kind === "notifications";
  const managerProjectionId = selectedGoalId;
  const items = useMemo(() => {
    const heartbeatSchedules: WorkspaceTimelineItem[] = Object.values(proposals)
      .filter((proposal) => proposal.actionKind === "heartbeat.bind" && proposal.goalId && proposal.status === "applied")
      .map((proposal) => ({
        id: `schedule:${proposal.goalId}:heartbeat`,
        kind: "schedule" as const,
        schedule: {
          agentId: selectedAgentId,
          executionHistory: [],
          goalId: proposal.goalId!,
          label: proposal.title,
          nextRunAt: proposal.status === "applied" ? "等待下次宿主唤醒" : "等待宿主确认",
          notificationRule: "仅在需要你时通知",
          schedule: proposal.fields.find((field) => field.label === "cadence")?.value ?? "由 heartbeat-prompt 生命周期驱动",
          scheduleId: `${proposal.goalId}:heartbeat`,
          scheduleKind: "heartbeat" as const,
          status: proposal.status === "applied" ? "active" as const : "draft" as const,
          stopCondition: proposal.fields.find((field) => field.label === "stop condition")?.value ?? "Goal 完成或 owner 停止",
          timezone: proposal.fields.find((field) => field.label === "timezone")?.value ?? "Asia/Shanghai",
        },
      }));
    const merged: WorkspaceTimelineItem[] = [
      ...defaultTimeline(model, managerProjectionId),
      ...(model.timeline ?? []),
      ...heartbeatSchedules,
      ...dedupeProposals(Object.values(proposals)).map((proposal) => ({ id: `proposal:${proposal.previewId}`, kind: "proposal" as const, proposal })),
    ];
    const projected = [...new Map(merged.map((item) => [item.id, item])).values()]
      .filter((item) => item.kind !== "proposal"
        || !["stale", "error"].includes(item.proposal.status)
        || sessionProposalIds.includes(item.proposal.previewId));
    return projected.filter((item) => {
      if (!selectedGoalId) return true;
      if (item.kind === "message") return true;
      if (item.kind === "proposal") return !item.proposal.goalId || item.proposal.goalId === selectedGoalId;
      if (item.kind === "attention") return item.attention.goalId === selectedGoalId;
      if (item.kind === "run") return item.run.goalId === selectedGoalId;
      if (item.kind === "schedule") return item.schedule.goalId === selectedGoalId;
      return item.output.goalId === selectedGoalId;
    });
  }, [managerProjectionId, model, proposals, selectedAgentId, selectedGoalId, sessionProposalIds]);
  const visibleTimelineItems = useMemo(() => {
    if (!activeSessionRun) return items;
    return items.filter((item) => {
      if (item.kind === "message") return true;
      if (item.kind === "run") return item.run.runId === activeSessionRun.runId;
      if (item.kind === "output") return item.output.runId === activeSessionRun.runId;
      return false;
    });
  }, [activeSessionRun, items]);
  useEffect(() => {
    if (!activeSessionRun) return;
    const latestRun = items.find((item) => item.kind === "run" && item.run.runId === activeSessionRun.runId);
    if (!latestRun || latestRun.kind !== "run") return;
    const currentSignature = JSON.stringify({
      completedSteps: activeSessionRun.completedSteps,
      latestActivity: activeSessionRun.latestActivity,
      messages: activeSessionRun.sessionMessages,
      sessionStatus: activeSessionRun.sessionStatus,
      status: activeSessionRun.status,
      totalSteps: activeSessionRun.totalSteps,
    });
    const latestSignature = JSON.stringify({
      completedSteps: latestRun.run.completedSteps,
      latestActivity: latestRun.run.latestActivity,
      messages: latestRun.run.sessionMessages,
      sessionStatus: latestRun.run.sessionStatus,
      status: latestRun.run.status,
      totalSteps: latestRun.run.totalSteps,
    });
    if (currentSignature !== latestSignature) setActiveSessionRun(latestRun.run);
  }, [activeSessionRun, items]);
  const managerMessages = useMemo(
    () => items.flatMap((item) => item.kind === "message" ? [item.message] : []),
    [items],
  );
  const goalMessages = useMemo(
    () => selectedGoal ? items.flatMap((item) => item.kind === "message" ? [item.message] : []) : [],
    [items, selectedGoal],
  );
  useEffect(() => {
    if (selectedGoal || managerChatOpen) return;
    if (managerMessages.some((message) => message.pending)) {
      setManagerConversationReceiptVisible(true);
    }
  }, [managerChatOpen, managerMessages, selectedGoal]);
  useEffect(() => {
    if (!selectedGoal || selectedGoalTab === "chat") return;
    if (goalMessages.some((message) => message.pending)) {
      setGoalConversationReceiptVisible(true);
    }
  }, [goalMessages, selectedGoal, selectedGoalTab]);
  const managerChatItems = useMemo(
    () => items.filter((item) => item.kind === "message"
      || (item.kind === "proposal" && sessionProposalIds.includes(item.proposal.previewId))),
    [items, sessionProposalIds],
  );
  const lastChatItem = managerChatItems[managerChatItems.length - 1];
  const latestMessageTextLength = lastChatItem?.kind === "message" ? lastChatItem.message.text.length : 0;
  useEffect(() => {
    if (!managerChatOpen || !channelScrollRef.current) return;
    const frame = window.requestAnimationFrame(() => {
      if (channelScrollRef.current) channelScrollRef.current.scrollTop = channelScrollRef.current.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [managerChatItems.length, managerChatOpen, latestMessageTextLength]);
  const drawerSelection = useMemo<WorkspaceDrawerSelection | null>(() => {
    if (selection?.kind === "notifications") return null;
    if (selection?.kind !== "run") return selection;
    const currentRun = items.find((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> =>
      item.kind === "run" && item.run.runId === selection.item.runId
    );
    return currentRun ? { item: currentRun.run, kind: "run" } : selection;
  }, [items, selection]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([fetchGoalContexts(), fetchLarkConnections()])
      .then(([contexts, connections]) => {
        if (cancelled) return;
        setGoalContexts(Object.fromEntries(contexts.map((row) => [row.goal_id, row.repository])));
        setLarkConnections(connections);
      })
      .catch(() => {
        // Local context is optional; the Goal workspace stays usable without it.
      });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!mobileSidebarOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileSidebarOpen]);

  // Morning digest: computed once per manager-home visit, measured against the previous visit.
  useEffect(() => {
    if (digestInitRef.current || selectedGoalId || !items.length) return;
    digestInitRef.current = true;
    let since = Number.NaN;
    try {
      since = Date.parse(window.localStorage.getItem("loopx-pw-last-visit") ?? "");
      window.localStorage.setItem("loopx-pw-last-visit", new Date().toISOString());
    } catch {
      // Storage unavailable: show current attention count only, without a time baseline.
    }
    const runs = items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> => item.kind === "run").map((item) => item.run);
    const isFresh = (time?: string) => {
      const parsed = Date.parse(time ?? "");
      return !Number.isNaN(since) && !Number.isNaN(parsed) && parsed > since;
    };
    setDigest({
      attention: managerNeedsYouCount,
      done: runs.filter((run) => run.status === "completed" && isFresh(run.latestActivity)).length,
      failed: runs.filter((run) => (run.status === "failed" || run.status === "interrupted") && isFresh(run.latestActivity)).length,
    });
  }, [items, managerNeedsYouCount, selectedGoalId]);

  useEffect(() => {
    let cancelled = false;
    void listTypedActions(selectedGoalId ? { goalId: selectedGoalId } : { contextKind: "manager" })
      .then((stored) => {
        if (cancelled) return;
        const restored = Object.fromEntries(stored
          .filter((proposal) => ["ready", "gated", "deferred", "applying"].includes(proposal.status))
          .map((proposal) => {
            const projected = workspaceProposal(proposal);
            return [projected.previewId, projected];
          }));
        setProposals((current) => ({ ...current, ...restored }));
      })
      .catch(() => {
        // The workspace remains usable when the optional local proposal store is unavailable.
      });
    return () => { cancelled = true; };
  }, [selectedGoalId]);

  async function createPreview(request: WorkspaceActionPreviewRequest) {
    let local: WorkspaceActionPreview;
    try {
      local = callbacks.onPreviewAction
        ? await callbacks.onPreviewAction(request)
        : workspaceProposal(await previewTypedAction(request));
    } catch (error) {
      if (!(error instanceof ChatApiError) || error.payload.error_code !== "action_preview_gate") throw error;
      const rawGate = error.payload.gate && typeof error.payload.gate === "object"
        ? error.payload.gate as Record<string, unknown>
        : {};
      const rawCandidates = Array.isArray(rawGate.candidates) ? rawGate.candidates : [];
      const workspaceCandidates = rawCandidates.flatMap((candidate) => {
        if (!candidate || typeof candidate !== "object") return [];
        const item = candidate as Record<string, unknown>;
        return typeof item.workspace_ref === "string" && typeof item.label === "string"
          ? [{ label: item.label, workspaceRef: item.workspace_ref }]
          : [];
      });
      const gateKind = String(rawGate.kind ?? "workspace_selection_required");
      const requiresAgentBinding = gateKind === "agent_binding_required"
        || gateKind === "agent_identity_selection_required";
      local = {
        actionKind: request.actionKind,
        fields: workspaceCandidates.map((candidate) => ({ label: candidate.label, value: candidate.workspaceRef })),
        gate: {
          kind: gateKind,
          nextAction: typeof rawGate.next_action === "string" ? rawGate.next_action : undefined,
          summary: String(rawGate.summary ?? "请选择 Goal 所属工作区。"),
        },
        impact: requiresAgentBinding
          ? "先完成 Agent 身份绑定，再重新检查原操作；当前没有写入 Goal。"
          : "选择工作区后会重新展示待确认操作，选择本身不会写入状态。",
        previewId: `workspace-choice-${Date.now().toString(36)}`,
        sourceRequest: request,
        status: "gated",
        title: requiresAgentBinding ? "先绑定 Agent" : "选择 Goal 工作区",
        workspaceCandidates,
      };
    }
    setSessionProposalIds((current) => current.includes(local.previewId) ? current : [...current, local.previewId]);
    setProposals((current) => ({ ...current, [local.previewId]: local }));
    setSelection({ item: local, kind: "proposal" });
    return local;
  }

  function requestGoalCreate() {
    selectGoal(null);
    setComposerDraft(`manager:${selectedAgentId}`, "我想创建一个长期 Goal：\n目标：\n完成标准：\n执行边界（可选）：\n关联仓库（可选）：\n通知方式（可选）：");
    window.requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function requestGoalLifecycle(goal: WorkspaceGoal, operation: "stop" | "resume") {
    await createPreview({
      actionKind: "goal.lifecycle",
      context: { kind: "goal_directory", goal_id: goal.goalId },
      idempotencyKey: `workspace-goal-${operation}-${goal.goalId}-${Date.now().toString(36)}`,
      normalizedParameters: {
        goal_id: goal.goalId,
        operation,
        reason: operation === "stop" ? "Stopped from the owner workspace" : "Resumed from the owner workspace",
      },
      summary: operation === "stop" ? `停止 Goal：${goal.title}` : `恢复 Goal：${goal.title}`,
    });
  }

  function prepareScheduleDraft(kind: "heartbeat" | "monitor", goalId: string | null) {
    if (!goalId) {
      setComposer(kind === "heartbeat"
        ? "设置 Heartbeat：\nGoal：\n频率：每天\n停止条件：Goal 完成\n通知：仅在需要我时"
        : "配置定时检查：\nGoal：\n检查内容：\n频率：每 2 小时\n停止条件：Goal 完成");
    } else {
      setComposer(kind === "heartbeat"
        ? "为当前 Goal 设置 Heartbeat：\n频率：每天\n停止条件：Goal 完成\n通知：仅在需要我时"
        : "为当前 Goal 添加定时检查：\n检查内容：\n频率（支持 30 分钟 / 2 小时 / 每天）：每 2 小时\n停止条件：Goal 完成");
    }
    setSelection(null);
    window.requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function requestSchedule(kind: "heartbeat" | "monitor", goalId: string | null, intent = "") {
    const delegated = await callbacks.onRequestScheduleConfig?.(kind, goalId);
    if (delegated) {
      setSessionProposalIds((current) => current.includes(delegated.previewId) ? current : [...current, delegated.previewId]);
      setProposals((current) => ({ ...current, [delegated.previewId]: delegated }));
      setSelection({ item: delegated, kind: "proposal" });
      return;
    }
    if (!goalId) {
      setComposer(kind === "heartbeat" ? "为哪个 Goal 设置 Heartbeat？" : "为哪个 Goal 添加定时检查？");
      return;
    }
    const timestamp = Date.now().toString(36);
    await createPreview({
      actionKind: kind === "heartbeat" ? "heartbeat.bind" : "monitor.create",
      context: { kind: "schedule", goal_id: goalId },
      idempotencyKey: `workspace-${kind}-${goalId}-${timestamp}`,
      normalizedParameters: kind === "heartbeat" ? {
        agent_id: selectedAgentId,
        cadence: cadenceFromMessage(intent),
        goal_id: goalId,
        stop_condition: stopConditionFromMessage(intent),
        timezone: "Asia/Shanghai",
      } : {
        agent_id: selectedAgentId,
        cadence: cadenceFromMessage(intent),
        goal_id: goalId,
        stop_condition: stopConditionFromMessage(intent),
        target: monitorTargetFromMessage(intent),
        target_key: `goal-${goalId}`,
        timezone: "Asia/Shanghai",
      },
      summary: kind === "heartbeat" ? "为当前 Goal 设置 Heartbeat" : `为当前 Goal 创建定时检查：${monitorTargetFromMessage(intent)}`,
    });
  }

  const drawerCallbacks: PersonalWorkspaceCallbacks = {
    ...callbacks,
    onOpenRunSession: async (run) => {
      if (run.goalId !== selectedGoalId) selectGoal(run.goalId);
      setSelectedGoalTab("chat");
      await callbacks.onOpenRunSession?.(run);
      setActiveSessionRun(run);
      setSelection(null);
    },
    onOpenGoal: async (goalId) => {
      await callbacks.onRefresh?.();
      selectGoal(goalId);
    },
    onOpenGoalView: (tab) => {
      setSelectedGoalTab(tab);
      if (tab === "chat") setActiveSessionRun(null);
      setSelection(null);
    },
    onOpenOutput: (output) => {
      if (output.goalId !== selectedGoalId) selectGoal(output.goalId);
      setSelectedGoalTab("files");
      callbacks.onOpenOutput?.(output);
    },
    onApplyProposal: async (proposal) => {
      setActionFeedback(`正在执行：${proposal.title}`);
      setProposals((current) => ({ ...current, [proposal.previewId]: { ...proposal, status: "applying" } }));
      setSelection({ item: { ...proposal, status: "applying" }, kind: "proposal" });
      try {
        if (callbacks.onApplyProposal) {
          await callbacks.onApplyProposal(proposal);
          const applied = { ...proposal, status: "applied" as const };
          setProposals((current) => ({ ...current, [proposal.previewId]: applied }));
          setSelection({ item: applied, kind: "proposal" });
          setActionFeedback(`已完成：${proposal.title}`);
          if (proposal.actionKind === "goal.lifecycle") {
            await callbacks.onRefresh?.();
            if (proposal.lifecycleOperation === "stop") selectGoal(null);
          }
          return;
        }
        const result = await applyTypedAction(proposal.previewId);
        const applied = workspaceProposal(result.proposal);
        setProposals((current) => ({ ...current, [proposal.previewId]: applied }));
        setSelection({ item: applied, kind: "proposal" });
        setActionFeedback(`已完成：${applied.title}`);
        // Keep the success receipt visible. Refresh and navigation happen when
        // the user chooses the explicit "进入 Goal" action in the drawer.
        if (applied.actionKind === "todo.create" || applied.actionKind === "goal.lifecycle") {
          await callbacks.onRefresh?.();
        }
        if (applied.actionKind === "goal.lifecycle" && applied.lifecycleOperation === "stop") {
          selectGoal(null);
        }
      } catch (error) {
        if (error instanceof ChatApiError && error.payload.error_code === "protected_action") {
          const rawGate = error.payload.gate;
          const gate = rawGate && typeof rawGate === "object" ? rawGate as Record<string, unknown> : {};
          const gated = {
            ...proposal,
            gate: {
              kind: String(gate.kind ?? "protected_action"),
              nextAction: typeof gate.next_action === "string" ? gate.next_action : undefined,
              summary: String(gate.summary ?? error.message),
            },
            status: "gated" as const,
          };
          setProposals((current) => ({ ...current, [proposal.previewId]: gated }));
          setSelection({ item: gated, kind: "proposal" });
          setActionFeedback(`需要你确认：${gated.gate.summary}`);
          if (proposal.actionKind === "goal.create" && proposal.goalId) {
            callbacks.onRefresh?.();
            selectGoal(proposal.goalId);
          }
          return;
        }
        const stale = error instanceof Error && /stale|状态.*变化|conflict/i.test(error.message);
        const failed = {
          ...proposal,
          errorMessage: error instanceof Error ? error.message : String(error),
          status: (stale ? "stale" : "error") as "stale" | "error",
        };
        setProposals((current) => ({ ...current, [proposal.previewId]: failed }));
        setSelection({ item: failed, kind: "proposal" });
        setActionFeedback(`执行失败：${failed.errorMessage}`);
      }
    },
    onCancelProposal: async (proposal) => {
      setSelection(null);
      setProposals((current) => {
        const next = { ...current };
        delete next[proposal.previewId];
        return next;
      });
      try {
        callbacks.onCancelProposal?.(proposal);
        if (!callbacks.onCancelProposal) await cancelTypedAction(proposal.previewId);
      } catch (error) {
        setProposals((current) => ({ ...current, [proposal.previewId]: proposal }));
        setActionFeedback(`取消失败：${error instanceof Error ? error.message : String(error)}`);
      }
    },
    onTransitionProposal: async (proposal, transition) => {
      const transitioned = workspaceProposal(await transitionTypedAction(proposal.previewId, transition));
      setSessionProposalIds((current) => current.includes(transitioned.previewId) ? current : [...current, transitioned.previewId]);
      setProposals((current) => {
        const next = { ...current };
        if (transition === "regenerate") delete next[proposal.previewId];
        next[transitioned.previewId] = transitioned;
        return next;
      });
      setSelection({ item: transitioned, kind: "proposal" });
    },
    onSelectWorkspaceCandidate: async (proposal, workspaceRef) => {
      if (!proposal.sourceRequest) return;
      setProposals((current) => {
        const next = { ...current };
        delete next[proposal.previewId];
        return next;
      });
      await createPreview({
        ...proposal.sourceRequest,
        idempotencyKey: `${proposal.sourceRequest.idempotencyKey}-${workspaceRef}`,
        normalizedParameters: { ...proposal.sourceRequest.normalizedParameters, workspace_ref: workspaceRef },
      });
    },
    onPreviewAction: createPreview,
    onRequestScheduleConfig: (kind, goalId) => prepareScheduleDraft(kind, goalId),
    onOpenNotificationSettings: (goalId) => setSelection({ goalId, kind: "notifications" }),
    onFetchNotificationTargets: () => fetchGoalChannelTargets(),
    onSetupGoalChannel: (options) => setupGoalChannel(options),
    onToggleGoalAutoNotify: (options) => configureGoalChannelAutoNotify(options),
    onUpdateSchedule: async (schedule, operation) => {
      const timestamp = Date.now().toString(36);
      const heartbeat = schedule.scheduleKind === "heartbeat";
      await createPreview({
        actionKind: heartbeat ? "heartbeat.bind" : "monitor.update",
        context: { kind: "schedule", goal_id: schedule.goalId },
        idempotencyKey: `workspace-monitor-${schedule.scheduleId}-${operation}-${timestamp}`,
        normalizedParameters: {
          agent_id: schedule.agentId ?? selectedAgentId,
          ...(!heartbeat && operation === "run_now" ? { endpoint_id: selectedAgentId } : {}),
          ...(operation === "edit" ? { cadence: "2h", ...(heartbeat ? { timezone: schedule.timezone ?? "Asia/Shanghai" } : {}) } : {}),
          goal_id: schedule.goalId,
          operation,
          ...(!heartbeat && operation === "run_now" && schedule.sessionId ? { session_id: schedule.sessionId } : {}),
          ...(!heartbeat ? { todo_id: schedule.scheduleId } : {}),
        },
        summary: operation === "pause" ? `暂停自动运行：${schedule.label}`
          : operation === "resume" ? `恢复自动运行：${schedule.label}`
            : operation === "run_now" ? `立即运行：${schedule.label}`
              : operation === "stop" ? `停止自动运行：${schedule.label}`
                : `编辑自动运行生命周期：${schedule.label}`,
      });
    },
  };

  function selectGoal(goalId: string | null) {
    setLocalGoalId(goalId);
    setManagerChatOpen(false);
    setManagerConversationReceiptVisible(false);
    setGoalConversationReceiptVisible(false);
    setActiveSessionRun(null);
    setSelection(null);
    setSelectedGoalTab("chat");
    setMobileSidebarOpen(false);
    callbacks.onSelectGoal?.(goalId);
  }

  function selectAgent(agentId: string) {
    setLocalAgentId(agentId);
    callbacks.onSelectAgent?.(agentId);
  }

  async function sendMessage(messageOverride?: string) {
    const pendingImages = messageOverride ? [] : imageAttachments;
    const message = (messageOverride ?? composer).trim() || (pendingImages.length ? "请结合这些图片分析当前 Goal，并告诉我下一步。" : "");
    if (!message || sending) return;
    if (!messageOverride) {
      setComposer("");
      setImageAttachments([]);
    }
    setImageAttachmentError(null);
    setSending(true);
    try {
      if (pendingImages.length) {
        if (!selectedGoalId) setManagerConversationReceiptVisible(true);
        else if (selectedGoalTab !== "chat") setGoalConversationReceiptVisible(true);
        await callbacks.onSendMessage?.(message, selectedAgentId, selectedGoalId, pendingImages);
        return;
      }
      const intentRoute = routeWorkspaceInput(message, {
        agents: agents.map((agent) => ({ agentId: agent.agentId, label: agent.label })),
        goalId: selectedGoalId,
        todos: (selectedGoal?.agentTodos ?? []).map((todo) => ({ text: todo.text, todoId: todo.todoId })),
      });
      if (intentRoute.route === "clarify") {
        setComposer(message);
        setActionFeedback("这句话包含多个可能修改状态的操作。请一次描述一项操作，我会逐项展示确认预览。");
        return;
      }
      if (intentRoute.actionKind === "goal.create") {
        const intent = structuredGoalIntentFromMessage(message);
        const goalId = compactGoalSlug(intent.title);
        await createPreview({
          actionKind: "goal.create",
          context: { kind: "manager", goal_id: null, natural_language: message },
          idempotencyKey: `workspace-goal-intent-${goalId}-${Date.now().toString(36)}`,
          normalizedParameters: {
            agent_id: selectedAgentId,
            completion_criteria: intent.completionCriteria,
            execution_boundary: intent.executionBoundary,
            goal_id: goalId,
            heartbeat: {
              cadence: cadenceFromMessage(message),
              enabled: intentRoute.normalizedParameters.heartbeat_enabled === true,
              timezone: "Asia/Shanghai",
            },
            initial_todos: intent.initialTodos,
            objective: intent.objective,
            permission: intent.permission,
            stop_condition: stopConditionFromMessage(message),
            title: intent.title,
            workspace_ref: "current",
          },
          summary: `创建 Goal：${intent.title}`,
        });
        return;
      }
      if (selectedGoalId && intentRoute.actionKind === "heartbeat.bind") {
        await requestSchedule("heartbeat", selectedGoalId, message);
        return;
      }
      if (selectedGoalId && intentRoute.actionKind === "monitor.create") {
        const scheduleError = unsupportedCalendarScheduleReason(message);
        if (scheduleError) {
          setComposer(message);
          setActionFeedback(scheduleError);
          return;
        }
        await requestSchedule("monitor", selectedGoalId, message);
        return;
      }
      const requestedAgent = mentionedAgent(message, agents);
      if (selectedGoalId && requestedAgent && intentRoute.actionKind === "agent.bind") {
        await createPreview({
          actionKind: "agent.bind",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-agent-bind-${selectedGoalId}-${requestedAgent.agentId}-${Date.now().toString(36)}`,
          normalizedParameters: { agent_id: requestedAgent.agentId, goal_id: selectedGoalId },
          summary: `将 ${requestedAgent.label} 绑定到 ${selectedGoal?.title ?? selectedGoalId}`,
        });
        return;
      }
      if (selectedGoalId && intentRoute.actionKind === "todo.create") {
        if (intentRoute.normalizedParameters.start_execution === true) {
          await createPreview({
            actionKind: "todo.create",
            context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
            idempotencyKey: `workspace-task-start-${selectedGoalId}-${Date.now().toString(36)}`,
            normalizedParameters: {
              endpoint_id: requestedAgent?.agentId ?? selectedAgentId,
              goal_id: selectedGoalId,
              start_execution: true,
              text: message,
            },
            summary: `交给 Agent 执行：${message.slice(0, 120)}`,
          });
          return;
        }
        const assignedAgentId = requestedAgent?.agentId
          ?? (/(交给|分配给|让).{0,24}(agent|codex|claude|kimi)/iu.test(message) ? selectedAgentId : null);
        await createPreview({
          actionKind: "todo.create",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-todo-create-${selectedGoalId}-${Date.now().toString(36)}`,
          normalizedParameters: {
            ...(assignedAgentId ? { endpoint_id: assignedAgentId } : {}),
            goal_id: selectedGoalId,
            text: todoTextFromMessage(message),
          },
          summary: `创建 Todo：${todoTextFromMessage(message)}`,
        });
        return;
      }
      const matchedTodo = selectedGoal?.agentTodos.find((todo) =>
        message.includes(todo.todoId) || message.includes(todo.text));
      const todoOperation = typeof intentRoute.normalizedParameters.operation === "string"
        ? intentRoute.normalizedParameters.operation
        : null;
      if (selectedGoalId && matchedTodo && intentRoute.actionKind === "todo.update" && todoOperation) {
        await createPreview({
          actionKind: "todo.update",
          context: { kind: "todo", goal_id: selectedGoalId, todo_id: matchedTodo.todoId, natural_language: message },
          idempotencyKey: `workspace-todo-update-${matchedTodo.todoId}-${todoOperation}-${Date.now().toString(36)}`,
          normalizedParameters: {
            ...(todoOperation === "reassign" && requestedAgent ? { endpoint_id: requestedAgent.agentId } : {}),
            ...(todoOperation === "block" ? { note: message } : {}),
            ...(todoOperation === "defer" ? { resume_when: "owner_resume" } : {}),
            goal_id: selectedGoalId,
            operation: todoOperation,
            todo_id: matchedTodo.todoId,
          },
          summary: `更新 Todo：${matchedTodo.text}`,
        });
        return;
      }
      if (selectedGoalId && intentRoute.actionKind === "goal.update") {
        await createPreview({
          actionKind: "goal.update",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-protected-${selectedGoalId}-${Date.now().toString(36)}`,
          normalizedParameters: { goal_id: selectedGoalId, status: "operator_gate_requested" },
          summary: `请求受保护操作：${message.slice(0, 160)}`,
        });
        return;
      }
      if (!selectedGoalId) setManagerConversationReceiptVisible(true);
      else if (selectedGoalTab !== "chat") setGoalConversationReceiptVisible(true);
      await callbacks.onSendMessage?.(message, selectedAgentId, selectedGoalId);
    } catch (error) {
      if (!messageOverride) {
        setComposer(message);
        setImageAttachments(pendingImages);
      }
      const errorMessage = error instanceof Error ? error.message : "消息发送失败，请稍后重试。";
      setActionFeedback(`发送失败：${errorMessage}`);
    } finally {
      setSending(false);
    }
  }

  const selectedAgentLabel = agents.find((agent) => agent.agentId === selectedAgentId)?.label ?? selectedAgentId;
  const goalDraftActive = !selectedGoal && composer.startsWith("我想创建一个长期 Goal：");
  const goalRunningCount = items.filter((item) =>
    item.kind === "run"
    && Boolean(item.run.sessionId)
    && Boolean(item.run.canInterrupt)
    && (item.run.status === "running" || item.run.status === "queued")
  ).length;

  async function selectImages(files: FileList | readonly File[] | null) {
    if (!files?.length) return;
    const available = maxImageAttachmentCount - imageAttachments.length;
    const selected = Array.from(files).slice(0, Math.max(0, available));
    const invalid = selected.find((file) => !acceptedImageTypes.has(file.type));
    const oversized = selected.find((file) => file.size > maxImageAttachmentBytes);
    if (available <= 0) {
      setImageAttachmentError(`最多添加 ${maxImageAttachmentCount} 张图片。`);
      return;
    }
    if (invalid) {
      setImageAttachmentError("支持 PNG、JPEG、WebP 和 GIF 图片。");
      return;
    }
    if (oversized) {
      setImageAttachmentError(`单张图片不能超过 ${maxImageAttachmentBytes / 1024 / 1024}MB。`);
      return;
    }
    try {
      const loaded = await Promise.all(selected.map(readImageAttachment));
      setImageAttachments((current) => [...current, ...loaded].slice(0, maxImageAttachmentCount));
      setImageAttachmentError(files.length > selected.length ? `最多添加 ${maxImageAttachmentCount} 张图片。` : null);
    } catch (error) {
      setImageAttachmentError(error instanceof Error ? error.message : "图片读取失败。");
    } finally {
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  }

  function handleComposerPaste(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    const images = Array.from(event.clipboardData.items)
      .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
      .flatMap((item) => {
        const file = item.getAsFile();
        return file ? [file] : [];
      });
    if (!images.length) return;
    event.preventDefault();
    void selectImages(images);
  }

  async function refreshLarkState() {
    const connections = await fetchLarkConnections();
    setLarkConnections(connections);
  }

  async function refreshWorkspace() {
    if (!callbacks.onRefresh || refreshState === "loading") return;
    setRefreshState("loading");
    try {
      await callbacks.onRefresh();
      setRefreshState("done");
    } catch {
      setRefreshState("error");
    }
    window.setTimeout(() => setRefreshState("idle"), 1800);
  }

  return (
    <WorkspaceShell
      drawer={drawerSelection ? <ContextDrawer agents={agents} callbacks={drawerCallbacks} goalNotifications={model.goalNotifications ?? []} goals={workspaceGoals} larkConnections={larkConnections} onClose={() => {
        if (drawerSelection.kind === "proposal" && ["applied", "rejected"].includes(drawerSelection.item.status)) {
          setProposals((current) => {
            const next = { ...current };
            delete next[drawerSelection.item.previewId];
            return next;
          });
        }
        setSelection(null);
      }} runs={items.flatMap((item) => item.kind === "run" ? [item.run] : [])} selection={drawerSelection} /> : null}
      drawerOpen={drawerSelection !== null}
      mobileSidebarOpen={mobileSidebarOpen}
      onCloseMobileSidebar={() => setMobileSidebarOpen(false)}
      theme={theme}
      main={notificationSettingsOpen ? (
        <LarkSettingsPage
          focusGoalConnection={Boolean(selection?.kind === "notifications" && selection.goalId)}
          goals={workspaceGoals}
          initialGoalId={selection?.kind === "notifications" ? selection.goalId ?? selectedGoalId : selectedGoalId}
          onChanged={() => void refreshLarkState()}
          onClose={() => setSelection(null)}
        />
      ) : (
        <div className="personal-channel">
          <ChannelHeader
            agents={agents}
            managerChatOpen={managerChatOpen}
            mobileNavigationOpen={mobileSidebarOpen}
            onOpenGoalDetail={selectedGoal ? () => setSelection({ item: selectedGoal, kind: "goal" }) : undefined}
            onRefresh={callbacks.onRefresh ? () => void refreshWorkspace() : undefined}
            onOpenNavigation={() => setMobileSidebarOpen(true)}
            onOpenManagerChat={() => {
              setManagerConversationReceiptVisible(false);
              setManagerChatOpen(true);
            }}
            onSelectGoalTab={(tab) => {
              setSelectedGoalTab(tab);
              if (tab === "chat") {
                setActiveSessionRun(null);
                setGoalConversationReceiptVisible(false);
              }
            }}
            onSelectAgent={selectAgent}
            onReturnManagerHome={() => {
              setManagerChatOpen(false);
              setManagerConversationReceiptVisible(false);
              window.requestAnimationFrame(() => channelScrollRef.current?.scrollTo({ behavior: "smooth", top: 0 }));
            }}
            onToggleTheme={() => setTheme((current) => {
              const next = current === "paper" ? "brutal" : "paper";
              try { window.localStorage.setItem("loopx-pw-theme", next); } catch { /* Keep the in-memory preference. */ }
              return next;
            })}
            selectedAgentId={selectedAgentId}
            refreshState={refreshState}
            selectedGoal={selectedGoal}
            selectedGoalTab={selectedGoalTab}
            theme={theme}
          />
          <div className="personal-channel-scroll" ref={channelScrollRef}>
            {!selectedGoal && !managerChatOpen && digest && (digest.done + digest.failed + digest.attention) > 0 ? (
              <section className="personal-digest-card" aria-label="你不在的时候">
                <strong>你不在的时候</strong>
                <div className="personal-digest-stats">
                  <span><b>{digest.done}</b>完成</span>
                  <span><b>{digest.failed}</b>异常</span>
                  <span><b>{digest.attention}</b>等你确认</span>
                </div>
              </section>
            ) : null}
            {!selectedGoal && !managerChatOpen ? (
              <section className="personal-manager-greeting">
                <span><Bot size={20} /></span>
                <div><strong>你好，我是 LoopX 管家</strong><p>你有 {managerNeedsYouCount} 项需要处理，其中 {managerBlockingCount} 项正在阻塞 Agent。</p></div>
              </section>
            ) : null}
            {selectedGoal && selectedGoalTab === "tasks" ? (
              <GoalTasksView
                goal={selectedGoal}
                items={items}
                onDraftTaskFromMessage={(reply) => {
                  const taskDraft = sanitizeTaskDraftFromReply(reply);
                  setComposer(`创建一个 Task：${taskDraft}`);
                  setActionFeedback("已根据回复生成 Task 草稿。编辑后发送，LoopX 会先展示确认预览。");
                  window.requestAnimationFrame(() => composerRef.current?.focus());
                }}
                onOpenChat={() => setSelectedGoalTab("chat")}
                onQuickComplete={(todo) => void createPreview({
                  actionKind: "todo.update",
                  context: { goal_id: todo.goalId, kind: "todo", todo_id: todo.todoId },
                  idempotencyKey: `workspace-todo-${todo.todoId}-complete-${Date.now().toString(36)}`,
                  normalizedParameters: { goal_id: todo.goalId, operation: "complete", todo_id: todo.todoId },
                  summary: `标记完成：${todo.text}`,
                })}
                onSelect={setSelection}
                userTodos={model.userTodos}
              />
            ) : selectedGoal && selectedGoalTab === "files" ? (
              <section className="personal-object-list"><header><strong>Files & Outputs</strong><span>{items.filter((item) => item.kind === "output").length}</span></header>{items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "output" }> => item.kind === "output").map((item) => <button key={item.id} onClick={() => setSelection({ item: item.output, kind: "output" })} type="button"><span>↗</span><strong>{item.output.title}</strong><p>{item.output.summary ?? item.output.safePreview ?? item.output.kind ?? "公开安全产出"}</p><small title={item.output.createdAt}>{[item.output.goalTitle, item.output.todoId ? `Task ${item.output.todoId}` : null, activityTimeLabel(item.output.createdAt)].filter(Boolean).join(" · ")}</small></button>)}</section>
            ) : !selectedGoal && !managerChatOpen ? (
              <ManagerHomeBoard goals={workspaceGoals} onSelectGoal={selectGoal} systemHealth={model.systemHealth} />
            ) : !selectedGoal ? (
              <ChannelTimeline items={managerChatItems} onSelect={setSelection} selectedGoal={null} />
            ) : (
              <>
                {selectedGoal && activeSessionRun?.goalId === selectedGoal.goalId ? (
                  <SessionRecordHeader
                    onClose={() => setActiveSessionRun(null)}
                    onOpenDetails={() => setSelection({ item: activeSessionRun, kind: "run" })}
                    run={activeSessionRun}
                  />
                ) : null}
                <ChannelTimeline items={visibleTimelineItems} onSelect={setSelection} selectedGoal={selectedGoal} />
              </>
            )}
          </div>
          <div className="personal-composer-wrap">
            {!selectedGoal && !managerChatOpen && managerConversationReceiptVisible && managerMessages.length ? (
              <ManagerConversationTray
                messages={managerMessages}
                onClose={() => setManagerConversationReceiptVisible(false)}
                onOpenConversation={() => {
                  setManagerConversationReceiptVisible(false);
                  setManagerChatOpen(true);
                }} />
            ) : null}
            {selectedGoal && selectedGoalTab !== "chat" && goalConversationReceiptVisible && goalMessages.length ? (
              <ManagerConversationTray
                agentLabel={selectedAgentLabel}
                messages={goalMessages}
                onClose={() => setGoalConversationReceiptVisible(false)}
                onDraftTask={selectedGoalTab === "tasks" ? (reply) => {
                  const taskDraft = sanitizeTaskDraftFromReply(reply);
                  setComposer(`创建一个 Task：${taskDraft}`);
                  setActionFeedback("已根据回复生成 Task 草稿。编辑后发送，LoopX 会先展示确认预览。");
                  window.requestAnimationFrame(() => composerRef.current?.focus());
                } : undefined}
                onOpenConversation={() => {
                  setGoalConversationReceiptVisible(false);
                  setSelectedGoalTab("chat");
                }}
                title={`${selectedGoal.title} · ${selectedAgentLabel}`}
              />
            ) : null}
            {actionFeedback ? (
              <div className="personal-action-feedback" role="status">
                <span>{actionFeedback}</span>
                <button aria-label="关闭操作回执" onClick={() => setActionFeedback(null)} type="button"><X size={14} /></button>
              </div>
            ) : null}
            <p className="personal-composer-hint">
              {selectedGoal
                ? goalRunningCount > 0
                  ? `${selectedAgentLabel} 正在执行 ${goalRunningCount} 个任务 · 你的消息作为纠偏进入本会话，不会打断执行`
                  : `你的消息由 ${selectedAgentLabel} 在本 Goal 的会话中接收`
                : "你的消息由 LoopX 管家跨 Goal 接收，支持全局询问与创建 Goal"}
            </p>
            {selectedGoal ? (
              <div className="personal-quick-prompts">
                <button aria-label="将“我现在该做什么”填入编辑框" className="is-draft" onClick={() => fillQuickPrompt("我现在该做什么？")} title="填入编辑框，确认后再发送" type="button"><MessageCircleQuestion size={13} /><span>询问下一步</span><small className="personal-prompt-subtle">草稿</small></button>
                <button className="is-immediate" disabled={sending} onClick={() => void sendMessage("请给我一份当前 Goal 的进度报告：已完成、执行中、阻塞和下一步。")} title="点击后立即向当前 Agent 发送请求" type="button"><Send size={13} /><span>向 Agent 获取进度报告</span><em className="personal-prompt-badge">立即发送</em></button>
                <button aria-label="配置定时检查" className="is-draft" onClick={() => prepareScheduleDraft("monitor", selectedGoalId)} title="先填写检查内容、频率和停止条件，不会立即创建" type="button"><CalendarClock size={13} /><span>配置定时检查</span><small className="personal-prompt-subtle">草稿</small></button>
              </div>
            ) : (
              <div className="personal-quick-prompts">
                <button aria-label="将“有哪些 Goal 正在等我”填入编辑框" className="is-draft" onClick={() => fillQuickPrompt("有哪些 Goal 正在等我？我现在该优先处理什么？")} title="填入编辑框，确认后再发送" type="button"><MessageCircleQuestion size={13} /><span>询问全局待办</span><small className="personal-prompt-subtle">草稿</small></button>
                <button className="is-immediate" disabled={sending} onClick={() => void sendMessage("请帮我汇总所有活跃 Goal 的最新进展与阻塞。")} title="点击后立即向 LoopX 管家获取全局进展" type="button"><Send size={13} /><span>汇总所有 Goal 进展</span><em className="personal-prompt-badge">立即发送</em></button>
                <button aria-label="创建新 Goal" className="is-draft" onClick={requestGoalCreate} title="填入 Goal 模板草稿，检查后再创建" type="button"><Plus size={13} /><span>创建新 Goal</span><small className="personal-prompt-subtle">草稿</small></button>
              </div>
            )}
            {goalDraftActive ? <div className="personal-goal-draft-status" role="status"><strong>Goal 草稿</strong><span>补充内容后发送，LoopX 会先展示待确认操作。</span></div> : null}
            {imageAttachments.length ? <div className="personal-composer-images" aria-label="待发送图片">{imageAttachments.map((attachment) => (
              <figure key={attachment.id}>
                <img alt={attachment.name} src={attachment.dataUrl} />
                <button aria-label={`移除图片 ${attachment.name}`} onClick={() => setImageAttachments((current) => current.filter((item) => item.id !== attachment.id))} type="button"><X size={13} /></button>
              </figure>
            ))}</div> : null}
            {imageAttachmentError ? <p className="personal-composer-error" role="alert">{imageAttachmentError}</p> : null}
            <div
              className="personal-channel-composer"
              onDragOver={(event) => {
                if ([...event.dataTransfer.items].some((item) => item.kind === "file" && item.type.startsWith("image/"))) {
                  event.preventDefault();
                }
              }}
              onDrop={(event) => {
                const images = [...event.dataTransfer.files].filter((file) => file.type.startsWith("image/"));
                if (!images.length) return;
                event.preventDefault();
                void selectImages(images);
              }}
            >
              <span><Bot size={17} />{agents.find((agent) => agent.agentId === selectedAgentId)?.label ?? selectedAgentId}</span>
              <button
                aria-label="添加图片"
                className="personal-composer-attach"
                disabled={sending || imageAttachments.length >= maxImageAttachmentCount}
                onClick={() => imageInputRef.current?.click()}
                title="选择、粘贴或拖入图片"
                type="button"
              >
                <Paperclip size={17} />
              </button>
              <input accept="image/png,image/jpeg,image/webp,image/gif" aria-label="图片文件选择器" className="personal-composer-file-input" disabled={sending || imageAttachments.length >= maxImageAttachmentCount} multiple onChange={(event) => void selectImages(event.target.files)} ref={imageInputRef} type="file" />
              <textarea
                aria-label="向 LoopX 发送消息"
                onChange={(event) => setComposer(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
                onPaste={handleComposerPaste}
                placeholder={selectedGoal ? `询问或纠偏 ${selectedGoal.title}…` : "问问 LoopX 管家，或描述一个新 Goal…"}
                ref={composerRef}
                rows={1}
                value={composer}
              />
              <button aria-label={goalDraftActive ? "检查并创建 Goal" : "发送"} disabled={(!composer.trim() && imageAttachments.length === 0) || sending} onClick={() => void sendMessage()} title={goalDraftActive ? "检查 Goal 内容并进入确认" : "发送消息"} type="button"><Send size={18} /></button>
            </div>
          </div>
        </div>
      )}
      sidebar={(
        <GoalSidebar
          attentionCount={managerNeedsYouCount}
          goals={workspaceGoals}
          onRequestGoalCreate={requestGoalCreate}
          onRequestGoalLifecycle={(goal, operation) => void requestGoalLifecycle(goal, operation)}
          onOpenNotifications={() => setSelection({ kind: "notifications" })}
          onSelectGoal={selectGoal}
          ownerLabel={ownerLabel}
          selectedGoalId={selectedGoalId}
        />
      )}
    />
  );
}
