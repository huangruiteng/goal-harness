import { AlertCircle, ChevronRight } from "lucide-react";

import type { WorkspaceAttention } from "../personal-workspace-model";
import { attentionAgeLabel } from "../personal-workspace-model";

export function AttentionRow({ attention, onSelect }: { attention: WorkspaceAttention; onSelect: () => void }) {
  const age = attentionAgeLabel(attention.updatedAt);
  return (
    <button className="personal-timeline-row personal-attention-row" data-testid="personal-browse-row" onClick={onSelect} type="button">
      <span className="personal-row-icon is-attention"><AlertCircle size={18} /></span>
      <span className="personal-row-copy">
        <small>{attention.goalTitle ?? attention.goalId} · 需要你{age ? ` · 已等待 ${age}` : ""}</small>
        <strong>{attention.text}</strong>
      </span>
      <span className={`personal-priority-dot is-${attention.priority ?? (attention.blocking ? "high" : "medium")}`} />
      <span className={`personal-row-status ${attention.blocking ? "is-blocking" : "is-pending"}`}>{attention.blocking ? "阻塞" : "待处理"}</span>
      <ChevronRight size={17} />
    </button>
  );
}
