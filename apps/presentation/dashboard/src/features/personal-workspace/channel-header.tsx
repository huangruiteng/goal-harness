import { Bot, ChevronDown, Eye, Info, Menu, RefreshCw } from "lucide-react";

import { localizedGoalState, useWorkspaceI18n } from "./i18n";
import type { WorkspaceAgentOption, WorkspaceGoal, WorkspaceGoalTab } from "./personal-workspace-model";
import { goalUsageLabel } from "./personal-workspace-model";

export function ChannelHeader({
  agents,
  managerChatOpen,
  mobileNavigationOpen,
  onOpenGoalDetail,
  onOpenManagerChat,
  onRefresh,
  onOpenNavigation,
  onSelectGoalTab,
  onSelectAgent,
  onReturnManagerHome,
  refreshState,
  readOnlySourceLabel,
  selectedAgentId,
  selectedGoal,
  selectedGoalTab,
}: {
  agents: WorkspaceAgentOption[];
  managerChatOpen?: boolean;
  mobileNavigationOpen?: boolean;
  onOpenGoalDetail?: () => void;
  onOpenManagerChat?: () => void;
  onRefresh?: () => void;
  onOpenNavigation?: () => void;
  onSelectGoalTab: (tab: WorkspaceGoalTab) => void;
  onSelectAgent: (agentId: string) => void;
  onReturnManagerHome?: () => void;
  refreshState?: "idle" | "loading" | "done" | "error";
  readOnlySourceLabel?: string;
  selectedAgentId: string;
  selectedGoal: WorkspaceGoal | null;
  selectedGoalTab: WorkspaceGoalTab;
}) {
  const { locale, t } = useWorkspaceI18n();
  return (
    <header className="personal-channel-header">
      <button aria-expanded={mobileNavigationOpen ?? false} aria-label={t("header.openGoalNavigation")} className="personal-icon-button personal-mobile-menu" onClick={onOpenNavigation} type="button"><Menu size={18} /></button>
      <div className="personal-channel-title">
        <h1>{selectedGoal?.title ?? t("header.manager")}</h1>
        <p>{selectedGoal
          ? `${selectedGoal.agentLabel ?? selectedGoal.agentId} · ${localizedGoalState(selectedGoal.state, locale)}${goalUsageLabel(selectedGoal.usage) ? ` · ${goalUsageLabel(selectedGoal.usage)}` : ""} · ${selectedGoal.nextSentence}`
          : t("header.managerDescription")}</p>
      </div>
      {selectedGoal ? (
        <nav aria-label={t("header.goalView")} className="personal-goal-tabs">
          <button aria-current={selectedGoalTab === "chat" ? "page" : undefined} onClick={() => onSelectGoalTab("chat")} type="button">{t("header.chat")}</button>
          <button aria-current={selectedGoalTab === "tasks" ? "page" : undefined} onClick={() => onSelectGoalTab("tasks")} type="button">{t("header.tasks")}</button>
          <button aria-current={selectedGoalTab === "files" ? "page" : undefined} onClick={() => onSelectGoalTab("files")} type="button">{t("header.files")}</button>
        </nav>
      ) : (
        <nav aria-label={t("header.managerView")} className="personal-goal-tabs">
          <button aria-current={!managerChatOpen ? "page" : undefined} onClick={onReturnManagerHome} type="button">{t("header.managerOverview")}</button>
          <button aria-current={managerChatOpen ? "page" : undefined} onClick={onOpenManagerChat} type="button">{t("header.chat")}</button>
        </nav>
      )}
      {selectedGoal && onOpenGoalDetail ? (
        <button aria-label={t("header.goalDetails")} className="personal-icon-button" onClick={onOpenGoalDetail} title={t("header.goalDetails")} type="button">
          <Info size={17} />
        </button>
      ) : null}
      <div className="personal-channel-actions">
        {readOnlySourceLabel ? (
          <span className="personal-read-only-source" title={t("header.readOnlySourceDescription", { source: readOnlySourceLabel })}><Eye size={15} />{readOnlySourceLabel}<small>{t("common.readOnly")}</small></span>
        ) : (
          <label className="personal-agent-select">
            <Bot size={16} />
            <select
              aria-label={t("header.selectAgent")}
              onChange={(event) => onSelectAgent(event.target.value)}
              value={selectedAgentId}
            >
              {agents.map((agent) => (
                <option disabled={!agent.available} key={agent.agentId} value={agent.agentId}>
                  {agent.label}{agent.available ? "" : ` · ${t("header.agentUnavailable")}`}
                </option>
              ))}
            </select>
            <ChevronDown aria-hidden size={14} />
          </label>
        )}
        <span className="personal-live-indicator"><i />{t("header.live")}</span>
        {onRefresh ? (
          <span className={`personal-refresh-control is-${refreshState ?? "idle"}`}>
            {refreshState === "loading" ? <small>{t("header.refreshing")}</small> : refreshState === "done" ? <small>{t("header.refreshDone")}</small> : refreshState === "error" ? <small>{t("header.refreshFailed")}</small> : null}
            <button aria-label={refreshState === "loading" ? t("header.refreshing") : t("header.refresh")} className="personal-icon-button" disabled={refreshState === "loading"} onClick={onRefresh} type="button">
              <RefreshCw className={refreshState === "loading" ? "is-spinning" : undefined} size={17} />
            </button>
          </span>
        ) : null}
      </div>
    </header>
  );
}
