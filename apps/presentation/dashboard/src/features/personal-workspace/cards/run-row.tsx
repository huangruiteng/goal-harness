import { Bot, ChevronRight, LoaderCircle } from "lucide-react";

import type { WorkspaceRun } from "../personal-workspace-model";

const runStatusLabel: Record<WorkspaceRun["status"], string> = {
  completed: "已完成",
  failed: "需检查",
  interrupted: "已中断",
  queued: "已安排",
  running: "执行中",
  waiting: "等待条件",
};

export function RunRow({ onSelect, run }: { onSelect: () => void; run: WorkspaceRun }) {
  const progress = run.totalSteps > 0 ? Math.min(100, (run.completedSteps / run.totalSteps) * 100) : 0;
  return (
    <button aria-label={`查看执行过程与结果：${run.title}`} className="personal-timeline-row personal-run-row" data-testid="personal-browse-row" onClick={onSelect} type="button">
      <span className="personal-row-icon is-run"><Bot size={18} /></span>
      <span className="personal-run-identity"><small>{run.goalTitle}</small><strong>{run.agentLabel}</strong></span>
      <span className="personal-row-copy"><strong>{run.title}</strong><small>{run.latestActivity}</small></span>
      <span className="personal-run-progress" aria-label={`${run.completedSteps}/${run.totalSteps}`}>
        <small>{run.completedSteps}/{run.totalSteps}</small><i><b style={{ width: `${progress}%` }} /></i>
      </span>
      <span className={`personal-row-status is-${run.status}`}>
        {run.status === "running" ? <LoaderCircle className="personal-spin" size={14} /> : null}
        {runStatusLabel[run.status]}
      </span>
      {run.sessionId ? <span className="personal-run-open-label">查看执行过程与结果</span> : null}
      <ChevronRight size={17} />
    </button>
  );
}
