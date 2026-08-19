import { Bell, Bot, ChevronRight, CircleUserRound, Plus } from "lucide-react";

import type { WorkspaceGoal } from "./personal-workspace-model";

const goalStateClass: Record<WorkspaceGoal["state"], string> = {
  "需修复": "is-danger",
  "等你": "is-warning",
  "等待条件": "is-info",
  "推进中": "is-success",
  "安静运行": "is-quiet",
  "已完成": "is-quiet",
};

export function GoalSidebar({
  attentionCount,
  goals,
  onRequestGoalCreate,
  onOpenNotifications,
  onSelectGoal,
  ownerLabel = "个人工作区",
  selectedGoalId,
}: {
  attentionCount: number;
  goals: WorkspaceGoal[];
  onRequestGoalCreate?: () => void;
  onOpenNotifications?: () => void;
  onSelectGoal: (goalId: string | null) => void;
  ownerLabel?: string;
  selectedGoalId: string | null;
}) {
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
          <span className="personal-sidebar-title-actions"><small>{goals.length}</small><button aria-label="创建 Goal" onClick={onRequestGoalCreate} type="button"><Plus size={15} /></button></span>
        </div>
        <div className="personal-goal-list">
          {goals.map((goal) => (
            <button
              aria-current={selectedGoalId === goal.goalId ? "page" : undefined}
              className="personal-goal-link"
              key={goal.goalId}
              onClick={() => onSelectGoal(goal.goalId)}
              type="button"
            >
              <span className={`personal-goal-state-dot ${goalStateClass[goal.state]}`} />
              <span className="personal-goal-link-copy">
                <strong>{goal.title}</strong>
                <small>{goal.state}{goal.needsYou ? " · 需要你" : ""}</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
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
