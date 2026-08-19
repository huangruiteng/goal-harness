import { ChevronRight, FileCheck2 } from "lucide-react";

import type { WorkspaceOutput } from "../personal-workspace-model";

export function OutputRow({ onSelect, output }: { onSelect: () => void; output: WorkspaceOutput }) {
  return (
    <button className="personal-timeline-row personal-output-row" data-testid="personal-browse-row" onClick={onSelect} type="button">
      <span className="personal-row-icon is-output"><FileCheck2 size={18} /></span>
      <span className="personal-row-copy">
        <small>{output.goalTitle ?? output.goalId} · {output.agentLabel ?? "LoopX"}</small>
        <strong>{output.title}</strong>
        {output.summary ? <span>{output.summary}</span> : null}
      </span>
      {output.createdAt ? <time>{output.createdAt}</time> : null}
      <ChevronRight size={17} />
    </button>
  );
}
