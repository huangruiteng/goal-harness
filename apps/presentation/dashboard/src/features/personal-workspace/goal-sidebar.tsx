import { Bot, ChevronDown, ChevronRight, LoaderCircle, Pause, Plus, RotateCcw, Settings2, Trash2 } from "lucide-react";

import { localizedGoalState, useWorkspaceI18n } from "./i18n";
import type { WorkspaceGoal, WorkspaceGoalArchiveLoadState } from "./personal-workspace-model";
import { StatusSourceSwitcher, type StatusSourceControl } from "./status-source-switcher";

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
  goalArchiveLoadState = { error: null, phase: "ready" },
  lifecycleBusyGoalIds,
  onRequestGoalCreate,
  onOpenSettings,
  onRetryGoalArchive,
  onRequestGoalLifecycle,
  onSelectGoal,
  selectedGoalId,
  statusSourceControl,
}: {
  attentionCount: number;
  goals: WorkspaceGoal[];
  goalArchiveLoadState?: WorkspaceGoalArchiveLoadState;
  lifecycleBusyGoalIds?: ReadonlySet<string>;
  onRequestGoalCreate?: () => void;
  onOpenSettings?: () => void;
  onRetryGoalArchive?: () => void;
  onRequestGoalLifecycle?: (goal: WorkspaceGoal, operation: "stop" | "resume" | "delete") => void;
  onSelectGoal: (goalId: string | null) => void;
  selectedGoalId: string | null;
  statusSourceControl?: StatusSourceControl;
}) {
  const { locale, t } = useWorkspaceI18n();
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
          <small>{localizedGoalState(goal.state, locale)}{goal.needsYou && !stopped ? ` · ${t("home.lane.needsYou")}` : ""}</small>
        </span>
        <ChevronRight size={15} />
      </button>
      {onRequestGoalLifecycle ? (
        <>
          <button
            aria-label={`${stopped ? t("sidebar.resume") : t("sidebar.stop")} ${goal.title}`}
            aria-busy={lifecycleBusyGoalIds?.has(goal.goalId) || undefined}
            className={`personal-goal-lifecycle${lifecycleBusyGoalIds?.has(goal.goalId) ? " is-pending" : ""}`}
            disabled={lifecycleBusyGoalIds?.has(goal.goalId)}
            onClick={() => onRequestGoalLifecycle(goal, stopped ? "resume" : "stop")}
            title={stopped ? t("sidebar.resumeGoal") : t("sidebar.stopGoal")}
            type="button"
          >
            {lifecycleBusyGoalIds?.has(goal.goalId)
              ? <LoaderCircle size={13} />
              : stopped ? <RotateCcw size={13} /> : <Pause size={13} />}
          </button>
          {stopped ? (
            <button
              aria-label={`${t("sidebar.delete")} ${goal.title}`}
              className="personal-goal-lifecycle personal-goal-delete"
              onClick={() => onRequestGoalLifecycle(goal, "delete")}
              title={t("sidebar.deleteGoal")}
              type="button"
            >
              <Trash2 size={13} />
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
  return (
    <div className="personal-goal-directory">
      <div className="personal-sidebar-brand">
        <span className="personal-brand-mark"><Bot size={18} /></span>
        <span><strong>LoopX</strong><small>{t("sidebar.product")}</small></span>
      </div>

      {statusSourceControl ? <StatusSourceSwitcher {...statusSourceControl} /> : null}

      <nav aria-label={t("home.workspace")} className="personal-sidebar-nav">
        <button
          aria-current={selectedGoalId === null ? "page" : undefined}
          className="personal-manager-link"
          onClick={() => onSelectGoal(null)}
          type="button"
        >
          <span className="personal-manager-icon"><Bot size={17} /></span>
          <span>{t("sidebar.manager")}</span>
          {attentionCount > 0 ? <span className="personal-sidebar-count">{attentionCount}</span> : null}
          <ChevronRight size={15} />
        </button>

        <div className="personal-sidebar-section-title">
          <span>Goals</span>
          <span className="personal-sidebar-title-actions"><small>{activeGoals.length}</small>{onRequestGoalCreate ? <button aria-label={t("sidebar.createGoal")} onClick={onRequestGoalCreate} type="button"><Plus size={15} /></button> : null}</span>
        </div>
        <div className="personal-goal-list">
          {activeGoals.map((goal) => goalRow(goal, false))}
        </div>
        {stoppedGoals.length || goalArchiveLoadState.phase === "loading" || goalArchiveLoadState.phase === "error" ? (
          <details
            className="personal-stopped-goals"
            open={goalArchiveLoadState.phase === "error" ? true : undefined}
          >
            <summary>
              <ChevronDown size={13} />
              <span>{t("sidebar.stopped")}</span>
              {goalArchiveLoadState.phase === "loading"
                ? <LoaderCircle aria-label={t("sidebar.stoppedLoading")} className="is-spinning" size={13} />
                : <small>{stoppedGoals.length}</small>}
            </summary>
            <div className="personal-goal-list is-stopped">
              {goalArchiveLoadState.phase === "error" ? (
                <div className="personal-stopped-goal-error" role="alert">
                  <span>{t("sidebar.stoppedLoadFailed")}</span>
                  {onRetryGoalArchive ? <button onClick={onRetryGoalArchive} type="button">{t("sidebar.retryStopped")}</button> : null}
                </div>
              ) : null}
              {stoppedGoals.map((goal) => goalRow(goal, true))}
            </div>
          </details>
        ) : null}
      </nav>

      <div className="personal-sidebar-footer">
        {onOpenSettings ? (
          <button className="personal-sidebar-utility" onClick={onOpenSettings} type="button"><Settings2 size={17} /><span>{t("settings.open")}</span></button>
        ) : null}
      </div>
    </div>
  );
}
