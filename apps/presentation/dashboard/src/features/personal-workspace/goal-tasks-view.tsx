import { Check, ExternalLink, ListPlus, MessageSquareText, MoreHorizontal } from "lucide-react";

import type {
  WorkspaceDrawerSelection,
  WorkspaceGoal,
  WorkspaceModel,
  WorkspaceTimelineItem,
} from "./personal-workspace-model";
import { attentionAgeLabel } from "./personal-workspace-model";

/**
 * Goal Tasks tab: one kanban surface that merges owner decisions ("待确认")
 * with Agent work, scheduled monitors, and completed items — mirroring the
 * board insight that confirmation is a task state, not a separate list.
 * Columns are states; cards open the same typed-preview drawer as the chat.
 */
export function GoalTasksView({
  goal,
  items,
  onDraftTaskFromMessage,
  onOpenChat,
  onQuickComplete,
  onSelect,
  userTodos,
}: {
  goal: WorkspaceGoal;
  items: WorkspaceTimelineItem[];
  onDraftTaskFromMessage?: (message: string) => void;
  onOpenChat?: () => void;
  onQuickComplete?: (todo: WorkspaceGoal["agentTodos"][number] & { goalId: string; goalTitle: string; ownerLabel: string }) => void;
  onSelect: (selection: WorkspaceDrawerSelection) => void;
  userTodos: WorkspaceModel["userTodos"];
}) {
  const attentionItems = userTodos
    .filter((todo) => todo.goalId === goal.goalId)
    .map((todo) => ({ ...todo, goalTitle: goal.title }));
  const priorityRank = (todo: WorkspaceGoal["agentTodos"][number]) =>
    todo.priority === "P0" ? 0 : todo.priority === "P1" ? 1 : todo.priority === "P2" ? 2 : 3;
  const openAgentTodos = goal.agentTodos
    .filter((todo) => todo.taskClass !== "continuous_monitor" && !todo.done)
    .sort((left, right) => priorityRank(left) - priorityRank(right));
  const doneAgentTodos = goal.agentTodos.filter((todo) => todo.taskClass !== "continuous_monitor" && todo.done);
  const scheduleItems = items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "schedule" }> => item.kind === "schedule");
  const executionRuns = items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> =>
    item.kind === "run" && Boolean(item.run.todoId));
  const isEmpty = !attentionItems.length && !openAgentTodos.length && !doneAgentTodos.length && !scheduleItems.length;
  const conversation = items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "message" }> =>
    item.kind === "message" && (item.message.role === "user" || item.message.role === "assistant"));
  const latestUserIndex = conversation.reduce((latest, item, index) => item.message.role === "user" ? index : latest, -1);
  const latestUserMessage = latestUserIndex >= 0 ? conversation[latestUserIndex]?.message : null;
  const latestReply = latestUserIndex >= 0
    ? conversation.slice(latestUserIndex + 1).reverse().find((item) => item.message.role === "assistant")?.message
    : null;
  const replyPending = latestUserIndex >= 0
    && conversation.slice(latestUserIndex + 1).some((item) => item.message.role === "assistant" && item.message.pending);

  return (
    <div className="personal-task-kanban">
      {latestUserMessage ? (
        <section aria-label="最近对话与 Task 状态" className="personal-task-chat-receipt">
          <span className="personal-task-chat-icon"><MessageSquareText size={18} /></span>
          <div>
            <header><strong>{replyPending ? "已发送给 Agent" : latestReply ? "Agent 已回复" : "最近对话"}</strong><small>{goal.agentLabel ?? goal.agentId}</small></header>
            <p className="is-user"><b>你</b>{latestUserMessage.text}</p>
            {latestReply && !latestReply.pending ? <p className="is-assistant"><b>Agent</b>{latestReply.text}</p> : null}
            <small>{replyPending
              ? "正在处理；只有经过确认的任务操作才会更新 Tasks。"
              : "本次对话没有直接修改 Tasks。需要执行时，可先转成 Task 草稿并确认。"}</small>
          </div>
          <footer>
            <button onClick={onOpenChat} type="button"><MessageSquareText size={14} />查看回复</button>
            {latestReply && !replyPending && onDraftTaskFromMessage ? <button onClick={() => onDraftTaskFromMessage(latestReply.text)} type="button"><ListPlus size={14} />转为 Task</button> : null}
          </footer>
        </section>
      ) : null}
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-attention" />待确认</strong>
          <span>{attentionItems.length}</span>
        </header>
        {attentionItems.map((attention) => {
          const age = attentionAgeLabel(attention.updatedAt);
          return (
            <button key={attention.todoId} onClick={() => onSelect({ item: attention, kind: "attention" })} type="button">
              <span aria-hidden="true" className="is-attention">!</span>
              <strong>{attention.text}</strong>
              <small>
                <span className={`personal-row-status ${attention.blocking ? "is-blocking" : "is-pending"}`}>{attention.blocking ? "阻塞" : "待处理"}</span>
                {age ? <span className="personal-task-age">已等待 {age}</span> : null}
              </small>
            </button>
          );
        })}
        {!attentionItems.length ? <p className="personal-task-empty">没有待确认的任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-progress" />待执行 / 进行中</strong>
          <span>{openAgentTodos.length}</span>
        </header>
        {openAgentTodos.map((todo) => {
          const enriched = { ...todo, goalId: goal.goalId, goalTitle: goal.title, ownerLabel: todo.claimedBy ?? goal.agentLabel ?? goal.agentId };
          const execution = executionRuns.find((item) => item.run.todoId === todo.todoId)?.run;
          return (
            <div className={`personal-task-card${execution ? " has-session" : ""}`} key={todo.todoId}>
              <button onClick={() => onSelect({ item: enriched, kind: "todo" })} type="button">
                <span>○</span><strong>{todo.text}</strong>
                <small>
                  {todo.priority ? <span className={`personal-priority-badge is-${todo.priority.toLowerCase()}`}>{todo.priority}</span> : null}
                  {todo.status === "blocked" ? <span className="personal-priority-badge is-blocked">受阻</span> : null}
                  {execution ? <span className="personal-task-session-status">{execution.status === "running" || execution.status === "queued" ? "执行中" : execution.status === "failed" ? "Session 异常" : "等待继续"}</span> : null}
                  {!execution ? <span className="personal-task-session-status">待执行</span> : null}
                  {todo.claimedBy ?? goal.agentLabel ?? goal.agentId}
                </small>
              </button>
              <div className="personal-task-card-actions">
                {execution ? <button className="personal-task-session-link" aria-label={`查看执行过程：${todo.text}`} onClick={() => onSelect({ item: execution, kind: "run" })} title={execution.status === "completed" ? "查看结果" : "查看执行过程"} type="button"><ExternalLink size={14} /><span>{execution.status === "completed" ? "查看结果" : "查看执行过程"}</span></button> : null}
                {onQuickComplete ? <button aria-label={`标记完成：${todo.text}`} onClick={() => onQuickComplete(enriched)} title="标记完成" type="button"><Check size={14} /></button> : null}
                <button aria-label={`更多操作：${todo.text}`} onClick={() => onSelect({ item: enriched, kind: "todo" })} title="更多操作" type="button"><MoreHorizontal size={14} /></button>
              </div>
            </div>
          );
        })}
        {!openAgentTodos.length ? <p className="personal-task-empty">没有待执行或进行中的任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-schedule" />定时与持续</strong>
          <span>{scheduleItems.length}</span>
        </header>
        {scheduleItems.map((item) => (
          <button key={item.id} onClick={() => onSelect({ item: item.schedule, kind: "schedule" })} type="button">
            <span>◷</span><strong>{item.schedule.label}</strong><small>{item.schedule.status === "paused" ? "已暂停" : "执行中"}</small>
          </button>
        ))}
        {!scheduleItems.length ? <p className="personal-task-empty">没有定时任务。</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-done" />已完成</strong>
          <span>{doneAgentTodos.length}</span>
        </header>
        {doneAgentTodos.map((todo) => (
          <button key={todo.todoId} onClick={() => onSelect({ item: { ...todo, goalId: goal.goalId, goalTitle: goal.title, ownerLabel: todo.claimedBy ?? goal.agentLabel ?? goal.agentId }, kind: "todo" })} type="button">
            <span className="is-done">✓</span><strong>{todo.text}</strong><small>{todo.claimedBy ?? goal.agentLabel ?? goal.agentId}</small>
          </button>
        ))}
        {!doneAgentTodos.length ? <p className="personal-task-empty">还没有完成的任务。</p> : null}
      </section>
      {isEmpty ? (
        <p className="personal-task-empty" style={{ gridColumn: "1 / -1", border: 0, textAlign: "left" }}>
          这个 Goal 还没有任务。用下面的输入框描述下一步，LoopX 会先展示待确认操作。
        </p>
      ) : null}
    </div>
  );
}
