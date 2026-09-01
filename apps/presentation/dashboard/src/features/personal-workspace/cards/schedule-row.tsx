import { CalendarClock, ChevronRight, Radio } from "lucide-react";

import type { WorkspaceSchedule } from "../personal-workspace-model";
import { useWorkspaceI18n } from "../i18n";

export function ScheduleRow({ onSelect, schedule }: {
  onSelect: () => void;
  schedule: WorkspaceSchedule;
}) {
  const { t } = useWorkspaceI18n();
  const isHeartbeat = schedule.scheduleKind === "heartbeat";
  return (
    <button
      aria-label={`${isHeartbeat ? "Heartbeat" : t("tasks.scheduled")}：${schedule.label}；${schedule.status ?? "active"}`}
      className="personal-schedule-row"
      onClick={onSelect}
      type="button"
    >
      <span className="personal-schedule-icon">{isHeartbeat ? <Radio size={17} /> : <CalendarClock size={17} />}</span>
      <span className="personal-schedule-copy">
        <small>{isHeartbeat ? t("schedule.heartbeat") : t("schedule.monitor")}</small>
        <strong>{schedule.label}</strong>
        <p>{schedule.schedule ?? t("schedule.summary")}</p>
      </span>
      <span className={`personal-schedule-status is-${schedule.status ?? "active"}`}>{schedule.status === "paused" ? t("schedule.paused") : t("schedule.active")}</span>
      <ChevronRight size={16} />
    </button>
  );
}
