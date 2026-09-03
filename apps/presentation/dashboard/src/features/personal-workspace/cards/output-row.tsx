import { ChevronRight, FileCheck2, FileText } from "lucide-react";

import { useWorkspaceI18n } from "../i18n";
import type { WorkspaceOutput } from "../personal-workspace-model";

export function OutputRow({ onSelect, output }: { onSelect: () => void; output: WorkspaceOutput }) {
  const { t } = useWorkspaceI18n();
  const Icon = output.kind === "report" ? FileText : FileCheck2;
  return (
    <button className="personal-timeline-row personal-output-row" data-output-kind={output.kind} data-testid="personal-browse-row" onClick={onSelect} type="button">
      <span className="personal-row-icon is-output"><Icon size={18} /></span>
      <span className="personal-row-copy">
        <small>{output.goalTitle ?? output.goalId} · {output.agentLabel ?? "LoopX"}</small>
        <strong>{output.title}</strong>
        {output.summary ? <span>{output.summary}</span> : null}
        {output.report ? <small>{t("files.reportDelta", { added: output.report.addedCount, changed: output.report.changedCount })} · {t("files.verifiedReport")}</small> : null}
      </span>
      {output.createdAt ? <time>{output.createdAt}</time> : null}
      <ChevronRight size={17} />
    </button>
  );
}
