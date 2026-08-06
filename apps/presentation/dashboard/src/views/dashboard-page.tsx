import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Copy,
  Clock3,
  FileCheck2,
  FileJson2,
  FileText,
  Gauge,
  GitBranch,
  History,
  Link2,
  LayoutDashboard,
  Moon,
  Upload,
  Radar,
  RefreshCw,
  RotateCcw,
  Search,
  ShieldCheck,
  Sun,
  Terminal,
  Users,
} from "lucide-react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";

import { dashboardRoute } from "../router";
import {
  QueueItem,
  AuthorityRegistry,
  ComputeQuota,
  ControlPlanePolicy,
  ControllerReadiness,
  GlobalRegistryHealth,
  HumanReward,
  OperatorGate,
  OperatorGateResumeContract,
  ProjectMap,
  ReviewMaterial,
  RewardDryRunResponse,
  RunGoal,
  RunRecord,
  OrchestrationPolicy,
  StatusPayload,
  AgentManagementHandoffNote,
  AgentManagementProjection,
  ProjectAssetLatestValidation,
  ProjectAssetHandoffReadiness,
  ProjectAssetTodoSummary,
  TodoItem,
  TodoGroup,
  TodoIndexSummary,
  EventLedgerSummary,
  PromotionReadinessSummary,
  PromotionGate,
  DecisionFreshnessItem,
  DecisionFreshnessSummary,
  UsageSummary,
  exampleStatusPayload,
  AgentManagementStaleClaimHint,
  AgentManagementWorkspaceRef,
  formatStatusError,
  parseRewardDryRunResponse,
  parseStatusPayload,
} from "../data/status";
import { buildActionPacket, buildApprovedAgentHandoff, ProjectAssetSource } from "../data/action-packet";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Select } from "../components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table";
import { cn } from "../lib/utils";

type LaneKey = "user" | "codex" | "watch";

type LaneDefinition = {
  key: LaneKey;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  waitingOn: readonly string[];
  accent: string;
};

const laneConfig: LaneDefinition[] = [
  {
    key: "user",
    label: "用户 / 控制者",
    icon: Users,
    waitingOn: ["user_or_controller", "controller"],
    accent: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100",
  },
  {
    key: "codex",
    label: "Codex 可执行",
    icon: Bot,
    waitingOn: ["codex"],
    accent: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  },
  {
    key: "watch",
    label: "等待外部证据",
    icon: Radar,
    waitingOn: ["external_evidence"],
    accent: "border-sky-200 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-100",
  },
];

const severityVariant: Record<string, "neutral" | "success" | "warning" | "info" | "danger"> = {
  high: "danger",
  action: "warning",
  watch: "info",
};

const waitingLabel: Record<string, string> = {
  user_or_controller: "用户 / 控制者",
  controller: "控制者",
  codex: "Codex",
  external_evidence: "外部证据",
  clear: "无需等待",
};

const severityLabel: Record<string, string> = {
  high: "高优先级",
  action: "需处理",
  watch: "观察中",
  clear: "正常",
};

const lifecycleLabel: Record<string, string> = {
  connected: "已连接",
  mapped: "已映射",
  refreshed: "已刷新",
  adapter_inspected: "适配器已检查",
  reward_judged: "人工评价已记录",
  operator_approved: "操作者已批准",
  operator_gated: "等待操作者",
  controller_gated: "等待控制者",
  controller_ready: "控制者已就绪",
  registered: "已登记",
  planned: "已计划",
  run_recorded: "运行已记录",
};

const lifecycleVariant: Record<string, "neutral" | "success" | "warning" | "info" | "danger"> = {
  connected: "neutral",
  mapped: "info",
  refreshed: "warning",
  adapter_inspected: "info",
  reward_judged: "success",
  operator_approved: "success",
  operator_gated: "warning",
  controller_gated: "warning",
  controller_ready: "success",
  registered: "neutral",
  planned: "warning",
  run_recorded: "neutral",
};

type DataSource =
  | { kind: "example"; label: "内置示例" }
  | { kind: "url"; label: string }
  | { kind: "file"; label: string };

const defaultLiveStatusUrl = "http://127.0.0.1:8765/status.json";
const defaultGlobalStatusUrl = "http://127.0.0.1:8766/status.json";
const expectedStatusContractSchemaVersion = 2;
const fallbackStatusContractReloadHint = "scripts/macos-dashboard-launchagent.sh restart";
const rewardOptions = ["positive", "mixed", "neutral", "negative"] as const;
const rewardOptionLabel: Record<(typeof rewardOptions)[number], string> = {
  positive: "正向",
  mixed: "混合",
  neutral: "中性",
  negative: "负向",
};
const inputClassName =
  "h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm outline-none focus:ring-2 focus:ring-slate-400 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 dark:focus:ring-zinc-500";

type RewardValue = (typeof rewardOptions)[number];

function routeViewForUrl(view?: "ops" | "share") {
  return view === "ops" ? "ops" : undefined;
}

function currentRouteView(current: { view?: "ops" | "share" } | {}) {
  return "view" in current ? current.view : undefined;
}

function isLoopbackUrl(value: string) {
  try {
    const url = new URL(value);
    return ["127.0.0.1", "localhost", "::1", "[::1]"].includes(url.hostname);
  } catch {
    return false;
  }
}

function statusContractFreshnessIssue(payload: StatusPayload, source: DataSource) {
  if (source.kind !== "url" || !isLoopbackUrl(source.label)) {
    return null;
  }
  const schemaVersion = payload.status_contract.schema_version ?? 0;
  if (schemaVersion >= expectedStatusContractSchemaVersion) {
    return null;
  }
  return {
    reloadHint: payload.status_contract.reload_hint || fallbackStatusContractReloadHint,
    schemaVersion,
  };
}

function StatusContractFreshnessWarning({
  payload,
  source,
}: {
  payload: StatusPayload;
  source: DataSource;
}) {
  const issue = statusContractFreshnessIssue(payload, source);
  if (!issue) {
    return null;
  }
  return (
    <div
      className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950 shadow-sm dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"
      data-testid="status-contract-freshness-warning"
    >
      <div className="flex flex-wrap items-center gap-2 font-semibold">
        <CircleAlert className="h-4 w-4" />
        状态服务契约过旧
        <Badge variant="warning">schema v{issue.schemaVersion}</Badge>
      </div>
      <p className="mt-1">
        这个本机实时状态源低于看板期望的 schema v{expectedStatusContractSchemaVersion}；
        可能是 `127.0.0.1:8766` 仍在运行旧状态服务。使用前运行
        <span className="mx-1 font-mono">{issue.reloadHint}</span>
        后刷新页面。
      </p>
    </div>
  );
}

type RewardRequestBody = {
  goal_id: string;
  run_generated_at: string;
  decision: string;
  reward: RewardValue;
  reason_summary: string;
  follow_up?: string;
  recorded_at?: string;
};

type ReviewMaterialContent = {
  ok: boolean;
  goal_id?: string;
  path?: string;
  resolved_path?: string;
  bytes?: number;
  content?: string;
  error?: string;
};

type GoalDirectoryRow = {
  goal: RunGoal;
  queueItem?: QueueItem;
  latestRun?: RunRecord;
  status: string;
  waitingOn: string;
  severity: string;
  lifecyclePhase: string;
  lifecycleFlags: string[];
};

type TodoFocusItem = {
  goalId: string;
  role: "user" | "agent";
  text: string;
  openCount: number;
  totalCount: number;
  severity: string;
  waitingOn: string;
  phase: string;
  priority: number;
};

type TodoExplorerRole = "user" | "agent";

type TodoExplorerItem = {
  goalId: string;
  role: TodoExplorerRole;
  todo: TodoItem;
  sourceSection: string;
  source: string;
  openCount: number;
  totalCount: number;
  severity: string;
  waitingOn: string;
  phase: string;
  sourceOrder: number;
};

type AgentManagementStatus = {
  label: string;
  variant: BadgeVariant;
};

type AgentManagementRow = {
  agentId: string;
  claimedTodos: TodoExplorerItem[];
  evidenceRefs: string[];
  goalIds: string[];
  handoffNote?: AgentManagementHandoffNote | null;
  lastActivity?: string | null;
  nextSafeAction: string;
  primaryGoalId: string;
  quotaHints: string[];
  staleClaimHint?: AgentManagementStaleClaimHint | null;
  status: AgentManagementStatus;
  workspaceRef?: AgentManagementWorkspaceRef | null;
};

function todoExplorerIdentityKey(goalId: string, role: TodoExplorerRole, todo: TodoItem) {
  const stableId = todo.todo_id?.trim();
  if (stableId) {
    return `${goalId}:${role}:${stableId}`;
  }
  return `${goalId}:${role}:index:${todo.index}:${todo.text}`;
}

function laneFor(item: QueueItem) {
  return laneConfig.find((lane) => lane.waitingOn.includes(item.waiting_on));
}

function ShortText({ children }: { children: string }) {
  return <span className="line-clamp-2 break-words">{children}</span>;
}

function StatusBadge({ value }: { value: string }) {
  return <Badge variant={severityVariant[value] ?? "neutral"}>{severityLabel[value] ?? value}</Badge>;
}

function inferLifecyclePhase(status?: string | null, run?: RunRecord) {
  if (run?.controller_readiness?.decision_advisor_ready || run?.controller_readiness?.write_controller_ready) {
    return "controller_ready";
  }
  if (run?.controller_readiness) {
    return "controller_gated";
  }
  if (run?.human_reward) {
    return "reward_judged";
  }
  if (run?.operator_gate?.decision === "approve") {
    return "operator_approved";
  }
  if (run?.operator_gate) {
    return "operator_gated";
  }
  const value = status || run?.classification || "";
  if (value === "connected_without_run") {
    return "connected";
  }
  if (value === "read_only_project_map" || run?.project_map) {
    return "mapped";
  }
  if (value === "state_refreshed") {
    return "refreshed";
  }
  if (value && value !== "no_status") {
    return "adapter_inspected";
  }
  return "registered";
}

function normalizeLifecycle(primary?: string | null, flags?: string[]) {
  const cleanFlags = (flags ?? []).filter(Boolean);
  const phase = primary || cleanFlags[0] || "registered";
  const allFlags = cleanFlags.includes(phase) ? cleanFlags : [phase, ...cleanFlags];
  return {
    phase,
    flags: allFlags,
  };
}

function PhaseBadges({
  phase,
  flags,
  compact = false,
}: {
  phase?: string | null;
  flags?: string[];
  compact?: boolean;
}) {
  const normalized = normalizeLifecycle(phase, flags);
  const shown = compact ? [normalized.phase] : normalized.flags.slice(0, 3);
  return (
    <div className="flex flex-wrap gap-1.5">
      {shown.map((flag) => (
        <Badge key={flag} variant={lifecycleVariant[flag] ?? "neutral"}>
          {lifecycleLabel[flag] ?? flag}
        </Badge>
      ))}
      {!compact && normalized.flags.length > shown.length ? (
        <Badge variant="neutral">+{normalized.flags.length - shown.length}</Badge>
      ) : null}
    </div>
  );
}

function QueueGateSummary({ item, compact = false }: { item?: QueueItem; compact?: boolean }) {
  if (!item) {
    return null;
  }
  const gates = item.missing_gates ?? [];
  if (!item.controller_stage && gates.length === 0 && !item.next_handoff_condition) {
    return null;
  }
  return (
    <div className={cn("flex flex-wrap gap-1.5", compact ? "mt-1" : "mt-2")}>
      {item.controller_stage ? <Badge variant="info">{item.controller_stage}</Badge> : null}
      {gates.map((gate) => (
        <Badge key={gate} variant="warning">
          {gate}
        </Badge>
      ))}
      {item.next_handoff_condition && !compact ? (
        <span className="w-full text-xs leading-5 text-slate-500 dark:text-zinc-400">
          {item.next_handoff_condition}
        </span>
      ) : null}
    </div>
  );
}

function shellQuote(value: string) {
  if (/^[A-Za-z0-9_./:=@+-]+$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, "'\"'\"'")}'`;
}

function buildRewardCommand({
  goalId,
  registry,
  runtimeRoot,
  runGeneratedAt,
  decision,
  reward,
  reasonSummary,
  followUp,
}: {
  goalId: string;
  registry: string;
  runtimeRoot: string;
  runGeneratedAt: string;
  decision: string;
  reward: RewardValue;
  reasonSummary: string;
  followUp: string;
}) {
  const lines = [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  reward \\",
    `  --goal-id ${shellQuote(goalId)} \\`,
    `  --run-generated-at ${shellQuote(runGeneratedAt)} \\`,
    `  --decision ${shellQuote(decision || "decision_label")} \\`,
    `  --reward ${shellQuote(reward)} \\`,
    `  --reason-summary ${shellQuote(reasonSummary || "public_safe_reason")} \\`,
  ];
  if (followUp.trim()) {
    lines.push(`  --follow-up ${shellQuote(followUp.trim())} \\`);
  }
  lines.push("  --write-active-state-summary \\");
  lines.push("  --dry-run");
  return lines.join("\n");
}

function buildRewardApiUrls(source: DataSource) {
  if (source.kind !== "url" || !/^https?:\/\//i.test(source.label)) {
    return { dryRunUrl: null, appendUrl: null };
  }
  try {
    const url = new URL(source.label);
    const isLoopback = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(url.hostname);
    return isLoopback
      ? { dryRunUrl: `${url.origin}/reward/dry-run`, appendUrl: `${url.origin}/reward/append` }
      : { dryRunUrl: null, appendUrl: null };
  } catch {
    return { dryRunUrl: null, appendUrl: null };
  }
}

function localApiUrl(source: DataSource, path: string | null | undefined) {
  if (!path || source.kind !== "url" || !/^https?:\/\//i.test(source.label)) {
    return null;
  }
  try {
    const sourceUrl = new URL(source.label);
    const targetUrl = new URL(path, sourceUrl.origin);
    const isLoopback = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(targetUrl.hostname);
    return isLoopback ? targetUrl.toString() : null;
  } catch {
    return null;
  }
}

function buildControlPlaneApiUrls(source: DataSource, payload?: StatusPayload) {
  const localApi = payload?.local_dashboard_api;
  if (localApi) {
    return {
      dryRunUrl: localApiUrl(source, localApi.configure_goal_dry_run_url),
      applyUrl: localApiUrl(source, localApi.configure_goal_apply_url),
      writeEnabled: Boolean(localApi.control_plane_write_enabled),
    };
  }
  if (source.kind !== "url" || !/^https?:\/\//i.test(source.label)) {
    return { dryRunUrl: null, applyUrl: null, writeEnabled: null };
  }
  try {
    const url = new URL(source.label);
    const isLoopback = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(url.hostname);
    return isLoopback
      ? {
          dryRunUrl: `${url.origin}/control-plane/configure-goal/dry-run`,
          applyUrl: `${url.origin}/control-plane/configure-goal/apply`,
          writeEnabled: null,
        }
      : { dryRunUrl: null, applyUrl: null, writeEnabled: null };
  } catch {
    return { dryRunUrl: null, applyUrl: null, writeEnabled: null };
  }
}

function buildReviewMaterialUrl(source: DataSource, goalId: string, material: ReviewMaterial) {
  if (source.kind !== "url" || !/^https?:\/\//i.test(source.label) || !material.path) {
    return null;
  }
  try {
    const url = new URL(source.label);
    const isLoopback = ["127.0.0.1", "localhost", "::1", "[::1]"].includes(url.hostname);
    if (!isLoopback) {
      return null;
    }
    const materialUrl = new URL("/review-material", url.origin);
    materialUrl.searchParams.set("goal_id", goalId);
    materialUrl.searchParams.set("path", material.path);
    return materialUrl.toString();
  } catch {
    return null;
  }
}

function latestRunSortValue(run?: RunRecord) {
  return run?.generated_at ? Date.parse(run.generated_at) || 0 : 0;
}

function buildGoalDirectoryRows(goals: RunGoal[], queueItems: QueueItem[]) {
  const queueByGoal = new Map(queueItems.map((item) => [item.goal_id, item]));
  const seen = new Set<string>();
  const rows: GoalDirectoryRow[] = goals.map((goal) => {
    seen.add(goal.id);
    const queueItem = queueByGoal.get(goal.id);
    const latestRun = goal.latest_runs[0];
    const phase = queueItem?.lifecycle_phase
      ?? goal.lifecycle_phase
      ?? latestRun?.lifecycle_phase
      ?? inferLifecyclePhase(queueItem?.status ?? latestRun?.classification ?? goal.status, latestRun);
    const flags = queueItem?.lifecycle_flags?.length
      ? queueItem.lifecycle_flags
      : goal.lifecycle_flags?.length
        ? goal.lifecycle_flags
        : latestRun?.lifecycle_flags?.length
          ? latestRun.lifecycle_flags
          : [phase];
    return {
      goal,
      queueItem,
      latestRun,
      status: queueItem?.status ?? latestRun?.classification ?? goal.status ?? "no_status",
      waitingOn: queueItem?.waiting_on ?? "clear",
      severity: queueItem?.severity ?? "clear",
      lifecyclePhase: phase,
      lifecycleFlags: flags,
    };
  });

  for (const item of queueItems) {
    if (seen.has(item.goal_id)) {
      continue;
    }
    rows.push({
      goal: {
        id: item.goal_id,
        status: item.status,
        lifecycle_phase: item.lifecycle_phase ?? inferLifecyclePhase(item.status),
        lifecycle_flags: item.lifecycle_flags?.length ? item.lifecycle_flags : [item.lifecycle_phase ?? inferLifecyclePhase(item.status)],
        registry_member: false,
        legacy_runtime_goal: false,
        adapter_kind: null,
        adapter_status: null,
        index_exists: false,
        raw_index_records: 0,
        unique_runs: 0,
        latest_runs: [],
      },
      queueItem: item,
      status: item.status,
      waitingOn: item.waiting_on,
      severity: item.severity,
      lifecyclePhase: item.lifecycle_phase ?? inferLifecyclePhase(item.status),
      lifecycleFlags: item.lifecycle_flags?.length ? item.lifecycle_flags : [item.lifecycle_phase ?? inferLifecyclePhase(item.status)],
    });
  }

  const severityOrder: Record<string, number> = {
    high: 0,
    action: 1,
    watch: 2,
    clear: 3,
  };
  return rows.sort((a, b) => {
    const severityDelta = (severityOrder[a.severity] ?? 4) - (severityOrder[b.severity] ?? 4);
    if (severityDelta !== 0) {
      return severityDelta;
    }
    return latestRunSortValue(b.latestRun) - latestRunSortValue(a.latestRun);
  });
}

function GoalDirectory({
  rows,
  selectedGoalId,
  onSelectGoal,
}: {
  rows: GoalDirectoryRow[];
  selectedGoalId: string;
  onSelectGoal: (goalId: string) => void;
}) {
  const actionCount = rows.filter((row) => row.queueItem && row.waitingOn !== "external_evidence").length;
  const watchCount = rows.filter((row) => row.waitingOn === "external_evidence").length;
  const clearCount = rows.length - actionCount - watchCount;

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            Goal 目录
          </CardTitle>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="warning">{actionCount} 个需处理</Badge>
          <Badge variant="info">{watchCount} 个观察中</Badge>
          <Badge variant="success">{clearCount} 个正常</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
          <div className="divide-y divide-slate-200 dark:divide-zinc-800">
            {rows.map((row) => (
              <button
                className={cn(
                  "grid w-full gap-3 px-4 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-zinc-900 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)_minmax(180px,0.7fr)]",
                  row.goal.id === selectedGoalId && "bg-slate-100 dark:bg-zinc-900",
                )}
                key={row.goal.id}
                onClick={() => onSelectGoal(row.goal.id)}
                type="button"
              >
                <div className="min-w-0">
                  <div className="break-all text-sm font-semibold text-slate-950 dark:text-zinc-50">{row.goal.id}</div>
                  <div className="mt-1 line-clamp-1 text-xs text-slate-500 dark:text-zinc-400">
                    {row.goal.domain ?? "未设置领域"}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>{row.status}</Badge>
                    {row.severity === "clear" ? <Badge variant="success">正常</Badge> : <StatusBadge value={row.severity} />}
                    <QuotaChip quota={row.queueItem?.quota ?? row.goal.quota} />
                  </div>
                  <div className="mt-1">
                    <PhaseBadges compact flags={row.lifecycleFlags} phase={row.lifecyclePhase} />
                  </div>
                  <div className="mt-1 line-clamp-1 text-xs text-slate-500 dark:text-zinc-400">
                    {row.waitingOn === "clear" ? "没有待处理事项" : waitingLabel[row.waitingOn] ?? row.waitingOn}
                  </div>
                  <QueueGateSummary compact item={row.queueItem} />
                </div>
                <div className="min-w-0 md:text-right">
                  <div className="text-xs font-medium text-slate-500 dark:text-zinc-400">
                    {row.goal.unique_runs} 次运行 · {row.goal.raw_index_records} 条记录
                  </div>
                  <div className="mt-1 break-all text-xs text-slate-500 dark:text-zinc-400">
                    {row.latestRun?.generated_at ?? "尚无运行记录"}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function QueueTable({
  items,
  selectedGoalId,
  onSelectGoal,
}: {
  items: QueueItem[];
  selectedGoalId: string;
  onSelectGoal: (goalId: string) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<QueueItem>[]>(
    () => [
      {
        accessorKey: "goal_id",
        header: "Goal",
        cell: ({ row }) => (
          <button
            className="text-left font-medium text-slate-900 underline-offset-4 hover:underline dark:text-zinc-100"
            onClick={() => onSelectGoal(row.original.goal_id)}
            type="button"
          >
            {row.original.goal_id}
          </button>
        ),
      },
      {
        accessorKey: "status",
        header: "状态",
        cell: ({ row }) => <Badge>{row.original.status}</Badge>,
      },
      {
        accessorKey: "lifecycle_phase",
        header: "阶段",
        cell: ({ row }) => (
          <PhaseBadges
            compact
            flags={row.original.lifecycle_flags}
            phase={row.original.lifecycle_phase ?? inferLifecyclePhase(row.original.status)}
          />
        ),
      },
      {
        accessorKey: "waiting_on",
        header: "等待对象",
        cell: ({ row }) => waitingLabel[row.original.waiting_on] ?? row.original.waiting_on,
      },
      {
        accessorKey: "severity",
        header: "优先级",
        cell: ({ row }) => <StatusBadge value={row.original.severity} />,
      },
      {
        accessorKey: "quota",
        header: "配额",
        cell: ({ row }) => <QuotaChip quota={row.original.quota} />,
      },
      {
        accessorKey: "recommended_action",
        header: "下一步",
        cell: ({ row }) => (
          <div className="min-w-0">
            <ShortText>{row.original.recommended_action}</ShortText>
            <QueueGateSummary compact item={row.original} />
          </div>
        ),
      },
    ],
    [],
  );
  const table = useReactTable({
    data: items,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="min-w-0 overflow-x-auto rounded-lg border border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : (
                    <button
                      className="flex items-center gap-1 text-left"
                      onClick={header.column.getToggleSortingHandler()}
                      type="button"
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </button>
                  )}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow
              className={cn(
                "cursor-pointer",
                row.original.goal_id === selectedGoalId && "bg-slate-100 dark:bg-zinc-900",
              )}
              key={row.id}
              onClick={() => onSelectGoal(row.original.goal_id)}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function formatNullable(value: unknown, fallback = "无") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function artifactVariant(value?: boolean) {
  return value ? "success" : "neutral";
}

function rewardVariant(value?: string | null): "success" | "danger" | "warning" | "info" {
  if (value === "positive") {
    return "success";
  }
  if (value === "negative") {
    return "danger";
  }
  if (value === "mixed") {
    return "warning";
  }
  return "info";
}

type BadgeVariant = "neutral" | "success" | "warning" | "info" | "danger";

type OperatorActionBridgeItem = {
  label: string;
  body: string;
  command?: string;
  variant?: BadgeVariant;
};

type OperatorActionBridge = {
  title: string;
  badge: string;
  variant: BadgeVariant;
  body: string;
  items: OperatorActionBridgeItem[];
};

type OperatorDecision = {
  title: string;
  badge: string;
  variant: BadgeVariant;
  action: string;
  reason: string;
  needs: string[];
  phase: string;
  waitingOn: string;
};

type RewardDraftDefaults = {
  decision: string;
  reward: RewardValue;
  reasonSummary: string;
  followUp: string;
  label: string;
};

type UserActionKind = "reward" | "controller" | "codex" | "evidence" | "health";
type UserActionFilter = "all" | UserActionKind;

type UserActionSummaryItem = {
  goalId: string;
  kind: UserActionKind;
  title: string;
  badge: string;
  variant: BadgeVariant;
  summary: string;
  detail: string;
  operatorQuestion?: string;
  agentCommand?: string;
  safePathLabel: string;
  safePathCommand?: string;
  rewardHint: string;
  authorityCoverage?: AuthorityCoverage;
  quota?: ComputeQuota | null;
  userTodos?: TodoGroup | null;
  agentTodos?: TodoGroup | null;
  latestValidation?: ProjectAssetLatestValidation | null;
  projectOwner?: string | null;
  projectGate?: string | null;
  projectNextAction?: string | null;
  projectStopCondition?: string | null;
  projectAssetSource: ProjectAssetSource;
  handoffReadiness?: ProjectAssetHandoffReadiness | null;
  phase: string;
  waitingOn: string;
  draftLabel?: string;
  priority: number;
};

const userActionKindOrder: UserActionKind[] = ["reward", "controller", "codex", "evidence", "health"];
const userActionKindConfig: Record<UserActionKind, { label: string; variant: BadgeVariant }> = {
  reward: { label: "人工评价", variant: "warning" },
  controller: { label: "控制者", variant: "warning" },
  codex: { label: "Codex", variant: "success" },
  evidence: { label: "证据", variant: "info" },
  health: { label: "健康状态", variant: "danger" },
};

function firstOpenTodo(todos?: TodoGroup | null) {
  return todos?.items.find((item) => !item.done);
}

function todosFromProjectAssetSummary(
  summary?: ProjectAssetTodoSummary | null,
  fallback?: TodoGroup | null,
  sourceSection = "project_asset",
): TodoGroup | null {
  if (!summary) {
    return fallback ?? null;
  }
  const next = summary.next?.trim();
  const fallbackFirstOpen = firstOpenTodo(fallback);
  const summaryItems = (summary.items ?? []).filter((item) => !item.done && item.text?.trim());
  return {
    source_section: summary.source_section ?? fallback?.source_section ?? sourceSection,
    total_count: summary.total ?? fallback?.total_count ?? 0,
    open_count: summary.open ?? fallback?.open_count ?? 0,
    done_count: summary.done ?? fallback?.done_count ?? 0,
    items: fallback?.items?.length
      ? fallback.items
      : summaryItems.length
        ? summaryItems
      : (next
          ? [{
              index: summary.next_index ?? fallbackFirstOpen?.index ?? 1,
              done: false,
              text: next,
              review_materials: fallbackFirstOpen?.review_materials ?? [],
            }]
          : []),
  };
}

function todoCountLabel(todos?: TodoGroup | null) {
  if (!todos || todos.total_count === 0) {
    return null;
  }
  return `${todos.open_count}/${todos.total_count} 未完成`;
}

type HandoffReadinessView = {
  ready: boolean;
  shortLine: string;
  stateLine: string;
  latestRunLine?: string | null;
  recentRunLine?: string | null;
  failedLabel: string;
  probe?: string | null;
  variant: BadgeVariant;
};

function buildHandoffReadinessView(readiness?: ProjectAssetHandoffReadiness | null): HandoffReadinessView | null {
  if (!readiness) {
    return null;
  }
  const checks = readiness.checks ?? {};
  const failed = Object.entries(checks)
    .filter(([, value]) => value === false)
    .map(([key]) => key);
  const failedLabel = failed.length ? failed.join(", ") : "无";
  const ready = Boolean(readiness.ready);
  const postRunSeen = Boolean(readiness.post_handoff_run_seen);
  const handoffStatus = readiness.handoff_status ?? (ready ? "ready_waiting_for_run" : "not_ready");
  const latestRun = readiness.post_handoff_latest_run;
  const recentScales = (readiness.post_handoff_recent_runs ?? [])
    .map((run) => run.delivery_batch_scale)
    .filter((scale): scale is string => Boolean(scale));
  return {
    ready,
    shortLine: [
      ready ? "已就绪" : "未就绪",
      `Codex 就绪=${Boolean(readiness.codex_ready)}`,
      `来源=${readiness.source ?? "未知"}`,
      `配额状态=${quotaStateLabel[readiness.quota_state ?? ""] ?? readiness.quota_state ?? "未知"}`,
      `未通过=${failedLabel}`,
    ].join("；"),
    stateLine: [
      `状态=${handoffStatus}`,
      `已看到交接后运行=${postRunSeen}`,
      readiness.handoff_ready_at ? `就绪时间=${readiness.handoff_ready_at}` : null,
    ].filter(Boolean).join("；"),
    latestRunLine: latestRun
      ? [
        latestRun.classification ?? "未知",
        latestRun.generated_at ? `时间=${latestRun.generated_at}` : null,
        latestRun.delivery_batch_scale ? `批次规模=${latestRun.delivery_batch_scale}` : null,
        latestRun.json_exists !== undefined ? `JSON=${Boolean(latestRun.json_exists)}` : null,
        latestRun.markdown_exists !== undefined ? `Markdown=${Boolean(latestRun.markdown_exists)}` : null,
      ].filter(Boolean).join("；")
      : null,
    recentRunLine: recentScales.length
      ? [
        recentScales.join(","),
        `连续小规模运行=${readiness.post_handoff_small_scale_streak ?? 0}`,
      ].join("；")
      : null,
    failedLabel,
    probe: readiness.next_probe,
    variant: postRunSeen ? "info" : ready ? "success" : "warning",
  };
}

function HandoffReadinessPanel({
  goalId,
  readiness,
  testId = "handoff-readiness-panel",
}: {
  goalId?: string;
  readiness?: ProjectAssetHandoffReadiness | null;
  testId?: string;
}) {
  const view = buildHandoffReadinessView(readiness);
  if (!view) {
    return null;
  }
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border p-3 text-xs leading-5",
        view.ready
          ? "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"
          : "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100",
      )}
      data-goal-id={goalId}
      data-testid={testId}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={view.variant}>{view.ready ? "交接已就绪" : "交接受阻"}</Badge>
        <span className="break-words font-medium">{view.shortLine}</span>
      </div>
      <p className="mt-2 break-words">
        <span className="font-medium">未通过检查：</span> {view.failedLabel}
      </p>
      <p className="mt-1 break-words">
        <span className="font-medium">交接状态：</span> {view.stateLine}
      </p>
      {view.latestRunLine ? (
        <p className="mt-1 break-words">
          <span className="font-medium">交接后运行：</span> {view.latestRunLine}
        </p>
      ) : null}
      {view.recentRunLine ? (
        <p className="mt-1 break-words">
          <span className="font-medium">近期规模：</span> {view.recentRunLine}
        </p>
      ) : null}
      {view.probe ? (
        <p className="mt-1 break-words">
          <span className="font-medium">检查入口：</span> {view.probe}
        </p>
      ) : null}
    </div>
  );
}

function todoFocusPriority({
  role,
  severity,
  waitingOn,
  phase,
}: {
  role: TodoFocusItem["role"];
  severity: string;
  waitingOn: string;
  phase: string;
}) {
  const severityRank: Record<string, number> = {
    high: 0,
    action: 1,
    watch: 2,
    clear: 3,
  };
  const waitingRank: Record<string, number> = role === "user"
    ? {
        user_or_controller: 0,
        controller: 1,
        external_evidence: 2,
        codex: 3,
        clear: 4,
      }
    : {
        codex: 0,
        user_or_controller: 1,
        controller: 2,
        external_evidence: 3,
        clear: 4,
      };
  const phaseRank = phase === "controller_gated" || phase === "operator_gated"
    ? 0
    : phase === "mapped" || phase === "refreshed"
      ? 1
      : 2;
  return ((severityRank[severity] ?? 4) * 100) + ((waitingRank[waitingOn] ?? 5) * 10) + phaseRank;
}

function buildTodoFocusItems(rows: GoalDirectoryRow[]): TodoFocusItem[] {
  const items: TodoFocusItem[] = [];

  for (const row of rows) {
    const projectAsset = row.queueItem?.project_asset;
    const userTodos = todosFromProjectAssetSummary(projectAsset?.user_todos, row.queueItem?.user_todos, "project_asset.user_todos");
    const agentTodos = todosFromProjectAssetSummary(projectAsset?.agent_todos, row.queueItem?.agent_todos, "project_asset.agent_todos");
    for (const [role, todos] of [
      ["user", userTodos],
      ["agent", agentTodos],
    ] as const) {
      const todo = firstOpenTodo(todos);
      if (!todo) {
        continue;
      }
      items.push({
        goalId: row.goal.id,
        role,
        text: todo.text,
        openCount: todos?.open_count ?? 1,
        totalCount: todos?.total_count ?? 1,
        severity: row.severity,
        waitingOn: row.waitingOn,
        phase: row.lifecyclePhase,
        priority: todoFocusPriority({
          role,
          severity: row.severity,
          waitingOn: row.waitingOn,
          phase: row.lifecyclePhase,
        }),
      });
    }
  }

  return items.sort((a, b) => a.priority - b.priority || a.goalId.localeCompare(b.goalId));
}

function todoDisplayTitle(todo: TodoItem) {
  return todo.title?.trim() || todo.text;
}

function todoDisplayStatus(todo: TodoItem) {
  return todo.status?.trim() || (todo.done ? "done" : "open");
}

function todoDisplayStatusLabel(todo: TodoItem) {
  const status = todoDisplayStatus(todo);
  return {
    blocked: "已阻塞",
    deferred: "已推迟",
    done: "已完成",
    open: "未完成",
  }[status] ?? status;
}

function todoExplorerStatusVariant(item: TodoExplorerItem): BadgeVariant {
  const todo = item.todo;
  const status = todoDisplayStatus(todo);
  if (status === "done") {
    return "success";
  }
  if (status === "blocked") {
    return "danger";
  }
  if (status === "deferred") {
    return "neutral";
  }
  return item.role === "user" ? "warning" : "info";
}

function todoRoleLabel(role: TodoExplorerRole) {
  return role === "user" ? "用户" : "Agent";
}

function collectTodoExplorerItems(rows: GoalDirectoryRow[], todoIndex?: TodoIndexSummary | null): TodoExplorerItem[] {
  const items: TodoExplorerItem[] = [];
  const seenKeys = new Set<string>();

  for (const row of rows) {
    const projectAsset = row.queueItem?.project_asset;
    const groups: Array<[TodoExplorerRole, TodoGroup | null]> = [
      ["user", todosFromProjectAssetSummary(projectAsset?.user_todos, row.queueItem?.user_todos, "project_asset.user_todos")],
      ["agent", todosFromProjectAssetSummary(projectAsset?.agent_todos, row.queueItem?.agent_todos, "project_asset.agent_todos")],
    ];
    for (const [role, group] of groups) {
      for (const [sourceOrder, todo] of (group?.items ?? []).entries()) {
        const key = todoExplorerIdentityKey(row.goal.id, role, todo);
        if (seenKeys.has(key)) {
          continue;
        }
        items.push({
          goalId: row.goal.id,
          role,
          todo,
          sourceSection: todo.source_section ?? group?.source_section ?? `${role}_todos`,
          source: "attention_queue",
          openCount: group?.open_count ?? 0,
          totalCount: group?.total_count ?? 0,
          severity: row.severity,
          waitingOn: row.waitingOn,
          phase: row.lifecyclePhase,
          sourceOrder,
        });
        seenKeys.add(key);
      }
    }
  }

  const rowByGoal = new Map(rows.map((row) => [row.goal.id, row]));
  for (const [sourceOrder, todo] of (todoIndex?.items ?? []).entries()) {
    const goalId = todo.goal_id;
    const rawRole = todo.role === "user" || todo.role === "agent" ? todo.role : "agent";
    const key = todoExplorerIdentityKey(goalId, rawRole, todo);
    if (seenKeys.has(key)) {
      continue;
    }
    const row = rowByGoal.get(goalId);
    items.push({
      goalId,
      role: rawRole,
      todo,
      sourceSection: todo.source_section ?? todo.source ?? "todo_index",
      source: todo.source ?? "todo_index",
      openCount: 0,
      totalCount: 0,
      severity: row?.severity ?? "watch",
      waitingOn: row?.waitingOn ?? "codex",
      phase: row?.lifecyclePhase ?? "indexed",
      sourceOrder: sourceOrder + 10_000,
    });
    seenKeys.add(key);
  }

  return items.sort((left, right) => {
    const leftDone = left.todo.done ? 1 : 0;
    const rightDone = right.todo.done ? 1 : 0;
    return leftDone - rightDone
      || left.goalId.localeCompare(right.goalId)
      || left.role.localeCompare(right.role)
      || left.todo.index - right.todo.index
      || left.sourceOrder - right.sourceOrder;
  });
}

function compactUnique(values: Array<string | null | undefined>, limit = 4) {
  return Array.from(new Set(values.map((value) => value?.trim()).filter(Boolean) as string[])).slice(0, limit);
}

function agentIdForTodo(item: TodoExplorerItem) {
  const indexedAgent = (item.todo as { agent_id?: string | null }).agent_id?.trim();
  return item.todo.claimed_by?.trim() || indexedAgent || "unassigned-agent-lane";
}

function todoActivityTimestamp(todo: TodoItem) {
  return todo.updated_at || (todo as { latest_event_at?: string | null }).latest_event_at || null;
}

function timestampValue(value?: string | null) {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatAgentActivity(value?: string | null) {
  if (!value) {
    return "没有活动时间";
  }
  return value.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC");
}

function agentManagementStatus(openTodos: TodoExplorerItem[], claimedTodos: TodoExplorerItem[]): AgentManagementStatus {
  if (openTodos.some((item) => todoDisplayStatus(item.todo) === "blocked")) {
    return { label: "已阻塞", variant: "danger" };
  }
  if (openTodos.some((item) => item.todo.task_class === "continuous_monitor" || item.todo.action_kind?.includes("monitor"))) {
    return { label: "监控中", variant: "info" };
  }
  if (openTodos.length > 0) {
    return { label: "执行中", variant: "success" };
  }
  if (claimedTodos.length > 0) {
    return { label: "空闲", variant: "neutral" };
  }
  return { label: "等待中", variant: "warning" };
}

function agentManagementProjectionStatus(state?: string | null): AgentManagementStatus {
  const normalized = state?.trim().toLowerCase();
  if (!normalized) {
    return { label: "等待中", variant: "warning" };
  }
  if (normalized.includes("block")) {
    return { label: "已阻塞", variant: "danger" };
  }
  if (normalized.includes("monitor")) {
    return { label: "监控中", variant: "info" };
  }
  if (normalized.includes("active") || normalized.includes("running") || normalized.includes("claimed")) {
    return { label: "执行中", variant: "success" };
  }
  if (normalized.includes("done") || normalized.includes("clear") || normalized.includes("idle")) {
    return { label: normalized.includes("idle") ? "空闲" : "正常", variant: "neutral" };
  }
  return { label: normalized, variant: "neutral" };
}

function evidenceRefsForTodo(item: TodoExplorerItem) {
  const todo = item.todo as TodoItem & {
    latest_event_kind?: string | null;
    latest_event_at?: string | null;
  };
  const eventRef = todo.latest_event_kind
    ? `${todo.latest_event_kind}${todo.latest_event_at ? ` @ ${todo.latest_event_at}` : ""}`
    : null;
  return [
    todo.evidence ? `证据=${todo.evidence}` : null,
    eventRef ? `事件=${eventRef}` : null,
    item.source ? `来源=${item.source}` : null,
    ...todo.review_materials.map((material) => material.label || material.path),
  ];
}

function normalizeHandoffNote(note?: AgentManagementHandoffNote | null): AgentManagementHandoffNote | null {
  if (!note) {
    return null;
  }
  const hasBody = [
    note.summary,
    note.suggested_next_action,
    note.intent,
    note.blocker,
    note.from_agent,
    note.to_agent,
    ...(note.evidence_refs ?? []),
  ].some((value) => value?.trim());
  return hasBody ? note : null;
}

function handoffNoteSummary(note: AgentManagementHandoffNote) {
  return note.summary?.trim()
    || note.suggested_next_action?.trim()
    || note.intent?.trim()
    || "这个 Agent 已有结构化交接信息。";
}

function handoffNoteBadges(note: AgentManagementHandoffNote) {
  const route = note.from_agent || note.to_agent
    ? `${note.from_agent ?? "未知"} -> ${note.to_agent ?? "未知"}`
    : null;
  const intent = note.intent ? `意图=${note.intent.replace(/_/g, " ").slice(0, 36)}` : null;
  const evidenceCount = note.evidence_refs.length > 0
    ? `${note.evidence_refs.length} 条证据引用`
    : null;
  return compactUnique([
    note.schema_version ?? "handoff_note_v0",
    intent,
    note.blocker ? `阻塞=${note.blocker}` : null,
    route,
    evidenceCount,
  ], 4);
}

function normalizeWorkspaceRef(ref?: AgentManagementWorkspaceRef | null): AgentManagementWorkspaceRef | null {
  if (!ref) {
    return null;
  }
  const hasBody = [
    ref.kind,
    ref.label,
    ref.branch,
    ...(ref.write_scope ?? []),
  ].some((value) => value?.trim());
  return hasBody ? ref : null;
}

function workspaceRefSummary(ref: AgentManagementWorkspaceRef) {
  const kind = ref.kind?.trim() || "未知工作区";
  const label = ref.label?.trim() || ref.branch?.trim();
  if (label) {
    return `${kind.replace(/_/g, " ")} · ${label}`;
  }
  return kind.replace(/_/g, " ");
}

function workspaceRefBadges(ref: AgentManagementWorkspaceRef) {
  return compactUnique([
    ref.path_safe ? "路径可显示" : "路径已隐藏",
    ref.branch ? `分支=${ref.branch}` : null,
    ...(ref.write_scope ?? []).slice(0, 3).map((scope) => `范围=${scope}`),
  ], 4);
}

function normalizeStaleClaimHint(hint?: AgentManagementStaleClaimHint | null): AgentManagementStaleClaimHint | null {
  if (!hint) {
    return null;
  }
  const hasBody = [
    hint.state,
    hint.claimed_by,
    hint.last_activity_at,
    hint.reason,
    hint.recommended_operator_action,
  ].some((value) => value?.trim());
  return hasBody ? hint : null;
}

function staleClaimSummary(hint: AgentManagementStaleClaimHint) {
  return hint.reason?.trim()
    || hint.recommended_operator_action?.trim()
    || "手动交接前，需要操作者检查认领状态是否仍然有效。";
}

function staleClaimBadges(hint: AgentManagementStaleClaimHint) {
  return compactUnique([
    hint.state ?? "认领新鲜度",
    hint.claimed_by ? `认领者=${hint.claimed_by}` : null,
    hint.last_activity_at ? `最后活动=${formatAgentActivity(hint.last_activity_at)}` : null,
    hint.threshold_hours ? `>${hint.threshold_hours}h` : null,
  ], 4);
}

const agentAvatarTones = [
  "from-cyan-200 to-teal-300 text-teal-950",
  "from-emerald-200 to-lime-300 text-emerald-950",
  "from-amber-100 to-orange-200 text-amber-950",
  "from-violet-200 to-fuchsia-200 text-violet-950",
  "from-rose-200 to-pink-200 text-rose-950",
];

function agentInitials(agentId: string) {
  const chunks = agentId.split(/[-_\s]+/).filter(Boolean);
  const initials = (chunks.length > 1 ? chunks.slice(0, 2) : [agentId.slice(0, 2)])
    .map((chunk) => chunk[0]?.toUpperCase())
    .join("");
  return initials || "A";
}

function agentAvatarTone(agentId: string) {
  const hash = Array.from(agentId).reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return agentAvatarTones[hash % agentAvatarTones.length];
}

function agentStatusTone(variant: BadgeVariant) {
  if (variant === "success") {
    return {
      accent: "from-emerald-200 via-teal-300 to-transparent",
      dot: "bg-emerald-200 shadow-[0_0_14px_rgba(167,243,208,0.75)]",
      pill: "border-emerald-200/25 bg-emerald-200/10 text-emerald-100",
    };
  }
  if (variant === "danger") {
    return {
      accent: "from-rose-200 via-orange-200 to-transparent",
      dot: "bg-rose-200 shadow-[0_0_14px_rgba(254,205,211,0.65)]",
      pill: "border-rose-200/25 bg-rose-200/10 text-rose-100",
    };
  }
  if (variant === "warning") {
    return {
      accent: "from-amber-100 via-orange-200 to-transparent",
      dot: "bg-amber-100 shadow-[0_0_14px_rgba(254,243,199,0.65)]",
      pill: "border-amber-100/25 bg-amber-100/10 text-amber-50",
    };
  }
  if (variant === "info") {
    return {
      accent: "from-cyan-100 via-sky-200 to-transparent",
      dot: "bg-cyan-100 shadow-[0_0_14px_rgba(207,250,254,0.65)]",
      pill: "border-cyan-100/25 bg-cyan-100/10 text-cyan-50",
    };
  }
  return {
    accent: "from-stone-200 via-stone-300 to-transparent",
    dot: "bg-stone-200 shadow-[0_0_12px_rgba(231,229,228,0.35)]",
    pill: "border-stone-100/15 bg-stone-100/[0.06] text-stone-100",
  };
}

function buildAgentManagementRows(
  rows: GoalDirectoryRow[],
  todoIndex?: TodoIndexSummary | null,
  projection?: AgentManagementProjection | null,
): AgentManagementRow[] {
  const items = collectTodoExplorerItems(rows, todoIndex).filter((item) => item.role === "agent");
  const rowByGoal = new Map(rows.map((row) => [row.goal.id, row]));
  const grouped = new Map<string, TodoExplorerItem[]>();
  for (const item of items) {
    const agentId = agentIdForTodo(item);
    const bucket = grouped.get(agentId) ?? [];
    bucket.push(item);
    grouped.set(agentId, bucket);
  }
  const projectedByAgent = new Map((projection?.agents ?? []).map((row) => [row.agent_id, row]));
  const agentIds = Array.from(new Set([...grouped.keys(), ...projectedByAgent.keys()]));

  return agentIds.map((agentId) => {
    const claimedTodos = grouped.get(agentId) ?? [];
    const projected = projectedByAgent.get(agentId);
    const goalIds = compactUnique([
      ...claimedTodos.map((item) => item.goalId),
      projected?.current_todo?.goal_id,
      ...(projected?.goal_ids ?? []),
      projection?.goal_id,
    ], 6);
    const openTodos = claimedTodos.filter((item) => !item.todo.done);
    const primaryTodo = openTodos[0] ?? claimedTodos[0];
    const primaryGoalId = primaryTodo?.goalId ?? projected?.current_todo?.goal_id ?? goalIds[0] ?? "";
    const latestActivity = claimedTodos
      .map((item) => todoActivityTimestamp(item.todo))
      .concat([projected?.last_activity_at ?? null])
      .sort((left, right) => timestampValue(right) - timestampValue(left))[0] ?? null;
    const quotaHints = compactUnique(goalIds.map((goalId) => {
      const row = rowByGoal.get(goalId);
      return buildQuotaView(row?.queueItem?.quota ?? row?.goal.quota)?.shortLine;
    }), 3);
    const evidenceRefs = compactUnique([
      ...claimedTodos.flatMap(evidenceRefsForTodo),
      ...(projected?.evidence_refs ?? []),
    ], 5);
    const handoffNote = normalizeHandoffNote(projected?.handoff_note);
    const workspaceRef = normalizeWorkspaceRef(projected?.workspace_ref ?? projected?.current_todo?.workspace_ref);
    const staleClaimHint = normalizeStaleClaimHint(projected?.stale_claim_hint);
    return {
      agentId,
      claimedTodos,
      evidenceRefs,
      goalIds,
      handoffNote,
      lastActivity: latestActivity,
      nextSafeAction: projected?.next_action?.trim()
        || (primaryTodo ? todoDisplayTitle(primaryTodo.todo) : "执行前先检查当前状态投影"),
      primaryGoalId,
      quotaHints,
      staleClaimHint,
      status: projected?.state
        ? agentManagementProjectionStatus(projected.state)
        : agentManagementStatus(openTodos, claimedTodos),
      workspaceRef,
    };
  }).sort((left, right) => {
    const leftOpen = left.claimedTodos.some((item) => !item.todo.done) ? 0 : 1;
    const rightOpen = right.claimedTodos.some((item) => !item.todo.done) ? 0 : 1;
    return leftOpen - rightOpen
      || timestampValue(right.lastActivity) - timestampValue(left.lastActivity)
      || left.agentId.localeCompare(right.agentId);
  });
}

function todoExplorerHaystack(item: TodoExplorerItem) {
  const todo = item.todo;
  return [
    item.goalId,
    item.role,
    item.sourceSection,
    item.severity,
    item.waitingOn,
    item.phase,
    todo.todo_id,
    todo.priority,
    todo.status,
    todo.title,
    todo.text,
    todo.task_class,
    todo.action_kind,
    todo.claimed_by,
    todo.archive_state,
    todo.note,
    todo.evidence,
    item.source,
    (todo as { latest_event_kind?: string | null }).latest_event_kind,
    (todo as { latest_event_at?: string | null }).latest_event_at,
    (todo as { agent_id?: string | null }).agent_id,
    String(todo.index),
    ...(todo.required_capabilities ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function todoExplorerProjectOptions(items: TodoExplorerItem[]) {
  return Array.from(new Set(items.map((item) => item.goalId)))
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function ProjectTodoExplorer({
  onProjectChange,
  onQueryChange,
  onRoleChange,
  onSelectGoal,
  onStatusChange,
  query,
  role,
  rows,
  selectedTodoGoalId,
  selectedGoalId,
  status,
  todoIndex,
}: {
  onProjectChange: (goalId: string) => void;
  onQueryChange: (query: string) => void;
  onRoleChange: (role: "all" | TodoExplorerRole) => void;
  onSelectGoal: (goalId: string) => void;
  onStatusChange: (status: "all" | "open" | "done" | "blocked" | "deferred") => void;
  query: string;
  role: "all" | TodoExplorerRole;
  rows: GoalDirectoryRow[];
  selectedTodoGoalId: string;
  selectedGoalId: string;
  status: "all" | "open" | "done" | "blocked" | "deferred";
  todoIndex?: TodoIndexSummary | null;
}) {
  const allItems = useMemo(() => collectTodoExplorerItems(rows, todoIndex), [rows, todoIndex]);
  const projectOptions = useMemo(() => todoExplorerProjectOptions(allItems), [allItems]);
  const selectedProject = selectedTodoGoalId === "all" || projectOptions.includes(selectedTodoGoalId)
    ? selectedTodoGoalId
    : "all";
  const normalizedQuery = query.trim().toLowerCase();
  const filteredItems = allItems.filter((item) => {
    const projectMatches = selectedProject === "all" || item.goalId === selectedProject;
    const roleMatches = role === "all" || item.role === role;
    const itemStatus = todoDisplayStatus(item.todo);
    const statusMatches = status === "all" || itemStatus === status;
    const queryMatches = !normalizedQuery || todoExplorerHaystack(item).includes(normalizedQuery);
    return projectMatches && roleMatches && statusMatches && queryMatches;
  });
  const openCount = allItems.filter((item) => !item.todo.done).length;
  const agentCount = allItems.filter((item) => item.role === "agent").length;
  const visibleItems = filteredItems.slice(0, 80);

  return (
    <Card data-testid="project-todo-explorer">
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-4 w-4" />
            项目 Todo 浏览器
          </CardTitle>
          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            按项目、ID、文字、负责人、动作类型或认领 Agent 搜索当前 Todo。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="info">显示 {filteredItems.length}/{allItems.length}</Badge>
          <Badge variant="neutral">{projectOptions.length} 个项目</Badge>
          <Badge variant={openCount > 0 ? "warning" : "success"}>{openCount} 个未完成</Badge>
          <Badge variant="neutral">{agentCount} 个 Agent Todo</Badge>
          {todoIndex ? <Badge variant="neutral">{todoIndex.rollout_event_count} 个事件</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(180px,260px)_148px_148px]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-400 dark:text-zinc-500" />
            <input
              aria-label="搜索项目 Todo"
              className={cn(inputClassName, "pl-9")}
              data-testid="project-todo-search-input"
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="输入 Todo ID、关键词、负责人或动作类型"
              value={query}
            />
          </div>
          <Select
            aria-label="Todo 所属项目"
            onChange={(event) => onProjectChange(event.target.value)}
            value={selectedProject}
          >
            <option value="all">全部项目</option>
            {projectOptions.map((goalId) => (
              <option key={goalId} value={goalId}>
                {goalId}
              </option>
            ))}
          </Select>
          <Select
            aria-label="Todo 负责人"
            onChange={(event) => onRoleChange(event.target.value as "all" | TodoExplorerRole)}
            value={role}
          >
            <option value="all">全部负责人</option>
            <option value="user">用户 Todo</option>
            <option value="agent">Agent Todo</option>
          </Select>
          <Select
            aria-label="Todo 状态"
            onChange={(event) => onStatusChange(event.target.value as "all" | "open" | "done" | "blocked" | "deferred")}
            value={status}
          >
            <option value="all">全部状态</option>
            <option value="open">未完成</option>
            <option value="blocked">已阻塞</option>
            <option value="deferred">已推迟</option>
            <option value="done">已完成</option>
          </Select>
        </div>

        {visibleItems.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-zinc-700 dark:text-zinc-400">
            没有 Todo 匹配{query ? <span className="font-mono">“{query}”</span> : "当前筛选条件"}。
          </div>
        ) : (
          <div className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 dark:divide-zinc-800 dark:border-zinc-800">
            {visibleItems.map((item) => {
              const todo = item.todo;
              const statusLabel = todoDisplayStatusLabel(todo);
              const todoEventFields = todo as unknown as { latest_event_kind?: unknown };
              const latestEventKind = typeof todoEventFields.latest_event_kind === "string"
                ? todoEventFields.latest_event_kind
                : "";
              return (
                <button
                  className={cn(
                    "w-full bg-white px-4 py-3 text-left transition hover:bg-slate-50 dark:bg-zinc-950 dark:hover:bg-zinc-900",
                    item.goalId === selectedGoalId && "bg-slate-50 dark:bg-zinc-900",
                  )}
                  data-testid="project-todo-result"
                  key={`${item.goalId}-${item.role}-${todo.todo_id ?? todo.index}-${item.sourceOrder}`}
                  onClick={() => onSelectGoal(item.goalId)}
                  type="button"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={item.role === "user" ? "warning" : "info"}>{todoRoleLabel(item.role)}</Badge>
                    <Badge variant={todoExplorerStatusVariant(item)}>{statusLabel}</Badge>
                    {todo.priority ? <Badge variant={todo.priority === "P0" ? "danger" : "neutral"}>{todo.priority}</Badge> : null}
                    <span className="break-all text-xs font-medium text-slate-500 dark:text-zinc-400">{item.goalId}</span>
                    {todo.todo_id ? (
                      <span
                        className="break-all rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700 dark:bg-zinc-900 dark:text-zinc-300"
                        data-testid="project-todo-id"
                      >
                        {todo.todo_id}
                      </span>
                    ) : (
                      <span className="text-xs text-slate-400 dark:text-zinc-500">#{todo.index}</span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-800 dark:text-zinc-200">
                    {todoDisplayTitle(todo)}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-zinc-400">
                    <span>{item.sourceSection}</span>
                    {item.source ? <span>source={item.source}</span> : null}
                    {todo.action_kind ? <span>action={todo.action_kind}</span> : null}
                    {todo.task_class ? <span>class={todo.task_class}</span> : null}
                    {todo.claimed_by ? <span>claimed_by={todo.claimed_by}</span> : null}
                    {latestEventKind ? <span>event={latestEventKind}</span> : null}
                    {todo.updated_at ? <span>updated={todo.updated_at}</span> : null}
                  </div>
                  {todo.note ? (
                    <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">{todo.note}</p>
                  ) : null}
                </button>
              );
            })}
          </div>
        )}

        {filteredItems.length > visibleItems.length ? (
          <p className="text-xs text-slate-500 dark:text-zinc-400">
            当前只显示前 {visibleItems.length} 条结果，请缩小搜索范围查看其余内容。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TodoFocusColumn({
  icon: Icon,
  items,
  onSelectGoal,
  selectedGoalId,
  title,
  variant,
}: {
  icon: React.ComponentType<{ className?: string }>;
  items: TodoFocusItem[];
  onSelectGoal: (goalId: string) => void;
  selectedGoalId: string;
  title: string;
  variant: BadgeVariant;
}) {
  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex min-h-12 items-center justify-between gap-3 border-b border-slate-200 px-3 py-2 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <Icon className="h-4 w-4 text-slate-600 dark:text-zinc-300" />
          <h3 className="text-sm font-semibold text-slate-950 dark:text-zinc-50">{title}</h3>
        </div>
        <Badge variant={items.length > 0 ? variant : "success"}>{items.length}</Badge>
      </div>
      {items.length === 0 ? (
        <div className="p-3 text-sm text-slate-500 dark:text-zinc-400">没有未完成的 Todo。</div>
      ) : (
        <div className="divide-y divide-slate-200 dark:divide-zinc-800">
          {items.slice(0, 5).map((item) => (
            <button
              className={cn(
                "grid w-full gap-2 px-3 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-zinc-900",
                item.goalId === selectedGoalId && "bg-slate-100 dark:bg-zinc-900",
              )}
              key={`${item.role}-${item.goalId}-${item.text}`}
              onClick={() => onSelectGoal(item.goalId)}
              type="button"
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Badge variant="neutral">Goal</Badge>
                <span className="break-all text-sm font-semibold text-slate-950 dark:text-zinc-50">{item.goalId}</span>
              </div>
              <p className="line-clamp-2 break-words text-sm leading-6 text-slate-700 dark:text-zinc-300">{item.text}</p>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-zinc-400">
                <Badge variant={severityVariant[item.severity] ?? "neutral"}>{severityLabel[item.severity] ?? item.severity}</Badge>
                <Badge variant="neutral">{waitingLabel[item.waitingOn] ?? item.waitingOn}</Badge>
                <Badge variant="info">{item.openCount}/{item.totalCount} 未完成</Badge>
                <PhaseBadges compact phase={item.phase} />
              </div>
            </button>
          ))}
          {items.length > 5 ? (
            <div className="px-3 py-2 text-xs font-medium text-slate-500 dark:text-zinc-400">
              另有 {items.length - 5} 项
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function AgentManagementPanel({
  agentManagementProjection,
  onSelectGoal,
  rows,
  selectedGoalId,
  todoIndex,
}: {
  agentManagementProjection?: AgentManagementProjection | null;
  onSelectGoal: (goalId: string) => void;
  rows: GoalDirectoryRow[];
  selectedGoalId: string;
  todoIndex?: TodoIndexSummary | null;
}) {
  const [copiedAgentId, setCopiedAgentId] = useState<string | null>(null);
  const agentRows = useMemo(
    () => buildAgentManagementRows(rows, todoIndex, agentManagementProjection),
    [agentManagementProjection, rows, todoIndex],
  );
  const claimedTodoCount = agentRows.reduce((sum, row) => sum + row.claimedTodos.length, 0);

  async function copyReadOnlyCommand(row: AgentManagementRow) {
    const goalArg = row.primaryGoalId ? ` --goal-id ${shellQuote(row.primaryGoalId)}` : "";
    const command = `loopx --format json status${goalArg} --agent-id ${shellQuote(row.agentId)}`;
    const copied = await copyTextToClipboard(command);
    setCopiedAgentId(copied ? row.agentId : null);
  }

  return (
    <section
      className="overflow-hidden rounded-2xl border border-emerald-100/15 bg-[#061f1d] text-[#f5ead7] shadow-[0_24px_80px_rgba(2,6,23,0.34)]"
      data-testid="agent-management-panel"
    >
      <div className="border-b border-emerald-100/15 bg-[linear-gradient(180deg,rgba(10,48,43,0.94),rgba(4,24,22,0.98))] p-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 font-mono text-[11px] font-semibold uppercase tracking-[0.22em] text-emerald-100/60">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-100 shadow-[0_0_12px_rgba(209,250,229,0.8)]" />
              实时控制面
            </div>
            <h2 className="mt-2 flex items-center gap-2 text-sm font-semibold text-[#fff7e8]">
              <Users className="h-4 w-4 text-emerald-100" />
              Agent 管理
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-emerald-50/58">
              只读展示 Agent 工作线、交接信息、证据引用和配额提示。
            </p>
          </div>
          <div className="grid min-w-[min(100%,24rem)] grid-cols-3 gap-2">
            <div className="rounded-xl border border-emerald-100/15 bg-emerald-100/[0.04] px-3 py-2">
              <div className="font-mono text-[10px] font-semibold tracking-normal text-emerald-100/45">Agent</div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-[#fff7e8]">{agentRows.length}</div>
            </div>
            <div className="rounded-xl border border-[#e8c48e]/25 bg-[#e8c48e]/[0.08] px-3 py-2">
              <div className="font-mono text-[10px] font-semibold tracking-normal text-[#f4d8ad]/70">已认领</div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-[#ffe8bd]">{claimedTodoCount}</div>
            </div>
            <div className="rounded-xl border border-cyan-100/20 bg-cyan-100/[0.06] px-3 py-2">
              <div className="font-mono text-[10px] font-semibold tracking-normal text-cyan-100/70">事件</div>
              <div className="mt-1 text-lg font-semibold tabular-nums text-cyan-50">
                {todoIndex ? todoIndex.rollout_event_count : "-"}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="bg-[radial-gradient(circle_at_70%_-10%,rgba(20,184,166,0.12),transparent_34%),linear-gradient(180deg,rgba(6,39,35,0.94),rgba(3,18,17,1))] p-3 sm:p-4">
        {agentRows.length === 0 ? (
          <div className="rounded-xl border border-dashed border-emerald-100/20 bg-emerald-100/[0.035] p-4 text-sm text-emerald-50/60">
            目前没有 Agent 认领记录。给 Agent Todo 补充 `claimed_by` 或 `agent_id` 后会显示在这里。
          </div>
        ) : (
          <div className="grid items-start gap-3 xl:grid-cols-2 2xl:grid-cols-3">
            {agentRows.map((row) => {
              const openCount = row.claimedTodos.filter((item) => !item.todo.done).length;
              const statusTone = agentStatusTone(row.status.variant);
              return (
                <div
                  className={cn(
                    "group relative overflow-hidden rounded-xl border border-emerald-100/14 bg-[#062420]/82 p-3 shadow-[inset_0_1px_0_rgba(255,246,225,0.06)] transition hover:border-emerald-100/30 hover:bg-[#082c27]",
                    row.goalIds.includes(selectedGoalId) && "border-[#f3d7aa]/50 bg-[#0a302a] shadow-[0_0_0_1px_rgba(243,215,170,0.12)]",
                  )}
                  data-testid="agent-management-row"
                  key={row.agentId}
                >
                  <div className={cn("absolute inset-x-0 top-0 h-px bg-gradient-to-r", statusTone.accent)} />
                  <div className="flex items-start justify-between gap-3">
                    <button
                      className="flex min-w-0 flex-1 gap-3 text-left"
                      onClick={() => row.primaryGoalId && onSelectGoal(row.primaryGoalId)}
                      type="button"
                    >
                      <span className={cn(
                        "grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-gradient-to-br text-[11px] font-black shadow-[inset_0_1px_0_rgba(255,255,255,0.35)]",
                        agentAvatarTone(row.agentId),
                      )}>
                        {agentInitials(row.agentId)}
                      </span>
                      <div className="min-w-0">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className={cn(
                            "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold",
                            statusTone.pill,
                          )}>
                            <span className={cn("h-1.5 w-1.5 rounded-full", statusTone.dot)} />
                            {row.status.label}
                          </span>
                          <span className="break-all text-sm font-semibold text-[#fff7e8]">{row.agentId}</span>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {row.goalIds.map((goalId) => (
                            <span
                              className={cn(
                                "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                                goalId === selectedGoalId
                                  ? "border-[#f3d7aa]/40 bg-[#f3d7aa]/10 text-[#ffe6bd]"
                                  : "border-emerald-100/12 bg-emerald-100/[0.04] text-emerald-50/70",
                              )}
                              key={goalId}
                            >
                              {goalId}
                            </span>
                          ))}
                        </div>
                      </div>
                    </button>
                    <Button
                      aria-label={`复制 ${row.agentId} 的只读命令`}
                      className="h-8 shrink-0 border border-emerald-100/15 bg-emerald-100/[0.04] px-2 text-xs text-emerald-50/70 hover:bg-emerald-100/10 hover:text-[#fff7e8]"
                      data-testid="agent-management-copy-command"
                      onClick={() => void copyReadOnlyCommand(row)}
                      size="sm"
                      variant="ghost"
                    >
                      <Copy className="h-4 w-4" />
                      {copiedAgentId === row.agentId ? "已复制" : "复制"}
                    </Button>
                  </div>

                  <div className="mt-4 grid gap-3 text-sm">
                    <div className="grid grid-cols-2 gap-2">
                      <div className="rounded-lg border border-emerald-100/12 bg-emerald-100/[0.035] p-2">
                        <div className="font-mono text-[10px] font-semibold tracking-normal text-emerald-50/40">已认领 Todo</div>
                        <div className="mt-1 text-sm font-semibold tabular-nums text-[#fff7e8]">{openCount}/{row.claimedTodos.length} 未完成</div>
                      </div>
                      <div className="rounded-lg border border-emerald-100/12 bg-emerald-100/[0.035] p-2">
                        <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.17em] text-emerald-50/40">
                          <Clock3 className="h-3 w-3" />
                          最近活动
                        </div>
                        <div className="mt-1 line-clamp-1 break-words text-sm font-medium text-emerald-50/80">
                          {formatAgentActivity(row.lastActivity)}
                        </div>
                      </div>
                    </div>
                    <div className="rounded-lg border border-emerald-100/12 bg-black/18 p-3">
                      <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-emerald-50/40">
                        <Terminal className="h-3.5 w-3.5" />
                        下一步安全动作
                      </div>
                      <p className="mt-2 line-clamp-2 break-words leading-6 text-emerald-50/85">{row.nextSafeAction}</p>
                    </div>
                    {row.workspaceRef ? (
                      <div
                        className="rounded-xl border border-teal-100/[0.18] bg-teal-100/[0.055] p-3 shadow-[inset_0_1px_0_rgba(255,246,225,0.05)]"
                        data-testid="agent-management-workspace-ref"
                      >
                        <div className="flex gap-3">
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-teal-100/20 bg-teal-100/10 text-teal-50">
                            <GitBranch className="h-4 w-4" />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-50/[0.78]">
                              工作区提示
                              <span className="rounded-full border border-teal-100/20 px-1.5 py-0.5 text-[9px] tracking-normal text-teal-50/[0.62]">
                                只读
                              </span>
                            </div>
                            <p className="mt-1 line-clamp-2 break-words text-sm leading-6 text-teal-50/[0.88]">
                              {workspaceRefSummary(row.workspaceRef)}
                            </p>
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {workspaceRefBadges(row.workspaceRef).map((badge) => (
                            <span
                              className="rounded-full border border-teal-100/[0.15] bg-black/20 px-2 py-0.5 text-[11px] font-medium text-teal-50/[0.72]"
                              key={badge}
                            >
                              {badge}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {row.staleClaimHint ? (
                      <div
                        className="rounded-xl border border-[#f3d7aa]/[0.28] bg-[#f3d7aa]/[0.09] p-3 shadow-[inset_0_1px_0_rgba(255,246,225,0.06)]"
                        data-testid="agent-management-stale-claim-hint"
                      >
                        <div className="flex gap-3">
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-[#f3d7aa]/[0.25] bg-[#f3d7aa]/[0.12] text-[#ffe6bd]">
                            <CircleAlert className="h-4 w-4" />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-[#ffe6bd]/[0.78]">
                              认领状态可能过期
                              <span className="rounded-full border border-[#f3d7aa]/[0.25] px-1.5 py-0.5 text-[9px] tracking-normal text-[#ffe6bd]/[0.68]">
                                仅提醒
                              </span>
                            </div>
                            <p className="mt-1 line-clamp-2 break-words text-sm leading-6 text-[#ffe6bd]/90">
                              {staleClaimSummary(row.staleClaimHint)}
                            </p>
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {staleClaimBadges(row.staleClaimHint).map((badge) => (
                            <span
                              className="rounded-full border border-[#f3d7aa]/20 bg-black/20 px-2 py-0.5 text-[11px] font-medium text-[#ffe6bd]/[0.78]"
                              key={badge}
                            >
                              {badge}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {row.handoffNote ? (
                      <div
                        className="rounded-xl border border-cyan-100/20 bg-cyan-100/[0.07] p-3 shadow-[inset_0_1px_0_rgba(255,246,225,0.06)]"
                        data-testid="agent-management-handoff-note"
                      >
                        <div className="flex gap-3">
                          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-cyan-100/20 bg-cyan-100/10 text-cyan-50">
                            <FileText className="h-4 w-4" />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2 font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-cyan-50/80">
                              交接信息
                              <span className="rounded-full border border-cyan-100/20 px-1.5 py-0.5 text-[9px] tracking-normal text-cyan-50/65">
                                只读
                              </span>
                            </div>
                            <p className="mt-1 line-clamp-2 break-words text-sm leading-6 text-cyan-50/90">
                              {handoffNoteSummary(row.handoffNote)}
                            </p>
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {handoffNoteBadges(row.handoffNote).map((badge) => (
                            <span
                              className="rounded-full border border-cyan-100/15 bg-black/20 px-2 py-0.5 text-[11px] font-medium text-cyan-50/75"
                              key={badge}
                            >
                              {badge}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div>
                      <div className="font-mono text-[10px] font-semibold tracking-normal text-emerald-50/40">证据引用</div>
                      <div className="mt-1 grid min-w-0 gap-1.5">
                        {(row.evidenceRefs.length > 0 ? row.evidenceRefs : ["状态投影"]).map((ref) => (
                          <span
                            className="block min-w-0 overflow-hidden text-ellipsis whitespace-nowrap rounded-full border border-emerald-100/12 bg-emerald-100/[0.04] px-2 py-0.5 text-[11px] font-medium text-emerald-50/70"
                            key={ref}
                            title={ref}
                          >
                            {ref}
                          </span>
                        ))}
                      </div>
                    </div>
                    {row.quotaHints.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {row.quotaHints.map((hint) => (
                          <span
                            className="rounded-full border border-[#f3d7aa]/20 bg-[#f3d7aa]/[0.08] px-2 py-0.5 text-[11px] font-medium text-[#ffe6bd]/80"
                            key={hint}
                          >
                            {hint}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function TodoFocusPanel({
  rows,
  selectedGoalId,
  onSelectGoal,
}: {
  rows: GoalDirectoryRow[];
  selectedGoalId: string;
  onSelectGoal: (goalId: string) => void;
}) {
  const items = useMemo(() => buildTodoFocusItems(rows), [rows]);
  const userItems = items.filter((item) => item.role === "user");
  const agentItems = items.filter((item) => item.role === "agent");

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4" />
          Todo 重点
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant={userItems.length > 0 ? "warning" : "success"}>{userItems.length} 个用户 Todo</Badge>
          <Badge variant={agentItems.length > 0 ? "info" : "success"}>{agentItems.length} 个 Agent Todo</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 lg:grid-cols-2">
          <TodoFocusColumn
            icon={Users}
            items={userItems}
            onSelectGoal={onSelectGoal}
            selectedGoalId={selectedGoalId}
            title="用户 Todo"
            variant="warning"
          />
          <TodoFocusColumn
            icon={Bot}
            items={agentItems}
            onSelectGoal={onSelectGoal}
            selectedGoalId={selectedGoalId}
            title="Agent 优先 Todo"
            variant="info"
          />
        </div>
      </CardContent>
    </Card>
  );
}

function UserTodoCallout({
  blocksGate,
  focusWait,
  goalId,
  source,
  todos,
}: {
  blocksGate?: boolean;
  focusWait?: boolean;
  goalId: string;
  source: DataSource;
  todos?: TodoGroup | null;
}) {
  const todo = firstOpenTodo(todos);
  const count = todoCountLabel(todos);
  const materials = todo?.review_materials ?? [];
  const [activeMaterial, setActiveMaterial] = useState<ReviewMaterial | null>(null);
  const [materialContent, setMaterialContent] = useState<ReviewMaterialContent | null>(null);
  const [materialError, setMaterialError] = useState<string | null>(null);
  const [isReadingMaterial, setIsReadingMaterial] = useState(false);
  if (!todo) {
    return null;
  }

  async function readMaterial(material: ReviewMaterial) {
    const url = buildReviewMaterialUrl(source, goalId, material);
    if (!url) {
      setMaterialError("审阅材料只支持本机实时状态地址。");
      setActiveMaterial(material);
      setMaterialContent(null);
      return;
    }
    setIsReadingMaterial(true);
    setActiveMaterial(material);
    setMaterialError(null);
    setMaterialContent(null);
    try {
      const response = await fetch(url, { cache: "no-store" });
      const payload = await response.json() as ReviewMaterialContent;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      setMaterialContent(payload);
    } catch (error) {
      setMaterialError(formatStatusError(error));
    } finally {
      setIsReadingMaterial(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-2 dark:border-emerald-900/60 dark:bg-emerald-950/30">
      <div className="flex flex-wrap items-center gap-2">
        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700 dark:text-emerald-300" />
        <Badge variant="success">{blocksGate ? "先做用户待办" : focusWait ? "负责人阻塞" : "下一个用户 Todo"}</Badge>
        {count ? <Badge variant="neutral">{count}</Badge> : null}
      </div>
      <p className="mt-2 line-clamp-3 break-words text-sm font-medium leading-6 text-emerald-950 dark:text-emerald-100">
        {todo.text}
      </p>
      {blocksGate ? (
        <p className="mt-1 text-xs font-medium leading-5 text-emerald-800 dark:text-emerald-200">
          完成或明确暂缓这个用户待办后，再审批下面的确认项。
        </p>
      ) : null}
      {focusWait ? (
        <p className="mt-1 text-xs font-medium leading-5 text-emerald-800 dark:text-emerald-200">
          有新的负责人证据、干净基线或外部评估前保持重点等待，不恢复交付。
        </p>
      ) : null}
      {materials.length > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Badge variant="info">审阅材料</Badge>
          {materials.map((material) => {
            const label = material.label || material.path;
            const canRead = Boolean(material.exists && buildReviewMaterialUrl(source, goalId, material));
            return (
              <Button
                disabled={!material.exists || isReadingMaterial}
                key={`${material.path}-${material.anchor ?? ""}`}
                onClick={() => void readMaterial(material)}
                size="sm"
                variant={canRead ? "secondary" : "ghost"}
              >
                <FileText className="h-4 w-4" />
                {label}
              </Button>
            );
          })}
        </div>
      ) : null}
      {activeMaterial || materialError || materialContent ? (
        <div className="mt-3 rounded-md border border-emerald-200 bg-white/70 p-2 dark:border-emerald-900 dark:bg-zinc-950/60">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="break-all text-xs font-semibold text-emerald-950 dark:text-emerald-100">
                {activeMaterial?.label || activeMaterial?.path || "审阅材料"}
              </div>
              {materialContent?.bytes ? (
                <div className="text-[11px] text-emerald-800 dark:text-emerald-200">{materialContent.bytes} 字节</div>
              ) : null}
            </div>
            <Button
              onClick={() => {
                setActiveMaterial(null);
                setMaterialContent(null);
                setMaterialError(null);
              }}
              size="sm"
              variant="ghost"
            >
              关闭
            </Button>
          </div>
          {isReadingMaterial ? (
            <p className="mt-2 text-xs text-emerald-800 dark:text-emerald-200">正在读取审阅材料...</p>
          ) : null}
          {materialError ? <Badge variant="danger">{materialError.slice(0, 120)}</Badge> : null}
          {materialContent?.content ? (
            <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded border border-emerald-100 bg-white p-3 text-xs leading-5 text-slate-800 dark:border-emerald-900 dark:bg-zinc-950 dark:text-zinc-100">
              {materialContent.content}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

type CopyState = "idle" | "copied" | "failed";

type AuthorityCoverage = {
  badge: string;
  reviewLine: string;
  shortLine: string;
  variant: BadgeVariant;
};

type QuotaView = {
  label: string;
  reviewLine: string;
  shortLine: string;
  variant: BadgeVariant;
};

async function copyTextToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // Fall through to the legacy path for local HTTP previews.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    return document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }
}

function humanReviewPrompt(kind?: UserActionKind) {
  if (kind === "reward") {
    return {
      question: "是否把这次判断记录为与本次运行绑定的人工评价？",
      reply: "同意记录 / 暂不同意 + 一句话原因。",
      boundary: "只有去掉 --dry-run 参数才会写入人工评价和当前状态摘要；这不是写入控制、控制者接管或生产动作授权。",
    };
  }
  if (kind === "controller") {
    return {
      question: "是否允许目标项目进入只读控制者接管阶段？",
      reply: "同意先做只读映射预演 / 暂不同意 + 一句话原因。",
      boundary: "这只授权项目 Agent 预览执行路径；不写操作者确认、运行历史、写入控制、实验控制，也不执行生产动作。",
    };
  }
  if (kind === "codex") {
    return {
      question: "是否让项目 Agent 沿安全的本地路径继续？",
      reply: "同意继续 / 暂不同意 + 一句话原因。",
      boundary: "如果下一步需要写入、追加评价、审批或写入控制，项目 Agent 必须先停下等明确授权。",
    };
  }
  if (kind === "evidence") {
    return {
      question: "是否继续等待外部证据，而不升级成决策建议？",
      reply: "继续等待 / 不继续等待 + 一句话原因。",
      boundary: "观察状态不是人工评价、审批或控制者接管许可。",
    };
  }
  if (kind === "health") {
    return {
      question: "是否先修健康阻塞，再讨论人工评价、控制者或 Codex 交接？",
      reply: "先修阻塞 / 暂不处理 + 一句话原因。",
      boundary: "健康修复不等于授权追加评价、审批或写入控制。",
    };
  }
  return {
    question: "当前是否需要转给项目 Agent 继续处理？",
    reply: "继续 / 不继续 / 继续观察 + 一句话原因。",
    boundary: "本回复不自动写入人工评价、审批、控制者接管许可或写入控制。",
  };
}

function controllerReplyLine(goalId: string) {
  return `同意 ${goalId} 先做只读映射预演 / 暂不同意 + 一句话原因。`;
}

function controllerApprovalReason(goalId: string) {
  return `同意 ${goalId} 先做只读映射预演，不授权写入或生产动作`;
}

function durableOperatorGateRecordRule(kind?: UserActionKind) {
  if (kind !== "controller") {
    return null;
  }
  return "记录规则：如需持久记录本次判断，先用本地操作者确认预演；确认写入时去掉 --dry-run 参数；写入会生成操作者确认恢复合同（operator_gate_resume_contract_v0），只在该决策点重新对齐当前权威状态，不回滚或带回整个仓库；拒绝或暂缓时填写可公开的原因。";
}

function suggestedDecisionLine(kind?: UserActionKind, item?: UserActionSummaryItem, goalId?: string) {
  if (kind === "controller") {
    if (item?.operatorQuestion && firstOpenTodo(item.userTodos)) {
      return "先完成或确认用户待办，再判断是否同意放行；不授权写入或生产动作。";
    }
    const targetGoalId = goalId ?? item?.goalId;
    const lead = targetGoalId ? `同意 ${targetGoalId} 先做` : "同意先做";
    const question = item?.operatorQuestion ?? "";
    if (question.includes("read-only map")) {
      return `${lead}只读映射预演；不授权写入或生产动作。`;
    }
    return `${lead}只读控制者预演；不授权写入或生产动作。`;
  }
  if (kind === "reward") {
    return "同意记录这次人工评价 / 暂不同意，原因是...";
  }
  if (kind === "codex") {
    return "同意让 Codex 沿安全路径继续；如需写入再单独请求授权。";
  }
  if (kind === "evidence") {
    return "继续等待外部证据；暂不升级成决策建议。";
  }
  if (kind === "health") {
    return "先修健康阻塞；暂不处理人工评价、控制者或 Codex 交接。";
  }
  return "继续 / 不继续 / 继续观察，并补一句原因。";
}

function normalizeConflictRisk(value?: string | null) {
  return (value || "unknown").toLowerCase();
}

function authorityCoverageVariant({
  declared,
  conflictRisk,
  deprecatedCount,
  materialOwnerReviewCount,
  materialStaleCount,
  present,
  total,
}: {
  declared: boolean;
  conflictRisk?: string | null;
  deprecatedCount: number;
  materialOwnerReviewCount?: number;
  materialStaleCount?: number;
  present: number;
  total: number;
}): BadgeVariant {
  if (!declared) {
    return "neutral";
  }
  const risk = normalizeConflictRisk(conflictRisk);
  if (
    risk === "high" ||
    deprecatedCount > 0 ||
    (materialOwnerReviewCount ?? 0) > 0 ||
    (materialStaleCount ?? 0) > 0 ||
    (total > 0 && present < total)
  ) {
    return "warning";
  }
  if (risk === "medium") {
    return "warning";
  }
  return "success";
}

function buildAuthorityCoverageFromCounts({
  declared,
  pathExists,
  present,
  total,
  topics,
  materialTotal,
  materialRepositories,
  materialOwnerReviewRequired,
  materialStale,
  materialCurrentAuthority,
  deprecatedCount,
  conflictRisk,
}: {
  declared?: boolean | null;
  pathExists?: boolean | null;
  present?: number | null;
  total?: number | null;
  topics?: number | null;
  materialTotal?: number | null;
  materialRepositories?: number | null;
  materialOwnerReviewRequired?: number | null;
  materialStale?: number | null;
  materialCurrentAuthority?: number | null;
  deprecatedCount?: number | null;
  conflictRisk?: string | null;
}): AuthorityCoverage | undefined {
  const isDeclared = Boolean(declared);
  if (!isDeclared && !total && !topics && !materialTotal) {
    return undefined;
  }
  const presentCount = present ?? 0;
  const totalCount = total ?? 0;
  const topicCount = topics ?? 0;
  const materialCount = materialTotal ?? 0;
  const materialRepoCount = materialRepositories ?? 0;
  const materialOwnerReviewCount = materialOwnerReviewRequired ?? 0;
  const materialStaleCount = materialStale ?? 0;
  const materialCurrentAuthorityCount = materialCurrentAuthority ?? 0;
  const deprecated = deprecatedCount ?? 0;
  const risk = normalizeConflictRisk(conflictRisk);
  const pathText = pathExists == null ? "路径未检查" : pathExists ? "路径正常" : "路径缺失";
  const entryText = totalCount > 0 ? `默认条目 ${presentCount}/${totalCount}` : "未声明默认条目";
  const riskText = risk === "unknown" ? "风险未知" : `风险 ${risk}`;
  const materialText =
    materialCount > 0
      ? `材料 ${materialCount}；仓库 ${materialRepoCount}；需负责人审阅 ${materialOwnerReviewCount}；过期 ${materialStaleCount}；当前有效 ${materialCurrentAuthorityCount}`
      : "";
  const badge = !isDeclared
    ? "未配置注册表"
    : risk === "high" ||
        risk === "medium" ||
        deprecated > 0 ||
        materialOwnerReviewCount > 0 ||
        materialStaleCount > 0 ||
        (totalCount > 0 && presentCount < totalCount)
      ? "需要审阅"
      : "已覆盖";
  return {
    badge,
    reviewLine: isDeclared
      ? `权威源：已声明；${pathText}；${entryText}；主题 ${topicCount}；${riskText}${materialText ? `；${materialText}` : ""}${deprecated ? `；已弃用 ${deprecated}` : ""}。`
      : "权威源：未声明权威注册表；目前只能看到普通权威来源。",
    shortLine: isDeclared
      ? `${entryText}；主题 ${topicCount}；${materialText ? `${materialText}；` : ""}${riskText}`
      : "未声明权威注册表",
    variant: authorityCoverageVariant({
      declared: isDeclared,
      conflictRisk: risk,
      deprecatedCount: deprecated,
      materialOwnerReviewCount,
      materialStaleCount,
      present: presentCount,
      total: totalCount,
    }),
  };
}

function buildAuthorityCoverage({
  goal,
  run,
}: {
  goal?: RunGoal;
  run?: RunRecord;
}): AuthorityCoverage | undefined {
  const projectMap = run?.project_map;
  if (projectMap?.authority_registry_declared != null || projectMap?.authority_registry_default_entry_count != null) {
    return buildAuthorityCoverageFromCounts({
      declared: projectMap.authority_registry_declared,
      pathExists: projectMap.authority_registry_path_exists,
      present: projectMap.authority_registry_default_entries_present,
      total: projectMap.authority_registry_default_entry_count,
      topics: projectMap.topic_authority_count,
      materialTotal: projectMap.project_material_count,
      materialRepositories: projectMap.project_material_repository_count,
      materialOwnerReviewRequired: projectMap.project_material_owner_review_required_count,
      materialStale: projectMap.project_material_stale_count,
      materialCurrentAuthority: projectMap.project_material_current_authority_count,
      conflictRisk: projectMap.authority_registry_conflict_risk,
    });
  }
  const registry: AuthorityRegistry | null | undefined = goal?.authority_registry;
  if (!registry) {
    return undefined;
  }
  return buildAuthorityCoverageFromCounts({
    declared: registry.declared,
    pathExists: registry.path_exists,
    present: registry.default_entries_present,
    total: registry.default_entry_count,
    topics: registry.topic_authority_count,
    materialTotal: registry.project_material_count,
    materialRepositories: registry.project_material_repository_count,
    materialOwnerReviewRequired: registry.project_material_owner_review_required_count,
    materialStale: registry.project_material_stale_count,
    materialCurrentAuthority: registry.project_material_current_authority_count,
    deprecatedCount: registry.deprecated_source_count,
    conflictRisk: registry.conflict_risk,
  });
}

function buildAuthorityCoverageFromProjectMap(projectMap: ProjectMap): AuthorityCoverage | undefined {
  return buildAuthorityCoverageFromCounts({
    declared: projectMap.authority_registry_declared,
    pathExists: projectMap.authority_registry_path_exists,
    present: projectMap.authority_registry_default_entries_present,
    total: projectMap.authority_registry_default_entry_count,
    topics: projectMap.topic_authority_count,
    materialTotal: projectMap.project_material_count,
    materialRepositories: projectMap.project_material_repository_count,
    materialOwnerReviewRequired: projectMap.project_material_owner_review_required_count,
    materialStale: projectMap.project_material_stale_count,
    materialCurrentAuthority: projectMap.project_material_current_authority_count,
    conflictRisk: projectMap.authority_registry_conflict_risk,
  });
}

const quotaStateLabel: Record<string, string> = {
  blocked_health: "健康检查阻塞",
  eligible: "可以执行",
  focus_wait: "重点等待",
  operator_gate: "等待操作确认",
  paused: "已暂停",
  throttled: "已限流",
  waiting: "等待中",
};

const quotaStateReviewLabel: Record<string, string> = {
  blocked_health: "先修健康阻塞",
  eligible: "可自动推进",
  focus_wait: "等待负责人证据、干净基线或外部评估",
  operator_gate: "等待人或控制器决策",
  paused: "自动计算已暂停",
  throttled: "本窗口配额已用完",
  waiting: "等待证据或下一步",
};

function quotaVariant(state?: string | null): BadgeVariant {
  if (state === "eligible") {
    return "success";
  }
  if (state === "paused") {
    return "neutral";
  }
  if (state === "blocked_health") {
    return "danger";
  }
  if (state === "operator_gate" || state === "throttled") {
    return "warning";
  }
  return "info";
}

function formatQuotaCompute(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function buildQuotaView(quota?: ComputeQuota | null): QuotaView | undefined {
  if (!quota) {
    return undefined;
  }
  const state = quota.state || "waiting";
  const compute = quota.compute ?? 1;
  const spent = quota.spent_slots ?? 0;
  const allowed = quota.allowed_slots ?? 0;
  const computeText = formatQuotaCompute(compute);
  const recovery = isOutcomeFloorRecoveryQuota(quota);
  const stateLabel = recovery ? "允许恢复" : quotaStateLabel[state] ?? state;
  const reviewState = recovery
    ? `需要 Codex 做一次${recoveryEvidenceLabel(quota)}恢复任务`
    : quotaStateReviewLabel[state] ?? state;
  return {
    label: `配额 ${computeText}`,
    shortLine: `${stateLabel}；${spent}/${allowed} 个执行槽位`,
    reviewLine: `配额：计算量 ${computeText}；${reviewState}；${spent}/${allowed} 个执行槽位。`,
    variant: quotaVariant(state),
  };
}

function isFocusWaitQuota(quota?: ComputeQuota | null) {
  return (quota?.state ?? "") === "focus_wait";
}

function isOutcomeFloorRecoveryQuota(quota?: ComputeQuota | null) {
  return Boolean(
    quota
      && quota.state === "focus_wait"
      && quota.handoff_outcome_floor_block
      && quota.safe_bypass_allowed
      && quota.safe_bypass_kind === "outcome_floor_recovery",
  );
}

function recoveryEvidenceLabel(quota?: ComputeQuota | null) {
  const targets = quota?.must_advance ?? [];
  if (targets.some((target) => target === "ranker_or_cross_domain_evidence")) {
    return "排序器 / 跨域证据";
  }
  if (targets.length > 0) {
    return targets.map(shareMachineLabel).join(" / ");
  }
  return "结果级证据";
}

function formatLatestValidation(validation?: ProjectAssetLatestValidation | null) {
  if (!validation) {
    return null;
  }
  return [
    validation.classification,
    validation.summary,
  ].filter(Boolean).join("; ") || null;
}

function QuotaChip({ quota }: { quota?: ComputeQuota | null }) {
  const view = buildQuotaView(quota);
  if (!view) {
    return null;
  }
  return <Badge variant={view.variant}>{view.label}</Badge>;
}

type OperatorMentalModelItem = {
  id: string;
  label: string;
  badge: string;
  value: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
  variant: BadgeVariant;
};

function firstUsefulText(...values: Array<string | null | undefined>) {
  return values.find((value) => Boolean(value?.trim()))?.trim() ?? "";
}

function buildCanContinueView({
  agentTodo,
  quota,
  row,
  userTodo,
}: {
  agentTodo?: TodoItem;
  quota?: ComputeQuota | null;
  row: GoalDirectoryRow;
  userTodo?: TodoItem;
}) {
  const state = quota?.state ?? row.waitingOn;
  if (state === "eligible") {
    return {
      value: agentTodo ? "Agent 可以继续" : "已就绪，需要下一个 Todo",
      detail: agentTodo
        ? "存在可执行的 Agent 工作，配额限制也已放行。"
        : "当前允许执行，但还没有为这个 Goal 生成第一个 Agent Todo。",
      variant: agentTodo ? "success" : "warning",
    } as const;
  }
  if (state === "operator_gate" || row.waitingOn === "user_or_controller" || row.waitingOn === "controller") {
    return {
      value: "需要先做判断",
      detail: userTodo
        ? "下一次安全推进要先完成用户或控制者 Todo。"
        : "继续交付前需要通过人工或控制者确认。",
      variant: "warning",
    } as const;
  }
  if (row.waitingOn === "external_evidence" || state === "waiting") {
    return {
      value: "正在等待证据",
      detail: "外部证据或结束标记发生变化后才能继续。",
      variant: "info",
    } as const;
  }
  if (state === "blocked_health") {
    return {
      value: "需要先修复",
      detail: "控制面要求先修复健康问题，再继续交付。",
      variant: "danger",
    } as const;
  }
  if (state === "throttled" || state === "paused" || state === "focus_wait") {
    return {
      value: "暂时保持等待",
      detail: buildQuotaView(quota)?.shortLine ?? "当前控制面状态不允许继续交付。",
      variant: state === "paused" ? "neutral" : "warning",
    } as const;
  }
  return {
    value: "检查控制面",
    detail: buildQuotaView(quota)?.shortLine ?? row.status,
    variant: "neutral",
  } as const;
}

function buildOperatorMentalModelItems(row?: GoalDirectoryRow): OperatorMentalModelItem[] {
  if (!row) {
    return [];
  }
  const projectAsset = row.queueItem?.project_asset;
  const userTodos = todosFromProjectAssetSummary(projectAsset?.user_todos, row.queueItem?.user_todos, "project_asset.user_todos");
  const agentTodos = todosFromProjectAssetSummary(projectAsset?.agent_todos, row.queueItem?.agent_todos, "project_asset.agent_todos");
  const userTodo = firstOpenTodo(userTodos);
  const agentTodo = firstOpenTodo(agentTodos);
  const quota = row.queueItem?.quota ?? projectAsset?.quota ?? row.goal.quota;
  const canContinue = buildCanContinueView({ agentTodo, quota, row, userTodo });
  const evidence = firstUsefulText(
    formatLatestValidation(projectAsset?.latest_validation),
    row.latestRun?.health_check,
    row.latestRun?.classification
      ? `${row.latestRun.classification}${row.latestRun.generated_at ? ` at ${row.latestRun.generated_at}` : ""}`
      : null,
  );
  const nextStep = firstUsefulText(
    agentTodo?.text,
    projectAsset?.next_action,
    row.queueItem?.recommended_action,
    row.latestRun?.recommended_action,
  );
  const judgment = firstUsefulText(
    userTodo?.text,
    row.queueItem?.operator_question,
    row.queueItem?.next_handoff_condition,
  );

  return [
    {
      id: "goal",
      label: "目标",
      badge: severityLabel[row.severity] ?? row.severity,
      value: row.goal.id,
      detail: `${row.status}; ${waitingLabel[row.waitingOn] ?? row.waitingOn}; ${row.lifecyclePhase}`,
      icon: GitBranch,
      variant: row.severity === "clear" ? "success" : severityVariant[row.severity] ?? "neutral",
    },
    {
      id: "next-step",
      label: "下一步",
      badge: agentTodo ? "Todo" : "备用信息",
      value: nextStep || "尚未生成下一步",
      detail: agentTodo ? "来自已生成的 Agent Todo。" : "来自项目资产、队列建议或最近运行记录。",
      icon: Terminal,
      variant: agentTodo ? "info" : "neutral",
    },
    {
      id: "needs-your-judgment",
      label: "需要你判断",
      badge: judgment ? "需要确认" : "无需处理",
      value: judgment || "没有等待人工判断的事项",
      detail: userTodo ? "用户或控制者 Todo 是当前第一个交接项。" : "这个 Goal 当前没有用户确认环节。",
      icon: ShieldCheck,
      variant: judgment ? "warning" : "success",
    },
    {
      id: "evidence",
      label: "证据",
      badge: evidence ? "已有" : "暂无",
      value: evidence || "暂无摘要证据",
      detail: evidence ? "来自最近的验证或运行记录。" : "排查问题时请打开运行历史或状态来源。",
      icon: FileCheck2,
      variant: evidence ? "info" : "neutral",
    },
    {
      id: "can-continue",
      label: "是否可继续",
      badge: "执行限制",
      value: canContinue.value,
      detail: canContinue.detail,
      icon: Gauge,
      variant: canContinue.variant,
    },
  ];
}

function OperatorMentalModelPanel({
  row,
  onSelectGoal,
}: {
  row?: GoalDirectoryRow;
  onSelectGoal: (goalId: string) => void;
}) {
  const items = buildOperatorMentalModelItems(row);
  if (!row || items.length === 0) {
    return null;
  }
  return (
    <Card data-testid="operator-mental-model-panel">
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <LayoutDashboard className="h-4 w-4" />
            操作者概览
          </CardTitle>
          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            首屏把控制面状态整理成五个需要关注的问题。
          </p>
        </div>
        <Button onClick={() => onSelectGoal(row.goal.id)} size="sm" variant="secondary">
          <Search className="h-4 w-4" />
          查看详情
        </Button>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 lg:grid-cols-5">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <div
                className="min-h-32 rounded-lg border border-slate-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950"
                data-testid={`operator-model-${item.id}`}
                key={item.id}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-zinc-50">
                    <Icon className="h-4 w-4 text-slate-500 dark:text-zinc-400" />
                    {item.label}
                  </div>
                  <Badge variant={item.variant}>{item.badge}</Badge>
                </div>
                <p className="mt-3 line-clamp-3 break-words text-sm leading-6 text-slate-800 dark:text-zinc-200">
                  {item.value}
                </p>
                <p className="mt-2 line-clamp-2 break-words text-xs leading-5 text-slate-500 dark:text-zinc-400">
                  {item.detail}
                </p>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function controlPlaneForTarget(goal?: RunGoal, queueItem?: QueueItem): ControlPlanePolicy | null {
  return queueItem?.control_plane ?? queueItem?.project_asset?.control_plane ?? goal?.control_plane ?? null;
}

function orchestrationForTarget(goal?: RunGoal, queueItem?: QueueItem): OrchestrationPolicy | null {
  return queueItem?.project_asset?.orchestration ?? goal?.orchestration ?? goal?.spawn_policy ?? null;
}

function flagValue(value?: boolean | null) {
  return value ? "开启" : "关闭";
}

function orchestrationMode(policy?: OrchestrationPolicy | null) {
  if (!policy) {
    return "default";
  }
  const spawnAllowed = Boolean(policy.spawn_allowed || policy.allowed);
  const maxChildren = policy.max_children ?? 0;
  const explicitMode = policy.mode || policy.orchestration_mode || "";
  if ((!explicitMode || explicitMode === "default") && spawnAllowed && maxChildren > 0) {
    return "multi_subagent";
  }
  return explicitMode || "default";
}

function shellArg(value: string) {
  if (/^[A-Za-z0-9_./:=@,+-]+$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function buildHeartbeatInstallView(goal?: RunGoal, queueItem?: QueueItem): {
  badge: string;
  detail: string;
  variant: BadgeVariant;
} {
  const status = [queueItem?.status, goal?.status, goal?.adapter_status].filter(Boolean).join(" ").toLowerCase();
  if (status.includes("not_installed")) {
    return {
      badge: "未安装",
      detail: "状态中包含 not_installed",
      variant: "warning",
    };
  }
  if (status.includes("paused")) {
    return {
      badge: "已暂停",
      detail: "状态中包含 paused",
      variant: "neutral",
    };
  }
  if (status.includes("stage_deferred") || status.includes("deferred")) {
    return {
      badge: "已推迟",
      detail: "状态中包含 deferred",
      variant: "warning",
    };
  }
  if (queueItem || goal?.registry_member) {
    return {
      badge: "已观测到",
      detail: queueItem?.source ? `队列来源=${queueItem.source}` : "实时状态中已观测到注册表成员",
      variant: "success",
    };
  }
  return {
    badge: "未知",
    detail: "没有队列或注册表心跳信号",
    variant: "neutral",
  };
}

function ControlPlaneSettingRow({
  badge,
  detail,
  icon: Icon,
  label,
  variant,
}: {
  badge: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  variant: BadgeVariant;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0 text-slate-500 dark:text-zinc-400" />
          <span className="text-sm font-semibold text-slate-900 dark:text-zinc-100">{label}</span>
        </div>
        <Badge variant={variant}>{badge}</Badge>
      </div>
      <div className="mt-2 break-words text-xs leading-5 text-slate-500 dark:text-zinc-400">{detail}</div>
    </div>
  );
}

type ControlPlaneSettingsDraft = {
  quotaCompute: string;
  quotaWindowHours: string;
  selfRepairEnabled: boolean;
  selfRepairHealth: boolean;
  selfRepairWaitingProjection: boolean;
  orchestrationMode: "default" | "multi_subagent";
  spawnAllowed: boolean;
  maxChildren: string;
  allowedDomains: string;
};

type ConfigureGoalRequestBody = {
  allowed_domains: string[];
  clear_allowed_domains: boolean;
  goal_id: string;
  max_children: number;
  multi_subagent_feature: "off" | "enabled";
  quota_compute: number;
  quota_window_hours: number;
  self_repair_enabled: boolean;
  self_repair_health: boolean;
  self_repair_waiting_projection: boolean;
};

type ConfigureGoalApiResponse = {
  ok: boolean;
  dry_run?: boolean;
  execute?: boolean;
  written?: boolean;
  changed?: boolean;
  goal_id?: string;
  changed_fields?: string[];
  preview_id?: string;
  control_plane_summary?: string;
  orchestration_summary?: string;
  error?: string;
};

function buildControlPlaneSettingsDraft(goal?: RunGoal, queueItem?: QueueItem): ControlPlaneSettingsDraft {
  const quota = queueItem?.quota ?? queueItem?.project_asset?.quota ?? goal?.quota;
  const controlPlane = controlPlaneForTarget(goal, queueItem);
  const selfRepair = controlPlane?.self_repair;
  const orchestration = orchestrationForTarget(goal, queueItem);
  const mode = orchestrationMode(orchestration);
  return {
    quotaCompute: String(quota?.compute ?? 1),
    quotaWindowHours: String(quota?.window_hours ?? 24),
    selfRepairEnabled: Boolean(selfRepair?.enabled),
    selfRepairHealth: Boolean(selfRepair?.allow_health_blocker_repair),
    selfRepairWaitingProjection: Boolean(selfRepair?.allow_waiting_projection_repair),
    orchestrationMode: mode === "multi_subagent" ? "multi_subagent" : "default",
    spawnAllowed: Boolean(orchestration?.spawn_allowed || orchestration?.allowed),
    maxChildren: String(orchestration?.max_children ?? 0),
    allowedDomains: orchestration?.allowed_domains?.length ? orchestration.allowed_domains.join(", ") : "",
  };
}

function validDraftNumber(value: string, { min }: { min: number }) {
  const parsed = Number(value.trim());
  return Number.isFinite(parsed) && parsed >= min;
}

function buildConfigureGoalRequestBody(draft: ControlPlaneSettingsDraft, goalId?: string): ConfigureGoalRequestBody | null {
  if (!goalId || !validDraftNumber(draft.quotaCompute, { min: 0.000001 }) || !validDraftNumber(draft.quotaWindowHours, { min: 0.000001 }) || !validDraftNumber(draft.maxChildren, { min: 0 })) {
    return null;
  }
  const multiSubagentEnabled = draft.orchestrationMode === "multi_subagent" && draft.spawnAllowed;
  const domains = normalizedDomainList(draft.allowedDomains);
  return {
    allowed_domains: multiSubagentEnabled ? domains : [],
    clear_allowed_domains: !multiSubagentEnabled || domains.length === 0,
    goal_id: goalId,
    max_children: multiSubagentEnabled ? Number(draft.maxChildren.trim()) : 0,
    multi_subagent_feature: multiSubagentEnabled ? "enabled" : "off",
    quota_compute: Number(draft.quotaCompute.trim()),
    quota_window_hours: Number(draft.quotaWindowHours.trim()),
    self_repair_enabled: draft.selfRepairEnabled,
    self_repair_health: draft.selfRepairHealth,
    self_repair_waiting_projection: draft.selfRepairWaitingProjection,
  };
}

function booleanFlag(enabled: boolean, positive: string) {
  return enabled ? `--${positive}` : `--no-${positive}`;
}

function normalizedDomainList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function buildConfigureGoalCommand({
  draft,
  execute,
  goalId,
  registry,
}: {
  draft: ControlPlaneSettingsDraft;
  execute: boolean;
  goalId?: string;
  registry: string;
}) {
  if (!goalId) {
    return "";
  }
  const registryArg = registry ? shellArg(registry) : "$HOME/.codex/loopx/registry.global.json";
  const multiSubagentEnabled = draft.orchestrationMode === "multi_subagent" && draft.spawnAllowed;
  const parts = [
    "loopx",
    "--registry",
    registryArg,
    "configure-goal",
    "--goal-id",
    shellArg(goalId),
    "--quota-compute",
    shellArg(draft.quotaCompute.trim() || "1"),
    "--quota-window-hours",
    shellArg(draft.quotaWindowHours.trim() || "24"),
    booleanFlag(draft.selfRepairEnabled, "self-repair-enabled"),
    booleanFlag(draft.selfRepairHealth, "self-repair-health"),
    booleanFlag(draft.selfRepairWaitingProjection, "self-repair-waiting-projection"),
    "--multi-subagent-feature",
    multiSubagentEnabled ? "enabled" : "off",
    "--max-children",
    shellArg(multiSubagentEnabled ? draft.maxChildren.trim() || "0" : "0"),
  ];
  for (const domain of multiSubagentEnabled ? normalizedDomainList(draft.allowedDomains) : []) {
    parts.push("--allowed-domain", shellArg(domain));
  }
  if (!multiSubagentEnabled || !normalizedDomainList(draft.allowedDomains).length) {
    parts.push("--clear-allowed-domains");
  }
  if (execute) {
    parts.push("--execute");
  }
  return parts.join(" ");
}

function ControlPlaneSettingsPanel({
  applyUrl,
  dryRunUrl,
  goal,
  onStatusRefresh,
  queueItem,
  registry,
  writeEnabled,
}: {
  applyUrl: string | null;
  dryRunUrl: string | null;
  goal?: RunGoal;
  onStatusRefresh: () => Promise<void>;
  queueItem?: QueueItem;
  registry: string;
  writeEnabled: boolean | null;
}) {
  const quota = queueItem?.quota ?? queueItem?.project_asset?.quota ?? goal?.quota;
  const quotaView = buildQuotaView(quota);
  const controlPlane = controlPlaneForTarget(goal, queueItem);
  const selfRepair = controlPlane?.self_repair;
  const heartbeat = buildHeartbeatInstallView(goal, queueItem);
  const orchestration = orchestrationForTarget(goal, queueItem);
  const mode = orchestrationMode(orchestration);
  const domains = orchestration?.allowed_domains?.length ? `；允许的领域=${orchestration.allowed_domains.join(",")}` : "";

  const selfRepairEnabled = Boolean(selfRepair?.enabled);
  const selfRepairBadge = selfRepair ? `自动修复${selfRepairEnabled ? "已开启" : "已关闭"}` : "自动修复默认关闭";
  const selfRepairDetail = selfRepair
    ? `健康问题修复=${flagValue(selfRepair.allow_health_blocker_repair)}；等待状态修复=${flagValue(selfRepair.allow_waiting_projection_repair)}`
    : "这个 Goal 没有单独设置自动修复";
  const orchestrationVariant: BadgeVariant = mode === "multi_subagent" ? "info" : "neutral";
  const currentDraft = useMemo(
    () => buildControlPlaneSettingsDraft(goal, queueItem),
    [
      goal?.id,
      goal?.quota,
      goal?.control_plane,
      goal?.orchestration,
      goal?.spawn_policy,
      queueItem?.goal_id,
      queueItem?.quota,
      queueItem?.control_plane,
      queueItem?.project_asset?.quota,
      queueItem?.project_asset?.control_plane,
      queueItem?.project_asset?.orchestration,
    ],
  );
  const [draft, setDraft] = useState(currentDraft);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const [dryRunResult, setDryRunResult] = useState<ConfigureGoalApiResponse | null>(null);
  const [dryRunBody, setDryRunBody] = useState<ConfigureGoalRequestBody | null>(null);
  const [applyResult, setApplyResult] = useState<ConfigureGoalApiResponse | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [isDryRunning, setIsDryRunning] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(currentDraft);
  const goalId = goal?.id ?? queueItem?.goal_id;
  const dryRunCommand = buildConfigureGoalCommand({ draft, execute: false, goalId, registry });
  const applyCommand = buildConfigureGoalCommand({ draft, execute: true, goalId, registry });
  const requestBody = buildConfigureGoalRequestBody(draft, goalId);
  const canCopy = Boolean(goalId && dirty);
  const canDryRun = Boolean(dryRunUrl && dirty && requestBody);
  const canApply = Boolean(applyUrl && dryRunBody && dryRunResult?.ok && dryRunResult.preview_id && !applyResult?.written);
  const writeApiLabel = writeEnabled === true ? "写入接口已开启" : writeEnabled === false ? "写入接口已关闭" : "写入接口状态未知";
  const writeApiVariant: BadgeVariant = writeEnabled === true ? "success" : writeEnabled === false ? "warning" : "neutral";

  useEffect(() => {
    setDraft(currentDraft);
    setCopyState("idle");
    setDryRunResult(null);
    setDryRunBody(null);
    setApplyResult(null);
    setDryRunError(null);
    setApplyError(null);
  }, [currentDraft]);

  useEffect(() => {
    if (copyState === "idle") {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setCopyState("idle"), 1800);
    return () => window.clearTimeout(timeoutId);
  }, [copyState]);

  async function copyCommand(command: string) {
    if (!command) {
      return;
    }
    setCopyState((await copyTextToClipboard(command)) ? "copied" : "failed");
  }

  async function runDryRunCheck() {
    if (!dryRunUrl || !requestBody) {
      return;
    }
    setIsDryRunning(true);
    setDryRunError(null);
    setDryRunResult(null);
    setDryRunBody(null);
    setApplyResult(null);
    setApplyError(null);
    try {
      const response = await fetch(dryRunUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const payload = await response.json() as ConfigureGoalApiResponse;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      setDryRunResult(payload);
      setDryRunBody(requestBody);
    } catch (error) {
      setDryRunError(formatStatusError(error));
    } finally {
      setIsDryRunning(false);
    }
  }

  async function applySettings() {
    if (!applyUrl || !dryRunBody || !dryRunResult?.preview_id) {
      return;
    }
    setIsApplying(true);
    setApplyError(null);
    try {
      const response = await fetch(applyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...dryRunBody, preview_id: dryRunResult.preview_id }),
      });
      const payload = await response.json() as ConfigureGoalApiResponse;
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      setApplyResult(payload);
      setDryRunResult(payload);
      await onStatusRefresh();
    } catch (error) {
      setApplyError(formatStatusError(error));
    } finally {
      setIsApplying(false);
    }
  }

  return (
    <div
      className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-zinc-800 dark:bg-zinc-900"
      data-testid="control-plane-settings-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Gauge className="h-4 w-4 text-slate-600 dark:text-zinc-300" />
          <h3 className="text-sm font-semibold text-slate-950 dark:text-zinc-50">控制面设置</h3>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={selfRepairEnabled ? "success" : "neutral"}>{selfRepairEnabled ? "自动修复已开启" : "自动修复已关闭"}</Badge>
          <Badge variant={orchestrationVariant}>{mode === "multi_subagent" ? "多 Agent" : "默认编排"}</Badge>
          <Badge variant={dirty ? "warning" : "success"}>{dirty ? "有未保存修改" : "配置未修改"}</Badge>
          <Badge variant={dryRunUrl ? "info" : "neutral"}>{dryRunUrl ? "本机接口" : "仅可复制命令"}</Badge>
          <Badge variant={writeApiVariant}>{writeApiLabel}</Badge>
          {applyResult?.written ? <Badge variant="success">已应用</Badge> : null}
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <ControlPlaneSettingRow
          badge={quotaView?.label ?? "配额未知"}
          detail={quotaView?.shortLine ?? "尚未生成配额信息"}
          icon={Gauge}
          label="计算配额"
          variant={quotaView?.variant ?? "neutral"}
        />
        <ControlPlaneSettingRow
          badge={selfRepairBadge}
          detail={selfRepairDetail}
          icon={ShieldCheck}
          label="自动修复"
          variant={selfRepairEnabled ? "success" : "neutral"}
        />
        <ControlPlaneSettingRow
          badge={heartbeat.badge}
          detail={heartbeat.detail}
          icon={Terminal}
          label="心跳安装"
          variant={heartbeat.variant}
        />
        <ControlPlaneSettingRow
          badge={mode === "multi_subagent" ? "多 Agent" : "默认编排"}
          detail={`允许创建子 Agent=${flagValue(Boolean(orchestration?.spawn_allowed || orchestration?.allowed))}；最多子 Agent=${orchestration?.max_children ?? 0}${domains}`}
          icon={Bot}
          label="Agent 编排"
          variant={orchestrationVariant}
        />
      </div>
      <div className="mt-3 grid gap-3 rounded-lg border border-slate-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950 lg:grid-cols-2">
        <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
          <span>配额计算量</span>
          <input
            className={inputClassName}
            data-testid="control-plane-quota-compute"
            inputMode="decimal"
            onChange={(event) => setDraft((value) => ({ ...value, quotaCompute: event.target.value }))}
            value={draft.quotaCompute}
          />
        </label>
        <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
          <span>配额窗口（小时）</span>
          <input
            className={inputClassName}
            inputMode="decimal"
            onChange={(event) => setDraft((value) => ({ ...value, quotaWindowHours: event.target.value }))}
            value={draft.quotaWindowHours}
          />
        </label>
        <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
          <span>编排模式</span>
          <Select
            className="w-full"
            data-testid="control-plane-orchestration-mode"
            onChange={(event) =>
              setDraft((value) => ({
                ...value,
                orchestrationMode: event.target.value === "multi_subagent" ? "multi_subagent" : "default",
              }))
            }
            value={draft.orchestrationMode}
          >
            <option value="default">默认</option>
            <option value="multi_subagent">多 Agent</option>
          </Select>
        </label>
        <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
          <span>最多子 Agent 数</span>
          <input
            className={inputClassName}
            inputMode="numeric"
            onChange={(event) => setDraft((value) => ({ ...value, maxChildren: event.target.value }))}
            value={draft.maxChildren}
          />
        </label>
        <label className="block space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400 lg:col-span-2">
          <span>允许的工作领域</span>
          <input
            className={inputClassName}
            onChange={(event) => setDraft((value) => ({ ...value, allowedDomains: event.target.value }))}
            value={draft.allowedDomains}
          />
        </label>
        <div className="flex flex-wrap gap-3 text-xs font-medium text-slate-600 dark:text-zinc-300 lg:col-span-2">
          <label className="inline-flex items-center gap-2">
            <input
              checked={draft.selfRepairEnabled}
              onChange={(event) => setDraft((value) => ({ ...value, selfRepairEnabled: event.target.checked }))}
              type="checkbox"
            />
            自动修复
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              checked={draft.selfRepairHealth}
              onChange={(event) => setDraft((value) => ({ ...value, selfRepairHealth: event.target.checked }))}
              type="checkbox"
            />
            健康问题修复
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              checked={draft.selfRepairWaitingProjection}
              onChange={(event) => setDraft((value) => ({ ...value, selfRepairWaitingProjection: event.target.checked }))}
              type="checkbox"
            />
            等待状态修复
          </label>
          <label className="inline-flex items-center gap-2">
            <input
              checked={draft.spawnAllowed}
              onChange={(event) => setDraft((value) => ({ ...value, spawnAllowed: event.target.checked }))}
              type="checkbox"
            />
            允许创建子 Agent
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:col-span-2">
          <Button disabled={!dirty} onClick={() => setDraft(currentDraft)} size="sm" variant="ghost">
            <RotateCcw className="h-4 w-4" />
            重置
          </Button>
          <Button disabled={!canDryRun || isDryRunning} onClick={() => void runDryRunCheck()} size="sm">
            {isDryRunning ? <RefreshCw className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
            试运行检查
          </Button>
          <Button disabled={!canApply || isApplying} onClick={() => void applySettings()} size="sm" variant="primary">
            {isApplying ? <RefreshCw className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            应用注册表设置
          </Button>
          <Button disabled={!canCopy} onClick={() => void copyCommand(dryRunCommand)} size="sm">
            <Copy className="h-4 w-4" />
            复制试运行命令
          </Button>
          <Button disabled={!canCopy} onClick={() => void copyCommand(applyCommand)} size="sm" variant="primary">
            <Copy className="h-4 w-4" />
            复制应用命令
          </Button>
          {copyState === "copied" ? <Badge variant="success">已复制</Badge> : null}
          {copyState === "failed" ? <Badge variant="danger">复制失败</Badge> : null}
          {dryRunError ? <Badge variant="danger">{dryRunError.slice(0, 96)}</Badge> : null}
          {applyError ? <Badge variant="danger">{applyError.slice(0, 96)}</Badge> : null}
        </div>
        {dryRunResult?.ok ? (
          <div
            className="space-y-1 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100 lg:col-span-2"
            data-testid="control-plane-settings-dry-run-result"
          >
            <div>
              有变更={String(Boolean(dryRunResult.changed))} · 已写入={String(Boolean(dryRunResult.written))}
              {dryRunResult.preview_id ? ` · 预览编号=${dryRunResult.preview_id}` : ""}
            </div>
            {dryRunResult.changed_fields?.length ? <div>变更字段={dryRunResult.changed_fields.join(", ")}</div> : null}
            {dryRunResult.control_plane_summary ? <div>{dryRunResult.control_plane_summary}</div> : null}
            {dryRunResult.orchestration_summary ? <div>{dryRunResult.orchestration_summary}</div> : null}
          </div>
        ) : null}
        <pre
          className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-50 dark:border-zinc-800 lg:col-span-2"
          data-testid="control-plane-settings-command-preview"
        >
          {dryRunCommand || "请选择一个 Goal"}
        </pre>
      </div>
    </div>
  );
}

type ShareGoalSpec = {
  id: string;
  label: string;
  subtitle: string;
  emphasis: string;
  accent: string;
  icon: React.ComponentType<{ className?: string }>;
};

type EventLedgerClass = keyof EventLedgerSummary["totals"]["by_class_24h"];

type ShareGoalView = {
  agentTodos: TodoGroup | null;
  decisionFreshnessWarnings: DecisionFreshnessItem[];
  eventLedger?: EventLedgerSummary["goals"][number];
  row?: GoalDirectoryRow;
  spec: ShareGoalSpec;
  usage?: UsageSummary["goals"][number];
  userTodos: TodoGroup | null;
};

const shareGoalSpecs: ShareGoalSpec[] = [
  {
    id: "showcase-user-gate-safe-side-path",
    label: "0617 用户确认",
    subtitle: "公开演示 / 安全侧路",
    emphasis: "把用户决策、Agent 待办和安全侧路拆开管理：该等人的地方明确等人。",
    accent: "border-t-emerald-500",
    icon: GitBranch,
  },
  {
    id: "showcase-creator-operator",
    label: "创作者运营",
    subtitle: "合成案例 / 长程内容运营",
    emphasis: "让多个 Agent 围绕热点、素材、洞察和创作待办持续推进，但只展示脱敏演示数据。",
    accent: "border-t-amber-500",
    icon: Gauge,
  },
  {
    id: "showcase-side-agent-self-iteration",
    label: "平级 Agent 自迭代",
    subtitle: "公开仓库事实 / 平级协作",
    emphasis: "平级 Agent 通过认领、边界和独立工作区推进产品化、文档与验证。",
    accent: "border-t-rose-500",
    icon: ShieldCheck,
  },
  {
    id: "loopx-meta",
    label: "LoopX 自举",
    subtitle: "控制面自举与稳定性",
    emphasis: "把观察循环转成状态、配额和活动状态的可验证产品改动。",
    accent: "border-t-sky-500",
    icon: Radar,
  },
];

const shareStatusLabel: Record<string, string> = {
  dashboard_home_control_plane_promotion: "主屏已提升",
  dashboard_home_docs_contract_alignment: "主屏文档合约已对齐",
  dashboard_home_route_smoke_contract: "主屏路由合约已验证",
  state_refreshed: "状态已刷新",
  quota_slot_spent: "已记录配额",
  side_bypass_tau2_non_category_profile_admission_sweep: "独立证据扫描",
};

const shareDeliveryScaleLabel: Record<string, string> = {
  coherent_batch: "成组交付",
  implementation: "实现改动",
  multi_surface: "多面改动",
  single_surface: "单面改动",
  test_only: "仅测试合约",
};

const shareDeliveryOutcomeLabel: Record<string, string> = {
  outcome_gap: "产出差距",
  primary_goal_outcome: "主目标进展",
  surface_only: "仅表层进展",
};

const shareQuotaLabel: Record<string, string> = {
  blocked_health: "健康阻塞",
  eligible: "可自动推进",
  focus_wait: "暂缓不花配额",
  operator_gate: "等待用户决策",
  paused: "已暂停",
  throttled: "配额已满",
  waiting: "等待下一步",
};

const shareWaitingLabel: Record<string, string> = {
  clear: "无需关注",
  codex: "Agent 可处理",
  controller: "控制器待确认",
  external_evidence: "等待外部证据",
  user_or_controller: "用户待确认",
};

const eventClassLabel: Record<string, string> = {
  accounting: "花费记录",
  decision: "人类决策",
  evidence: "证据观察",
  state: "状态刷新",
  work: "实际推进",
};

const eventClassOrder = ["work", "evidence", "decision", "accounting", "state"] as const;

function cleanShareText(value?: string | null) {
  return (value ?? "")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\/Users\/[^\s，。；,;)]+/g, "[local]")
    .replace(/\s+/g, " ")
    .trim();
}

function compactShareText(value?: string | null, limit = 132) {
  const text = cleanShareText(value);
  if (!text) {
    return "暂无";
  }
  return text.length > limit ? `${text.slice(0, limit - 3).trimEnd()}...` : text;
}

function shareMachineLabel(value?: string | null) {
  const raw = value ?? "";
  if (!raw) {
    return "";
  }
  return shareStatusLabel[raw]
    ?? shareDeliveryScaleLabel[raw]
    ?? shareDeliveryOutcomeLabel[raw]
    ?? shareQuotaLabel[raw]
    ?? raw
      .replace(/_/g, " ")
      .replace(/\bquota\b/g, "配额")
      .replace(/\bguard\b/g, "守卫")
      .replace(/\bhandoff\b/g, "交接")
      .replace(/\bstate\b/g, "状态");
}

function shareRowById(rows: GoalDirectoryRow[]) {
  return new Map(rows.map((row) => [row.goal.id, row]));
}

function shareUsageById(usage?: UsageSummary | null) {
  return new Map((usage?.goals ?? []).map((goal) => [goal.goal_id, goal]));
}

function shareEventLedgerById(summary?: EventLedgerSummary | null) {
  return new Map((summary?.goals ?? []).map((goal) => [goal.goal_id, goal]));
}

function shareDecisionFreshnessById(summary?: DecisionFreshnessSummary | null) {
  const grouped = new Map<string, DecisionFreshnessItem[]>();
  for (const item of summary?.items ?? []) {
    if (!item.requires_decision_point_rebase) {
      continue;
    }
    const current = grouped.get(item.goal_id) ?? [];
    current.push(item);
    grouped.set(item.goal_id, current);
  }
  return grouped;
}

function shareDecisionKindLabel(kind?: string | null) {
  if (kind === "human_reward") {
    return "人工评价";
  }
  if (kind === "operator_gate") {
    return "操作者确认";
  }
  if (kind === "operator_gate_resume_contract") {
    return "恢复合同";
  }
  return kind ? shareMachineLabel(kind) : "决策";
}

function shareDecisionFreshnessStateLabel(state?: string | null) {
  if (state === "stale_rebase_required") {
    return "已过期，需重新确认";
  }
  if (state === "rebase_required") {
    return "有后续事件，需重新确认";
  }
  return shareMachineLabel(state) || "需重新确认";
}

function getShareTodos(row: GoalDirectoryRow | undefined, role: "user" | "agent") {
  if (!row) {
    return null;
  }
  const projectAsset = row.queueItem?.project_asset;
  return role === "user"
    ? todosFromProjectAssetSummary(projectAsset?.user_todos, row.queueItem?.user_todos, "project_asset.user_todos")
    : todosFromProjectAssetSummary(projectAsset?.agent_todos, row.queueItem?.agent_todos, "project_asset.agent_todos");
}

function shareTodoCount(todos?: TodoGroup | null) {
  if (!todos || todos.total_count === 0) {
    return "0/0";
  }
  return `${todos.open_count}/${todos.total_count}`;
}

type ShareTodoRole = "user" | "agent";

type ShareTopTodoItem = {
  done: boolean;
  index: number;
  role: ShareTodoRole;
  sourceOrder: number;
  text: string;
};

function shareTodoRoleLabel(role: ShareTodoRole) {
  return role === "user" ? "用户" : "Agent";
}

function shareTodoStatusLabel(todo: ShareTopTodoItem) {
  if (todo.done) {
    return "已完成";
  }
  return todo.role === "user" ? "待用户" : "待 Agent";
}

function shareTodoStatusVariant(todo: ShareTopTodoItem): BadgeVariant {
  if (todo.done) {
    return "success";
  }
  return todo.role === "user" ? "warning" : "info";
}

function shareTopTodoItems(view: ShareGoalView, limit = 4): ShareTopTodoItem[] {
  const groups: Array<[ShareTodoRole, TodoGroup | null]> = [
    ["user", view.userTodos],
    ["agent", view.agentTodos],
  ];
  return groups
    .flatMap(([role, group]) => (group?.items ?? []).map((todo, sourceOrder) => ({
      done: todo.done,
      index: todo.index,
      role,
      sourceOrder,
      text: todo.text,
    })))
    .sort((left, right) => {
      const leftPriority = (left.done ? 2 : 0) + (left.role === "agent" ? 1 : 0);
      const rightPriority = (right.done ? 2 : 0) + (right.role === "agent" ? 1 : 0);
      return leftPriority - rightPriority
        || left.sourceOrder - right.sourceOrder
        || left.index - right.index;
    })
    .slice(0, limit);
}

function ShareTopTodoList({
  className,
  compact = false,
  view,
}: {
  className?: string;
  compact?: boolean;
  view: ShareGoalView;
}) {
  const todos = shareTopTodoItems(view);
  if (todos.length === 0) {
    return (
      <div className={cn("rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500", className)}>
        当前没有可展示的项目 Todo。
      </div>
    );
  }
  return (
    <div className={cn("space-y-2", className)} data-testid={`share-top-todos-${view.spec.id}`}>
      {todos.map((todo, itemIndex) => {
        const StatusIcon = todo.done ? CheckCircle2 : Clock3;
        return (
          <div
            className={cn(
              "rounded-md border px-3 py-2",
              todo.done ? "border-emerald-200 bg-emerald-50/70" : "border-slate-200 bg-white",
            )}
            key={`${todo.role}-${todo.index}-${itemIndex}`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={todo.role === "user" ? "warning" : "info"}>{shareTodoRoleLabel(todo.role)}</Badge>
              <Badge variant={shareTodoStatusVariant(todo)}>
                <StatusIcon className="h-3 w-3" />
                {shareTodoStatusLabel(todo)}
              </Badge>
              <span className="text-[11px] font-medium text-slate-500">#{todo.index}</span>
            </div>
            <p className={cn("mt-1 break-words text-sm leading-6 text-slate-700", compact ? "line-clamp-2" : "line-clamp-3")}>
              {compactShareText(todo.text, compact ? 112 : 152)}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function ShareDependencyBlockerList({
  className,
  compact = false,
  view,
}: {
  className?: string;
  compact?: boolean;
  view: ShareGoalView;
}) {
  const blockers = view.row?.queueItem?.dependency_blockers;
  const items = blockers?.items ?? [];
  if (!blockers || blockers.open_count === 0 || items.length === 0) {
    return null;
  }
  return (
    <div className={cn("space-y-2", className)} data-testid={`share-dependency-blockers-${view.spec.id}`}>
      {items.slice(0, compact ? 2 : 4).map((blocker, itemIndex) => (
        <div
          className="rounded-md border border-amber-200 bg-amber-50/70 px-3 py-2"
          key={`${blocker.goal_id}-${blocker.index ?? itemIndex}`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warning">依赖阻塞</Badge>
            <span className="break-all text-[11px] font-semibold text-amber-700">{blocker.goal_id}</span>
            {blocker.waiting_on ? (
              <span className="text-[11px] font-medium text-amber-700">
                {shareWaitingLabel[blocker.waiting_on] ?? shareMachineLabel(blocker.waiting_on)}
              </span>
            ) : null}
          </div>
          <p className={cn("mt-1 break-words text-sm leading-6 text-amber-950", compact ? "line-clamp-2" : "line-clamp-3")}>
            {compactShareText(blocker.text, compact ? 108 : 148)}
          </p>
        </div>
      ))}
      {blockers.open_count > items.length ? (
        <div className="text-[11px] font-medium text-amber-700">
          另有 {blockers.open_count - items.length} 项依赖阻塞未展开。
        </div>
      ) : null}
    </div>
  );
}

function ShareDecisionFreshnessWarning({
  className,
  compact = false,
  view,
}: {
  className?: string;
  compact?: boolean;
  view: ShareGoalView;
}) {
  const items = view.decisionFreshnessWarnings;
  if (items.length === 0) {
    return null;
  }
  const visible = items.slice(0, compact ? 1 : 2);
  return (
    <div className={cn("space-y-2", className)} data-testid={`share-decision-freshness-${view.spec.id}`}>
      {visible.map((item, itemIndex) => (
        <div
          className="rounded-md border border-amber-200 bg-amber-50/80 px-3 py-2"
          key={`${item.decision_kind ?? "decision"}-${item.decision_at ?? itemIndex}`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="warning">决策需重新确认</Badge>
            <span className="text-[11px] font-semibold text-amber-700">
              {shareDecisionKindLabel(item.decision_kind)}
            </span>
            <span className="text-[11px] font-medium text-amber-700">
              {shareDecisionFreshnessStateLabel(item.freshness_state)}
            </span>
          </div>
          <p className={cn("mt-1 break-words text-sm leading-6 text-amber-950", compact ? "line-clamp-2" : "line-clamp-3")}>
            {compact
              ? "审批或转交前先重读当前控制面状态；这不是仓库回滚。"
              : "审批或转交前先重读注册表、当前状态、配额和运行状态；旧聊天或旧确认不能直接当作当前授权，这不是仓库回滚。"}
          </p>
          <div className="mt-1 flex flex-wrap gap-2 text-[11px] font-medium text-amber-700">
            <span>7d 新事件 {item.newer_event_count_7d ?? 0}</span>
            {item.age_days != null ? <span>决策年龄 {Math.round(item.age_days)}d</span> : null}
          </div>
        </div>
      ))}
      {items.length > visible.length ? (
        <div className="text-[11px] font-medium text-amber-700">
          另有 {items.length - visible.length} 个旧决策需要重新确认。
        </div>
      ) : null}
    </div>
  );
}

function shareOpenTotal(views: ShareGoalView[], role: "user" | "agent") {
  return views.reduce(
    (total, view) => {
      const todos = role === "user" ? view.userTodos : view.agentTodos;
      return {
        open: total.open + (todos?.open_count ?? 0),
        total: total.total + (todos?.total_count ?? 0),
      };
    },
    { open: 0, total: 0 },
  );
}

function quotaStateForShare(row?: GoalDirectoryRow) {
  return row?.queueItem?.project_asset?.quota?.state ?? row?.queueItem?.quota?.state ?? row?.goal.quota?.state ?? "waiting";
}

function quotaForShare(row?: GoalDirectoryRow) {
  return row?.queueItem?.project_asset?.quota ?? row?.queueItem?.quota ?? row?.goal.quota;
}

function shareStatusForGoal(view: ShareGoalView): { label: string; summary: string; variant: BadgeVariant } {
  const quota = quotaForShare(view.row);
  const quotaState = quota?.state ?? "waiting";
  if (!view.row) {
    return {
      label: "未接入",
      summary: "全局状态里还没有这个目标的当前投影。",
      variant: "neutral",
    };
  }
  if (isOutcomeFloorRecoveryQuota(quota)) {
    const gap = view.row.queueItem?.handoff_readiness?.post_handoff_outcome_gap_streak ?? quota?.post_handoff_outcome_gap_streak ?? 0;
    return {
      label: "需要 Codex 恢复",
      summary: `连续 ${gap || 1} 次产出差距；下一步只做 ${recoveryEvidenceLabel(quota)}，或写回具体阻塞。`,
      variant: "warning",
    };
  }
  if (view.spec.id === "showcase-user-gate-safe-side-path" && (view.userTodos?.open_count ?? 0) > 0) {
    return {
      label: "用户待办已捕获",
      summary: "用户决策被单独留给负责人；Agent 只推进与该决策独立的安全侧路。",
      variant: "warning",
    };
  }
  if (view.spec.id === "showcase-creator-operator") {
    return {
      label: "合成场景主动推进",
      summary: "创作运营待办可持续推进，但前台只呈现公开演示和合成数据。",
      variant: "info",
    };
  }
  if (view.spec.id === "loopx-meta") {
    return {
      label: "控制面健康",
      summary: "全局注册表、配额守卫和活动状态刷新处于可观测闭环。",
      variant: "success",
    };
  }
  if (quotaState === "eligible") {
    return {
      label: "可自动推进",
      summary: "当前没有用户闸门，Agent 可做一个有边界、有验证、有写回的小段推进。",
      variant: "success",
    };
  }
  return {
    label: shareQuotaLabel[quotaState] ?? shareMachineLabel(quotaState),
    summary: compactShareText(quota?.reason ?? view.row.queueItem?.recommended_action, 118),
    variant: quotaVariant(quotaState),
  };
}

function ShareDecisionFrame({
  status,
  view,
}: {
  status: ReturnType<typeof shareStatusForGoal>;
  view: ShareGoalView;
}) {
  const projectAsset = view.row?.queueItem?.project_asset;
  const waitingOwnerRaw = projectAsset?.owner ?? view.row?.waitingOn ?? "clear";
  const waitingOwner = shareWaitingLabel[waitingOwnerRaw] ?? (shareMachineLabel(waitingOwnerRaw) || waitingOwnerRaw);
  const recommendedAction = projectAsset?.next_action ?? view.row?.queueItem?.recommended_action ?? status.summary;
  const safetyBoundary = projectAsset?.stop_condition
    ?? view.row?.queueItem?.next_handoff_condition
    ?? "未显式授权写入或生产动作；只按当前配额和交接边界推进。";
  const firstUserTodo = firstOpenTodo(view.userTodos);
  const firstAgentTodo = firstOpenTodo(view.agentTodos);
  const missingTodoRoles = projectAsset?.todo_projection_gap?.missing_roles?.length
    ? projectAsset.todo_projection_gap.missing_roles.join(", ")
    : null;

  const rows: Array<readonly [string, string]> = [
    ["等待方", waitingOwner],
    ["推荐动作", compactShareText(recommendedAction, 108)],
    ["安全边界", compactShareText(safetyBoundary, 108)],
    ["首个用户 Todo", compactShareText(firstUserTodo?.text, 108)],
    ["最高优 Agent Todo", compactShareText(firstAgentTodo?.text, 108)],
  ];
  if (missingTodoRoles) {
    rows.push(["Todo 投影缺口", `缺少角色：${missingTodoRoles}`]);
  }

  return (
    <div
      className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3"
      data-testid={`share-decision-frame-${view.spec.id}`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge variant="neutral">第一屏决策帧</Badge>
        <span className="text-[11px] font-medium text-slate-500">先看等谁、能否推进、边界和下一步。</span>
      </div>
      <div className="grid gap-2 text-xs leading-5">
        {rows.map(([label, value]) => (
          <div className="grid grid-cols-[92px_minmax(0,1fr)] gap-2" key={label}>
            <div className="font-semibold text-slate-500">{label}</div>
            <div className="line-clamp-2 break-words font-medium text-slate-800">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function shareStatusText(row?: GoalDirectoryRow) {
  if (!row) {
    return "未接入";
  }
  return shareMachineLabel(row.status);
}

function ShareKpi({
  icon: Icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "success" | "warning" | "info" | "danger";
}) {
  const toneClass = {
    neutral: "border-slate-200 bg-white text-slate-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-950",
    warning: "border-amber-200 bg-amber-50 text-amber-950",
    info: "border-sky-200 bg-sky-50 text-sky-950",
    danger: "border-rose-200 bg-rose-50 text-rose-950",
  }[tone];
  return (
    <div className={cn("min-h-28 rounded-lg border px-4 py-3", toneClass)}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-current/70">{label}</div>
        <Icon className="h-4 w-4 text-current/60" />
      </div>
      <div className="mt-3 text-3xl font-semibold tracking-normal">{value}</div>
      <div className="mt-1 text-xs leading-5 text-current/70">{detail}</div>
    </div>
  );
}

function ShareProjectCard({ view }: { view: ShareGoalView }) {
  const Icon = view.spec.icon;
  const status = shareStatusForGoal(view);
  const quota = quotaForShare(view.row);
  const usage = view.usage;
  const dependencyBlockers = view.row?.queueItem?.dependency_blockers;
  const readiness = view.row?.queueItem?.handoff_readiness;
  const latest = readiness?.post_handoff_latest_run;
  const lastEvidence = latest
    ? [
      shareMachineLabel(latest.classification),
      latest.delivery_batch_scale ? `规模 ${shareMachineLabel(latest.delivery_batch_scale)}` : null,
      latest.delivery_outcome ? `结果 ${shareMachineLabel(latest.delivery_outcome)}` : null,
    ].filter(Boolean).join(" · ")
    : shareStatusText(view.row);

  return (
    <article
      className={cn(
        "grid min-h-[520px] content-between rounded-lg border border-slate-200 bg-white p-4 shadow-sm",
        "border-t-4",
        view.spec.accent,
      )}
      data-goal-id={view.spec.id}
    >
      <div className="min-w-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Icon className="h-4 w-4 text-slate-600" />
              <h3 className="text-xl font-semibold tracking-normal text-slate-950">{view.spec.label}</h3>
            </div>
            <p className="mt-1 text-sm font-medium text-slate-500">{view.spec.subtitle}</p>
          </div>
          <Badge variant={status.variant}>{status.label}</Badge>
        </div>
        <p className="mt-3 text-sm leading-6 text-slate-700">{view.spec.emphasis}</p>
        <ShareDecisionFrame status={status} view={view} />

        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          <div className="rounded-md border border-slate-200 bg-slate-50 px-2 py-2">
            <div className="text-lg font-semibold text-slate-950">{shareTodoCount(view.userTodos)}</div>
            <div className="text-[11px] font-medium text-slate-500">用户待办</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 px-2 py-2">
            <div className="text-lg font-semibold text-slate-950">{shareTodoCount(view.agentTodos)}</div>
            <div className="text-[11px] font-medium text-slate-500">Agent 待办</div>
          </div>
          <div className="rounded-md border border-slate-200 bg-slate-50 px-2 py-2">
            <div className="text-lg font-semibold text-slate-950">{usage?.progress_signal_run_count_24h ?? 0}</div>
            <div className="text-[11px] font-medium text-slate-500">24h 进展</div>
          </div>
        </div>

        <div className="mt-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <div className="text-xs font-semibold text-slate-500">前 4 个 Todo</div>
            <div className="flex flex-wrap gap-1">
              <Badge variant="warning">待用户</Badge>
              <Badge variant="info">待 Agent</Badge>
              <Badge variant="success">已完成</Badge>
              {dependencyBlockers?.open_count ? <Badge variant="warning">依赖 {dependencyBlockers.open_count}</Badge> : null}
            </div>
          </div>
          <ShareTopTodoList view={view} />
          <ShareDependencyBlockerList className="mt-2" view={view} />
          <ShareDecisionFreshnessWarning className="mt-2" view={view} />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3">
        <Badge variant={quotaVariant(quota?.state)}>{shareQuotaLabel[quota?.state ?? "waiting"] ?? (shareMachineLabel(quota?.state) || "等待下一步")}</Badge>
        <Badge variant="neutral">{shareWaitingLabel[view.row?.waitingOn ?? "clear"] ?? shareMachineLabel(view.row?.waitingOn)}</Badge>
        <Badge variant={view.row?.queueItem?.handoff_readiness?.ready ? "success" : "warning"}>
          {view.row?.queueItem?.handoff_readiness?.ready ? "交接可执行" : "交接受控"}
        </Badge>
        <span className="line-clamp-1 min-w-0 flex-1 text-xs text-slate-500">{lastEvidence}</span>
      </div>
    </article>
  );
}

function ShareTodoMatrix({ views }: { views: ShareGoalView[] }) {
  return (
    <section
      className="rounded-xl border border-slate-200 bg-white px-5 py-5 shadow-sm"
      data-testid="share-todo-matrix"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">Todo 责任矩阵</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            重点不是把所有项目都自动化掉，而是把“该人判断”和“该 Agent 推进”分清楚。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="warning">待用户</Badge>
          <Badge variant="info">待 Agent</Badge>
          <Badge variant="success">已完成</Badge>
        </div>
      </div>
      <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
        <div className="grid grid-cols-[170px_minmax(0,1fr)_220px] gap-0 bg-slate-50 text-xs font-semibold text-slate-500">
          <div className="px-3 py-2">项目</div>
          <div className="px-3 py-2">前 4 个 Todo（含状态）</div>
          <div className="px-3 py-2 text-right">控制状态</div>
        </div>
        <div className="divide-y divide-slate-200">
          {views.map((view) => {
            const status = shareStatusForGoal(view);
            const dependencyOpen = view.row?.queueItem?.dependency_blockers?.open_count ?? 0;
            return (
              <div
                className="grid min-h-[180px] grid-cols-[170px_minmax(0,1fr)_220px] gap-0 bg-white"
                key={view.spec.id}
              >
                <div className="px-3 py-3">
                  <div className="text-sm font-semibold text-slate-950">{view.spec.label}</div>
                  <div className="mt-1 text-[11px] leading-4 text-slate-500">{view.spec.subtitle}</div>
                </div>
                <div className="border-l border-slate-200 px-3 py-3">
                  <ShareTopTodoList compact view={view} />
                  <div className="mt-2 flex flex-wrap gap-2 text-xs font-medium">
                    <span className="text-amber-700">用户 {shareTodoCount(view.userTodos)}</span>
                    <span className="text-sky-700">Agent {shareTodoCount(view.agentTodos)}</span>
                    {dependencyOpen > 0 ? <span className="text-amber-700">依赖阻塞 {dependencyOpen}</span> : null}
                  </div>
                  <ShareDependencyBlockerList className="mt-2" compact view={view} />
                  <ShareDecisionFreshnessWarning className="mt-2" compact view={view} />
                </div>
                <div className="border-l border-slate-200 px-3 py-3 text-right">
                  <Badge variant={status.variant}>{status.label}</Badge>
                  <p className="mt-2 line-clamp-3 text-xs leading-5 text-slate-500">{status.summary}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

type ShareSignalTone = "rose" | "amber" | "emerald";

function ShareSignalCard({
  body,
  icon: Icon,
  metrics,
  status,
  steps,
  title,
  tone,
}: {
  body: string;
  icon: React.ComponentType<{ className?: string }>;
  metrics: { label: string; value: string }[];
  status: { label: string; variant: BadgeVariant };
  steps: { label: string; value: string }[];
  title: string;
  tone: ShareSignalTone;
}) {
  const toneClass = {
    rose: {
      border: "border-rose-200",
      header: "bg-rose-50 text-rose-950",
      icon: "bg-rose-100 text-rose-700",
      rule: "border-rose-200",
      text: "text-rose-950",
    },
    amber: {
      border: "border-amber-200",
      header: "bg-amber-50 text-amber-950",
      icon: "bg-amber-100 text-amber-700",
      rule: "border-amber-200",
      text: "text-amber-950",
    },
    emerald: {
      border: "border-emerald-200",
      header: "bg-emerald-50 text-emerald-950",
      icon: "bg-emerald-100 text-emerald-700",
      rule: "border-emerald-200",
      text: "text-emerald-950",
    },
  }[tone];

  return (
    <article className={cn("overflow-hidden rounded-xl border bg-white shadow-sm", toneClass.border)}>
      <div className={cn("flex min-h-[82px] items-start justify-between gap-3 px-5 py-4", toneClass.header)}>
        <div className="flex min-w-0 items-start gap-3">
          <div className={cn("mt-0.5 rounded-lg p-2", toneClass.icon)}>
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold tracking-normal">{title}</h2>
            <p className={cn("mt-1 text-sm leading-6", toneClass.text)}>{body}</p>
          </div>
        </div>
        <Badge variant={status.variant}>{status.label}</Badge>
      </div>

      <div className="px-5 py-4">
        <div className="grid grid-cols-3 gap-2">
          {metrics.map((metric) => (
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" key={metric.label}>
              <div className="text-[11px] font-medium text-slate-500">{metric.label}</div>
              <div className="mt-1 line-clamp-2 text-sm font-semibold leading-5 text-slate-950">{metric.value}</div>
            </div>
          ))}
        </div>
        <div className={cn("mt-4 grid grid-cols-3 gap-0 overflow-hidden rounded-lg border", toneClass.rule)}>
          {steps.map((step, index) => (
            <div
              className={cn(
                "bg-white px-3 py-3",
                index > 0 && "border-l",
                toneClass.rule,
              )}
              key={step.label}
            >
              <div className="text-[11px] font-semibold text-slate-500">{step.label}</div>
              <div className="mt-1 text-sm font-medium leading-5 text-slate-800">{step.value}</div>
            </div>
          ))}
        </div>
      </div>
    </article>
  );
}

function ShareGuardEvidence({
  payload,
  views,
}: {
  payload: StatusPayload;
  views: ShareGoalView[];
}) {
  const side = views.find((view) => view.spec.id === "showcase-side-agent-self-iteration");
  const creator = views.find((view) => view.spec.id === "showcase-creator-operator");
  const meta = views.find((view) => view.spec.id === "loopx-meta");
  const gate = views.find((view) => view.spec.id === "showcase-user-gate-safe-side-path");
  const sideGap = side?.row?.queueItem?.handoff_readiness?.post_handoff_outcome_gap_streak
    ?? side?.row?.queueItem?.quota?.post_handoff_outcome_gap_streak
    ?? 0;
  const creatorUsage = creator?.usage;
  const metaUsage = meta?.usage;

  return (
    <section
      className="rounded-2xl border border-slate-200 bg-white px-5 py-5 shadow-sm"
      data-testid="share-guard-evidence"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">限制条件与证据控制信号</h2>
          <p className="mt-1 text-sm leading-6 text-slate-600">
            控制面的价值不是继续制造 todo，而是把何时停、何时推进、何时写回变成同一套证据。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="warning">配额守卫</Badge>
          <Badge variant="info">证据等待</Badge>
          <Badge variant="success">状态写回</Badge>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr_1fr]">
        <ShareSignalCard
          body={`连续 ${sideGap || 3} 次产出差距后，控制面暂停自动消耗；没有排序器 / 跨域证据，只能给阻塞说明。`}
          icon={ShieldCheck}
          metrics={[
            { label: "触发阈值", value: `${sideGap || 3} 次产出差距` },
            { label: "禁止路径", value: "单面改动" },
            { label: "允许输出", value: "阻塞说明" },
          ]}
          status={{ label: "暂缓且不花配额", variant: "warning" }}
          steps={[
            { label: "触发", value: "表层小步重复" },
            { label: "控制", value: "暂缓不花配额" },
            { label: "写回", value: "证据或阻塞说明" },
          ]}
          title="独立同级 Agent：防止重复小步"
          tone="rose"
        />

        <ShareSignalCard
          body={`24h 已花 ${creatorUsage?.quota_spend_slots_24h ?? 0} 个配额槽，进展信号 ${creatorUsage?.progress_signal_run_count_24h ?? 0}；创作运营推进必须落到任务、证据、回顾或可展示产物。`}
          icon={Gauge}
          metrics={[
            { label: "24 小时配额", value: `${creatorUsage?.quota_spend_slots_24h ?? 0} 个槽位` },
            { label: "素材待办", value: "热点 / 洞察 / 语料" },
            { label: "展示边界", value: "仅合成数据" },
          ]}
          status={{ label: "主动推进", variant: "info" }}
          steps={[
            { label: "触发", value: "长期创作目标" },
            { label: "控制", value: "配额 + 证据边界" },
            { label: "写回", value: "演示结果 + 待办" },
          ]}
          title="创作者运营：持续运行的合成运营队列"
          tone="amber"
        />

        <ShareSignalCard
          body={`用户确认演示保留 ${gate?.userTodos?.open_count ?? 0} 个负责人决策；自举项目 24 小时进展信号 ${metaUsage?.progress_signal_run_count_24h ?? 0}，当前合约错误 ${payload.contract.summary.errors}。`}
          icon={FileCheck2}
          metrics={[
            { label: "公开用户确认", value: `${gate?.userTodos?.open_count ?? 0} 个未完成` },
            { label: "自举进展", value: `${metaUsage?.progress_signal_run_count_24h ?? 0} 个信号` },
            { label: "全局发现", value: `${payload.global_registry.summary.findings} 项` },
          ]}
          status={{ label: "已验证", variant: "success" }}
          steps={[
            { label: "触发", value: "状态刷新" },
            { label: "控制", value: "注册表事实来源" },
            { label: "写回", value: "活动状态写回" },
          ]}
          title="公开演示与自举：状态事实"
          tone="emerald"
        />
      </div>
    </section>
  );
}

function ShareAutonomousBacklog({
  summary,
}: {
  summary?: StatusPayload["attention_queue"]["autonomous_backlog_candidates"];
}) {
  const items = summary?.items ?? [];
  if (!summary || summary.open_count === 0 || items.length === 0) {
    return null;
  }
  return (
    <div className="mt-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-3" data-testid="share-autonomous-backlog">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-sky-700" />
          <div className="text-sm font-semibold text-sky-950">可自动推进候选</div>
        </div>
        <Badge variant="info">{summary.open_count}</Badge>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        {items.slice(0, 3).map((candidate, index) => (
          <div className="rounded-md border border-sky-200 bg-white px-3 py-2" key={`${candidate.goal_id}-${candidate.todo_index ?? index}`}>
            <div className="flex flex-wrap items-center gap-2">
              <span className="break-all text-[11px] font-semibold text-sky-700">{candidate.goal_id}</span>
              {candidate.priority ? <Badge variant="info">{candidate.priority}</Badge> : null}
            </div>
            <p className="mt-1 line-clamp-2 break-words text-sm leading-6 text-slate-700">
              {compactShareText(candidate.text, 118)}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function eventClassCount(
  counts: EventLedgerSummary["totals"]["by_class_24h"] | EventLedgerSummary["totals"]["by_class_7d"] | undefined,
  eventClass: EventLedgerClass,
) {
  return counts?.[eventClass] ?? 0;
}

function EventClassPill({
  counts,
  eventClass,
}: {
  counts?: EventLedgerSummary["totals"]["by_class_24h"] | EventLedgerSummary["totals"]["by_class_7d"];
  eventClass: EventLedgerClass;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-center shadow-sm">
      <div className="text-lg font-semibold text-slate-950">{eventClassCount(counts, eventClass)}</div>
      <div className="mt-0.5 text-[11px] font-medium text-slate-500">{eventClassLabel[eventClass]}</div>
    </div>
  );
}

function ShareEventLedgerStrip({ summary }: { summary?: EventLedgerSummary | null }) {
  if (!summary?.available) {
    return null;
  }
  const totals = summary.totals;
  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3" data-testid="share-event-ledger">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-slate-700" />
          <div>
            <div className="text-sm font-semibold text-slate-950">控制面事件账本投影</div>
            <p className="mt-0.5 text-xs leading-5 text-slate-500">
              对话任务只是工作入口；这里展示的是运行历史的精简事件投影。
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="neutral">{summary.source}</Badge>
          <Badge variant="info">{summary.sample_run_count} 个样本</Badge>
          <Badge variant="success">24h {totals.events_24h}</Badge>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-5">
        {eventClassOrder.map((eventClass) => (
          <EventClassPill counts={totals.by_class_24h} eventClass={eventClass} key={eventClass} />
        ))}
      </div>
    </div>
  );
}

function ShareEvidenceView({
  isLoading,
  onRefresh,
  payload,
  rows,
  source,
  theme,
  toggleTheme,
}: {
  isLoading: boolean;
  onRefresh: () => void;
  payload: StatusPayload;
  rows: GoalDirectoryRow[];
  source: DataSource;
  theme: "light" | "dark";
  toggleTheme: () => void;
}) {
  const rowById = shareRowById(rows);
  const eventLedgerById = shareEventLedgerById(payload.event_ledger_summary);
  const decisionFreshnessById = shareDecisionFreshnessById(payload.decision_freshness_summary);
  const usageById = shareUsageById(payload.usage_summary);
  const views = shareGoalSpecs.map((spec): ShareGoalView => {
    const row = rowById.get(spec.id);
    return {
      agentTodos: getShareTodos(row, "agent"),
      decisionFreshnessWarnings: decisionFreshnessById.get(spec.id) ?? [],
      eventLedger: eventLedgerById.get(spec.id),
      row,
      spec,
      usage: usageById.get(spec.id),
      userTodos: getShareTodos(row, "user"),
    };
  });
  const userOpenTotal = shareOpenTotal(views, "user");
  const agentOpenTotal = shareOpenTotal(views, "agent");
  const blockedCount = views.filter((view) => shareStatusForGoal(view).label.includes("暂缓")).length;
  const automation = payload.usage_summary?.totals.automation_run_count_24h ?? 0;
  const ledgerTotals = payload.event_ledger_summary?.totals;
  const progress = payload.usage_summary?.totals.progress_signal_run_count_24h ?? 0;
  const ledgerWork = eventClassCount(ledgerTotals?.by_class_24h, "work");
  const ledgerEvidence = eventClassCount(ledgerTotals?.by_class_24h, "evidence");

  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <main className="min-h-screen bg-[#f7f7f4] text-slate-950">
        <div className="mx-auto max-w-[1500px] space-y-5 px-5 py-5">
          <section
            className="rounded-2xl border border-slate-200 bg-white px-4 py-5 shadow-sm sm:px-6 sm:py-6"
            data-testid="share-overview"
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="success">LoopX 控制面</Badge>
                  <Badge variant="neutral">公开演示</Badge>
                  <Badge data-testid="share-source-label" title={source.label} variant="neutral">
                    {source.kind === "example" ? "内置示例" : source.kind === "url" ? "实时状态" : "导入文件"}
                  </Badge>
                  <Badge variant={payload.ok ? "success" : "danger"}>{payload.ok ? "状态健康" : "健康阻塞"}</Badge>
                </div>
                <h1 className="mt-3 text-3xl font-semibold leading-tight tracking-normal text-slate-950 sm:text-4xl sm:leading-tight">
                  把多项目 Agent 工作变成可管理的 Todo、证据和配额
                </h1>
                <p className="mt-3 max-w-3xl text-base leading-7 text-slate-600">
                  这个看板只展示公开演示：用户确认、平级 Agent 自迭代、创作者运营和 LoopX 自举统一到同一套控制面。
                  用户待办单独挂起，Agent 高优任务继续推进，配额守卫和交接合约负责防止重复空转。
                </p>
              </div>
              <div className="flex gap-2">
                <Button disabled={isLoading} onClick={toggleTheme} variant="secondary">
                  {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                  主题
                </Button>
                <Button disabled={isLoading} onClick={onRefresh} variant="primary">
                  <RefreshCw className="h-4 w-4" />
                  刷新证据
                </Button>
              </div>
            </div>

            <div className="mt-4">
              <StatusContractFreshnessWarning payload={payload} source={source} />
            </div>

            <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <ShareKpi
                detail="分享重点项目"
                icon={GitBranch}
                label="覆盖项目"
                value={String(views.length)}
              />
              <ShareKpi
                detail="打开 / 总数"
                icon={Users}
                label="用户待办"
                tone={userOpenTotal.open > 0 ? "warning" : "success"}
                value={`${userOpenTotal.open}/${userOpenTotal.total}`}
              />
              <ShareKpi
                detail="打开 / 总数"
                icon={Bot}
                label="Agent 待办"
                tone={agentOpenTotal.open > 0 ? "info" : "success"}
                value={`${agentOpenTotal.open}/${agentOpenTotal.total}`}
              />
              <ShareKpi
                detail={`${progress} 个进展信号；账本工作项 ${ledgerWork}`}
                icon={Gauge}
                label="24h 自动回合"
                tone="info"
                value={String(automation)}
              />
              <ShareKpi
                detail={`${ledgerEvidence} 个证据观察；重复小步会被拦住`}
                icon={ShieldCheck}
                label="暂缓不花配额"
                tone={blockedCount > 0 ? "warning" : "success"}
                value={String(blockedCount)}
              />
            </div>

            <ShareAutonomousBacklog summary={payload.attention_queue.autonomous_backlog_candidates} />
            <ShareEventLedgerStrip summary={payload.event_ledger_summary} />

            <div className="mt-5 grid gap-4 lg:grid-cols-2">
              {views.map((view) => (
                <ShareProjectCard key={view.spec.id} view={view} />
              ))}
            </div>
          </section>

          <ShareTodoMatrix views={views} />
          <ShareGuardEvidence payload={payload} views={views} />
        </div>
      </main>
    </div>
  );
}

function buildHumanFriendlyActionPacket({
  item,
  registry,
  runtimeRoot,
}: {
  item: UserActionSummaryItem;
  registry: string;
  runtimeRoot: string;
}) {
  const prompt = humanReviewPrompt(item.kind);
  const quotaView = buildQuotaView(item.quota);
  const handoffReadiness = buildHandoffReadinessView(item.handoffReadiness);
  const todo = firstOpenTodo(item.userTodos);
  const agentTodo = firstOpenTodo(item.agentTodos);
  const approvedAgentCommand = item.kind === "codex" && Boolean(item.agentCommand);
  const isFocusWait = isFocusWaitQuota(item.quota);
  const isRecoveryFocusWait = isOutcomeFloorRecoveryQuota(item.quota);
  const command = isFocusWait
    ? buildStatusCommand({ registry, runtimeRoot })
    : item.safePathCommand ?? item.agentCommand ?? buildStatusCommand({ registry, runtimeRoot });
  if (isRecoveryFocusWait) {
    const evidenceLabel = recoveryEvidenceLabel(item.quota);
    return buildActionPacket({
      goalId: item.goalId,
      title: item.title,
      summary: item.summary,
      userTodoText: todo?.text,
      agentTodoText: agentTodo?.text ?? `只做一次${evidenceLabel}恢复任务；如果证据范围不可用，写回具体阻塞原因后停止。`,
      todoBlocksGate: false,
      operatorQuestion: null,
      suggestedReply: `执行一次结果下限恢复任务：只做${evidenceLabel}或写回具体阻塞原因；完成验证和状态写回后再记一次配额。`,
      gateFallbackDecision: `执行一次结果下限恢复任务：只做${evidenceLabel}或写回具体阻塞原因。`,
      boundary: "普通交付仍被结果下限阻塞；不要继续摘要、队列、合同等表层传播，也不要做仅含合成数据的测试链。",
      durableRecordRule: "记录规则：已验证证据或阻塞原因 -> 刷新状态或运行事件 -> 只记一次配额；没有完成恢复产物就不记配额。",
      safePathLabel: item.safePathLabel || "恢复任务交接",
      command: item.safePathCommand ?? command,
      quotaShortLine: quotaView?.shortLine,
      authorityShortLine: item.authorityCoverage?.shortLine,
      projectOwner: item.projectOwner,
      projectGate: item.projectGate,
      projectNextAction: item.projectNextAction,
      projectStopCondition: item.projectStopCondition,
      projectAssetSource: item.projectAssetSource,
      handoffReadinessLine: handoffReadiness?.shortLine,
    });
  }
  if (isFocusWait) {
    return buildActionPacket({
      goalId: item.goalId,
      title: item.title,
      summary: item.summary,
      userTodoText: todo?.text,
      agentTodoText: agentTodo?.text ?? "只检查当前状态和历史；保持重点等待，并用中文回报仍在等待什么。",
      todoBlocksGate: false,
      operatorQuestion: null,
      suggestedReply: "继续保持重点等待；有新的负责人证据、干净基线或外部评估后再恢复交付。",
      gateFallbackDecision: "继续保持重点等待；有新的负责人证据、干净基线或外部评估后再恢复交付。",
      boundary: "这不是交付审批；项目 Agent 只做状态和历史检查，不执行交付路径、写入、追加评价或生产动作。",
      durableRecordRule: null,
      safePathLabel: "只检查状态和历史",
      command,
      quotaShortLine: quotaView?.shortLine,
      authorityShortLine: item.authorityCoverage?.shortLine,
      projectOwner: item.projectOwner,
      projectGate: item.projectGate,
      projectNextAction: item.projectNextAction,
      projectStopCondition: item.projectStopCondition,
      projectAssetSource: item.projectAssetSource,
      handoffReadinessLine: handoffReadiness?.shortLine,
    });
  }
  if (approvedAgentCommand && item.agentCommand) {
    return buildApprovedAgentHandoff({
      goalId: item.goalId,
      command: item.agentCommand,
      agentTodoText: agentTodo?.text,
      projectNextAction: item.projectNextAction,
      projectStopCondition: item.projectStopCondition,
      projectAssetSource: item.projectAssetSource,
    });
  }
  const reply = item.kind === "controller"
    ? controllerReplyLine(item.goalId)
    : approvedAgentCommand
      ? "转发下方【给项目 Agent】即可。"
      : prompt.reply;
  const todoBlocksGate = Boolean(todo && item.operatorQuestion);
  return buildActionPacket({
    goalId: item.goalId,
    title: item.title,
    summary: item.summary,
    userTodoText: todo?.text,
    agentTodoText: agentTodo?.text,
    todoBlocksGate,
    operatorQuestion: item.operatorQuestion,
    suggestedReply: reply,
    gateFallbackDecision: approvedAgentCommand
      ? "直接转发给已认领的项目 Agent；不追加写权限、全局接管或生产动作授权。"
      : suggestedDecisionLine(item.kind, item, item.goalId),
    boundary: approvedAgentCommand
      ? "只执行已批准的只读预演命令（agent_command）；如需写入或更高权限，项目 Agent 必须再次停下。"
      : prompt.boundary,
    durableRecordRule: durableOperatorGateRecordRule(item.kind),
    safePathLabel: approvedAgentCommand ? "已批准 Agent 命令" : item.safePathLabel,
    command,
    quotaShortLine: quotaView?.shortLine,
    authorityShortLine: item.authorityCoverage?.shortLine,
    projectOwner: item.projectOwner,
    projectGate: item.projectGate,
    projectNextAction: item.projectNextAction,
    projectStopCondition: item.projectStopCondition,
    projectAssetSource: item.projectAssetSource,
    handoffReadinessLine: handoffReadiness?.shortLine,
  });
}

function readinessVariant(readiness: ControllerReadiness): "success" | "warning" | "info" {
  if (readiness.decision_advisor_ready) {
    return "success";
  }
  if (readiness.read_only_observer_ready) {
    return "info";
  }
  return "warning";
}

function gateLabel(value: string) {
  const labels: Record<string, string> = {
    human_reward_capture: "记录人工评价",
    aligned_eval_decision_evidence: "等待可比较的证据",
    durable_goal_context: "保留持久 Goal 上下文",
  };
  return labels[value] ?? value;
}

function buildStatusCommand({
  registry,
  runtimeRoot,
}: {
  registry: string;
  runtimeRoot: string;
}) {
  return [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  --format json \\",
    "  status",
  ].join("\n");
}

function buildHistoryCommand({
  goalId,
  registry,
  runtimeRoot,
}: {
  goalId: string;
  registry: string;
  runtimeRoot: string;
}) {
  return [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  history \\",
    `  --goal-id ${shellQuote(goalId)} \\`,
    "  --limit 3",
  ].join("\n");
}

function buildReadOnlyMapDryRunCommand({
  goalId,
  registry,
  runtimeRoot,
}: {
  goalId: string;
  registry: string;
  runtimeRoot: string;
}) {
  return [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  read-only-map \\",
    `  --goal-id ${shellQuote(goalId)} \\`,
    "  --dry-run",
  ].join("\n");
}

function buildRefreshStateDryRunCommand({
  goalId,
  registry,
  runtimeRoot,
}: {
  goalId: string;
  registry: string;
  runtimeRoot: string;
}) {
  return [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  refresh-state \\",
    `  --goal-id ${shellQuote(goalId)} \\`,
    "  --dry-run",
  ].join("\n");
}

function buildOperatorGateDryRunCommand({
  goalId,
  registry,
  runtimeRoot,
}: {
  goalId: string;
  registry: string;
  runtimeRoot: string;
}) {
  return [
    "loopx \\",
    `  --registry ${shellQuote(registry)} \\`,
    `  --runtime-root ${shellQuote(runtimeRoot)} \\`,
    "  operator-gate \\",
    `  --goal-id ${shellQuote(goalId)} \\`,
    "  --decision approve \\",
    `  --reason-summary ${shellQuote(controllerApprovalReason(goalId))} \\`,
    "  --dry-run",
  ].join("\n");
}

function buildOperatorDecision({
  goal,
  queueItem,
}: {
  goal?: RunGoal;
  queueItem?: QueueItem;
}): OperatorDecision {
  const latestRun = goal?.latest_runs[0];
  const phase = goal?.lifecycle_phase
    ?? queueItem?.lifecycle_phase
    ?? latestRun?.lifecycle_phase
    ?? inferLifecyclePhase(queueItem?.status ?? goal?.status, latestRun);
  const waitingOn = queueItem?.waiting_on ?? "clear";
  const quota = queueItem?.project_asset?.quota ?? queueItem?.quota ?? goal?.quota;
  const missingGates = queueItem?.missing_gates ?? latestRun?.controller_readiness?.missing_gates ?? [];
  const action = queueItem?.recommended_action
    ?? latestRun?.recommended_action
    ?? "当前不需要操作者立即处理。";

  if (queueItem?.severity === "high") {
    return {
      title: "先修复健康问题",
      badge: "正在阻塞",
      variant: "danger" as BadgeVariant,
      action,
      reason: "当前存在高严重级别问题，其他决策需要先等待。",
      needs: missingGates.map(gateLabel),
      phase,
      waitingOn,
    };
  }

  if (waitingOn === "external_evidence") {
    return {
      title: "等待证据",
      badge: phase === "controller_gated" ? "缺少确认条件" : "观察中",
      variant: "info" as BadgeVariant,
      action,
      reason: phase === "controller_gated"
        ? "已有控制者证据，但这个 Goal 仍缺少决策确认。"
        : "下一条有用信号来自 Agent 循环之外。",
      needs: missingGates.map(gateLabel),
      phase,
      waitingOn,
    };
  }

  if (waitingOn === "user_or_controller" || waitingOn === "controller") {
    const controllerCopy = phase === "planned"
      ? {
          title: "审阅控制者接入",
          badge: "需要批准",
          reason: "已经识别这个 Goal，但尚未授权控制者接入。",
        }
      : {
          title: "审阅或授权",
          badge: "等待用户决定",
          reason: "下一步需要人工或目标控制者作出决定。",
        };
    return {
      ...controllerCopy,
      variant: "warning" as BadgeVariant,
      action,
      needs: missingGates.map(gateLabel),
      phase,
      waitingOn,
    };
  }

  if (waitingOn === "codex") {
    if (isOutcomeFloorRecoveryQuota(quota)) {
      return {
        title: "执行恢复证据任务",
        badge: "Codex 恢复",
        variant: "warning" as BadgeVariant,
        action,
        reason: `结果下限阻止了普通交付；Codex 应执行一次有边界的${recoveryEvidenceLabel(quota)}恢复任务，或写回具体阻塞原因。`,
        needs: missingGates.map(gateLabel),
        phase,
        waitingOn,
      };
    }
    if (quota?.state === "throttled" || quota?.state === "paused" || quota?.state === "focus_wait") {
      const restrictedCopy = quota.state === "throttled"
        ? { title: "等待配额恢复", badge: "已限流" }
        : quota.state === "paused"
          ? { title: "自动推进已暂停", badge: "已暂停" }
          : { title: "保持重点等待", badge: "重点等待" };
      return {
        ...restrictedCopy,
        variant: quota.state === "paused" ? "neutral" as BadgeVariant : "warning" as BadgeVariant,
        action,
        reason: buildQuotaView(quota)?.reviewLine ?? "当前控制面状态不允许开始新的 Agent 回合。",
        needs: missingGates.map(gateLabel),
        phase,
        waitingOn,
      };
    }
    const codexCopy = queueItem?.agent_command
      ? {
          title: "执行已批准的 Agent 命令",
          badge: "已批准交接",
          reason: "操作者已经批准，因此配额判断可以放行这条 Agent 命令。",
        }
      : phase === "mapped"
      ? {
          title: "让 Codex 使用项目映射",
          badge: "Codex 可以继续",
          reason: "项目已有只读映射；下一个 Agent 回合可以选择交接方式。",
        }
      : phase === "refreshed"
        ? {
            title: "让 Codex 继续",
            badge: "状态已刷新",
            reason: "Goal 状态已经变化，Agent 可以从刷新后的动作继续。",
          }
        : phase === "connected"
          ? {
              title: "让 Codex 创建第一次运行",
              badge: "需要首次运行",
              reason: "这个 Goal 已接入，但还没有产生精简运行记录。",
            }
          : {
              title: "让 Codex 继续",
              badge: "Codex 可以执行",
              reason: "这个 Goal 当前没有等待人工决策。",
            };
    return {
      ...codexCopy,
      variant: "success" as BadgeVariant,
      action,
      needs: missingGates.map(gateLabel),
      phase,
      waitingOn,
    };
  }

  if (phase === "reward_judged") {
    return {
      title: "已记录评价",
      badge: "已评价",
      variant: "success" as BadgeVariant,
      action,
      reason: "人工反馈已附加到最近一次运行。",
      needs: missingGates.map(gateLabel),
      phase,
      waitingOn,
    };
  }

  return {
    title: "用户无需立即操作",
    badge: "无需处理",
    variant: "neutral" as BadgeVariant,
    action,
    reason: "所选 Goal 当前没有需要关注的事项。",
    needs: missingGates.map(gateLabel),
    phase,
    waitingOn,
  };
}

function existingRewardValue(reward?: HumanReward | null): RewardValue {
  const value = reward?.reward;
  return rewardOptions.includes(value as RewardValue) ? value as RewardValue : "neutral";
}

function buildRewardDraftDefaults({
  goal,
  queueItem,
}: {
  goal?: RunGoal;
  queueItem?: QueueItem;
}): RewardDraftDefaults {
  const latestRun = goal?.latest_runs[0];
  const operatorDecision = buildOperatorDecision({ goal, queueItem });
  const quota = queueItem?.project_asset?.quota ?? queueItem?.quota ?? goal?.quota;
  const missingGates = new Set(queueItem?.missing_gates ?? latestRun?.controller_readiness?.missing_gates ?? []);
  const handoffCondition = queueItem?.next_handoff_condition
    ?? latestRun?.controller_readiness?.next_handoff_condition
    ?? "";

  if (latestRun?.human_reward) {
    return {
      decision: "review_existing_reward",
      reward: existingRewardValue(latestRun.human_reward),
      reasonSummary: "已经存在人工评价；添加新评价前请先审阅。",
      followUp: "把最近一次已评价运行作为下一轮 Agent 上下文。",
      label: "已有评价",
    };
  }

  if (queueItem?.severity === "high") {
    return {
      decision: "fix_health_first",
      reward: "negative",
      reasonSummary: "健康问题正在阻止批准或交接。",
      followUp: "先修复阻塞状态，再记录批准或启动后续工作。",
      label: "阻塞状态",
    };
  }

  if (operatorDecision.waitingOn === "external_evidence") {
    const needsReward = missingGates.has("human_reward_capture");
    return {
      decision: needsReward ? "record_human_reward_gate" : "watch_external_evidence",
      reward: "neutral",
      reasonSummary: needsReward
        ? "提供控制者决策建议前，需要操作者先做判断。"
        : "外部证据仍在等待中；这不代表已经批准。",
      followUp: handoffCondition || "先等待可比较的证据，再给出决策建议或启用写入控制。",
      label: needsReward ? "评价确认" : "证据观察",
    };
  }

  if (operatorDecision.waitingOn === "controller" || operatorDecision.waitingOn === "user_or_controller") {
    return {
      decision: operatorDecision.phase === "planned" ? "review_controller_opt_in" : "review_or_authorize",
      reward: "neutral",
      reasonSummary: "操作者正在审阅控制者确认；评价本身不会授予写入权限。",
      followUp: "追加控制者或写入控制状态前，先执行安全的试运行路径。",
      label: operatorDecision.phase === "planned" ? "控制者接入" : "操作者确认",
    };
  }

  if (isOutcomeFloorRecoveryQuota(quota)) {
    const evidenceLabel = recoveryEvidenceLabel(quota);
    return {
      decision: "run_outcome_floor_recovery",
      reward: "neutral",
      reasonSummary: `普通交付仍被结果下限阻塞；只允许一次${evidenceLabel}恢复任务或写回具体阻塞原因。`,
      followUp: "完成恢复证据和状态写回后，再重新判断是否允许普通交付。",
      label: "结果恢复",
    };
  }

  if (quota?.state === "throttled" || quota?.state === "paused" || (quota?.state === "focus_wait" && !isOutcomeFloorRecoveryQuota(quota))) {
    return {
      decision: "wait_for_control_plane",
      reward: "neutral",
      reasonSummary: buildQuotaView(quota)?.reviewLine ?? "当前控制面状态要求继续等待。",
      followUp: "配额或等待条件变化后，重新读取状态再决定是否继续。",
      label: quota.state === "throttled" ? "配额等待" : quota.state === "paused" ? "已暂停" : "重点等待",
    };
  }

  if (operatorDecision.waitingOn === "codex") {
    if (queueItem?.agent_command) {
      return {
        decision: "run_approved_agent_command",
        reward: "positive",
        reasonSummary: "操作者已经批准；Codex 可以使用已批准的 Agent 命令。",
        followUp: "只执行已批准的只读或试运行命令；写入或提高权限前必须停止。",
        label: "已批准命令",
      };
    }
    if (operatorDecision.phase === "mapped") {
      return {
        decision: "use_read_only_map",
        reward: "positive",
        reasonSummary: "只读映射已经足够支持下一次 Codex 交接。",
        followUp: "让 Codex 使用最新映射和历史；写入仍需单独批准。",
        label: "映射交接",
      };
    }
    if (operatorDecision.phase === "refreshed") {
      return {
        decision: "continue_from_refreshed_state",
        reward: "positive",
        reasonSummary: "刷新后的 Goal 状态为 Codex 提供了可用的下一步。",
        followUp: "让 Codex 先从刷新后的状态继续，再请求批准。",
        label: "状态刷新",
      };
    }
    return {
      decision: "continue_codex_action",
      reward: "neutral",
      reasonSummary: "Codex 可以继续，但这份评价只是试运行草稿。",
      followUp: "把安全命令路径作为下一轮 Agent 上下文。",
      label: "Codex 交接",
    };
  }

  return {
    decision: "review_latest_run",
    reward: "neutral",
    reasonSummary: operatorDecision.reason,
    followUp: "记录真实评价前先检查状态。",
    label: "操作者默认项",
  };
}

function buildUserActionSummaryItems({
  rows,
  registry,
  runtimeRoot,
}: {
  rows: GoalDirectoryRow[];
  registry: string;
  runtimeRoot: string;
}): UserActionSummaryItem[] {
  const items = rows.flatMap((row): UserActionSummaryItem[] => {
    const decision = buildOperatorDecision({ goal: row.goal, queueItem: row.queueItem });
    const draftDefaults = buildRewardDraftDefaults({ goal: row.goal, queueItem: row.queueItem });
    const bridge = buildOperatorActionBridge({
      goal: row.goal,
      queueItem: row.queueItem,
      registry,
      runtimeRoot,
    });
    const bridgeItem = bridge?.items.find((item) => item.command) ?? bridge?.items[0];
    const latestRun = row.latestRun;
    const authorityCoverage = buildAuthorityCoverage({ goal: row.goal, run: latestRun });
    const missingGates = new Set(row.queueItem?.missing_gates ?? latestRun?.controller_readiness?.missing_gates ?? []);
    const handoffCondition = row.queueItem?.next_handoff_condition
      ?? latestRun?.controller_readiness?.next_handoff_condition
      ?? "";
    const projectAsset = row.queueItem?.project_asset;
    const projectAssetSource: ProjectAssetSource = projectAsset ? "project_asset" : "legacy_raw_fallback";
    const quota = projectAsset?.quota ?? row.queueItem?.quota ?? row.goal.quota;
    const quotaState = quota?.state ?? "waiting";
    const userTodos = todosFromProjectAssetSummary(projectAsset?.user_todos, row.queueItem?.user_todos, "project_asset.user_todos");
    const agentTodos = todosFromProjectAssetSummary(projectAsset?.agent_todos, row.queueItem?.agent_todos, "project_asset.agent_todos");
    const nextAction = projectAsset?.next_action ?? decision.action;
    const stopCondition = projectAsset?.stop_condition ?? handoffCondition ?? decision.action;
    const latestValidation = projectAsset?.latest_validation;
    const handoffReadiness = row.queueItem?.handoff_readiness;
    const base = {
      goalId: row.goal.id,
      phase: decision.phase,
      waitingOn: decision.waitingOn,
      operatorQuestion: row.queueItem?.operator_question ?? undefined,
      agentCommand: row.queueItem?.agent_command ?? undefined,
      safePathLabel: bridgeItem?.label ?? bridge?.badge ?? "检查状态",
      safePathCommand: bridgeItem?.command,
      rewardHint: latestRun
        ? `${draftDefaults.decision} / ${draftDefaults.reward}`
        : `${draftDefaults.label} / 需要运行记录`,
      authorityCoverage,
      quota,
      userTodos,
      agentTodos,
      latestValidation,
      projectOwner: projectAsset?.owner,
      projectGate: projectAsset?.gate,
      projectNextAction: nextAction,
      projectStopCondition: stopCondition,
      projectAssetSource,
      handoffReadiness,
    };

    if (row.severity === "high") {
      return [{
        ...base,
        kind: "health",
        title: "先修复健康问题",
        badge: "正在阻塞",
        variant: "danger",
        summary: nextAction,
        detail: decision.reason,
        priority: 0,
      }];
    }

    if (missingGates.has("human_reward_capture")) {
      return [{
        ...base,
        kind: "reward",
        title: "记录人工评价",
        badge: "评价确认",
        variant: "warning",
        summary: draftDefaults.reasonSummary,
        detail: draftDefaults.followUp || stopCondition,
        draftLabel: draftDefaults.label,
        priority: 1,
      }];
    }

    if (decision.waitingOn === "controller" || decision.waitingOn === "user_or_controller") {
      return [{
        ...base,
        kind: "controller",
        title: decision.title,
        badge: decision.badge,
        variant: decision.variant,
        summary: row.queueItem?.operator_question ?? decision.reason,
        detail: stopCondition,
        draftLabel: draftDefaults.label,
        priority: 2,
      }];
    }

    if (decision.waitingOn === "external_evidence") {
      return [{
        ...base,
        kind: "evidence",
        title: "观察证据",
        badge: decision.badge,
        variant: "info",
        summary: decision.reason,
        detail: stopCondition,
        draftLabel: draftDefaults.label,
        priority: 3,
      }];
    }

    if (decision.waitingOn === "codex" && quotaState === "focus_wait") {
      if (isOutcomeFloorRecoveryQuota(quota)) {
        const evidenceLabel = recoveryEvidenceLabel(quota);
        return [{
          ...base,
          kind: "codex",
          title: "执行 Codex 恢复任务",
          badge: "恢复任务",
          variant: "warning",
          summary: `普通交付被结果下限阻塞；下一步只做一次${evidenceLabel}，或写回具体阻塞原因。`,
          detail: quota?.safe_bypass_policy ?? stopCondition,
          safePathLabel: "恢复任务交接",
          safePathCommand: buildHistoryCommand({ goalId: row.goal.id, registry, runtimeRoot }),
          draftLabel: "结果恢复",
          priority: 3,
        }];
      }
      const ownerTodo = firstOpenTodo(userTodos);
      return [{
        ...base,
        kind: "evidence",
        title: "重点等待负责人处理",
        badge: "重点等待",
        variant: "info",
        summary: ownerTodo
          ? `正在等待负责人处理：${ownerTodo.text}`
          : "恢复交付前，正在等待负责人证据、干净基线或外部评估。",
        detail: stopCondition,
        safePathLabel: "只检查状态和历史",
        safePathCommand: buildStatusCommand({ registry, runtimeRoot }),
        draftLabel: "重点等待",
        priority: 3,
      }];
    }

    if (decision.waitingOn === "codex" && (quotaState === "throttled" || quotaState === "paused")) {
      return [];
    }

    if (decision.waitingOn === "codex") {
      return [{
        ...base,
        kind: "codex",
        title: decision.title,
        badge: decision.badge,
        variant: "success",
        summary: draftDefaults.reasonSummary,
        detail: draftDefaults.followUp || stopCondition,
        draftLabel: draftDefaults.label,
        priority: 4,
      }];
    }

    if (decision.phase === "reward_judged") {
      return [{
        ...base,
        kind: "reward",
        title: "已记录评价",
        badge: "已评价",
        variant: "success",
        summary: decision.reason,
        detail: draftDefaults.followUp || stopCondition,
        draftLabel: draftDefaults.label,
        priority: 5,
      }];
    }

    return [];
  });

  return items.sort((a, b) => a.priority - b.priority || a.goalId.localeCompare(b.goalId));
}

function UserActionSummary({
  rows,
  selectedGoalId,
  onSelectGoal,
  selectedKind,
  onSelectKind,
  registry,
  runtimeRoot,
  source,
}: {
  rows: GoalDirectoryRow[];
  selectedGoalId: string;
  onSelectGoal: (goalId: string) => void;
  selectedKind: UserActionFilter;
  onSelectKind: (kind: UserActionFilter) => void;
  registry: string;
  runtimeRoot: string;
  source: DataSource;
}) {
  const items = buildUserActionSummaryItems({ rows, registry, runtimeRoot });
  const kindCounts = items.reduce<Record<UserActionKind, number>>((counts, item) => {
    counts[item.kind] += 1;
    return counts;
  }, {
    codex: 0,
    controller: 0,
    evidence: 0,
    health: 0,
    reward: 0,
  });
  const selectedKindCount = selectedKind === "all" ? items.length : kindCounts[selectedKind];
  const kindOptions = userActionKindOrder.filter((kind) => kindCounts[kind] > 0 || kind === selectedKind);
  const visibleItems = selectedKind === "all" ? items : items.filter((item) => item.kind === selectedKind);
  const showAllForEmptyFilter = selectedKind !== "all" && selectedKindCount === 0 && items.length > 0;
  const displayedItems = showAllForEmptyFilter ? items : visibleItems;
  const selectedKindLabel = selectedKind === "all" ? "全部" : userActionKindConfig[selectedKind].label;
  const [actionCopyState, setActionCopyState] = useState<{ key: string; state: CopyState } | null>(null);

  useEffect(() => {
    if (!actionCopyState || actionCopyState.state === "idle") {
      return;
    }
    const timeoutId = window.setTimeout(() => setActionCopyState(null), 1800);
    return () => window.clearTimeout(timeoutId);
  }, [actionCopyState]);

  async function copyActionPacket(item: UserActionSummaryItem) {
    const key = `${item.goalId}-${item.kind}-${item.title}`;
    const packet = buildHumanFriendlyActionPacket({ item, registry, runtimeRoot });
    setActionCopyState({ key, state: (await copyTextToClipboard(packet)) ? "copied" : "failed" });
  }

  return (
    <Card>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-4 w-4" />
            用户操作
          </CardTitle>
          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            根据状态、确认条件和评价默认值生成的首屏操作建议。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={items.length > 0 ? "warning" : "success"}>{items.length} 个操作</Badge>
          {selectedKind !== "all" ? (
            <Badge variant={userActionKindConfig[selectedKind].variant}>{userActionKindConfig[selectedKind].label}</Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="rounded-lg border border-slate-200 p-4 text-sm text-slate-500 dark:border-zinc-800 dark:text-zinc-400">
            当前没有需要用户处理的操作。
          </div>
        ) : (
          <div className="space-y-3">
            <div aria-label="用户操作类型筛选" className="flex flex-wrap gap-2">
              <Button
                aria-pressed={selectedKind === "all"}
                onClick={() => onSelectKind("all")}
                size="sm"
                variant={selectedKind === "all" ? "primary" : "secondary"}
              >
                全部
                <Badge variant="neutral">{items.length}</Badge>
              </Button>
              {kindOptions.map((kind) => (
                <Button
                  aria-pressed={selectedKind === kind}
                  key={kind}
                  onClick={() => onSelectKind(kind)}
                  size="sm"
                  variant={selectedKind === kind ? "primary" : "secondary"}
                >
                  {userActionKindConfig[kind].label}
                  <Badge variant={userActionKindConfig[kind].variant}>{kindCounts[kind]}</Badge>
                </Button>
              ))}
            </div>
            {showAllForEmptyFilter ? (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm leading-6 text-slate-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                当前没有“{selectedKindLabel}”操作，已显示全部活动操作。
              </div>
            ) : null}
            {displayedItems.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-200 p-4 text-sm text-slate-500 dark:border-zinc-800 dark:text-zinc-400">
                这个状态来源中没有“{selectedKindLabel}”操作。
              </div>
            ) : (
              <div className="grid gap-3 xl:grid-cols-2">
                {displayedItems.map((item) => {
                  const actionKey = `${item.goalId}-${item.kind}-${item.title}`;
                  const copyState = actionCopyState?.key === actionKey ? actionCopyState.state : "idle";
                  const isGateAction = item.kind === "controller" || item.waitingOn === "user_or_controller" || item.waitingOn === "controller";
                  const handoffReadiness = buildHandoffReadinessView(item.handoffReadiness);
                  const copyLabel = copyState === "copied"
                    ? "已复制"
                    : item.kind === "codex" && item.agentCommand
                      ? "复制交接信息"
                      : isFocusWaitQuota(item.quota)
                        ? "复制重点等待信息"
                      : "复制操作信息";
                  const agentTodo = firstOpenTodo(item.agentTodos);
                  return (
                  <article
                    className={cn(
                      "min-w-0 rounded-lg border p-3 text-left transition",
                      isGateAction
                        ? "border-amber-300 bg-amber-50/70 dark:border-amber-900/70 dark:bg-amber-950/30"
                        : "border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950",
                      item.goalId === selectedGoalId && "ring-2 ring-slate-300 dark:ring-zinc-700",
                    )}
                    key={actionKey}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <button
                        className="min-w-0 flex-1 text-left"
                        onClick={() => onSelectGoal(item.goalId)}
                        type="button"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <Badge variant="neutral">项目</Badge>
                          {item.goalId === selectedGoalId ? <Badge variant="success">已选择</Badge> : null}
                        </div>
                        <div className="mt-1 break-all text-base font-semibold leading-6 text-slate-950 dark:text-zinc-50">{item.goalId}</div>
                        <div className="mt-1 break-words text-sm font-medium text-slate-600 dark:text-zinc-300">{item.title}</div>
                      </button>
                      <div className="flex flex-wrap items-center gap-2">
                        {copyState === "failed" ? <Badge variant="danger">复制失败</Badge> : null}
                        <Button
                          aria-label={`复制 ${item.goalId} 的操作信息`}
                          onClick={(event) => {
                            event.stopPropagation();
                            void copyActionPacket(item);
                          }}
                          size="sm"
                          variant="secondary"
                        >
                          {copyState === "copied" ? <CheckCircle2 className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                          {copyLabel}
                        </Button>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <Badge variant={userActionKindConfig[item.kind].variant}>{userActionKindConfig[item.kind].label}</Badge>
                      <Badge variant={item.variant}>{item.badge}</Badge>
                      <PhaseBadges compact phase={item.phase} />
                      {item.waitingOn !== "clear" ? (
                        <Badge variant="neutral">{waitingLabel[item.waitingOn] ?? item.waitingOn}</Badge>
                      ) : null}
                      <QuotaChip quota={item.quota} />
                      {handoffReadiness ? (
                        <Badge variant={handoffReadiness.variant}>
                          {handoffReadiness.ready ? "交接已就绪" : "交接被阻塞"}
                        </Badge>
                      ) : null}
                      {item.draftLabel ? <Badge variant="info">{item.draftLabel}</Badge> : null}
                    </div>
                    {(item.projectAssetSource === "legacy_raw_fallback" || item.projectOwner || item.projectGate || item.projectNextAction || item.projectStopCondition || handoffReadiness) ? (
                      <div className="mt-3 border-t border-slate-200 pt-3 text-xs leading-5 text-slate-600 dark:border-zinc-800 dark:text-zinc-300">
                        <div className="flex flex-wrap items-center gap-2">
                          {item.projectAssetSource === "legacy_raw_fallback" ? (
                            <Badge variant="warning">旧版原始数据备用</Badge>
                          ) : (
                            <Badge variant="neutral">项目资产</Badge>
                          )}
                          {item.projectAssetSource !== "legacy_raw_fallback" && item.projectOwner ? <Badge variant="info">负责人 {item.projectOwner}</Badge> : null}
                          {item.projectAssetSource !== "legacy_raw_fallback" && item.projectGate ? <Badge variant="warning">确认条件 {item.projectGate}</Badge> : null}
                        </div>
                        {item.projectAssetSource === "legacy_raw_fallback" ? (
                          <p className="mt-2 break-words font-medium text-amber-700 dark:text-amber-200">
                            负责人、确认条件和停止条件没有项目资产支持；下方使用原始状态备用数据。
                          </p>
                        ) : null}
                        {item.projectNextAction ? (
                          <p className="mt-2 line-clamp-2 break-words">
                            <span className="font-medium">{item.projectAssetSource === "legacy_raw_fallback" ? "备用下一步：" : "下一步："}</span> {item.projectNextAction}
                          </p>
                        ) : null}
                        {item.projectStopCondition ? (
                          <p className="mt-1 line-clamp-2 break-words">
                            <span className="font-medium">{item.projectAssetSource === "legacy_raw_fallback" ? "备用停止条件：" : "停止条件："}</span> {item.projectStopCondition}
                          </p>
                        ) : null}
                        {handoffReadiness ? (
                          <div className="mt-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-xs leading-5 dark:border-zinc-800 dark:bg-zinc-900">
                            <p className="break-words">
                              <span className="font-medium">交接就绪度：</span> {handoffReadiness.shortLine}
                            </p>
                            <p className="mt-1 break-words">
                              <span className="font-medium">交接状态：</span> {handoffReadiness.stateLine}
                            </p>
                            {handoffReadiness.latestRunLine ? (
                              <p className="mt-1 break-words">
                                <span className="font-medium">交接后运行：</span> {handoffReadiness.latestRunLine}
                              </p>
                            ) : null}
                            {handoffReadiness.probe ? (
                              <p className="mt-1 break-words">
                                <span className="font-medium">探测结果：</span> {handoffReadiness.probe}
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    <UserTodoCallout
                      blocksGate={Boolean(item.operatorQuestion && firstOpenTodo(item.userTodos))}
                      focusWait={isFocusWaitQuota(item.quota)}
                      goalId={item.goalId}
                      source={source}
                      todos={item.userTodos}
                    />
                    {item.operatorQuestion ? (
                      <div className="mt-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <CircleAlert className="h-3.5 w-3.5 text-amber-700 dark:text-amber-300" />
                          <Badge variant="warning">需要操作者回答</Badge>
                        </div>
                        <p className="mt-2 line-clamp-3 break-words text-sm font-medium leading-6 text-amber-950 dark:text-amber-100">
                          {item.operatorQuestion}
                        </p>
                      </div>
                    ) : (
                      <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-700 dark:text-zinc-300">{item.summary}</p>
                    )}
                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">{item.detail}</p>
                    {item.agentCommand ? (
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-zinc-400">
                        <Badge variant="info">{item.operatorQuestion ? "批准后可执行 Agent 命令" : "已批准 Agent 命令"}</Badge>
                      </div>
                    ) : null}
                    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3 text-xs text-slate-600 dark:border-zinc-800 dark:text-zinc-300">
                      <Badge variant="neutral">安全路径</Badge>
                      <span className="line-clamp-1 break-words font-medium">{item.safePathLabel}</span>
                      <Badge variant="info">评价</Badge>
                      <span className="font-medium">{item.rewardHint}</span>
                      {item.authorityCoverage ? (
                        <>
                          <Badge variant={item.authorityCoverage.variant}>权威来源</Badge>
                          <span className="line-clamp-1 break-words font-medium">{item.authorityCoverage.shortLine}</span>
                        </>
                      ) : null}
                      {buildQuotaView(item.quota) ? (
                        <>
                          <Gauge className="h-3.5 w-3.5 text-slate-500 dark:text-zinc-400" />
                          <Badge variant={buildQuotaView(item.quota)?.variant}>配额</Badge>
                          <span className="font-medium">{buildQuotaView(item.quota)?.shortLine}</span>
                        </>
                      ) : null}
                      {formatLatestValidation(item.latestValidation) ? (
                        <>
                          <FileCheck2 className="h-3.5 w-3.5 text-slate-500 dark:text-zinc-400" />
                          <Badge variant="neutral">验证</Badge>
                          <span className="line-clamp-1 break-words font-medium">
                            {formatLatestValidation(item.latestValidation)}
                          </span>
                        </>
                      ) : null}
                      {agentTodo ? (
                        <>
                          <Bot className="h-3.5 w-3.5 text-slate-500 dark:text-zinc-400" />
                          <Badge variant="info">Agent Todo</Badge>
                          <span className="line-clamp-1 break-words font-medium">{agentTodo.text}</span>
                        </>
                      ) : null}
                    </div>
                  </article>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function buildOperatorActionBridge({
  goal,
  queueItem,
  registry,
  runtimeRoot,
}: {
  goal?: RunGoal;
  queueItem?: QueueItem;
  registry: string;
  runtimeRoot: string;
}): OperatorActionBridge | null {
  const goalId = goal?.id ?? queueItem?.goal_id;
  if (!goalId) {
    return null;
  }
  const latestRun = goal?.latest_runs[0];
  const phase = goal?.lifecycle_phase
    ?? queueItem?.lifecycle_phase
    ?? latestRun?.lifecycle_phase
    ?? inferLifecyclePhase(queueItem?.status ?? goal?.status, latestRun);
  const waitingOn = queueItem?.waiting_on ?? "clear";
  const missingGates = new Set(queueItem?.missing_gates ?? latestRun?.controller_readiness?.missing_gates ?? []);
  const statusCommand = buildStatusCommand({ registry, runtimeRoot });

  if (queueItem?.severity === "high") {
    return {
      title: "安全命令路径",
      badge: "检查",
      variant: "danger",
      body: "评价、批准或交接这个 Goal 前，先解决阻塞健康问题。",
      items: [
        {
          label: "检查状态",
          body: "使用机器可读状态合同定位当前阻塞项。",
          command: statusCommand,
          variant: "danger",
        },
      ],
    };
  }

  if (waitingOn === "external_evidence") {
    const items: OperatorActionBridgeItem[] = [
      {
        label: "观察确认条件",
        body: "在可比较的证据到达前，保持观察这个 Goal。",
        command: statusCommand,
        variant: "info",
      },
    ];
    if (missingGates.has("human_reward_capture")) {
      items.push({
        label: "评价确认",
        body: "判断所选运行后使用下方评价命令草稿；操作者明确记录前保持试运行。",
        variant: "warning",
      });
    }
    if (queueItem?.next_handoff_condition) {
      items.push({
        label: "交接条件",
        body: queueItem.next_handoff_condition,
        variant: "neutral",
      });
    }
    return {
      title: "安全命令路径",
      badge: "观察",
      variant: "info",
      body: "看板可以验证下一份评价草稿，但不能把缺少证据当成批准。",
      items,
    };
  }

  if (waitingOn === "user_or_controller" || waitingOn === "controller") {
    const command = queueItem?.agent_command
      ?? buildReadOnlyMapDryRunCommand({ goalId, registry, runtimeRoot });
    const gateDraftCommand = buildOperatorGateDryRunCommand({ goalId, registry, runtimeRoot });
    return {
      title: "安全命令路径",
      badge: phase === "planned" ? "接入确认" : "批准",
      variant: "warning",
      body: "批准仍需人工或控制者在浏览器外决定；安全的本机命令是试运行。",
      items: [
        {
          label: "只读映射试运行",
          body: "追加任何运行记录前，先预览控制者交接内容。",
          command,
          variant: "warning",
        },
        {
          label: "操作者确认试运行草稿",
          body: "人工批准后由用户预览；明确记录确认前保留 --dry-run。",
          command: gateDraftCommand,
          variant: "neutral",
        },
        {
          label: "批准边界",
          body: "评价信号或看板审阅本身不会授予写入控制权。",
          variant: "neutral",
        },
      ],
    };
  }

  if (waitingOn === "codex") {
    const quota = queueItem?.project_asset?.quota ?? queueItem?.quota ?? goal?.quota;
    if (isOutcomeFloorRecoveryQuota(quota)) {
      const evidenceLabel = recoveryEvidenceLabel(quota);
      return {
        title: "恢复任务路径",
        badge: "限定恢复",
        variant: "warning",
        body: `普通交付仍被结果下限阻塞；只允许一次${evidenceLabel}恢复任务或写回具体阻塞原因。`,
        items: [
          {
            label: "恢复任务边界",
            body: quota?.safe_bypass_policy ?? `只做${evidenceLabel}，不能执行普通 Agent 交接。`,
            variant: "warning",
          },
          {
            label: "检查最近证据",
            body: "开始恢复任务前先读取最近历史，确认没有重复消耗配额。",
            command: buildHistoryCommand({ goalId, registry, runtimeRoot }),
            variant: "neutral",
          },
        ],
      };
    }
    if (quota?.state === "throttled" || quota?.state === "paused" || (quota?.state === "focus_wait" && !isOutcomeFloorRecoveryQuota(quota))) {
      const quotaView = buildQuotaView(quota);
      return {
        title: "安全命令路径",
        badge: quota.state === "paused" ? "已暂停" : "等待",
        variant: quota.state === "paused" ? "neutral" : "warning",
        body: "当前配额状态不允许开始新的 Agent 回合；这里只提供只读状态检查。",
        items: [
          {
            label: "检查配额状态",
            body: quotaView?.reviewLine ?? "确认配额或等待条件是否已经变化。",
            command: statusCommand,
            variant: quota.state === "paused" ? "neutral" : "warning",
          },
        ],
      };
    }
    const fallbackCommand = phase === "refreshed"
      ? buildRefreshStateDryRunCommand({ goalId, registry, runtimeRoot })
      : phase === "connected"
        ? buildReadOnlyMapDryRunCommand({ goalId, registry, runtimeRoot })
        : buildHistoryCommand({ goalId, registry, runtimeRoot });
    const command = queueItem?.agent_command
      ?? fallbackCommand;
    const commandIsGateApproved = Boolean(queueItem?.agent_command);
    return {
      title: "安全命令路径",
      badge: "交接",
      variant: "success",
      body: "这个 Goal 已准备好进入 Agent 回合；看板负责交接上下文，不直接执行 Agent 工作。",
      items: [
        {
          label: commandIsGateApproved ? "已批准 Agent 命令" : phase === "mapped" ? "读取最新映射" : "预览下一次运行",
          body: commandIsGateApproved
            ? "这条命令有效，因为操作者确认已记录为批准。"
            : phase === "mapped"
            ? "把精简映射和最近历史作为 Agent 上下文。"
            : "追加运行记录前，先试运行下一状态或映射命令。",
          command,
          variant: "success",
        },
      ],
    };
  }

  if (phase === "reward_judged") {
    return {
      title: "安全命令路径",
      badge: "已记录",
      variant: "success",
      body: "所选运行已经附加精简人工评价。",
      items: [
        {
          label: "审阅历史",
          body: "把最近历史作为下一轮 Agent 上下文。",
          command: buildHistoryCommand({ goalId, registry, runtimeRoot }),
          variant: "success",
        },
      ],
    };
  }

  return {
    title: "安全命令路径",
    badge: "状态",
    variant: "neutral",
    body: "当前没有直接用户操作；继续把当前状态合同作为 Agent 的信息来源。",
    items: [
      {
        label: "检查状态",
        body: "开始新操作前，先读取面向 Agent 的精简状态。",
        command: statusCommand,
        variant: "neutral",
      },
    ],
  };
}

function OperatorDecisionPanel({
  goal,
  queueItem,
  registry,
  runtimeRoot,
}: {
  goal?: RunGoal;
  queueItem?: QueueItem;
  registry: string;
  runtimeRoot: string;
}) {
  const decision = buildOperatorDecision({ goal, queueItem });
  const bridge = buildOperatorActionBridge({ goal, queueItem, registry, runtimeRoot });
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase text-slate-500 dark:text-zinc-400">操作者决策</div>
          <div className="mt-1 text-base font-semibold text-slate-950 dark:text-zinc-50">{decision.title}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={decision.variant}>{decision.badge}</Badge>
          <PhaseBadges compact phase={decision.phase} />
          {decision.waitingOn !== "clear" ? (
            <Badge variant="neutral">{waitingLabel[decision.waitingOn] ?? decision.waitingOn}</Badge>
          ) : null}
        </div>
      </div>
      <p className="mt-3 leading-6 text-slate-700 dark:text-zinc-300">{decision.action}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">{decision.reason}</p>
      {decision.needs.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {decision.needs.map((need) => (
            <Badge key={need} variant="warning">
              {need}
            </Badge>
          ))}
        </div>
      ) : null}
      {bridge ? (
        <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-slate-500 dark:text-zinc-400" />
            <span className="font-medium text-slate-950 dark:text-zinc-50">{bridge.title}</span>
            <Badge variant={bridge.variant}>{bridge.badge}</Badge>
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">{bridge.body}</p>
          <div className="mt-3 space-y-2">
            {bridge.items.map((item) => (
              <div className="rounded-md border border-slate-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950" key={`${item.label}-${item.command ?? item.body}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={item.variant ?? "neutral"}>{item.label}</Badge>
                  {item.command ? <Badge variant="info">试运行路径</Badge> : null}
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">{item.body}</p>
                {item.command ? (
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-50 dark:border-zinc-800">
                    {item.command}
                  </pre>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function HumanRewardSummary({ reward }: { reward: HumanReward }) {
  return (
    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm dark:border-emerald-900 dark:bg-emerald-950">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={rewardVariant(reward.reward)}>人工评价</Badge>
        {reward.decision ? <span className="font-medium text-emerald-950 dark:text-emerald-100">{reward.decision}</span> : null}
        {reward.recorded_at ? <span className="text-xs text-emerald-700 dark:text-emerald-300">{reward.recorded_at}</span> : null}
      </div>
      {reward.reason_summary ? (
        <p className="mt-2 leading-6 text-emerald-900 dark:text-emerald-100">{reward.reason_summary}</p>
      ) : null}
      {reward.follow_up ? (
        <p className="mt-1 text-xs leading-5 text-emerald-800 dark:text-emerald-200">{reward.follow_up}</p>
      ) : null}
    </div>
  );
}

function operatorGateVariant(gate: OperatorGate): BadgeVariant {
  if (gate.decision === "approve") {
    return "success";
  }
  if (gate.decision === "reject") {
    return "danger";
  }
  return "warning";
}

function OperatorGateSummary({ gate }: { gate: OperatorGate }) {
  return (
    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-900/60 dark:bg-amber-950/30">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={operatorGateVariant(gate)}>操作者确认</Badge>
        {gate.gate ? <span className="font-medium text-amber-950 dark:text-amber-100">{gate.gate}</span> : null}
        {gate.decision ? <Badge variant={operatorGateVariant(gate)}>{gate.decision === "approve" ? "批准" : gate.decision === "reject" ? "拒绝" : gate.decision}</Badge> : null}
        {gate.recorded_at ? <Badge variant="neutral">{gate.recorded_at}</Badge> : null}
      </div>
      {gate.operator_question ? (
        <p className="mt-2 leading-6 text-amber-950 dark:text-amber-100">{gate.operator_question}</p>
      ) : null}
      {gate.reason_summary ? (
        <p className="mt-1 text-xs leading-5 text-amber-900 dark:text-amber-100">{gate.reason_summary}</p>
      ) : null}
      {gate.follow_up ? (
        <p className="mt-1 text-xs leading-5 text-amber-800 dark:text-amber-200">{gate.follow_up}</p>
      ) : null}
      {gate.agent_command ? (
        <code className="mt-2 block overflow-x-auto whitespace-pre-wrap rounded-md bg-slate-950 p-2 text-xs leading-5 text-slate-50">
          {gate.agent_command}
        </code>
      ) : null}
    </div>
  );
}

function OperatorGateResumeContractSummary({ contract }: { contract: OperatorGateResumeContract }) {
  const checks = [
    contract.freshness_check,
    contract.precondition_check,
    contract.migration_or_rebase_result,
    contract.validation_after_resume,
  ].filter(Boolean);
  return (
    <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm dark:border-emerald-900/60 dark:bg-emerald-950/30">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="success">从检查点恢复</Badge>
        {contract.version ? <Badge variant="neutral">{contract.version}</Badge> : null}
        {contract.gate_id ? <span className="font-medium text-emerald-950 dark:text-emerald-100">{contract.gate_id}</span> : null}
        {contract.operator_decision ? <Badge variant="success">{contract.operator_decision}</Badge> : null}
      </div>
      {contract.latest_state_ref ? (
        <p className="mt-2 text-xs leading-5 text-emerald-900 dark:text-emerald-100">{contract.latest_state_ref}</p>
      ) : null}
      {checks.length > 0 ? (
        <ul className="mt-2 space-y-1 text-xs leading-5 text-emerald-800 dark:text-emerald-200">
          {checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      ) : null}
      {contract.resulting_action ? (
        <p className="mt-2 text-xs leading-5 text-emerald-950 dark:text-emerald-100">{contract.resulting_action}</p>
      ) : null}
    </div>
  );
}

function ControllerReadinessSummary({ readiness }: { readiness: ControllerReadiness }) {
  const missing = readiness.missing_gates ?? [];
  return (
    <div className="mt-3 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm dark:border-sky-900 dark:bg-sky-950">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={readinessVariant(readiness)}>控制者就绪度</Badge>
        {readiness.classification ? <span className="font-medium text-sky-950 dark:text-sky-100">{readiness.classification}</span> : null}
        {missing.length > 0 ? <Badge variant="warning">缺少 {missing.length} 项</Badge> : <Badge variant="success">确认条件已满足</Badge>}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <Badge variant={readiness.read_only_observer_ready ? "success" : "neutral"}>只读观察</Badge>
        <Badge variant={readiness.decision_advisor_ready ? "success" : "neutral"}>决策建议</Badge>
        <Badge variant={readiness.write_controller_ready ? "success" : "neutral"}>写入控制</Badge>
      </div>
      {readiness.review_judgment ? (
        <p className="mt-2 leading-6 text-sky-900 dark:text-sky-100">{readiness.review_judgment}</p>
      ) : null}
      {readiness.next_handoff_condition ? (
        <p className="mt-1 text-xs leading-5 text-sky-800 dark:text-sky-200">{readiness.next_handoff_condition}</p>
      ) : null}
      {readiness.gates.length > 0 ? (
        <div className="mt-3 space-y-1">
          {readiness.gates.map((gate) => (
            <div className="flex gap-2 text-xs leading-5 text-sky-900 dark:text-sky-100" key={`${gate.id}-${gate.ok}`}>
              <Badge variant={gate.ok ? "success" : "warning"}>{gate.ok ? "通过" : "缺少"}</Badge>
              <span className="break-words">
                {gate.id}
                {gate.review ? `: ${gate.review}` : ""}
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ProjectMapSummary({ projectMap }: { projectMap: ProjectMap }) {
  const sections = `${projectMap.sections_found ?? 0}/${projectMap.sections_checked ?? 0}`;
  const files = `${projectMap.files_present ?? 0}/${projectMap.files_checked ?? 0}`;
  const authorityCoverage = buildAuthorityCoverageFromProjectMap(projectMap);
  return (
    <div className="mt-3 rounded-md border border-indigo-200 bg-indigo-50 p-3 text-sm dark:border-indigo-900 dark:bg-indigo-950">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="info">项目映射</Badge>
        {projectMap.adapter_kind ? (
          <span className="font-medium text-indigo-950 dark:text-indigo-100">{projectMap.adapter_kind}</span>
        ) : null}
        {projectMap.adapter_status ? <Badge variant="neutral">{projectMap.adapter_status}</Badge> : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <Badge variant="neutral">来源 {projectMap.authority_source_count ?? 0}</Badge>
        {authorityCoverage ? <Badge variant={authorityCoverage.variant}>{authorityCoverage.badge}</Badge> : null}
        <Badge variant="neutral">限制条件 {projectMap.guard_count ?? 0}</Badge>
        <Badge variant="info">章节 {sections}</Badge>
        <Badge variant="info">文件 {files}</Badge>
      </div>
      {authorityCoverage ? (
        <p className="mt-2 text-xs leading-5 text-indigo-900 dark:text-indigo-100">{authorityCoverage.reviewLine}</p>
      ) : null}
    </div>
  );
}

function LatestRun({ run }: { run: RunRecord }) {
  const lifecyclePhase = run.lifecycle_phase ?? inferLifecyclePhase(run.classification, run);
  return (
    <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{run.generated_at}</span>
        <Badge variant="info">{formatNullable(run.classification, "未分类")}</Badge>
        <PhaseBadges compact flags={run.lifecycle_flags} phase={lifecyclePhase} />
        {run.health_check ? <Badge variant="success">{run.health_check}</Badge> : null}
        {run.human_reward ? <Badge variant={rewardVariant(run.human_reward.reward)}>评价</Badge> : null}
        {run.operator_gate ? <Badge variant={operatorGateVariant(run.operator_gate)}>确认</Badge> : null}
        {run.operator_gate_resume_contract ? <Badge variant="success">恢复合同</Badge> : null}
        {run.controller_readiness ? <Badge variant={readinessVariant(run.controller_readiness)}>就绪度</Badge> : null}
        <Badge variant={artifactVariant(run.json_exists)}>JSON</Badge>
        <Badge variant={artifactVariant(run.markdown_exists)}>Markdown</Badge>
      </div>
      {run.recommended_action ? (
        <p className="mt-2 text-sm leading-6 text-slate-700 dark:text-zinc-300">{run.recommended_action}</p>
      ) : null}
      {run.controller_readiness ? <ControllerReadinessSummary readiness={run.controller_readiness} /> : null}
      {run.human_reward ? <HumanRewardSummary reward={run.human_reward} /> : null}
      {run.operator_gate ? <OperatorGateSummary gate={run.operator_gate} /> : null}
      {run.operator_gate_resume_contract ? (
        <OperatorGateResumeContractSummary contract={run.operator_gate_resume_contract} />
      ) : null}
      {run.project_map ? <ProjectMapSummary projectMap={run.project_map} /> : null}
    </div>
  );
}

function RewardCommandDraft({
  goal,
  queueItem,
  registry,
  runtimeRoot,
  dryRunUrl,
  appendUrl,
  onStatusRefresh,
}: {
  goal?: RunGoal;
  queueItem?: QueueItem;
  registry: string;
  runtimeRoot: string;
  dryRunUrl: string | null;
  appendUrl: string | null;
  onStatusRefresh: () => Promise<void>;
}) {
  const latestRun = goal?.latest_runs[0];
  const activeQuota = queueItem?.project_asset?.quota ?? queueItem?.quota ?? goal?.quota;
  const activeQuotaMustAdvanceKey = (activeQuota?.must_advance ?? []).join("|");
  const missingGateKey = (queueItem?.missing_gates ?? latestRun?.controller_readiness?.missing_gates ?? []).join("|");
  const draftDefaults = useMemo(
    () => buildRewardDraftDefaults({ goal, queueItem }),
    [
      goal?.id,
      goal?.status,
      goal?.lifecycle_phase,
      latestRun?.generated_at,
      latestRun?.classification,
      latestRun?.lifecycle_phase,
      latestRun?.human_reward?.recorded_at,
      latestRun?.human_reward?.decision,
      latestRun?.human_reward?.reward,
      latestRun?.controller_readiness?.classification,
      latestRun?.controller_readiness?.next_handoff_condition,
      queueItem?.status,
      queueItem?.waiting_on,
      queueItem?.severity,
      queueItem?.recommended_action,
      queueItem?.lifecycle_phase,
      queueItem?.next_handoff_condition,
      activeQuota?.state,
      activeQuota?.compute,
      activeQuota?.spent_slots,
      activeQuota?.allowed_slots,
      activeQuota?.handoff_outcome_floor_block,
      activeQuota?.safe_bypass_allowed,
      activeQuota?.safe_bypass_kind,
      activeQuota?.safe_bypass_policy,
      activeQuotaMustAdvanceKey,
      missingGateKey,
    ],
  );
  const [decision, setDecision] = useState(draftDefaults.decision);
  const [reward, setReward] = useState<RewardValue>(draftDefaults.reward);
  const [reasonSummary, setReasonSummary] = useState(draftDefaults.reasonSummary);
  const [followUp, setFollowUp] = useState(draftDefaults.followUp);
  const [dryRunResult, setDryRunResult] = useState<RewardDryRunResponse | null>(null);
  const [dryRunRequestBody, setDryRunRequestBody] = useState<RewardRequestBody | null>(null);
  const [appendResult, setAppendResult] = useState<RewardDryRunResponse | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);
  const [isDryRunning, setIsDryRunning] = useState(false);
  const [appendError, setAppendError] = useState<string | null>(null);
  const [isAppending, setIsAppending] = useState(false);
  const command = goal && latestRun
    ? buildRewardCommand({
        goalId: goal.id,
        registry,
        runtimeRoot,
        runGeneratedAt: latestRun.generated_at,
        decision,
        reward,
        reasonSummary,
        followUp,
      })
    : "";
  const canDryRun = Boolean(command && dryRunUrl && decision.trim() && reasonSummary.trim());
  const canAppend = Boolean(
    appendUrl
    && dryRunRequestBody
    && dryRunResult?.ok
    && dryRunResult.preview_id
    && !dryRunResult.appended
    && !appendResult?.appended,
  );

  useEffect(() => {
    setDecision(draftDefaults.decision);
    setReward(draftDefaults.reward);
    setReasonSummary(draftDefaults.reasonSummary);
    setFollowUp(draftDefaults.followUp);
    setDryRunResult(null);
    setDryRunRequestBody(null);
    setAppendResult(null);
    setDryRunError(null);
    setAppendError(null);
  }, [
    draftDefaults.decision,
    draftDefaults.reward,
    draftDefaults.reasonSummary,
    draftDefaults.followUp,
    goal?.id,
    latestRun?.generated_at,
  ]);

  function rewardRequestBody(): RewardRequestBody | null {
    if (!goal || !latestRun) {
      return null;
    }
    return {
      goal_id: goal.id,
      run_generated_at: latestRun.generated_at,
      decision,
      reward,
      reason_summary: reasonSummary,
      follow_up: followUp.trim() || undefined,
    };
  }

  async function runDryRunCheck() {
    if (!goal || !latestRun || !dryRunUrl) {
      return;
    }
    setIsDryRunning(true);
    setDryRunError(null);
    setDryRunResult(null);
    setDryRunRequestBody(null);
    setAppendResult(null);
    setAppendError(null);
    try {
      const requestBody = rewardRequestBody();
      if (!requestBody) {
        return;
      }
      const response = await fetch(dryRunUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const payload = parseRewardDryRunResponse(await response.json());
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      const recordedAt = payload.human_reward?.recorded_at;
      setDryRunRequestBody(recordedAt ? { ...requestBody, recorded_at: recordedAt } : requestBody);
      setDryRunResult(payload);
    } catch (error) {
      setDryRunError(formatStatusError(error));
    } finally {
      setIsDryRunning(false);
    }
  }

  async function appendRewardOverlay() {
    const requestBody = dryRunRequestBody;
    if (!appendUrl || !requestBody || !dryRunResult?.preview_id) {
      return;
    }
    setIsAppending(true);
    setAppendError(null);
    try {
      const response = await fetch(appendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...requestBody,
          preview_id: dryRunResult.preview_id,
          write_active_state_summary: true,
        }),
      });
      const payload = parseRewardDryRunResponse(await response.json());
      if (!response.ok || !payload.ok || !payload.appended) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      setAppendResult(payload);
      setDryRunResult(payload);
      await onStatusRefresh();
    } catch (error) {
      setAppendError(formatStatusError(error));
    } finally {
      setIsAppending(false);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-center gap-2">
        <Terminal className="h-4 w-4 text-slate-500 dark:text-zinc-400" />
        <span className="font-medium">评价命令草稿</span>
        <Badge variant="info">仅限本机</Badge>
        <Badge variant={command ? "warning" : "neutral"}>{command ? "试运行" : "需要运行记录"}</Badge>
        <Badge variant="neutral">{draftDefaults.label}</Badge>
        {dryRunResult?.ok ? <Badge variant="success">已验证</Badge> : null}
      </div>
      {command ? (
        <div className="mt-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-slate-50 p-2 text-xs text-slate-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
            <span>默认值来自所选操作者决策和缺少的确认条件。</span>
            <Button
              onClick={() => {
                setDecision(draftDefaults.decision);
                setReward(draftDefaults.reward);
                setReasonSummary(draftDefaults.reasonSummary);
                setFollowUp(draftDefaults.followUp);
                setDryRunResult(null);
                setDryRunRequestBody(null);
                setAppendResult(null);
                setDryRunError(null);
                setAppendError(null);
              }}
              size="sm"
              variant="ghost"
            >
              恢复默认值
            </Button>
          </div>
          <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_160px]">
            <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
              <span>决定</span>
              <input className={inputClassName} onChange={(event) => setDecision(event.target.value)} value={decision} />
            </label>
            <label className="space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
              <span>评价</span>
              <Select className="w-full" value={reward} onChange={(event) => setReward(event.target.value as RewardValue)}>
                {rewardOptions.map((option) => (
                  <option key={option} value={option}>
                    {rewardOptionLabel[option]}
                  </option>
                ))}
              </Select>
            </label>
          </div>
          <label className="block space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
            <span>原因摘要</span>
            <input className={inputClassName} onChange={(event) => setReasonSummary(event.target.value)} value={reasonSummary} />
          </label>
          <label className="block space-y-1 text-xs font-medium text-slate-500 dark:text-zinc-400">
            <span>后续动作</span>
            <input className={inputClassName} onChange={(event) => setFollowUp(event.target.value)} value={followUp} />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <Button disabled={!canDryRun || isDryRunning} onClick={() => void runDryRunCheck()} size="sm">
              {isDryRunning ? <RefreshCw className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
              试运行检查
            </Button>
            <Badge variant={dryRunUrl ? "info" : "neutral"}>{dryRunUrl ? "本机接口" : "手动命令"}</Badge>
            <Badge variant={appendUrl ? "warning" : "neutral"}>{appendUrl ? "追加接口" : "仅可复制或使用命令"}</Badge>
            {dryRunError ? <Badge variant="danger">{dryRunError.slice(0, 96)}</Badge> : null}
            {appendError ? <Badge variant="danger">{appendError.slice(0, 96)}</Badge> : null}
          </div>
          {dryRunResult?.ok ? (
            <div className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">
              <div>
                {dryRunResult.goal_id} · {dryRunResult.selected_run?.generated_at} · 已追加={String(dryRunResult.appended)}
              </div>
              {dryRunResult.active_state_summary ? (
                <p>{dryRunResult.active_state_summary}</p>
              ) : null}
              {dryRunResult.project_agent_visibility?.history_command ? (
                <code className="block rounded border border-emerald-200 bg-white/60 p-2 text-[11px] leading-4 dark:border-emerald-900 dark:bg-zinc-950/50">
                  {dryRunResult.project_agent_visibility.history_command}
                </code>
              ) : null}
              {dryRunResult.preview_id && !appendResult?.appended ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded border border-emerald-200 bg-white/70 p-2 dark:border-emerald-900 dark:bg-zinc-950/50">
                  <span>预览已绑定这个 Goal、运行记录和评价内容。追加操作会写入一条绑定运行记录的人工评价。</span>
                  <Button disabled={!canAppend || isAppending} onClick={() => void appendRewardOverlay()} size="sm">
                    {isAppending ? <RefreshCw className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
                    追加人工评价
                  </Button>
                </div>
              ) : null}
              {appendResult?.appended ? (
                <div className="rounded border border-emerald-300 bg-emerald-100 p-2 font-medium dark:border-emerald-800 dark:bg-emerald-900">
                  评价已追加，状态已刷新。下一次 Agent 运行可以从运行历史中读取。
                </div>
              ) : null}
            </div>
          ) : null}
          <pre className="overflow-x-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-950 p-3 text-xs leading-5 text-slate-50 dark:border-zinc-800">
            {command}
          </pre>
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500 dark:text-zinc-400">没有可评价的精简运行记录。</p>
      )}
    </div>
  );
}

function RunHistoryPanel({
  controlPlaneApplyUrl,
  controlPlaneDryRunUrl,
  controlPlaneWriteEnabled,
  goal,
  onStatusRefresh,
  queueItem,
  registry,
  runtimeRoot,
  rewardDryRunUrl,
  rewardAppendUrl,
}: {
  controlPlaneApplyUrl: string | null;
  controlPlaneDryRunUrl: string | null;
  controlPlaneWriteEnabled: boolean | null;
  goal?: RunGoal;
  onStatusRefresh: () => Promise<void>;
  queueItem?: QueueItem;
  registry: string;
  runtimeRoot: string;
  rewardDryRunUrl: string | null;
  rewardAppendUrl: string | null;
}) {
  const latestRuns = goal?.latest_runs ?? [];
  const authorityCoverage = buildAuthorityCoverage({ goal, run: latestRuns[0] });
  const artifactReady = latestRuns.filter((run) => run.json_exists && run.markdown_exists).length;
  const rewardReady = latestRuns.filter((run) => Boolean(run.human_reward)).length;
  const readinessReady = latestRuns.filter((run) => Boolean(run.controller_readiness)).length;
  const lifecyclePhase = goal?.lifecycle_phase ?? queueItem?.lifecycle_phase ?? inferLifecyclePhase(queueItem?.status, latestRuns[0]);
  const lifecycleFlags = goal?.lifecycle_flags?.length ? goal.lifecycle_flags : queueItem?.lifecycle_flags ?? [];
  return (
    <Card data-testid="selected-goal-detail">
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <History className="h-4 w-4" />
            运行历史
          </CardTitle>
        </div>
        {queueItem ? <StatusBadge value={queueItem.severity} /> : null}
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          <div>
            <div className="break-all text-sm font-semibold">{goal?.id ?? queueItem?.goal_id ?? "尚未选择 Goal"}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {goal?.status ? <Badge>{goal.status}</Badge> : null}
              {goal?.adapter_kind ? <Badge variant="neutral">{goal.adapter_kind}</Badge> : null}
              {goal?.adapter_status ? <Badge variant="info">{goal.adapter_status}</Badge> : null}
              {goal?.legacy_runtime_goal ? <Badge variant="warning">旧版运行时</Badge> : null}
            </div>
            <div className="mt-2">
              <PhaseBadges flags={lifecycleFlags} phase={lifecyclePhase} />
            </div>
            {authorityCoverage ? (
              <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={authorityCoverage.variant}>权威来源覆盖</Badge>
                  <span className="text-xs font-medium text-slate-700 dark:text-zinc-300">{authorityCoverage.shortLine}</span>
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-600 dark:text-zinc-300">{authorityCoverage.reviewLine}</p>
              </div>
            ) : null}
          </div>

          <OperatorDecisionPanel
            goal={goal}
            queueItem={queueItem}
            registry={registry}
            runtimeRoot={runtimeRoot}
          />

          <ControlPlaneSettingsPanel
            applyUrl={controlPlaneApplyUrl}
            dryRunUrl={controlPlaneDryRunUrl}
            goal={goal}
            onStatusRefresh={onStatusRefresh}
            queueItem={queueItem}
            registry={registry}
            writeEnabled={controlPlaneWriteEnabled}
          />

          <div className="grid gap-2 sm:grid-cols-4">
            <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-slate-500 dark:text-zinc-400">原始记录</div>
              <div className="mt-1 text-lg font-semibold">{goal?.raw_index_records ?? 0}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-slate-500 dark:text-zinc-400">独立运行</div>
              <div className="mt-1 text-lg font-semibold">{goal?.unique_runs ?? 0}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
              <div className="flex items-center gap-1 text-xs text-slate-500 dark:text-zinc-400">
                <FileCheck2 className="h-3.5 w-3.5" />
                产物
              </div>
              <div className="mt-1 text-lg font-semibold">{artifactReady}/{latestRuns.length}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
              <div className="text-xs text-slate-500 dark:text-zinc-400">就绪度</div>
              <div className="mt-1 text-lg font-semibold">{readinessReady}/{latestRuns.length}</div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800 sm:col-span-4">
              <div className="text-xs text-slate-500 dark:text-zinc-400">人工评价</div>
              <div className="mt-1 text-lg font-semibold">{rewardReady}/{latestRuns.length}</div>
            </div>
          </div>

          {queueItem ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
              <div className="font-medium">队列建议动作</div>
              <p className="mt-1 leading-6 text-slate-700 dark:text-zinc-300">{queueItem.recommended_action}</p>
              {queueItem.operator_question ? (
                <div className="mt-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-zinc-400">
                    操作者确认
                  </div>
                  <p className="mt-1 leading-6 text-slate-800 dark:text-zinc-200">{queueItem.operator_question}</p>
                </div>
              ) : null}
              {queueItem.agent_command ? (
                <div className="mt-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-zinc-400">
                    Agent 命令
                  </div>
                  <code className="mt-1 block overflow-x-auto whitespace-pre rounded-md bg-white px-2 py-1.5 text-xs text-slate-700 dark:bg-zinc-950 dark:text-zinc-300">
                    {queueItem.agent_command}
                  </code>
                </div>
              ) : null}
              <QueueGateSummary item={queueItem} />
              <HandoffReadinessPanel
                goalId={queueItem.goal_id}
                readiness={queueItem.handoff_readiness}
                testId="selected-queue-handoff-readiness"
              />
            </div>
          ) : null}

          <RewardCommandDraft
            appendUrl={rewardAppendUrl}
            dryRunUrl={rewardDryRunUrl}
            goal={goal}
            onStatusRefresh={onStatusRefresh}
            queueItem={queueItem}
            registry={registry}
            runtimeRoot={runtimeRoot}
          />

          <div className="space-y-2">
            {latestRuns.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-300 p-4 text-sm text-slate-500 dark:border-zinc-700 dark:text-zinc-400">
                还没有精简运行记录。
              </div>
            ) : (
              latestRuns.map((run) => <LatestRun key={`${run.goal_id}-${run.generated_at}`} run={run} />)
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function HealthFindingList({
  title,
  items,
  emptyLabel,
  variant,
}: {
  title: string;
  items: string[];
  emptyLabel: string;
  variant: "success" | "warning" | "danger" | "info";
}) {
  return (
    <div className="min-w-0 p-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase text-slate-500 dark:text-zinc-500">{title}</h3>
        <Badge variant={items.length > 0 ? variant : "neutral"}>{items.length}</Badge>
      </div>
      <div className="mt-3 space-y-2">
        {items.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-zinc-400">{emptyLabel}</p>
        ) : (
          items.map((item) => (
            <div className="text-sm leading-6 text-slate-700 dark:text-zinc-300" key={item}>
              {item}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ContractHealthPanel({ contract }: { contract: StatusPayload["contract"] }) {
  const checks = contract.checks ?? [];
  return (
    <Card className={cn(!contract.ok && "border-rose-200 dark:border-rose-900")}>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4" />
            状态合同健康度
          </CardTitle>
          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            {contract.ok ? "公开边界正常" : "存在阻塞合同问题"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={contract.ok ? "success" : "danger"}>{contract.ok ? "健康" : "已阻塞"}</Badge>
          <Badge variant={contract.errors.length > 0 ? "danger" : "neutral"}>
            {contract.summary.errors} 个错误
          </Badge>
          <Badge variant={contract.warnings.length > 0 ? "warning" : "neutral"}>
            {contract.summary.warnings} 个警告
          </Badge>
          <Badge variant="info">{contract.summary.checks} 项检查</Badge>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="divide-y divide-slate-200 dark:divide-zinc-800 lg:grid lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          <HealthFindingList emptyLabel="没有阻塞错误" items={contract.errors} title="错误" variant="danger" />
          <HealthFindingList emptyLabel="没有警告" items={contract.warnings} title="警告" variant="warning" />
          <HealthFindingList emptyLabel="没有最近检查" items={checks} title="检查" variant="info" />
        </div>
      </CardContent>
    </Card>
  );
}

function GlobalRegistryHealthPanel({ health }: { health: GlobalRegistryHealth }) {
  const summary = health.summary;
  const findings = health.findings ?? [];
  const checks = health.checks ?? [];
  const hasFindings = findings.length > 0;

  return (
    <Card className={cn(!health.ok && "border-rose-200 dark:border-rose-900")}>
      <CardHeader className="flex-wrap">
        <div>
          <CardTitle className="flex items-center gap-2">
            <GitBranch className="h-4 w-4" />
            全局注册表
          </CardTitle>
          <p className="mt-2 text-sm text-slate-500 dark:text-zinc-400">
            {health.available ? "共享多项目注册表健康状态" : "没有找到全局注册表"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={health.ok ? "success" : "danger"}>{health.ok ? "健康" : "已阻塞"}</Badge>
          <Badge variant="info">{health.global_goal_count} 个 Goal</Badge>
          <Badge variant={summary.action > 0 ? "warning" : "neutral"}>{summary.action} 个需处理</Badge>
          <Badge variant={summary.high > 0 ? "danger" : "neutral"}>{summary.high} 个高严重级别</Badge>
          <Badge variant="neutral">{summary.info} 条信息</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 text-sm md:grid-cols-3">
          <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
            <div className="text-xs text-slate-500 dark:text-zinc-400">注册表范围</div>
            <div className="mt-1 font-medium">
              {health.current_registry_is_global ? "全局" : "项目本地"}
            </div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
            <div className="text-xs text-slate-500 dark:text-zinc-400">来源注册表</div>
            <div className="mt-1 font-medium">{health.source_registry_count}</div>
          </div>
          <div className="rounded-lg border border-slate-200 p-3 dark:border-zinc-800">
            <div className="text-xs text-slate-500 dark:text-zinc-400">检查</div>
            <div className="mt-1 font-medium">{summary.checks}</div>
          </div>
        </div>

        {hasFindings ? (
          <div className="space-y-2">
            {findings.map((finding) => (
              <div
                className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900"
                key={`${finding.kind}-${finding.goal_id ?? finding.goal_ids.join(",")}-${finding.message}`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={severityVariant[finding.severity] ?? "info"}>{severityLabel[finding.severity] ?? finding.severity}</Badge>
                  <span className="font-medium">{finding.kind}</span>
                  {finding.goal_id ? <span className="break-all text-slate-500 dark:text-zinc-400">{finding.goal_id}</span> : null}
                </div>
                <p className="mt-2 leading-6 text-slate-700 dark:text-zinc-300">{finding.message}</p>
                {finding.goal_ids.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {finding.goal_ids.map((goalId) => (
                      <Badge key={goalId} variant="neutral">
                        {goalId}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                <p className="mt-2 text-xs leading-5 text-slate-500 dark:text-zinc-400">
                  {finding.recommended_action}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-500 dark:text-zinc-400">没有发现过期来源注册表、缺失状态文件或重复 Goal ID。</p>
        )}

        {checks.length > 0 ? (
          <div className="space-y-1 text-xs leading-5 text-slate-500 dark:text-zinc-400">
            {checks.map((check) => (
              <div key={check}>{check}</div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function StatusRequestView({
  error,
  isLoading,
  onReset,
  onRetry,
  requestedUrl,
  theme,
  toggleTheme,
}: {
  error: string | null;
  isLoading: boolean;
  onReset: () => void;
  onRetry: () => void;
  requestedUrl: string;
  theme: "light" | "dark";
  toggleTheme: () => void;
}) {
  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <main className="min-h-screen bg-[#f6f7f9] text-slate-950 dark:bg-[#09090b] dark:text-zinc-50">
        <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6">
          <div>
            <h1 className="text-xl font-semibold">LoopX 看板</h1>
            <p className="mt-1 break-all text-sm text-slate-500 dark:text-zinc-400">{requestedUrl}</p>
          </div>
          <Button aria-label="切换主题" onClick={toggleTheme} size="icon" variant="secondary">
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </header>
        <div className="mx-auto max-w-3xl p-4 sm:p-6">
          <Card data-testid="initial-status-state">
            <CardContent className="flex min-h-64 items-center justify-center p-6">
              <div className="max-w-xl text-center">
                {error ? (
                  <CircleAlert className="mx-auto h-6 w-6 text-rose-600 dark:text-rose-300" />
                ) : (
                  <RefreshCw className="mx-auto h-6 w-6 animate-spin text-slate-500 dark:text-zinc-400" />
                )}
                <p className="mt-3 text-sm font-medium">
                  {error ? "无法加载实时状态" : "正在加载实时状态"}
                </p>
                {error ? (
                  <>
                    <p className="mt-2 break-words text-sm leading-6 text-slate-500 dark:text-zinc-400">{error}</p>
                    <div className="mt-4 flex flex-wrap justify-center gap-2">
                      <Button disabled={isLoading} onClick={onRetry}>
                        <RefreshCw className="h-4 w-4" />
                        重试
                      </Button>
                      <Button disabled={isLoading} onClick={onReset} variant="ghost">
                        使用示例
                      </Button>
                    </div>
                  </>
                ) : null}
              </div>
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  );
}

export function DashboardPage() {
  const search = dashboardRoute.useSearch();
  const navigate = dashboardRoute.useNavigate();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const [payload, setPayload] = useState<StatusPayload>(exampleStatusPayload);
  const [source, setSource] = useState<DataSource>({ kind: "example", label: "内置示例" });
  const [statusUrl, setStatusUrl] = useState(search.statusUrl);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [requestedStatusUrl, setRequestedStatusUrl] = useState<string | null>(
    search.statusUrl.trim() || null,
  );
  const [exampleModeRequested, setExampleModeRequested] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const suppressedStatusUrlRef = useRef<string | null>(null);
  const routeStatusRequestUrl = !exampleModeRequested && source.kind === "example"
    ? search.statusUrl.trim()
    : "";
  const activeStatusRequestUrl = requestedStatusUrl ?? routeStatusRequestUrl;
  const statusRequestActive = Boolean(activeStatusRequestUrl);
  const refreshStatusUrl = source.kind === "url" ? source.label : search.statusUrl.trim();
  const queue = payload.attention_queue;
  const runHistory = payload.run_history;
  const goalRows = useMemo(
    () => buildGoalDirectoryRows(runHistory.goals, queue.items),
    [runHistory.goals, queue.items],
  );
  const rewardApiUrls = useMemo(() => buildRewardApiUrls(source), [source]);
  const controlPlaneApiUrls = useMemo(() => buildControlPlaneApiUrls(source, payload), [payload, source]);

  async function loadFromUrl(url: string) {
    const trimmed = url.trim();
    if (!trimmed) {
      setLoadError("状态地址不能为空");
      return;
    }
    suppressedStatusUrlRef.current = null;
    setExampleModeRequested(false);
    setRequestedStatusUrl(trimmed);
    setIsLoading(true);
    setLoadError(null);
    try {
      const response = await fetch(trimmed, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`加载 ${trimmed} 时返回 HTTP ${response.status}`);
      }
      const nextPayload = parseStatusPayload(await response.json());
      setPayload(nextPayload);
      setSource({ kind: "url", label: trimmed });
      setStatusUrl(trimmed);
      await navigate({
        search: (current) => ({
          ...current,
          statusUrl: trimmed,
          view: routeViewForUrl(currentRouteView(current)),
        }),
      });
      setRequestedStatusUrl(null);
    } catch (error) {
      setLoadError(formatStatusError(error));
    } finally {
      setIsLoading(false);
    }
  }

  async function loadFromFile(file: File) {
    suppressedStatusUrlRef.current = null;
    setExampleModeRequested(false);
    setIsLoading(true);
    setLoadError(null);
    try {
      const nextPayload = parseStatusPayload(JSON.parse(await file.text()));
      setPayload(nextPayload);
      setSource({ kind: "file", label: file.name });
    } catch (error) {
      setLoadError(formatStatusError(error));
    } finally {
      setIsLoading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  }

  function resetToExample() {
    suppressedStatusUrlRef.current = search.statusUrl.trim() || null;
    setExampleModeRequested(true);
    setPayload(exampleStatusPayload);
    setSource({ kind: "example", label: "内置示例" });
    setStatusUrl("");
    setRequestedStatusUrl(null);
    setLoadError(null);
    void navigate({
      search: (current) => ({
        ...current,
        statusUrl: "",
        view: routeViewForUrl(currentRouteView(current)),
      }),
    });
  }

  useEffect(() => {
    const trimmedStatusUrl = search.statusUrl.trim();
    if (trimmedStatusUrl) {
      if (suppressedStatusUrlRef.current === trimmedStatusUrl) {
        return;
      }
      if (source.kind !== "url" || source.label !== trimmedStatusUrl) {
        void loadFromUrl(trimmedStatusUrl);
      }
      return;
    }
    suppressedStatusUrlRef.current = null;
    if (exampleModeRequested) {
      return;
    }
    if (search.view !== "ops" && source.kind === "example") {
      void loadFromUrl(defaultGlobalStatusUrl);
    }
  }, [exampleModeRequested, search.statusUrl, search.view, source.kind, source.label]);

  useEffect(() => {
    if (search.statusUrl && source.kind === "example") {
      return;
    }
    const goalIds = new Set(goalRows.map((row) => row.goal.id));
    if (goalRows.length === 0) {
      if (search.goalId) {
        void navigate({
          search: (current) => ({
            ...current,
            goalId: "",
          }),
        });
      }
      return;
    }
    if (search.goalId && !goalIds.has(search.goalId)) {
      void navigate({
        search: (current) => ({
          ...current,
          goalId: "",
        }),
      });
    }
  }, [goalRows, navigate, search.goalId, search.statusUrl, source.kind]);

  const filteredItems = queue.items.filter((item) => {
    const lane = laneFor(item)?.key ?? "all";
    const laneMatches = search.lane === "all" || search.lane === lane;
    const severityMatches = search.severity === "all" || search.severity === item.severity;
    return laneMatches && severityMatches;
  });
  const runHistoryOptions = goalRows.map((row) => row.goal.id);
  const selectedGoalId = runHistoryOptions.includes(search.goalId)
    ? search.goalId
    : runHistoryOptions[0] ?? "";
  const selectedGoal = runHistory.goals.find((goal) => goal.id === selectedGoalId);
  const selectedQueueItem = queue.items.find((item) => item.goal_id === selectedGoalId);
  const userActionItems = useMemo(
    () => buildUserActionSummaryItems({
      registry: payload.registry,
      rows: goalRows,
      runtimeRoot: payload.runtime_root,
    }),
    [goalRows, payload.registry, payload.runtime_root],
  );
  const selectedActionItem = useMemo(() => {
    const focusedItems = search.actionKind === "all"
      ? userActionItems
      : userActionItems.filter((item) => item.kind === search.actionKind);
    return (search.goalId ? focusedItems.find((item) => item.goalId === selectedGoalId) : undefined)
      ?? focusedItems[0]
      ?? (search.goalId ? userActionItems.find((item) => item.goalId === selectedGoalId) : undefined)
      ?? userActionItems[0];
  }, [search.actionKind, search.goalId, selectedGoalId, userActionItems]);
  const selectedReviewGoalId = selectedActionItem?.goalId ?? selectedGoalId;
  const selectedMentalModelRow = goalRows.find((row) => row.goal.id === selectedReviewGoalId)
    ?? goalRows.find((row) => row.goal.id === selectedGoalId)
    ?? goalRows[0];

  function selectGoal(goalId: string) {
    void navigate({
      search: (current) => ({
        ...current,
        goalId,
      }),
    });
  }

  if (statusRequestActive) {
    return (
      <StatusRequestView
        error={loadError}
        isLoading={isLoading}
        onReset={resetToExample}
        onRetry={() => void loadFromUrl(activeStatusRequestUrl)}
        requestedUrl={activeStatusRequestUrl}
        theme={theme}
        toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
      />
    );
  }

  if (search.view !== "ops") {
    return (
      <ShareEvidenceView
        isLoading={isLoading}
        onRefresh={() => void loadFromUrl(source.kind === "url" ? source.label : (statusUrl || defaultGlobalStatusUrl))}
        payload={payload}
        rows={goalRows}
        source={source}
        theme={theme}
        toggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
      />
    );
  }

  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <div className="min-h-screen bg-[#f6f7f9] text-slate-950 dark:bg-[#09090b] dark:text-zinc-50">
        <div className="grid min-h-screen lg:grid-cols-[240px_1fr]">
          <aside className="border-b border-black/10 bg-[#0b0d12] text-white lg:border-b-0 lg:border-r dark:border-zinc-800">
            <div className="flex h-16 items-center gap-3 px-5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white text-slate-950">
                <GitBranch className="h-4 w-4" />
              </div>
              <div>
                <div className="text-sm font-semibold">LoopX</div>
                <div className="text-xs text-zinc-400">本机控制面</div>
              </div>
            </div>
            <nav className="flex gap-1 px-3 pb-3 lg:block lg:space-y-1 lg:pb-0">
              <a className="flex items-center gap-2 rounded-md bg-white/10 px-3 py-2 text-sm font-medium text-white" href="/">
                <LayoutDashboard className="h-4 w-4" />
                看板
              </a>
            </nav>
          </aside>

          <main className="min-w-0">
            <header className="sticky top-0 z-10 flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/90 sm:px-6">
              <div>
                <h1 className="text-2xl font-semibold">Goal 控制台</h1>
                <p className="mt-1 break-all text-sm text-slate-500 dark:text-zinc-400">
                  {`${payload.registry} · ${payload.runtime_root}`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="icon" variant="secondary" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="切换主题">
                  {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                </Button>
                <Button
                  disabled={isLoading}
                  onClick={() => (refreshStatusUrl ? void loadFromUrl(refreshStatusUrl) : resetToExample())}
                  variant="primary"
                >
                  <RefreshCw className="h-4 w-4" />
                  刷新
                </Button>
              </div>
            </header>

            <div className="space-y-5 p-4 sm:p-6">
              <StatusContractFreshnessWarning payload={payload} source={source} />

              <section>
                <OperatorMentalModelPanel row={selectedMentalModelRow} onSelectGoal={selectGoal} />
              </section>

              <section>
                <TodoFocusPanel rows={goalRows} onSelectGoal={selectGoal} selectedGoalId={selectedReviewGoalId} />
              </section>

              <section>
                <ProjectTodoExplorer
                  onProjectChange={(todoGoalId) =>
                    navigate({
                      search: (current) => ({
                        ...current,
                        todoGoalId,
                      }),
                    })
                  }
                  onQueryChange={(todoQuery) =>
                    navigate({
                      search: (current) => ({
                        ...current,
                        todoQuery,
                      }),
                    })
                  }
                  onRoleChange={(todoRole) =>
                    navigate({
                      search: (current) => ({
                        ...current,
                        todoRole,
                      }),
                    })
                  }
                  onSelectGoal={selectGoal}
                  onStatusChange={(todoStatus) =>
                    navigate({
                      search: (current) => ({
                        ...current,
                        todoStatus,
                      }),
                    })
                  }
                  query={search.todoQuery}
                  role={search.todoRole}
                  rows={goalRows}
                  selectedTodoGoalId={search.todoGoalId}
                  selectedGoalId={selectedGoalId}
                  status={search.todoStatus}
                  todoIndex={payload.todo_index}
                />
              </section>

              <section>
                <AgentManagementPanel
                  agentManagementProjection={payload.agent_management_projection}
                  onSelectGoal={selectGoal}
                  rows={goalRows}
                  selectedGoalId={selectedReviewGoalId}
                  todoIndex={payload.todo_index}
                />
              </section>

              <section>
                <UserActionSummary
                  selectedKind={search.actionKind}
                  onSelectKind={(actionKind) =>
                    navigate({
                      search: (current) => ({
                        ...current,
                        actionKind,
                      }),
                    })
	                  }
	                  registry={payload.registry}
                  rows={goalRows}
                  runtimeRoot={payload.runtime_root}
                  onSelectGoal={selectGoal}
                  selectedGoalId={selectedReviewGoalId}
                  source={source}
                />
              </section>

              <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard icon={payload.ok ? CheckCircle2 : CircleAlert} label="状态" value={payload.ok ? "健康" : "已阻塞"} tone={payload.ok ? "success" : "danger"} />
                <MetricCard icon={GitBranch} label="Goal 数量" value={String(payload.goal_count)} tone="neutral" />
                <MetricCard icon={Clock3} label="运行次数" value={String(payload.run_count)} tone="info" />
                <MetricCard icon={FileJson2} label="队列项" value={String(queue.item_count)} tone="warning" />
              </section>

              <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-3">
                <UsageStatsPanel usage={payload.usage_summary} />
                <EventLedgerSummaryPanel summary={payload.event_ledger_summary} />
                <PromotionReadinessSummaryPanel summary={payload.promotion_readiness_summary} />
                <PromotionGatePanel gate={payload.promotion_gate} />
                <DecisionFreshnessSummaryPanel summary={payload.decision_freshness_summary} />
              </div>

              <GoalDirectory rows={goalRows} onSelectGoal={selectGoal} selectedGoalId={selectedGoalId} />

              <GlobalRegistryHealthPanel health={payload.global_registry} />

              <ContractHealthPanel contract={payload.contract} />

              <Card>
                <CardContent className="pt-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={source.kind === "example" ? "neutral" : "success"}>数据来源</Badge>
                      <span className="break-all text-sm font-medium">{source.label}</span>
                      {loadError ? <Badge variant="danger">{loadError.slice(0, 120)}</Badge> : null}
                    </div>
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-end">
                      <input
                        aria-label="状态地址"
                        className="h-9 min-w-0 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-900 shadow-sm outline-none focus:ring-2 focus:ring-slate-400 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-100 dark:focus:ring-zinc-500 sm:min-w-72 sm:flex-1 lg:w-80 lg:flex-none"
                        onChange={(event) => setStatusUrl(event.target.value)}
                        placeholder={defaultLiveStatusUrl}
                        value={statusUrl}
                      />
                      <Button disabled={isLoading} onClick={() => void loadFromUrl(statusUrl)}>
                        <Link2 className="h-4 w-4" />
                        加载地址
                      </Button>
                      <input
                        accept="application/json,.json"
                        className="hidden"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) {
                            void loadFromFile(file);
                          }
                        }}
                        ref={fileInputRef}
                        type="file"
                      />
                      <Button disabled={isLoading} onClick={() => fileInputRef.current?.click()}>
                        <Upload className="h-4 w-4" />
                        导入 JSON
                      </Button>
                      <Button disabled={isLoading} onClick={resetToExample} variant="ghost">
                        示例
                      </Button>
                      <Button disabled={isLoading} onClick={() => void loadFromUrl(defaultLiveStatusUrl)} variant="ghost">
                        实时
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div>
                    <CardTitle>关注分区</CardTitle>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-3 lg:grid-cols-3">
                    {laneConfig.map((lane) => {
                      const Icon = lane.icon;
                      const items = queue.items.filter((item) => lane.waitingOn.includes(item.waiting_on));
                      return (
                        <div className={cn("min-h-52 rounded-lg border p-3", lane.accent)} key={lane.key}>
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 text-sm font-semibold">
                              <Icon className="h-4 w-4" />
                              {lane.label}
                            </div>
                            <Badge>{items.length}</Badge>
                          </div>
                          <div className="mt-3 space-y-2">
                            {items.length === 0 ? (
                              <p className="text-sm opacity-70">无需处理</p>
                            ) : (
                              items.map((item) => (
                                <button
                                  className="w-full rounded-md border border-current/15 bg-white/65 p-3 text-left text-sm transition hover:bg-white dark:bg-zinc-950/55 dark:hover:bg-zinc-950"
                                  key={item.goal_id}
                                  onClick={() => selectGoal(item.goal_id)}
                                  type="button"
                                >
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="break-all font-medium">{item.goal_id}</span>
                                    <StatusBadge value={item.severity} />
                                  </div>
                                  <p className="mt-2 text-xs leading-5 opacity-80">{item.recommended_action}</p>
                                  <QueueGateSummary compact item={item} />
                                </button>
                              ))
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>

              <section className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
                <Card className="min-w-0">
                  <CardHeader className="flex-wrap">
                    <div>
                      <CardTitle>关注队列</CardTitle>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Select
                        aria-label="分区筛选"
                        value={search.lane}
                        onChange={(event) =>
                          navigate({
                            search: (current) => ({
                              ...current,
                              lane: event.target.value as typeof search.lane,
                            }),
                          })
                        }
                      >
                        <option value="all">全部分区</option>
                        <option value="user">用户 / 控制者</option>
                        <option value="codex">Codex 可执行</option>
                        <option value="watch">等待外部证据</option>
                      </Select>
                      <Select
                        aria-label="严重级别筛选"
                        value={search.severity}
                        onChange={(event) =>
                          navigate({
                            search: (current) => ({
                              ...current,
                              severity: event.target.value as typeof search.severity,
                            }),
                          })
                        }
                      >
                        <option value="all">全部严重级别</option>
                        <option value="high">高</option>
                        <option value="action">需处理</option>
                        <option value="watch">观察中</option>
                      </Select>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <QueueTable items={filteredItems} onSelectGoal={selectGoal} selectedGoalId={selectedGoalId} />
                  </CardContent>
                </Card>

                <div className="min-w-0 space-y-3">
                  {runHistoryOptions.length > 0 ? (
                    <Select aria-label="运行历史 Goal" onChange={(event) => selectGoal(event.target.value)} value={selectedGoalId}>
                      {runHistoryOptions.map((goalId) => (
                        <option key={goalId} value={goalId}>
                          {goalId}
                        </option>
                      ))}
                    </Select>
                  ) : null}
                  <RunHistoryPanel
                    controlPlaneApplyUrl={controlPlaneApiUrls.applyUrl}
                    controlPlaneDryRunUrl={controlPlaneApiUrls.dryRunUrl}
                    controlPlaneWriteEnabled={controlPlaneApiUrls.writeEnabled}
                    goal={selectedGoal}
                    onStatusRefresh={async () => {
                      if (source.kind === "url") {
                        await loadFromUrl(source.label);
                      }
                    }}
                    queueItem={selectedQueueItem}
                    registry={payload.registry}
                    rewardAppendUrl={rewardApiUrls.appendUrl}
                    rewardDryRunUrl={rewardApiUrls.dryRunUrl}
                    runtimeRoot={payload.runtime_root}
                  />
                </div>
              </section>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

function formatUsageCount(value?: number | null) {
  return String(value ?? 0);
}

function formatUsageShare(value?: number | null) {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function UsageMetric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="min-h-20 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-xs font-medium uppercase text-slate-500 dark:text-zinc-400">{label}</div>
      <div className="mt-2 break-words text-xl font-semibold text-slate-950 dark:text-zinc-50">{value}</div>
    </div>
  );
}

function EventLedgerSummaryPanel({ summary }: { summary?: EventLedgerSummary | null }) {
  if (!summary?.available) {
    return null;
  }
  const totals = summary.totals;
  const topGoals = summary.goals.slice(0, 5);
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <History className="h-4 w-4" />
          控制面事件账本
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant="info">{summary.source}</Badge>
          <Badge variant="neutral">{summary.sample_run_count} 个样本</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm leading-6 text-slate-600 dark:text-zinc-300">
          对话任务不是事实来源；这里是运行历史的精简投影，用来判断最近变化属于推进、证据、决策、状态还是花费。
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {eventClassOrder.map((eventClass) => (
            <UsageMetric
              key={eventClass}
              label={eventClassLabel[eventClass]}
              value={`${eventClassCount(totals.by_class_24h, eventClass)} / ${eventClassCount(totals.by_class_7d, eventClass)}`}
            />
          ))}
        </div>
        {topGoals.length ? (
          <div
            className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-zinc-800"
            data-testid="event-ledger-goal-table"
          >
            <div className="grid grid-cols-[minmax(0,1fr)_72px_72px_92px] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
              <div>Goal</div>
              <div className="text-right">24h</div>
              <div className="text-right">7d</div>
              <div className="text-right">最近事件</div>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-zinc-800">
              {topGoals.map((goal) => (
                <div
                  className="grid grid-cols-[minmax(0,1fr)_72px_72px_92px] gap-2 px-3 py-2 text-sm"
                  key={goal.goal_id}
                >
                  <div className="min-w-0 break-all font-medium text-slate-900 dark:text-zinc-100">{goal.goal_id}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{goal.events_24h}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{goal.events_7d}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{eventClassLabel[goal.latest_event_class as EventLedgerClass] ?? goal.latest_event_class ?? "未知"}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {summary.proxy_note ? (
          <div className="mt-3 text-xs text-slate-500 dark:text-zinc-400">{summary.proxy_note}</div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function promotionReadinessVariant(summary: PromotionReadinessSummary): "success" | "warning" | "danger" {
  if (summary.is_fresh && !summary.requires_readiness_run) {
    return "success";
  }
  if (summary.freshness_status === "missing" || summary.freshness_status === "unknown") {
    return "danger";
  }
  return "warning";
}

function promotionGateVariant(gate: PromotionGate): "success" | "warning" | "danger" {
  if (gate.can_promote && !gate.should_warn) {
    return "success";
  }
  if (gate.gate_state === "warning") {
    return "warning";
  }
  return "danger";
}

function promotionFreshnessLabel(value?: string | null) {
  return {
    fresh: "最新",
    stale: "已过期",
    missing: "缺失",
    unknown: "未知",
  }[value ?? "unknown"] ?? value ?? "未知";
}

function promotionGateStateLabel(value?: string | null) {
  return {
    clear: "可晋级",
    ready: "可晋级",
    blocked: "已阻塞",
    warning: "需检查",
    unknown: "未知",
  }[value ?? "unknown"] ?? value ?? "未知";
}

function PromotionReadinessSummaryPanel({ summary }: { summary?: PromotionReadinessSummary | null }) {
  if (!summary) {
    return null;
  }
  const variant = promotionReadinessVariant(summary);
  const status = promotionFreshnessLabel(summary.freshness_status);
  const age = summary.age_hours == null ? "无" : `${summary.age_hours} 小时`;
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          晋级就绪度
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant={variant}>{status}</Badge>
          <Badge variant={summary.requires_readiness_run ? "warning" : "success"}>
            {summary.requires_readiness_run ? "需要重新运行" : "已就绪"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm leading-6 text-slate-600 dark:text-zinc-300">
          这里从同一份只追加运行历史中观察灰度版本的晋级就绪度；对话任务和安装器日志都不是事实来源。
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <UsageMetric label="新鲜度" value={status} />
          <UsageMetric label="距今时间" value={age} />
          <UsageMetric label="样本数" value={formatUsageCount(summary.sample_run_count)} />
        </div>
        <div className="mt-4 space-y-1 text-xs text-slate-500 dark:text-zinc-400">
          <div className="break-all">Goal={summary.goal_id ?? "无"}</div>
          <div>检查窗口={summary.freshness_window_hours ?? 24} 小时 · 产物={String(Boolean(summary.json_exists))}/{String(Boolean(summary.markdown_exists))}</div>
          {summary.generated_at ? <div>生成时间={summary.generated_at}</div> : null}
          {summary.reason ? <div>{summary.reason}</div> : null}
          {summary.proxy_note ? <div>{summary.proxy_note}</div> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function PromotionGatePanel({ gate }: { gate?: PromotionGate | null }) {
  if (!gate) {
    return null;
  }
  const readiness = gate.readiness;
  const variant = promotionGateVariant(gate);
  const freshness = promotionFreshnessLabel(readiness?.freshness_status);
  const age = readiness?.age_hours == null ? "无" : `${readiness.age_hours} 小时`;
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" />
          晋级确认
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant={variant}>{promotionGateStateLabel(gate.gate_state)}</Badge>
          <Badge variant={gate.can_promote ? "success" : "warning"}>
            {gate.can_promote ? "可以晋级" : "需要先检查"}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          <UsageMetric label="是否可晋级" value={gate.can_promote ? "是" : "否"} />
          <UsageMetric label="新鲜度" value={freshness} />
          <UsageMetric label="距今时间" value={age} />
        </div>
        <div className="mt-4 space-y-1 text-xs text-slate-500 dark:text-zinc-400">
          <div>需要警告={String(gate.should_warn)} · 非阻塞={String(gate.non_blocking)}</div>
          {readiness?.generated_at ? <div>生成时间={readiness.generated_at}</div> : null}
          {gate.recommended_action ? <div className="break-words">建议动作={gate.recommended_action}</div> : null}
          {gate.warning_message ? <div className="break-words text-amber-700 dark:text-amber-300">{gate.warning_message}</div> : null}
        </div>
      </CardContent>
    </Card>
  );
}

function DecisionFreshnessSummaryPanel({ summary }: { summary?: DecisionFreshnessSummary | null }) {
  if (!summary?.available) {
    return null;
  }
  const counts = summary.summary;
  const topItems = summary.items
    .filter((item) => item.requires_decision_point_rebase || item.freshness_state !== "fresh")
    .sort((left, right) => {
      const leftStale = left.requires_decision_point_rebase ? 0 : 1;
      const rightStale = right.requires_decision_point_rebase ? 0 : 1;
      return leftStale - rightStale
        || (right.newer_event_count_7d ?? 0) - (left.newer_event_count_7d ?? 0)
        || (right.age_days ?? 0) - (left.age_days ?? 0);
    })
    .slice(0, 5);
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <RotateCcw className="h-4 w-4" />
          决策新鲜度
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant={counts.rebase_required_count > 0 ? "warning" : "success"}>
            需重新确认 {counts.rebase_required_count}
          </Badge>
          <Badge variant="neutral">{summary.window_days} 天窗口</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <p className="mb-3 text-sm leading-6 text-slate-600 dark:text-zinc-300">
          这里检查旧评价或确认是否需要在审批、转交前重读当前控制面状态；精确回放仍以只追加运行历史为准。
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <UsageMetric label="决策数" value={formatUsageCount(counts.decision_count)} />
          <UsageMetric label="已过期" value={formatUsageCount(counts.stale_count)} />
          <UsageMetric label="需重新确认" value={formatUsageCount(counts.rebase_required_count)} />
          <UsageMetric label="仍然有效" value={formatUsageCount(counts.fresh_count)} />
        </div>
        {topItems.length ? (
          <div
            className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-zinc-800"
            data-testid="decision-freshness-table"
          >
            <div className="grid grid-cols-[minmax(0,1fr)_92px_72px_72px] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
              <div>Goal</div>
              <div className="text-right">状态</div>
              <div className="text-right">事件</div>
              <div className="text-right">距今天数</div>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-zinc-800">
              {topItems.map((item, index) => (
                <div
                  className="grid grid-cols-[minmax(0,1fr)_92px_72px_72px] gap-2 px-3 py-2 text-sm"
                  key={`${item.goal_id}-${item.decision_at ?? index}`}
                >
                  <div className="min-w-0">
                    <div className="break-all font-medium text-slate-900 dark:text-zinc-100">{item.goal_id}</div>
                    <div className="mt-0.5 text-[11px] text-slate-500 dark:text-zinc-400">
                      {shareDecisionKindLabel(item.decision_kind)}
                    </div>
                  </div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">
                    {shareDecisionFreshnessStateLabel(item.freshness_state)}
                  </div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{item.newer_event_count_7d ?? 0}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">
                    {item.age_days != null ? `${Math.round(item.age_days)}d` : "-"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-100">
            当前样本里没有需要重新确认的检查点决策。
          </div>
        )}
        {summary.proxy_note ? (
          <div className="mt-3 text-xs text-slate-500 dark:text-zinc-400">{summary.proxy_note}</div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function UsageStatsPanel({ usage }: { usage?: UsageSummary | null }) {
  if (!usage?.available) {
    return null;
  }
  const totals = usage.totals;
  const topGoals = usage.goals.slice(0, 5);
  return (
    <Card>
      <CardHeader className="flex-wrap">
        <CardTitle className="flex items-center gap-2">
          <Gauge className="h-4 w-4" />
          使用情况快照
        </CardTitle>
        <div className="flex flex-wrap gap-2">
          <Badge variant="info">{usage.source}</Badge>
          <Badge variant="neutral">{usage.sample_run_count} 个样本</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <UsageMetric label="24 小时运行" value={formatUsageCount(totals.runs_24h)} />
          <UsageMetric label="7 天运行" value={formatUsageCount(totals.runs_7d)} />
          <UsageMetric
            label="配额槽位"
            value={`${formatUsageCount(totals.quota_spend_slots_24h)} / ${formatUsageCount(totals.quota_spend_slots_7d)}`}
          />
          <UsageMetric
            label="自动化运行"
            value={`${formatUsageCount(totals.automation_run_count_24h)} / ${formatUsageCount(totals.automation_run_count_7d)}`}
          />
          <UsageMetric
            label="有进展运行"
            value={`${formatUsageCount(totals.progress_signal_run_count_24h)} / ${formatUsageCount(totals.progress_signal_run_count_7d)}`}
          />
        </div>
        {topGoals.length ? (
          <div
            className="mt-4 overflow-hidden rounded-lg border border-slate-200 dark:border-zinc-800"
            data-testid="usage-goal-table"
          >
            <div className="grid grid-cols-[minmax(0,1fr)_70px_70px_80px_80px] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
              <div>Goal</div>
              <div className="text-right">24h</div>
              <div className="text-right">7d</div>
              <div className="text-right">进展</div>
              <div className="text-right">占比</div>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-zinc-800">
              {topGoals.map((goal) => (
                <div
                  className="grid grid-cols-[minmax(0,1fr)_70px_70px_80px_80px] gap-2 px-3 py-2 text-sm"
                  key={goal.goal_id}
                >
                  <div className="min-w-0 break-all font-medium text-slate-900 dark:text-zinc-100">{goal.goal_id}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{goal.runs_24h}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{goal.runs_7d}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{goal.progress_signal_run_count_24h}</div>
                  <div className="text-right text-slate-600 dark:text-zinc-300">{formatUsageShare(goal.project_share_24h)}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
        {usage.proxy_note ? (
          <div className="mt-3 text-xs text-slate-500 dark:text-zinc-400">{usage.proxy_note}</div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MetricCard({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  tone: "neutral" | "success" | "warning" | "info" | "danger";
}) {
  const toneClass = {
    neutral: "text-slate-700 dark:text-zinc-300",
    success: "text-emerald-700 dark:text-emerald-300",
    warning: "text-amber-700 dark:text-amber-300",
    info: "text-sky-700 dark:text-sky-300",
    danger: "text-rose-700 dark:text-rose-300",
  }[tone];
  return (
    <Card className="min-h-32">
      <CardHeader>
        <div>
          <CardTitle>{label}</CardTitle>
          <div className="mt-3 text-3xl font-semibold">{value}</div>
        </div>
        <Icon className={cn("h-5 w-5", toneClass)} />
      </CardHeader>
    </Card>
  );
}
