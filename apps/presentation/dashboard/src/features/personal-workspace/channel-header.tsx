import { Bot, ChevronDown, Info, Menu, Palette, RefreshCw } from "lucide-react";

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
  onToggleTheme,
  refreshState,
  selectedAgentId,
  selectedGoal,
  selectedGoalTab,
  theme,
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
  onToggleTheme: () => void;
  refreshState?: "idle" | "loading" | "done" | "error";
  selectedAgentId: string;
  selectedGoal: WorkspaceGoal | null;
  selectedGoalTab: WorkspaceGoalTab;
  theme: "brutal" | "paper";
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
      {selectedGoal ? (
        <nav aria-label="Goal 视图" className="personal-goal-tabs">
          <button aria-current={selectedGoalTab === "chat" ? "page" : undefined} onClick={() => onSelectGoalTab("chat")} type="button">Chat</button>
          <button aria-current={selectedGoalTab === "tasks" ? "page" : undefined} onClick={() => onSelectGoalTab("tasks")} type="button">Tasks</button>
          <button aria-current={selectedGoalTab === "files" ? "page" : undefined} onClick={() => onSelectGoalTab("files")} type="button">Files</button>
        </nav>
      ) : (
        <nav aria-label="管家视图" className="personal-goal-tabs">
          <button aria-current={!managerChatOpen ? "page" : undefined} onClick={onReturnManagerHome} type="button">总览</button>
          <button aria-current={managerChatOpen ? "page" : undefined} onClick={onOpenManagerChat} type="button">Chat</button>
        </nav>
      )}
      {selectedGoal && onOpenGoalDetail ? (
        <button aria-label="Goal 详情" className="personal-icon-button" onClick={onOpenGoalDetail} title="Goal 详情" type="button">
          <Info size={17} />
        </button>
      ) : null}
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
        <button
          aria-label={theme === "paper" ? "切换到野兽主题" : "切换到默认主题"}
          className="personal-icon-button"
          onClick={onToggleTheme}
          title={theme === "paper" ? "切换到野兽主题" : "切换到默认主题"}
          type="button"
        ><Palette size={17} /></button>
        {onRefresh ? (
          <span className={`personal-refresh-control is-${refreshState ?? "idle"}`}>
            {refreshState === "loading" ? <small>刷新中</small> : refreshState === "done" ? <small>刚刚更新</small> : refreshState === "error" ? <small>刷新失败</small> : null}
            <button aria-label={refreshState === "loading" ? "正在刷新" : "刷新状态"} className="personal-icon-button" disabled={refreshState === "loading"} onClick={onRefresh} type="button">
              <RefreshCw className={refreshState === "loading" ? "is-spinning" : undefined} size={17} />
            </button>
          </span>
        ) : null}
      </div>
    </header>
  );
}
