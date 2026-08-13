import { Bot, ChevronDown, Menu, RefreshCw } from "lucide-react";

import type { WorkspaceAgentOption, WorkspaceGoal, WorkspaceGoalTab } from "./personal-workspace-model";
import { goalUsageLabel } from "./personal-workspace-model";

export function ChannelHeader({
  agents,
  mobileNavigationOpen,
  onRefresh,
  onOpenNavigation,
  onSelectGoalTab,
  onSelectAgent,
  selectedAgentId,
  selectedGoal,
  selectedGoalTab,
}: {
  agents: WorkspaceAgentOption[];
  mobileNavigationOpen?: boolean;
  onRefresh?: () => void;
  onOpenNavigation?: () => void;
  onSelectGoalTab: (tab: WorkspaceGoalTab) => void;
  onSelectAgent: (agentId: string) => void;
  selectedAgentId: string;
  selectedGoal: WorkspaceGoal | null;
  selectedGoalTab: WorkspaceGoalTab;
}) {
  return (
    <header className="personal-channel-header">
      <button aria-expanded={mobileNavigationOpen ?? false} aria-label="打开 Goal 导航" className="personal-icon-button personal-mobile-menu" onClick={onOpenNavigation} type="button"><Menu size={18} /></button>
      <div className="personal-channel-title">
        <h1>{selectedGoal?.title ?? "LoopX 管家"}</h1>
        <p>{selectedGoal
          ? `${selectedGoal.agentLabel ?? selectedGoal.agentId} · ${selectedGoal.state}${goalUsageLabel(selectedGoal.usage) ? ` · ${goalUsageLabel(selectedGoal.usage)}` : ""} · ${selectedGoal.nextSentence}`
          : "跨 Goal 的个人工作入口"}</p>
      </div>
      {selectedGoal ? <nav aria-label="Goal 视图" className="personal-goal-tabs">{(["chat", "tasks", "files"] as const).map((tab) => <button aria-current={selectedGoalTab === tab ? "page" : undefined} key={tab} onClick={() => onSelectGoalTab(tab)} type="button">{tab === "chat" ? "Chat" : tab === "tasks" ? "Tasks" : "Files"}</button>)}</nav> : null}
      <div className="personal-channel-actions">
        <label className="personal-agent-select">
          <Bot size={16} />
          <select
            aria-label="选择 Agent"
            onChange={(event) => onSelectAgent(event.target.value)}
            value={selectedAgentId}
          >
            {agents.map((agent) => (
              <option disabled={!agent.available} key={agent.agentId} value={agent.agentId}>
                {agent.label}{agent.available ? "" : " · 不可用"}
              </option>
            ))}
          </select>
          <ChevronDown aria-hidden size={14} />
        </label>
        <span className="personal-live-indicator"><i />实时</span>
        {onRefresh ? (
          <button aria-label="刷新状态" className="personal-icon-button" onClick={onRefresh} type="button">
            <RefreshCw size={17} />
          </button>
        ) : null}
      </div>
    </header>
  );
}
