import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Bell,
  Bot,
  CalendarClock,
  Check,
  ChevronDown,
  Copy,
  Download,
  ExternalLink,
  GitBranch,
  MessageCircleQuestion,
  MoreHorizontal,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Send,
  Square,
  X,
} from "lucide-react";

import type {
  PersonalWorkspaceCallbacks,
  WorkspaceAgentOption,
  WorkspaceAttention,
  WorkspaceDrawerSelection,
  WorkspaceGoal,
  WorkspaceGoalNotification,
  WorkspaceRun,
  WorkspaceTodo,
} from "./personal-workspace-model";
import type { LarkGoalConnection } from "../../data/chat";
import { attentionAgeLabel, formatCostUsd, formatDurationMs, formatTokenCount, hasGoalUsage, workspaceSessionStatusLabel } from "./personal-workspace-model";
import { NotificationSettingsPanel } from "./notification-settings-panel";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "select:not([disabled])",
  "input:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

type TodoOperation = "block" | "complete" | "defer" | "successor_create";

const todoTransitions = [
  { label: "标记阻塞", operation: "block" },
  { label: "暂缓", operation: "defer" },
  { label: "创建后续 Todo", operation: "successor_create" },
] as const satisfies readonly { label: string; operation: TodoOperation }[];

const decisionTransitions = [
  { label: "拒绝", resolution: "reject" },
  { label: "稍后决定", resolution: "defer" },
] as const;

export function ContextDrawer({ agents, callbacks, goalNotifications = [], goals = [], larkConnections = [], onClose, runs = [], selection }: {
  agents: WorkspaceAgentOption[];
  callbacks: PersonalWorkspaceCallbacks;
  goalNotifications?: WorkspaceGoalNotification[];
  goals?: WorkspaceGoal[];
  larkConnections?: LarkGoalConnection[];
  onClose: () => void;
  runs?: WorkspaceRun[];
  selection: WorkspaceDrawerSelection;
}) {
  const [correction, setCorrection] = useState("");
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [repositoryCopyState, setRepositoryCopyState] = useState<"idle" | "copied" | "error">("idle");
  const [runDrawerTab, setRunDrawerTab] = useState<"record" | "details">("record");
  const [todoAgentId, setTodoAgentId] = useState(agents.find((agent) => agent.available)?.agentId ?? "codex");
  const closeRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const selectionIdentity = selection.kind === "run" ? `run:${selection.item.runId}`
    : selection.kind === "proposal" ? `proposal:${selection.item.previewId}`
      : selection.kind === "todo" ? `todo:${selection.item.todoId}`
        : selection.kind === "attention" ? `attention:${selection.item.todoId}`
          : selection.kind === "output" ? `output:${selection.item.outputId}`
            : selection.kind === "schedule" ? `schedule:${selection.item.scheduleId}`
              : selection.kind === "notifications" ? `notifications:${selection.goalId ?? "workspace"}`
                : `goal:${selection.item.goalId}`;

  useEffect(() => {
    setRepositoryCopyState("idle");
    setDiagnosticsOpen(false);
    setRunDrawerTab("record");
  }, [selectionIdentity]);

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "Tab") {
        const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [])
          .filter((element) => !element.hasAttribute("disabled") && element.getAttribute("aria-hidden") !== "true");
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [onClose]);

  const title = selection.kind === "attention" ? "需要你"
    : selection.kind === "todo" ? "Todo 详情"
      : selection.kind === "run" ? "执行 Session"
        : selection.kind === "output" ? "产出详情"
          : selection.kind === "proposal" ? (selection.item.status === "applied" ? "执行结果" : "确认执行")
            : selection.kind === "schedule" ? (selection.item.scheduleKind === "heartbeat" ? "Heartbeat" : "定时检查")
              : selection.kind === "notifications" ? "通知设置"
                  : "Goal 详情";
  const goalId = selection.kind === "proposal" ? selection.item.goalId ?? "manager"
    : selection.kind === "notifications" ? "workspace"
      : selection.item.goalId;
  const contextLabel = selection.kind === "attention" ? selection.item.goalTitle ?? "当前 Goal"
    : selection.kind === "todo" ? selection.item.goalTitle
      : selection.kind === "run" ? selection.item.goalTitle
        : selection.kind === "output" ? selection.item.goalTitle ?? "当前 Goal"
          : selection.kind === "goal" ? selection.item.title
            : selection.kind === "schedule" ? "当前 Goal 的自动运行"
              : selection.kind === "notifications" ? "飞书群通知绑定"
                  : selection.item.goalId ? "当前 Goal 的待确认变更" : "管家待确认变更";
  const selectedGoalRun = selection.kind === "goal"
    ? runs.find((run) => run.goalId === selection.item.goalId && Boolean(run.sessionId))
      ?? runs.find((run) => run.goalId === selection.item.goalId)
    : null;
  const hasProjectedRunActivity = selection.kind === "run" && (
    selection.item.completedSteps > 0
    || Boolean(selection.item.latestActivity)
    || Boolean(selection.item.outputs?.length)
  );

  async function sendCorrection() {
    if (selection.kind !== "run" || !correction.trim()) return;
    await callbacks.onCorrectRun?.(selection.item, correction.trim());
    setCorrection("");
  }

  async function previewTodoTransition(todo: WorkspaceTodo, operation: TodoOperation, label: string) {
    if (operation === "successor_create") {
      await callbacks.onPreviewAction?.({
        actionKind: "todo.create",
        context: { goal_id: todo.goalId, kind: "todo", todo_id: todo.todoId },
        idempotencyKey: `workspace-todo-successor-${todo.todoId}-${Date.now().toString(36)}`,
        normalizedParameters: { goal_id: todo.goalId, text: `${todo.text} 的后续工作` },
        summary: `创建后续 Todo：${todo.text}`,
      });
      return;
    }
    await callbacks.onPreviewAction?.({
      actionKind: "todo.update",
      context: { goal_id: todo.goalId, kind: "todo", todo_id: todo.todoId },
      idempotencyKey: `workspace-todo-${todo.todoId}-${operation}-${Date.now().toString(36)}`,
      normalizedParameters: {
        goal_id: todo.goalId,
        operation,
        ...(operation === "block" ? { note: "Owner 标记为阻塞，等待补充上下文。" } : {}),
        ...(operation === "defer" ? { resume_when: "owner_resume" } : {}),
        todo_id: todo.todoId,
      },
      summary: `${label}：${todo.text}`,
    });
  }

  async function previewDecision(attention: WorkspaceAttention, decision: "approve" | typeof decisionTransitions[number]["resolution"], label: string) {
    await callbacks.onPreviewAction?.({
      actionKind: "gate.resolve",
      context: { goal_id: attention.goalId, kind: "todo", todo_id: attention.todoId },
      idempotencyKey: `workspace-decision-${attention.todoId}-${decision}-${Date.now().toString(36)}`,
      normalizedParameters: {
        goal_id: attention.goalId,
        decision,
        todo_id: attention.todoId,
      },
      summary: `${label}：${attention.text}`,
    });
  }

  return (
    <div
      aria-labelledby="personal-drawer-title"
      aria-modal="true"
      className="personal-context-drawer"
      data-context-kind={selection.kind}
      ref={drawerRef}
      role="dialog"
    >
      <header className="personal-drawer-header">
        <div><h2 id="personal-drawer-title">{title}</h2><p>{contextLabel}</p></div>
        <button aria-label={`关闭详情：返回${contextLabel}`} className="personal-icon-button personal-drawer-close" onClick={onClose} ref={closeRef} type="button">
          <ArrowLeft className="personal-mobile-back" size={18} />
          <X className="personal-desktop-close" size={18} />
        </button>
      </header>

      <div className="personal-drawer-body">
        {selection.kind === "attention" ? (
          <>
            <section className="personal-detail-card is-attention">
              <small>{selection.item.blocking ? "正在阻塞 Agent" : "等待你的决定"}</small>
              <h3>{selection.item.text}</h3>
              <dl>
                <div><dt>Goal</dt><dd>{selection.item.goalTitle ?? selection.item.goalId}</dd></div>
                <div><dt>优先级</dt><dd>{selection.item.priority ?? "medium"}</dd></div>
                {attentionAgeLabel(selection.item.updatedAt) ? <div><dt>等待</dt><dd>已等待 {attentionAgeLabel(selection.item.updatedAt)}</dd></div> : null}
                <div><dt>原因</dt><dd>{selection.item.explanation ?? "该决定会影响当前 Todo 的下一步执行。"}</dd></div>
                <div><dt>证据</dt><dd>{selection.item.evidence ?? "当前状态没有附加公开安全证据；下一步仍会先展示 Preview。"}</dd></div>
              </dl>
            </section>
            <button className="personal-primary-action" onClick={() => void previewDecision(selection.item, "approve", "确认处理")} type="button"><Check size={17} />查看影响并决定</button>
            <details className="personal-compact-menu">
              <summary><MoreHorizontal size={17} />更多决定</summary>
              <div>
                <button onClick={() => void callbacks.onExplainDecision?.(selection.item)} type="button"><MessageCircleQuestion size={16} />解释此决定</button>
                {decisionTransitions.map((transition) => (
                  <button key={transition.resolution} onClick={() => void previewDecision(selection.item, transition.resolution, transition.label)} type="button">{transition.label}</button>
                ))}
              </div>
            </details>
          </>
        ) : null}

        {selection.kind === "todo" ? (
          <>
            <section className="personal-detail-card">
              <small>{selection.item.taskClass ?? "bounded_task"}</small>
              <h3>{selection.item.text}</h3>
              <dl>
                <div><dt>Goal</dt><dd>{selection.item.goalTitle}</dd></div>
                <div><dt>Owner</dt><dd>{selection.item.ownerLabel ?? selection.item.claimedBy ?? "未分配"}</dd></div>
                <div><dt>任务类型</dt><dd>{selection.item.taskClass ?? "普通 Todo"}</dd></div>
                <div><dt>状态</dt><dd>{selection.item.status ?? (selection.item.done ? "completed" : "open")}</dd></div>
                <div><dt>依赖</dt><dd>{selection.item.dependencies?.join(" · ") || "无"}</dd></div>
                <div><dt>下一转换</dt><dd>{selection.item.nextTransition ?? (selection.item.done ? "可创建后续 Todo" : "推进或更新状态")}</dd></div>
              </dl>
            </section>
            <div className="personal-todo-actions" aria-label="Todo 待确认操作">
              <strong className="personal-todo-actions-title">操作</strong>
              {selection.item.done ? null : (
                <button className="personal-primary-action" onClick={() => void previewTodoTransition(selection.item, "complete", "标记完成")} type="button"><Check size={17} />标记完成</button>
              )}
              <label className="personal-inline-agent-select">改派给
                <select aria-label="选择 Todo 新负责人" onChange={(event) => setTodoAgentId(event.target.value)} value={todoAgentId}>
                  {agents.filter((agent) => agent.available).map((agent) => <option key={agent.agentId} value={agent.agentId}>{agent.label}</option>)}
                </select>
                <button className="personal-secondary-action" onClick={() => void callbacks.onPreviewAction?.({
                  actionKind: "todo.update",
                  context: { goal_id: selection.item.goalId, kind: "todo", todo_id: selection.item.todoId },
                  idempotencyKey: `workspace-todo-${selection.item.todoId}-reassign-${todoAgentId}-${Date.now().toString(36)}`,
                  normalizedParameters: { agent_id: todoAgentId, goal_id: selection.item.goalId, operation: "reassign", todo_id: selection.item.todoId },
                  summary: `重新分配：${selection.item.text}`,
                })} type="button">检查变更</button>
              </label>
              <details className="personal-compact-menu">
                <summary><MoreHorizontal size={17} />更多操作</summary>
                <div>
                  {todoTransitions.map((transition) => (
                    <button key={transition.operation} onClick={() => void previewTodoTransition(selection.item, transition.operation, transition.label)} type="button">{transition.label}</button>
                  ))}
                </div>
              </details>
            </div>
          </>
        ) : null}

        {selection.kind === "goal" ? (
          <>
            <section className="personal-detail-card">
              <small>{selection.item.state}</small>
              <h3>{selection.item.title}</h3>
              <p>{selection.item.agentSentence}</p>
              {hasGoalUsage(selection.item.usage) ? (
                <dl>
                  <div><dt>Tokens 24h / 7d</dt><dd>{formatTokenCount(selection.item.usage.tokens24h)} / {formatTokenCount(selection.item.usage.tokens7d)}</dd></div>
                  <div><dt>成本 24h / 7d</dt><dd>{formatCostUsd(selection.item.usage.costUsd24h)} / {formatCostUsd(selection.item.usage.costUsd7d)}</dd></div>
                  <div><dt>运行时长 24h / 7d</dt><dd>{formatDurationMs(selection.item.usage.durationMs24h)} / {formatDurationMs(selection.item.usage.durationMs7d)}</dd></div>
                </dl>
              ) : null}
            </section>
            {(() => {
              const notification = goalNotifications.find((row) => row.goalId === selection.item.goalId);
              const connection = larkConnections.find((row) => row.goal_id === selection.item.goalId);
              return (
                <>
                  {selection.item.repository ? (
                    <section className="personal-detail-card personal-goal-repository">
                      <div className="personal-detail-card-title"><small>Repository</small><em>Read only</em></div>
                      <h3><GitBranch size={16} />{selection.item.repository.label}</h3>
                      <dl>
                        <div><dt>Branch</dt><dd>{selection.item.repository.branch || "detached"}</dd></div>
                        <div><dt>Role</dt><dd>Execution workspace</dd></div>
                      </dl>
                      <button className="personal-secondary-action" onClick={() => {
                        const write = navigator.clipboard?.writeText(selection.item.repository?.identity ?? "");
                        if (!write) {
                          setRepositoryCopyState("error");
                          return;
                        }
                        void write.then(() => setRepositoryCopyState("copied")).catch(() => setRepositoryCopyState("error"));
                      }} type="button"><Copy size={15} />{repositoryCopyState === "copied" ? "已复制仓库标识" : "复制仓库标识"}</button>
                      {repositoryCopyState === "error" ? <p className="personal-copy-feedback is-error" role="status">复制失败，请检查浏览器剪贴板权限。</p> : repositoryCopyState === "copied" ? <p className="personal-copy-feedback" role="status">已复制，可粘贴到其他工具。</p> : null}
                    </section>
                  ) : null}
                  <section className="personal-detail-card personal-goal-notification">
                  <small>Lark connection</small>
                  {connection ? (
                    <>
                      <h3>{connection.app_label}<span className="personal-connection-status">Connected</span></h3>
                      <dl>
                        <div><dt>Group</dt><dd>{connection.chat_name}</dd></div>
                        <div><dt>Topic</dt><dd># {connection.topic_name}</dd></div>
                        <div><dt>Trigger</dt><dd>{connection.incoming_mode === "mentions" ? "Someone mentions the Agent" : "All messages"}</dd></div>
                        <div><dt>Reply mode</dt><dd>Topic reply</dd></div>
                        <div><dt>Human-gate 自动通知</dt><dd>{notification?.humanGateAutoNotifyEnabled ? "开" : "关"}</dd></div>
                        {notification?.lastNotifiedAt ? (
                          <div><dt>最近通知</dt><dd>{notification.lastNotifiedAt}</dd></div>
                        ) : null}
                      </dl>
                    </>
                  ) : (
                    <>
                      <h3>未配置</h3>
                      <p>配置后，当这个 Goal 出现需要你确认的变更时，会自动发飞书通知。</p>
                    </>
                  )}
                  <button className="personal-secondary-action" onClick={() => callbacks.onOpenNotificationSettings?.(selection.item.goalId)} type="button"><Bell size={16} />{connection ? "管理 Lark connection" : "Connect Lark App"}</button>
                  </section>
                </>
              );
            })()}
            <section className="personal-detail-card personal-goal-session">
              <small>Execution Session</small>
              {selectedGoalRun?.sessionId ? (
                <>
                  <h3>{workspaceSessionStatusLabel(selectedGoalRun.sessionStatus ?? selectedGoalRun.status)}</h3>
                  <p>{selectedGoalRun.title}</p>
                  <button className="personal-primary-action" onClick={() => void callbacks.onOpenRunSession?.(selectedGoalRun)} type="button"><Play size={16} />查看最近执行过程</button>
                </>
              ) : (
                <>
                  <h3>尚未启动执行 Session</h3>
                  <p>Agent 开始执行后，运行记录会稳定显示在这里。</p>
                </>
              )}
            </section>
            <div className="personal-drawer-action-grid">
              <button className="personal-secondary-action" onClick={() => callbacks.onRequestScheduleConfig?.("heartbeat", selection.item.goalId)} type="button"><Radio size={16} />设置 Heartbeat</button>
              <button className="personal-secondary-action" onClick={() => callbacks.onRequestScheduleConfig?.("monitor", selection.item.goalId)} type="button"><CalendarClock size={16} />添加定时检查</button>
            </div>
          </>
        ) : null}

        {selection.kind === "run" ? (
          <>
            <div aria-label="Session 视图" className="personal-run-drawer-tabs" role="tablist">
              <button aria-selected={runDrawerTab === "record"} onClick={() => setRunDrawerTab("record")} role="tab" type="button">执行过程与结果</button>
              <button aria-selected={runDrawerTab === "details"} onClick={() => setRunDrawerTab("details")} role="tab" type="button">详情与操作</button>
            </div>
            {runDrawerTab === "record" ? (
              <>
                <section className="personal-detail-card personal-session-summary">
                  <small>{selection.item.agentLabel} · {workspaceSessionStatusLabel(selection.item.sessionStatus ?? selection.item.status)}</small>
                  <h3>{selection.item.title}</h3>
                  <p>{selection.item.latestActivity}</p>
                  <dl>
                    <div><dt>Goal</dt><dd>{selection.item.goalTitle}</dd></div>
                    <div><dt>进度</dt><dd>{selection.item.completedSteps}/{selection.item.totalSteps}</dd></div>
                  </dl>
                </section>
                <section aria-label="执行记录" className="personal-session-message-record">
                  <h3>运行记录</h3>
                  {selection.item.sessionMessages?.length ? (
                    <ol>{selection.item.sessionMessages.map((message) => (
                      <li className={`is-${message.role}`} key={message.messageId}>
                        <i />
                        <div>
                          <header><strong>{message.role === "user" ? "收到任务" : message.role === "assistant" ? "已完成" : "需检查"}</strong>{message.createdAt ? <time>{new Date(message.createdAt).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })}</time> : null}</header>
                          <p>{message.text}</p>
                        </div>
                      </li>
                    ))}</ol>
                  ) : (
                    <p className="personal-session-empty">{hasProjectedRunActivity
                      ? `当前没有可展示的逐步运行记录。LoopX 已读取到 ${selection.item.completedSteps}/${selection.item.totalSteps} 的投影进度${selection.item.outputs?.length ? `和 ${selection.item.outputs.length} 项产出` : ""}；请在“详情与操作”检查 Session 状态。`
                      : "还没有运行记录。Agent 尚未开始这次执行；请在“详情与操作”查看等待条件或恢复 Session。"}</p>
                  )}
                  {selection.item.status === "running" ? <div className="personal-session-active-step"><i /><span><strong>正在分析</strong><small>Agent 正在继续执行，记录会自动更新。</small></span></div> : null}
                </section>
                {selection.item.outputs?.length ? (
                  <section className="personal-execution-history" aria-labelledby="personal-run-outputs-title">
                    <h3 id="personal-run-outputs-title">本次运行产出</h3>
                    <ol>{selection.item.outputs.map((output) => <li key={output.outputId}><span><strong>{output.title}</strong><small>{output.createdAt ?? output.kind ?? "公开安全产出"}</small></span></li>)}</ol>
                  </section>
                ) : null}
              </>
            ) : (
              <>
                <section className="personal-detail-card">
                  <small>{selection.item.agentLabel} · {workspaceSessionStatusLabel(selection.item.status)}</small>
                  <h3>{selection.item.title}</h3>
                  <p>{selection.item.latestActivity}</p>
                  <dl>
                    <div><dt>Goal</dt><dd>{selection.item.goalTitle}</dd></div>
                    <div><dt>进度</dt><dd>{selection.item.completedSteps}/{selection.item.totalSteps}</dd></div>
                    <div><dt>会话状态</dt><dd>{workspaceSessionStatusLabel(selection.item.sessionStatus ?? selection.item.status)}</dd></div>
                    <div><dt>可恢复</dt><dd>{selection.item.resumable === false ? "否" : "是"}</dd></div>
                  </dl>
                </section>
                {selection.item.sessionStatus === "resume_failed" ? (
                  <section className="personal-recovery-panel" aria-label="Session 恢复失败">
                    <strong>上游 Session 恢复失败</strong>
                    <p>本地历史已经保留，请选择恢复路径。</p>
                    <button className="personal-primary-action" onClick={() => void callbacks.onRetryResumeRun?.(selection.item)} type="button"><RotateCcw size={16} />重试恢复</button>
                    <button className="personal-secondary-action" onClick={() => void callbacks.onStartNewRunSession?.(selection.item)} type="button"><Play size={16} />携带上下文开始新 Session</button>
                  </section>
                ) : null}
                <section className="personal-correction-panel">
                  <header><span><Bot size={16} />与 {selection.item.agentLabel} 纠偏</span></header>
                  <p>消息会沿用当前 Goal、Todo 与 Agent Session 上下文。</p>
                  <div className="personal-correction-composer">
                    <textarea
                      aria-label={`输入纠偏信息：Goal ${selection.item.goalTitle}，Agent ${selection.item.agentLabel}，Run ${selection.item.title}`}
                      onChange={(event) => setCorrection(event.target.value)}
                      placeholder="例如：先关注权限风险，暂时不要提交…"
                      rows={3}
                      value={correction}
                    />
                    <button aria-label="发送纠偏" disabled={!correction.trim()} onClick={() => void sendCorrection()} type="button"><Send size={16} /></button>
                  </div>
                </section>
                <details className="personal-compact-menu personal-run-more">
                  <summary><MoreHorizontal size={17} />更多运行操作</summary>
                  <div>
                    <button disabled={!selection.item.canInterrupt} onClick={() => void callbacks.onInterruptRun?.(selection.item)} type="button"><Pause size={16} />中断本次运行</button>
                    <button disabled={selection.item.resumable === false} onClick={() => void callbacks.onRetryResumeRun?.(selection.item)} type="button"><RotateCcw size={16} />重试恢复</button>
                    <button onClick={() => void callbacks.onStartNewRunSession?.(selection.item)} type="button"><Play size={16} />开始新 Session</button>
                    <button onClick={() => void callbacks.onCloseRunSession?.(selection.item)} type="button"><Square size={16} />关闭 Session</button>
                  </div>
                </details>
              </>
            )}
          </>
        ) : null}

        {selection.kind === "output" ? (
          <>
            <section className="personal-detail-card">
              <small>{selection.item.kind ?? "output"}</small>
              <h3>{selection.item.title}</h3>
              <p>{selection.item.summary ?? "该产出已记录到当前 Goal。"}</p>
              <dl>
                <div><dt>Goal</dt><dd>{selection.item.goalTitle ?? selection.item.goalId}</dd></div>
                <div><dt>Todo</dt><dd>{selection.item.todoId ?? "未关联"}</dd></div>
                <div><dt>Run</dt><dd>{selection.item.runId ?? "未关联"}</dd></div>
                <div><dt>Agent</dt><dd>{selection.item.agentLabel ?? selection.item.agentId ?? "LoopX"}</dd></div>
              </dl>
            </section>
            {selection.item.safePreview ? <pre aria-label="公开安全产出预览" className="personal-safe-preview">{selection.item.safePreview}</pre> : <p className="personal-preview-unavailable">此产出没有可用的公开安全内联预览。</p>}
            <div className="personal-drawer-action-grid">
              <button className="personal-primary-action" onClick={() => { callbacks.onOpenOutput?.(selection.item); onClose(); }} type="button"><ExternalLink size={16} />打开</button>
              <button className="personal-secondary-action" disabled={!callbacks.onExportOutput} onClick={() => void callbacks.onExportOutput?.(selection.item)} type="button"><Download size={16} />导出</button>
            </div>
          </>
        ) : null}

        {selection.kind === "proposal" ? (
          <>
            <section className="personal-proposal-card">
              <small>{selection.item.actionKind} · {selection.item.status}</small>
              <h3>{selection.item.title}</h3>
              <p>{selection.item.impact}</p>
              {selection.item.status === "ready" ? <p className="personal-proposal-explainer">确认后，LoopX 会执行这项变更并显示写入结果。关闭或取消不会修改任何状态。</p> : null}
              <dl>{selection.item.fields.map((field) => <div key={field.label}><dt>{field.label}</dt><dd>{field.value}</dd></div>)}</dl>
            </section>
            {selection.item.status === "applied" ? <p className="personal-proposal-state is-applied"><Check size={16} />已应用，LoopX 状态将刷新。</p> : null}
            {selection.item.status === "applied" && selection.item.goalId ? <button className="personal-primary-action" onClick={() => void (async () => { await callbacks.onOpenGoal?.(selection.item.goalId!); onClose(); })()} type="button"><ExternalLink size={16} />{selection.item.actionKind === "goal.create" ? "进入新 Goal" : "查看更新后的 Goal"}</button> : null}
            {selection.item.status === "stale" ? <p className="personal-proposal-state is-stale">来源状态已变化，请按最新状态重新检查。</p> : null}
            {selection.item.status === "error" ? <div className="personal-proposal-state is-error"><span>应用失败，没有写入任何变更。</span>{selection.item.errorMessage ? <small>{selection.item.errorMessage}</small> : null}<small>请刷新 Goal 状态后重新生成；若仍失败，可保留此页并查看高级诊断。</small></div> : null}
            {selection.item.status === "rejected" ? <p className="personal-proposal-state is-error">已拒绝，这项变更不会写入。</p> : null}
            {selection.item.status === "deferred" ? <p className="personal-proposal-state is-gated">已暂缓，可稍后继续应用或重新生成。</p> : null}
            {selection.item.status === "gated" ? <div className="personal-proposal-state is-gated"><span><strong>需要宿主确认</strong>页面无权直接批准这类权限变更，你的点击没有写入任何内容。</span>{selection.item.gate?.nextAction ? <small>{selection.item.gate.nextAction}</small> : null}</div> : null}
            {selection.item.status === "gated" && selection.item.actionKind === "gate.resolve" ? (() => {
              const fieldValue = (label: string) => selection.item.fields.find((field) => field.label === label)?.value;
              const gateGoalId = fieldValue("goal id");
              const gateTodoId = fieldValue("todo id");
              if (!gateGoalId || !gateTodoId) return null;
              return (
                <section className="personal-detail-card personal-gate-cli-hint">
                  <small>在终端执行一条命令即可完成审批：</small>
                  <code>loopx todo complete --goal-id {gateGoalId} --todo-id {gateTodoId} --decision-outcome approve</code>
                  <small>不同意就把末尾的 approve 换成 reject。执行后这条提醒会自动消失。</small>
                </section>
              );
            })() : null}
            {selection.item.workspaceCandidates?.length ? <div className="personal-workspace-candidates" aria-label="可选择的工作区">{selection.item.workspaceCandidates.map((candidate) => <button key={candidate.workspaceRef} onClick={() => void callbacks.onSelectWorkspaceCandidate?.(selection.item, candidate.workspaceRef)} type="button"><strong>{candidate.label}</strong><small>{candidate.workspaceRef}</small></button>)}</div> : null}
            {selection.item.status === "error" ? <button className="personal-primary-action" onClick={() => void callbacks.onTransitionProposal?.(selection.item, "regenerate")} type="button"><RotateCcw size={17} />基于最新状态重试</button> : selection.item.status !== "gated" ? <button className="personal-primary-action" disabled={!['ready', 'deferred'].includes(selection.item.status)} onClick={() => void callbacks.onApplyProposal?.(selection.item)} type="button"><Check size={17} />{selection.item.status === "applying" ? "正在应用…" : selection.item.primaryLabel ?? "确认并应用"}</button> : null}
            {["stale", "gated", "rejected"].includes(selection.item.status) ? <button className="personal-secondary-action" onClick={() => void callbacks.onTransitionProposal?.(selection.item, "regenerate")} type="button"><RotateCcw size={16} />按最新状态重新检查</button> : null}
            {["ready", "gated"].includes(selection.item.status) ? <div className="personal-drawer-action-grid"><button className="personal-secondary-action" onClick={() => void callbacks.onTransitionProposal?.(selection.item, "defer")} type="button">稍后</button><button className="personal-secondary-action" onClick={() => void callbacks.onTransitionProposal?.(selection.item, "reject")} type="button">拒绝</button></div> : null}
            {!["applied", "applying"].includes(selection.item.status) ? <button className="personal-secondary-action" onClick={onClose} type="button">关闭</button> : null}
          </>
        ) : null}

        {selection.kind === "schedule" ? (
          <>
            <section className="personal-detail-card">
              <small>{selection.item.scheduleKind === "heartbeat" ? "Goal Heartbeat" : "continuous_monitor"} · {selection.item.status ?? "active"}</small>
              <h3>{selection.item.label}</h3>
              <p>{selection.item.target ?? selection.item.schedule ?? "由 LoopX 调度器按 Goal 配置唤醒。"}</p>
              <dl>
                <div><dt>时区</dt><dd>{selection.item.timezone ?? "本地时区"}</dd></div>
                <div><dt>下次执行</dt><dd>{selection.item.nextRunAt ?? "等待调度"}</dd></div>
                <div><dt>上次执行</dt><dd>{selection.item.previousRunAt ?? "尚未执行"}</dd></div>
                <div><dt>通知</dt><dd>{selection.item.notificationRule ?? "仅在需要你时通知"}</dd></div>
                <div><dt>停止条件</dt><dd>{selection.item.stopCondition ?? "Goal 完成或 owner 停止"}</dd></div>
              </dl>
            </section>
            {selection.item.scheduleKind === "monitor" ? <button className="personal-primary-action" onClick={() => void callbacks.onUpdateSchedule?.(selection.item, "run_now")} type="button"><Play size={16} />立即运行</button> : null}
            <div className="personal-drawer-action-grid">
              <button className="personal-secondary-action" onClick={() => void callbacks.onUpdateSchedule?.(selection.item, selection.item.status === "paused" ? "resume" : "pause")} type="button">{selection.item.status === "paused" ? <Play size={16} /> : <Pause size={16} />}{selection.item.status === "paused" ? "恢复" : "暂停"}</button>
              <button className="personal-secondary-action" onClick={() => void callbacks.onUpdateSchedule?.(selection.item, "edit")} type="button"><CalendarClock size={16} />改为每 2 小时</button>
            </div>
            <button className="personal-danger-action" onClick={() => void callbacks.onUpdateSchedule?.(selection.item, "stop")} type="button"><Square size={16} />停止{selection.item.scheduleKind === "heartbeat" ? " Heartbeat" : "定时检查"}</button>
            <section className="personal-execution-history" aria-labelledby="personal-execution-history-title">
              <h3 id="personal-execution-history-title">执行历史</h3>
              {selection.item.executionHistory?.length ? (
                <ol>{selection.item.executionHistory.map((entry, index) => <li key={`${entry.timestamp}:${entry.runId ?? index}`}><span><strong>{entry.label}</strong><small>{entry.timestamp}</small></span><em className={`is-${entry.status}`}>{entry.status}</em></li>)}</ol>
              ) : <p>暂无执行记录。</p>}
            </section>
          </>
        ) : null}

        {selection.kind === "notifications" ? (
          <NotificationSettingsPanel
            callbacks={callbacks}
            goalNotifications={goalNotifications}
            goals={goals}
            onChanged={() => callbacks.onRefresh?.()}
          />
        ) : null}

        {selection.kind === "run" || selection.kind === "proposal" || selection.kind === "schedule" ? (
          <>
            <button aria-expanded={diagnosticsOpen} className="personal-diagnostics-trigger" onClick={() => setDiagnosticsOpen((value) => !value)} type="button">
              <span>高级诊断</span><ChevronDown className={diagnosticsOpen ? "is-open" : ""} size={16} />
            </button>
            {diagnosticsOpen ? (
              <div className="personal-diagnostics">
                <code>goal_id: {goalId}</code><code>kind: {selection.kind}</code>
                {selection.kind === "run" ? <><code>session_id: {selection.item.sessionId ?? "未绑定"}</code><code>turn_id: {selection.item.turnId ?? "空闲"}</code><code>adapter: {selection.item.agentId}</code><code>status: {selection.item.sessionStatus ?? selection.item.status}</code></> : selection.kind === "proposal" ? <><code>action: {selection.item.actionKind}</code><code>status: {selection.item.status}</code></> : <><code>schedule_id: {selection.item.scheduleId}</code><code>status: {selection.item.status ?? "active"}</code></>}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
