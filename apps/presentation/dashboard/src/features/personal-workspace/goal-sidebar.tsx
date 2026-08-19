import { Bell, Bot, ChevronDown, ChevronRight, CircleUserRound, Pause, Plus, RotateCcw } from "lucide-react";

import type { WorkspaceGoal } from "./personal-workspace-model";

const goalStateClass: Record<WorkspaceGoal["state"], string> = {
  "需修复": "is-danger",
  "等你": "is-warning",
  "等待条件": "is-info",
  "推进中": "is-success",
  "安静运行": "is-quiet",
  "已完成": "is-quiet",
  "已停止": "is-stopped",
};

export function GoalSidebar({
  attentionCount,
  goals,
  onRequestGoalCreate,
  onOpenNotifications,
  onRequestGoalLifecycle,
  onSelectGoal,
  ownerLabel = "个人工作区",
  selectedGoalId,
}: {
  attentionCount: number;
  goals: WorkspaceGoal[];
  onRequestGoalCreate?: () => void;
  onOpenNotifications?: () => void;
  onRequestGoalLifecycle?: (goal: WorkspaceGoal, operation: "stop" | "resume") => void;
  onSelectGoal: (goalId: string | null) => void;
  ownerLabel?: string;
  selectedGoalId: string | null;
}) {
  const activeGoals = goals.filter((goal) => goal.activationState !== "stopped");
  const stoppedGoals = goals.filter((goal) => goal.activationState === "stopped");
  const goalRow = (goal: WorkspaceGoal, stopped: boolean) => (
    <div className="personal-goal-row" key={goal.goalId}>
      <button
        aria-current={selectedGoalId === goal.goalId ? "page" : undefined}
        className="personal-goal-link"
        onClick={() => onSelectGoal(goal.goalId)}
        type="button"
      >
        <span className={`personal-goal-state-dot ${goalStateClass[goal.state]}`} />
        <span className="personal-goal-link-copy">
          <strong>{goal.title}</strong>
          <small>{goal.state}{goal.needsYou && !stopped ? " · 需要你" : ""}</small>
        </span>
        <ChevronRight size={15} />
      </button>
      {onRequestGoalLifecycle ? (
        <button
          aria-label={`${stopped ? "恢复" : "停止"} ${goal.title}`}
          className="personal-goal-lifecycle"
          onClick={() => onRequestGoalLifecycle(goal, stopped ? "resume" : "stop")}
          title={stopped ? "恢复 Goal" : "停止 Goal"}
          type="button"
        >
          {stopped ? <RotateCcw size={13} /> : <Pause size={13} />}
        </button>
      ) : null}
    </div>
  );
  return (
    <div className="personal-goal-directory">
      <div className="personal-sidebar-brand">
        <span className="personal-brand-mark"><Bot size={18} /></span>
        <span><strong>LoopX</strong><small>个人 Agent 工作区</small></span>
      </div>

      <nav aria-label="工作区频道" className="personal-sidebar-nav">
        <button
          aria-current={selectedGoalId === null ? "page" : undefined}
          className="personal-manager-link"
          onClick={() => onSelectGoal(null)}
          type="button"
        >
          <span className="personal-manager-icon"><Bot size={17} /></span>
          <span>LoopX 管家</span>
          {attentionCount > 0 ? <span className="personal-sidebar-count">{attentionCount}</span> : null}
          <ChevronRight size={15} />
        </button>

        <div className="personal-sidebar-section-title">
          <span>Goals</span>
          <span className="personal-sidebar-title-actions"><small>{activeGoals.length}</small><button aria-label="创建 Goal" onClick={onRequestGoalCreate} type="button"><Plus size={15} /></button></span>
        </div>
        <div className="personal-goal-list">
          {activeGoals.map((goal) => goalRow(goal, false))}
        </div>
        {stoppedGoals.length ? (
          <details className="personal-stopped-goals">
            <summary>
              <ChevronDown size={13} />
              <span>已停止</span>
              <small>{stoppedGoals.length}</small>
            </summary>
            <div className="personal-goal-list is-stopped">
              {stoppedGoals.map((goal) => goalRow(goal, true))}
            </div>
          </details>
        ) : null}
      </nav>

      <div className="personal-sidebar-footer">
        {onOpenNotifications ? (
          <button className="personal-sidebar-utility" onClick={onOpenNotifications} type="button"><Bell size={17} /><span>通知设置</span></button>
        ) : null}
        <div className="personal-owner-row"><CircleUserRound size={22} /><span>{ownerLabel}</span></div>
      </div>
    </div>
  );
}
