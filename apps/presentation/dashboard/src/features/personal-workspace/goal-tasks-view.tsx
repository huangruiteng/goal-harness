import { Check, ExternalLink, ListPlus, MessageSquareText, MoreHorizontal } from "lucide-react";

import type {
  WorkspaceDrawerSelection,
  WorkspaceGoal,
  WorkspaceModel,
  WorkspaceTimelineItem,
} from "./personal-workspace-model";
import { localizedAttentionAge, useWorkspaceI18n } from "./i18n";

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
  const { t } = useWorkspaceI18n();
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
    <>
      {latestUserMessage ? (
        <section aria-label={t("tasks.chatRecent")} className="personal-task-chat-receipt">
          <span className="personal-task-chat-icon"><MessageSquareText size={18} /></span>
          <div>
            <header><strong>{replyPending ? t("tasks.chatPending") : latestReply ? t("tasks.chatAgentReplied") : t("tasks.chatRecent")}</strong><small>{goal.agentLabel ?? goal.agentId}</small></header>
            <p className="is-user"><b>{t("common.you")}</b>{latestUserMessage.text}</p>
            {latestReply && !latestReply.pending ? <p className="is-assistant"><b>{t("common.agent")}</b>{latestReply.text}</p> : null}
            <small>{replyPending
              ? t("tasks.chatPendingDescription")
              : t("tasks.chatUnchangedDescription")}</small>
          </div>
          <footer>
            <button onClick={onOpenChat} type="button"><MessageSquareText size={14} />{t("tasks.chatViewReply")}</button>
            {latestReply && !replyPending && onDraftTaskFromMessage ? <button onClick={() => onDraftTaskFromMessage(latestReply.text)} type="button"><ListPlus size={14} />{t("tasks.convertToTask")}</button> : null}
          </footer>
        </section>
      ) : null}
      <div className="personal-task-kanban">
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-attention" />{t("timeline.waitingConfirmation")}</strong>
          <span>{attentionItems.length}</span>
        </header>
        {attentionItems.map((attention) => {
          const age = localizedAttentionAge(attention.updatedAt, t);
          return (
            <button key={attention.todoId} onClick={() => onSelect({ item: attention, kind: "attention" })} type="button">
              <span aria-hidden="true" className="is-attention">!</span>
              <strong>{attention.text}</strong>
              <small>
                <span className={`personal-row-status ${attention.blocking ? "is-blocking" : "is-pending"}`}>{attention.blocking ? t("tasks.blocked") : t("tasks.pending")}</span>
                {age ? <span className="personal-task-age">{t("tasks.waitingAge", { age })}</span> : null}
              </small>
            </button>
          );
        })}
        {!attentionItems.length ? <p className="personal-task-empty">{t("tasks.emptyConfirm")}</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-progress" />{t("tasks.pendingAndRunning")}</strong>
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
                  {todo.status === "blocked" ? <span className="personal-priority-badge is-blocked">{t("tasks.blocked")}</span> : null}
                  {execution ? <span className="personal-task-session-status">{execution.status === "running" || execution.status === "queued" ? t("runs.running") : execution.status === "failed" ? t("tasks.sessionError") : t("common.waiting")}</span> : null}
                  {!execution ? <span className="personal-task-session-status">{t("tasks.waiting")}</span> : null}
                  {todo.claimedBy ?? goal.agentLabel ?? goal.agentId}
                </small>
              </button>
              <div className="personal-task-card-actions">
                {execution ? <button className="personal-task-session-link" aria-label={t("tasks.openExecution", { name: todo.text })} onClick={() => onSelect({ item: execution, kind: "run" })} title={execution.status === "completed" ? t("tasks.viewResult") : t("tasks.viewExecution")} type="button"><ExternalLink size={14} /><span>{execution.status === "completed" ? t("tasks.viewResult") : t("tasks.viewExecution")}</span></button> : null}
                {onQuickComplete ? <button aria-label={t("tasks.markComplete", { name: todo.text })} onClick={() => onQuickComplete(enriched)} title={t("tasks.completed")} type="button"><Check size={14} /></button> : null}
                <button aria-label={t("tasks.moreActions", { name: todo.text })} onClick={() => onSelect({ item: enriched, kind: "todo" })} title={t("common.actions")} type="button"><MoreHorizontal size={14} /></button>
              </div>
            </div>
          );
        })}
        {!openAgentTodos.length ? <p className="personal-task-empty">{t("tasks.emptyRunning")}</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-schedule" />{t("tasks.scheduled")}</strong>
          <span>{scheduleItems.length}</span>
        </header>
        {scheduleItems.map((item) => (
          <button key={item.id} onClick={() => onSelect({ item: item.schedule, kind: "schedule" })} type="button">
            <span>◷</span><strong>{item.schedule.label}</strong><small>{item.schedule.status === "paused" ? t("schedule.paused") : t("schedule.active")}</small>
          </button>
        ))}
        {!scheduleItems.length ? <p className="personal-task-empty">{t("tasks.emptySchedules")}</p> : null}
      </section>
      <section className="personal-object-list">
        <header>
          <strong><i className="personal-kanban-dot tone-done" />{t("tasks.completed")}</strong>
          <span>{Math.max(goal.doneTodoCount ?? 0, doneAgentTodos.length)}</span>
        </header>
        {doneAgentTodos.map((todo) => (
          <button key={todo.todoId} onClick={() => onSelect({ item: { ...todo, goalId: goal.goalId, goalTitle: goal.title, ownerLabel: todo.claimedBy ?? goal.agentLabel ?? goal.agentId }, kind: "todo" })} type="button">
            <span className="is-done">✓</span><strong>{todo.text}</strong><small>{todo.claimedBy ?? goal.agentLabel ?? goal.agentId}</small>
          </button>
        ))}
        {!doneAgentTodos.length ? <p className="personal-task-empty">{(goal.doneTodoCount ?? 0) > 0
          ? t("tasks.completedSummary", { count: goal.doneTodoCount ?? 0 })
          : t("tasks.emptyCompleted")}</p> : null}
      </section>
      </div>
      {isEmpty ? (
        <p className="personal-task-empty">
          {t("tasks.emptyGoal")}
        </p>
      ) : null}
    </>
  );
}
