export type WorkspaceGoalState =
  | "需修复"
  | "等你"
  | "等待条件"
  | "推进中"
  | "安静运行"
  | "已完成";

export type WorkspaceAgentTodo = {
  claimedBy?: string | null;
  dependencies?: string[];
  done: boolean;
  evidence?: string | null;
  nextTransition?: string | null;
  status?: string | null;
  taskClass?: string | null;
  text: string;
  todoId: string;
};

export type WorkspaceTodo = WorkspaceAgentTodo & {
  goalId: string;
  goalTitle: string;
  ownerLabel?: string | null;
};

export type WorkspaceGoalUsage = {
  costUsd7d: number;
  costUsd24h: number;
  durationMs7d: number;
  durationMs24h: number;
  tokens7d: number;
  tokens24h: number;
};

export type WorkspaceGoal = {
  agentId: string;
  agentLabel?: string;
  agentSentence: string;
  agentTodos: WorkspaceAgentTodo[];
  goalId: string;
  latestActivity?: string;
  needsYou?: string | null;
  needsYouBlocking?: boolean;
  nextSentence: string;
  state: WorkspaceGoalState;
  title: string;
  usage?: WorkspaceGoalUsage | null;
};

export type WorkspaceAttention = {
  blocking: boolean;
  evidence?: string | null;
  explanation?: string | null;
  goalId: string;
  goalTitle?: string;
  priority?: "high" | "medium" | "low";
  text: string;
  todoId: string;
  updatedAt?: string | null;
};

export type WorkspaceRun = {
  agentId: string;
  agentLabel: string;
  canInterrupt?: boolean;
  completedSteps: number;
  goalId: string;
  goalTitle: string;
  latestActivity: string;
  resumable?: boolean;
  runId: string;
  sessionId?: string;
  sessionStatus?: string;
  status: "queued" | "running" | "waiting" | "completed" | "failed" | "interrupted";
  title: string;
  totalSteps: number;
  turnId?: string;
  outputs?: Array<Pick<WorkspaceOutput, "outputId" | "title" | "kind" | "createdAt">>;
};

export type WorkspaceOutput = {
  agentId?: string;
  agentLabel?: string;
  createdAt?: string;
  goalId: string;
  goalTitle?: string;
  kind?: "document" | "code" | "report" | "evidence";
  outputId: string;
  runId?: string;
  safePreview?: string;
  summary?: string;
  title: string;
  todoId?: string;
};

export type WorkspaceChannel = "manager" | "attention" | "running" | "outputs";
export type WorkspaceGoalTab = "chat" | "tasks" | "files";

export type WorkspaceAgentSettings = {
  adapterKind?: string;
  agentId: string;
  available: boolean;
  capability?: string;
  interrupt?: boolean;
  label: string;
  location?: string;
  resume?: boolean;
  source?: string;
  streaming?: boolean;
  toolCalls?: boolean;
  trustScope?: string;
  workspaceCompatibility?: string;
};

export type WorkspaceScheduleKind = "heartbeat" | "monitor";

export type WorkspaceSchedule = {
  agentId?: string;
  executionHistory?: Array<{
    label: string;
    runId?: string;
    status: "completed" | "failed" | "interrupted" | "running";
    timestamp: string;
  }>;
  goalId: string;
  label: string;
  nextRunAt?: string;
  notificationRule?: string;
  previousRunAt?: string;
  schedule?: string;
  scheduleId?: string;
  scheduleKind: WorkspaceScheduleKind;
  sessionId?: string;
  status?: "active" | "paused" | "draft" | "error";
  stopCondition?: string;
  target?: string;
  timezone?: string;
};

export type WorkspaceActionPreview = {
  actionKind:
    | "goal.create"
    | "goal.update"
    | "todo.create"
    | "todo.update"
    | "agent.bind"
    | "heartbeat.bind"
    | "monitor.create"
    | "monitor.update"
    | "gate.resolve"
    | "run.correct";
  agentLabel?: string;
  fields: Array<{ label: string; value: string }>;
  goalId?: string;
  impact: string;
  gate?: {
    kind: string;
    nextAction?: string;
    summary: string;
  };
  previewId: string;
  primaryLabel?: string;
  status: "draft" | "ready" | "applying" | "applied" | "gated" | "stale" | "error" | "rejected" | "deferred";
  title: string;
  sourceRequest?: WorkspaceActionPreviewRequest;
  workspaceCandidates?: Array<{ label: string; workspaceRef: string }>;
};

export type WorkspaceMessage = {
  agentLabel?: string;
  id: string;
  pending?: boolean;
  role: "assistant" | "user" | "system";
  text: string;
  time?: string;
};

export type WorkspaceTimelineItem =
  | { id: string; kind: "message"; message: WorkspaceMessage }
  | { attention: WorkspaceAttention; id: string; kind: "attention" }
  | { id: string; kind: "run"; run: WorkspaceRun }
  | { id: string; kind: "schedule"; schedule: WorkspaceSchedule }
  | { id: string; kind: "output"; output: WorkspaceOutput }
  | { id: string; kind: "proposal"; proposal: WorkspaceActionPreview };

export type WorkspaceModel = {
  blockingTodoCount: number;
  goals: WorkspaceGoal[];
  openUserTodoCount: number;
  timeline?: WorkspaceTimelineItem[];
  userTodos: WorkspaceAttention[];
};

export type WorkspaceAgentOption = {
  adapterKind?: string;
  agentId: string;
  available: boolean;
  capability?: string;
  interrupt?: boolean;
  label: string;
  location?: string;
  resume?: boolean;
  source?: string;
  streaming?: boolean;
  toolCalls?: boolean;
  trustScope?: string;
  workspaceCompatibility?: string;
};

export type WorkspaceDrawerSelection =
  | { item: WorkspaceAttention; kind: "attention" }
  | { item: WorkspaceGoal; kind: "goal" }
  | { item: WorkspaceTodo; kind: "todo" }
  | { item: WorkspaceRun; kind: "run" }
  | { item: WorkspaceOutput; kind: "output" }
  | { item: WorkspaceActionPreview; kind: "proposal" }
  | { item: WorkspaceAgentSettings; kind: "agent" }
  | {
      item: WorkspaceSchedule;
      kind: "schedule";
    };

export type PersonalHomeCompatibleModel = {
  blockingTodoCount: number;
  goals: WorkspaceGoal[];
  openUserTodoCount: number;
  userTodos: WorkspaceAttention[];
};

export type PersonalWorkspaceCallbacks = {
  onApplyProposal?: (proposal: WorkspaceActionPreview) => void | Promise<void>;
  onApplyAttention?: (attention: WorkspaceAttention) => void;
  onCancelProposal?: (proposal: WorkspaceActionPreview) => void;
  onTransitionProposal?: (proposal: WorkspaceActionPreview, transition: "regenerate" | "reject" | "defer") => void | Promise<void>;
  onSelectWorkspaceCandidate?: (proposal: WorkspaceActionPreview, workspaceRef: string) => void | Promise<void>;
  onCorrectRun?: (run: WorkspaceRun, message: string) => void | Promise<void>;
  onCloseRunSession?: (run: WorkspaceRun) => void | Promise<void>;
  onExplainDecision?: (attention: WorkspaceAttention) => void | Promise<void>;
  onExportOutput?: (output: WorkspaceOutput) => void | Promise<void>;
  onInterruptRun?: (run: WorkspaceRun) => void | Promise<void>;
  onOpenGoal?: (goalId: string) => void;
  onOpenOutput?: (output: WorkspaceOutput) => void;
  onRefresh?: () => void;
  onPreviewAction?: (request: WorkspaceActionPreviewRequest) => WorkspaceActionPreview | Promise<WorkspaceActionPreview>;
  onRequestGoalCreate?: () => WorkspaceActionPreview | Promise<WorkspaceActionPreview | void> | void;
  onRequestScheduleConfig?: (kind: WorkspaceScheduleKind, goalId: string | null) => WorkspaceActionPreview | Promise<WorkspaceActionPreview | void> | void;
  onRetryResumeRun?: (run: WorkspaceRun) => void | Promise<void>;
  onStartNewRunSession?: (run: WorkspaceRun) => void | Promise<void>;
  onUpdateSchedule?: (schedule: WorkspaceSchedule, operation: "edit" | "pause" | "resume" | "run_now" | "stop") => void | Promise<void>;
  onSendMessage?: (message: string, agentId: string, goalId: string | null) => void | Promise<void>;
  onSelectAgent?: (agentId: string) => void;
  onSelectChannel?: (channel: WorkspaceChannel) => void;
  onSelectGoal?: (goalId: string | null) => void;
};

export type WorkspaceActionPreviewRequest = {
  actionKind: WorkspaceActionPreview["actionKind"];
  context: Record<string, unknown>;
  idempotencyKey: string;
  normalizedParameters: Record<string, unknown>;
  summary: string;
};

export function normalizePersonalHomeModel(model: PersonalHomeCompatibleModel): WorkspaceModel {
  return {
    blockingTodoCount: model.blockingTodoCount,
    goals: model.goals,
    openUserTodoCount: model.openUserTodoCount,
    userTodos: model.userTodos,
  };
}

export function goalTitleFor(model: WorkspaceModel, goalId: string) {
  return model.goals.find((goal) => goal.goalId === goalId)?.title ?? goalId;
}

/** Human-readable waiting time for an open attention item; null when under an hour or unknown. */
export function attentionAgeLabel(updatedAt?: string | null): string | null {
  if (!updatedAt) return null;
  const then = new Date(updatedAt).getTime();
  if (Number.isNaN(then)) return null;
  const diff = Date.now() - then;
  if (diff < 3_600_000) return null;
  const days = Math.floor(diff / 86_400_000);
  if (days >= 1) return `${days} 天`;
  return `${Math.floor(diff / 3_600_000)} 小时`;
}

export function formatTokenCount(value?: number | null): string {
  const n = value ?? 0;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function formatCostUsd(value?: number | null): string {
  return `$${(value ?? 0).toFixed(2)}`;
}

export function formatDurationMs(value?: number | null): string {
  const ms = value ?? 0;
  if (ms >= 3_600_000) return `${(ms / 3_600_000).toFixed(1)}h`;
  if (ms >= 60_000) return `${(ms / 60_000).toFixed(1)}m`;
  if (ms >= 1_000) return `${Math.round(ms / 1_000)}s`;
  return `${ms}ms`;
}

/** True only when a goal has actually reported usage; zeros mean ingestion has not landed yet. */
export function hasGoalUsage(usage?: WorkspaceGoalUsage | null): usage is WorkspaceGoalUsage {
  return Boolean(usage && (usage.tokens24h + usage.tokens7d + usage.costUsd24h + usage.costUsd7d + usage.durationMs24h + usage.durationMs7d) > 0);
}

/** Compact header chip, e.g. "7d 45.6k tokens · $0.42"; null when nothing reported. */
export function goalUsageLabel(usage?: WorkspaceGoalUsage | null): string | null {
  if (!hasGoalUsage(usage)) return null;
  return `7d ${formatTokenCount(usage.tokens7d)} tokens · ${formatCostUsd(usage.costUsd7d)}`;
}
