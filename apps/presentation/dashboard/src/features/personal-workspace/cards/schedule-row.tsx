import { CalendarClock, ChevronRight, Radio } from "lucide-react";

import type { WorkspaceSchedule } from "../personal-workspace-model";

export function ScheduleRow({ onSelect, schedule }: {
  onSelect: () => void;
  schedule: WorkspaceSchedule;
}) {
  const isHeartbeat = schedule.scheduleKind === "heartbeat";
  return (
    <button
      aria-label={`${isHeartbeat ? "Heartbeat" : "定时检查"}：${schedule.label}；${schedule.status ?? "active"}`}
      className="personal-schedule-row"
      onClick={onSelect}
      type="button"
    >
      <span className="personal-schedule-icon">{isHeartbeat ? <Radio size={17} /> : <CalendarClock size={17} />}</span>
      <span className="personal-schedule-copy">
        <small>{isHeartbeat ? "Goal Heartbeat" : "定时与持续任务"}</small>
        <strong>{schedule.label}</strong>
        <p>{schedule.schedule ?? "按 LoopX 调度约束持续检查"}</p>
      </span>
      <span className={`personal-schedule-status is-${schedule.status ?? "active"}`}>{schedule.status === "paused" ? "已暂停" : "执行中"}</span>
      <ChevronRight size={16} />
    </button>
  );
}
