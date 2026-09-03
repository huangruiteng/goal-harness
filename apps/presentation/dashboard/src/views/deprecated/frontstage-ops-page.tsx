import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bot,
  CircleAlert,
  Clock3,
  ExternalLink,
  GitBranch,
  LayoutDashboard,
  ListChecks,
  RefreshCw,
  Search,
  ShieldCheck,
  Users,
} from "lucide-react";

import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import {
  fetchFrontstageStatusPayload,
  localDashboardApiCapabilities,
  resolveFrontstageOpsStatusUrl,
  statusContractFreshnessIssue,
} from "../../data/local-status-query";
import {
  actionKindTone,
  deriveOperatorStateSignals,
  eventClassificationTone,
  leaseStatusTone,
  sampleGoalChannelProjection,
  type BadgeTone,
  type GoalChannelProjection,
  type GoalChannelTodo,
} from "../../data/goal-channel-frontstage";
import { formatStatusError, type StatusPayload } from "../../data/status";
import { cn } from "../../lib/utils";
import "./frontstage-ops.css";

export type DeprecatedFrontstageOpsSearch = {
  goalId: string;
  statusUrl: string;
  todoLane: "all" | "user" | "agent";
  todoQuery: string;
};

type ProjectionOption = {
  goalId: string;
  projection: GoalChannelProjection;
};

function statusTone(value?: string): BadgeTone {
  const normalized = value?.toLowerCase();
  if (!normalized) return "neutral";
  if (["done", "closed", "resolved"].includes(normalized)) return "success";
  if (
    [
      "blocked",
      "action_required",
      "waiting",
      "capability_wait",
      "workspace_repair",
    ].includes(normalized)
  )
    return "warning";
  if (["failed", "error"].includes(normalized)) return "danger";
  return "info";
}

function priorityTone(priority?: string): BadgeTone {
  if (priority === "P0") return "danger";
  if (priority === "P1") return "warning";
  if (priority === "P2") return "info";
  return "neutral";
}

function text(value: unknown) {
  return value === null || value === undefined ? "n/a" : String(value);
}

function artifactText(value: unknown) {
  const rendered = text(value);
  return rendered.length > 96 ? `${rendered.slice(0, 93)}...` : rendered;
}

function warningText(value: string | string[] | undefined) {
  return Array.isArray(value)
    ? value.join(", ")
    : (value ?? "compact source warning");
}

function openTodoCount(todos: GoalChannelTodo[]) {
  return todos.filter((todo) => todo.status === "open").length;
}

function filterTodos(todos: GoalChannelTodo[], query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return todos;
  return todos.filter((todo) =>
    [
      todo.todo_id,
      todo.priority,
      todo.status,
      todo.title,
      todo.claimed_by,
      todo.task_class,
      todo.action_kind,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(normalized),
  );
}

function projectionOptions(payload: StatusPayload): ProjectionOption[] {
  return payload.attention_queue.items.flatMap((item) =>
    item.goal_channel_projection
      ? [{ goalId: item.goal_id, projection: item.goal_channel_projection }]
      : [],
  );
}

function Panel({
  children,
  className,
  icon: Icon,
  title,
}: {
  children: React.ReactNode;
  className?: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}) {
  return (
    <section
      className={cn(
        "rounded-lg border border-slate-200 bg-white shadow-sm",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          <Icon className="h-4 w-4 text-slate-500" />
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

function TodoRow({ todo }: { todo: GoalChannelTodo }) {
  return (
    <div className="grid gap-3 border-b border-slate-200 px-3 py-3 last:border-b-0 md:grid-cols-[96px_minmax(0,1fr)_156px]">
      <div className="flex flex-wrap gap-1">
        {todo.priority ? (
          <Badge variant={priorityTone(todo.priority)}>{todo.priority}</Badge>
        ) : null}
        <Badge variant={statusTone(todo.status)}>{todo.status}</Badge>
      </div>
      <div className="min-w-0">
        <p className="break-words text-sm font-medium leading-6 text-slate-950">
          {todo.title}
        </p>
        <div className="mt-1 flex flex-wrap gap-2 text-[11px] font-medium text-slate-500">
          {todo.todo_id ? <span>{todo.todo_id}</span> : null}
          {todo.task_class ? <span>{todo.task_class}</span> : null}
        </div>
        {todo.action_kind ? (
          <div className="mt-2">
            <Badge variant={actionKindTone(todo.action_kind)}>
              {todo.action_kind}
            </Badge>
          </div>
        ) : null}
      </div>
      <div className="flex items-start justify-start md:justify-end">
        {todo.claimed_by ? (
          <Badge variant="info">
            <Bot className="h-3 w-3" />
            {todo.claimed_by}
          </Badge>
        ) : (
          <Badge variant="neutral">unclaimed</Badge>
        )}
      </div>
    </div>
  );
}

function EmptyLane({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-4 text-sm font-medium leading-6 text-slate-500">
      {children}
    </div>
  );
}

export function DeprecatedFrontstageOpsPage({
  onNavigate,
  onOpenShowcase,
  search,
}: {
  onNavigate: (next: Partial<DeprecatedFrontstageOpsSearch>) => Promise<void>;
  onOpenShowcase: () => Promise<void>;
  search: DeprecatedFrontstageOpsSearch;
}) {
  const [statusUrl, setStatusUrl] = useState(search.statusUrl);
  const [manualLoadError, setManualLoadError] = useState<string | null>(null);
  const resolvedStatusUrl = useMemo(
    () =>
      search.statusUrl
        ? resolveFrontstageOpsStatusUrl(search.statusUrl, window.location.href)
        : null,
    [search.statusUrl],
  );
  const statusQuery = useQuery({
    enabled: Boolean(resolvedStatusUrl?.source),
    queryFn: () =>
      fetchFrontstageStatusPayload(resolvedStatusUrl?.source?.url ?? ""),
    queryKey: [
      "deprecated-frontstage-ops-status",
      resolvedStatusUrl?.source?.url ?? "",
    ],
  });
  const payload = statusQuery.data ?? null;
  const options = useMemo(
    () => (payload ? projectionOptions(payload) : []),
    [payload],
  );
  const selectedGoalId = options.some(
    (option) => option.goalId === search.goalId,
  )
    ? search.goalId
    : (options[0]?.goalId ?? sampleGoalChannelProjection.goal_id);
  const projection =
    options.find((option) => option.goalId === selectedGoalId)?.projection ??
    sampleGoalChannelProjection;
  const freshnessIssue =
    payload && resolvedStatusUrl?.source
      ? statusContractFreshnessIssue(payload, resolvedStatusUrl.source)
      : null;
  const capabilities =
    payload && resolvedStatusUrl?.source
      ? localDashboardApiCapabilities(payload, resolvedStatusUrl.source)
      : null;
  const loadError =
    manualLoadError ??
    resolvedStatusUrl?.error ??
    (statusQuery.error ? formatStatusError(statusQuery.error) : null) ??
    (statusQuery.isSuccess && options.length === 0
      ? "status feed has no goal_channel_projection items; showing demo fixture"
      : null);
  const queryState = !resolvedStatusUrl?.source
    ? "query idle"
    : statusQuery.isFetching
      ? "query fetching"
      : statusQuery.isStale
        ? "query stale"
        : "query fresh";

  useEffect(() => setStatusUrl(search.statusUrl), [search.statusUrl]);
  useEffect(() => {
    if (options.length && search.goalId !== selectedGoalId)
      void onNavigate({ goalId: selectedGoalId });
  }, [onNavigate, options, search.goalId, selectedGoalId]);

  async function loadStatus() {
    const resolved = resolveFrontstageOpsStatusUrl(
      statusUrl,
      window.location.href,
    );
    if (resolved.error || !resolved.source) {
      setManualLoadError(resolved.error ?? "status URL is invalid");
      return;
    }
    setManualLoadError(null);
    if (search.statusUrl === resolved.source.url) {
      await statusQuery.refetch();
      return;
    }
    await onNavigate({ goalId: "", statusUrl: resolved.source.url });
  }

  const openUserTodos = openTodoCount(projection.user_todos);
  const openAgentTodos = openTodoCount(projection.agent_todos);
  const claimedAgentTodos = projection.agent_todos.filter((todo) =>
    Boolean(todo.claimed_by),
  ).length;
  const claimOwners = Array.from(
    new Set(
      [
        ...projection.agent_todos.map((todo) => todo.claimed_by),
        ...projection.active_leases.map((lease) => lease.owner_agent),
      ].filter((value): value is string => Boolean(value)),
    ),
  );
  const quotaUsed = `${text(projection.quota.spent_slots)} / ${text(projection.quota.allowed_slots ?? "?")}`;
  const userTodos =
    search.todoLane === "agent"
      ? []
      : filterTodos(projection.user_todos, search.todoQuery);
  const agentTodos =
    search.todoLane === "user"
      ? []
      : filterTodos(projection.agent_todos, search.todoQuery);
  const visibleTodoCount = userTodos.length + agentTodos.length;
  const totalTodoCount =
    projection.user_todos.length + projection.agent_todos.length;
  const operatorSignals = deriveOperatorStateSignals(projection);
  const personalWorkspaceHref = `/?${new URLSearchParams({ goalId: selectedGoalId, statusUrl: search.statusUrl }).toString()}`;

  return (
    <main
      className="frontstage-ops-workspace min-h-screen bg-[#f7f7f4] px-4 py-4 text-slate-950 sm:px-5"
      data-frontstage-surface="ops-control-plane"
      data-mode={projection.mode}
      data-schema={projection.schema_version}
      data-testid="goal-channel-frontstage-route"
    >
      <div
        className="mx-auto mb-4 flex max-w-[1500px] flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950"
        data-testid="frontstage-ops-deprecated"
        role="status"
      >
        <span>
          <strong>Deprecated diagnostic surface.</strong> New operator workflows
          and milestone reports live in Personal Workspace.
        </span>
        <a
          className="rounded-md bg-amber-950 px-3 py-2 font-semibold text-white"
          href={personalWorkspaceHref}
        >
          Open Personal Workspace
        </a>
      </div>
      <div
        className="frontstage-workspace-shell mx-auto grid max-w-[1500px] gap-4 xl:grid-cols-[260px_minmax(0,1fr)_320px]"
        data-testid="frontstage-ops-workspace-shell"
      >
        <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm xl:sticky xl:top-4 xl:self-start">
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-slate-950 text-white">
              <GitBranch className="h-4 w-4" />
            </div>
            <div>
              <strong>LoopX</strong>
              <div className="text-xs text-slate-500">
                Deprecated diagnostics
              </div>
            </div>
          </div>
          <div className="mt-4 grid gap-2">
            <a
              className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium"
              href="/"
            >
              <LayoutDashboard className="h-4 w-4" />
              Personal Workspace
            </a>
            <button
              className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-left text-sm font-medium"
              onClick={() => void onOpenShowcase()}
              type="button"
            >
              <Activity className="h-4 w-4" />
              Public Showcase
            </button>
            <a
              className="flex items-center gap-2 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium"
              href="/frontstage/developer"
            >
              <ExternalLink className="h-4 w-4" />
              Developer cockpit
            </a>
          </div>
          <div
            className="mt-5 space-y-2 rounded-md border border-slate-200 bg-slate-50 p-3"
            data-testid="frontstage-live-source-panel"
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="warning">ops live</Badge>
              <Badge variant={payload ? "info" : "neutral"}>
                {payload ? "live status feed" : "bundled fixture"}
              </Badge>
              <Badge variant={payload ? "success" : "neutral"}>
                {queryState}
              </Badge>
            </div>
            <input
              aria-label="Status URL"
              className="h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-xs"
              data-testid="frontstage-status-url-input"
              onChange={(event) => setStatusUrl(event.target.value)}
              placeholder="/status.local.json or http://127.0.0.1:8766/status.json"
              value={statusUrl}
            />
            <div className="text-[11px] font-medium text-slate-500">
              Ops statusUrl accepts only relative or loopback sources.
            </div>
            <div className="flex gap-2">
              <Button
                className="flex-1"
                data-testid="frontstage-load-status-url"
                disabled={statusQuery.isFetching}
                onClick={() => void loadStatus()}
                size="sm"
                variant="primary"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                Load
              </Button>
              <Button
                data-testid="frontstage-reset-demo"
                disabled={statusQuery.isFetching}
                onClick={() => void onOpenShowcase()}
                size="sm"
              >
                Showcase
              </Button>
            </div>
            {options.length ? (
              <Select
                aria-label="Goal channel"
                className="w-full text-xs"
                data-testid="frontstage-goal-select"
                onChange={(event) =>
                  void onNavigate({ goalId: event.target.value })
                }
                value={selectedGoalId}
              >
                {options.map((option) => (
                  <option key={option.goalId} value={option.goalId}>
                    {option.projection.display_name}
                  </option>
                ))}
              </Select>
            ) : null}
            {loadError ? (
              <div
                className="flex gap-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-2 text-xs text-amber-950"
                data-testid="frontstage-load-error"
              >
                <CircleAlert className="h-3.5 w-3.5" />
                {loadError}
              </div>
            ) : null}
            {freshnessIssue ? (
              <div
                className="rounded-md border border-amber-200 bg-amber-50 px-2 py-2 text-xs text-amber-950"
                data-testid="frontstage-stale-daemon-repair"
              >
                status service contract stale · schema v
                {freshnessIssue.schemaVersion}
                <p>
                  Restart with{" "}
                  <span className="font-mono">{freshnessIssue.reloadHint}</span>
                  .
                </p>
              </div>
            ) : null}
            {capabilities ? (
              <div
                className="grid gap-2 rounded-md border border-slate-200 bg-white px-2 py-2 text-xs leading-5 text-slate-600"
                data-testid="frontstage-local-api-capabilities"
              >
                <div className="flex flex-wrap gap-2">
                  <Badge variant="info">TanStack Query</Badge>
                  <Badge
                    variant={
                      capabilities.readOnlyDefault ? "success" : "warning"
                    }
                  >
                    {capabilities.readOnlyDefault
                      ? "read-only default"
                      : "write opt-in active"}
                  </Badge>
                </div>
                <div>
                  <strong>local_dashboard_api:</strong> {capabilities.source}
                </div>
                <span>
                  reward dry-run{" "}
                  {capabilities.rewardDryRunUrl
                    ? "advertised"
                    : "not advertised"}
                  ; append{" "}
                  {capabilities.rewardWriteEnabled
                    ? "enabled by loopback opt-in"
                    : "disabled"}
                </span>
                <span>
                  control-plane dry-run{" "}
                  {capabilities.controlPlaneDryRunUrl
                    ? "advertised"
                    : "not advertised"}
                  ; apply{" "}
                  {capabilities.controlPlaneWriteEnabled
                    ? "enabled by loopback opt-in"
                    : "disabled"}
                </span>
                <span>
                  Write affordances require explicit loopback opt-in and
                  preview-locked APIs.
                </span>
              </div>
            ) : null}
          </div>
        </aside>

        <section className="frontstage-ops-main-pane space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white px-5 py-5 shadow-sm">
            <div className="flex flex-wrap gap-2">
              <Badge variant="success">goal_channel_projection_v0</Badge>
              <Badge variant="warning">ops live</Badge>
              <Badge variant={payload ? "success" : "neutral"}>
                {payload ? "url" : "demo"}
              </Badge>
            </div>
            <h1 className="mt-3 text-2xl font-semibold">
              {projection.display_name}
            </h1>
            <p className="mt-1 text-sm text-slate-500">
              Always-on agent operations, with human judgment kept in the
              control plane.
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-700">
              {projection.next_action}
            </p>
            <div
              className="mt-5 grid gap-2 border-t border-slate-200 pt-4 sm:grid-cols-2 xl:grid-cols-4"
              data-testid="frontstage-operations-strip"
            >
              {[
                [
                  "human gate",
                  projection.decision_frame.user_action_required
                    ? "explicit"
                    : "clear",
                ],
                [
                  "agent work",
                  projection.decision_frame.agent_action_required
                    ? "running"
                    : "idle",
                ],
                [
                  "claimed lanes",
                  `${claimedAgentTodos} / ${projection.agent_todos.length}`,
                ],
                ["evidence loop", `${projection.recent_events.length} events`],
              ].map(([label, value]) => (
                <div
                  className="rounded-md border border-slate-200 bg-slate-50 px-3 py-3"
                  key={label}
                >
                  <div className="text-[11px] font-semibold uppercase text-slate-500">
                    {label}
                  </div>
                  <div className="mt-2">
                    <Badge variant="info">{value}</Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <Panel icon={LayoutDashboard} title="Management Surface Mock">
            <div
              className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3"
              data-testid="frontstage-management-surface-mock"
            >
              {[
                [
                  "mission",
                  "Mission Bar",
                  "goal_id + next_action",
                  projection.display_name,
                ],
                [
                  "team",
                  "Team Roster",
                  "active_leases + claimed_by",
                  `${claimOwners.length} visible agents`,
                ],
                [
                  "tickets",
                  "Ticket Board",
                  "user_todos + agent_todos",
                  `${openUserTodos + openAgentTodos} open tickets`,
                ],
                [
                  "gates",
                  "Gate Inbox",
                  "decision_frame + open_gates",
                  projection.decision_frame.user_action_required
                    ? "decision visible"
                    : "clear",
                ],
                [
                  "cadence",
                  "Cadence / Budget",
                  "quota + scheduler hints",
                  quotaUsed,
                ],
                [
                  "evidence",
                  "Evidence Timeline",
                  "recent_events + artifacts",
                  `${projection.recent_events.length} events`,
                ],
              ].map(([id, label, source, value]) => (
                <div
                  className="rounded-md border border-slate-200 bg-slate-50 p-3"
                  data-testid={`frontstage-management-${id}`}
                  key={id}
                >
                  <strong>{label}</strong>
                  <div className="text-[11px] text-slate-500">{source}</div>
                  <div className="mt-2 text-lg font-semibold">{value}</div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel icon={Users} title="Decision Frame">
              <div className="grid gap-2 p-4">
                <Badge
                  variant={
                    projection.decision_frame.user_action_required
                      ? "success"
                      : "neutral"
                  }
                >
                  {projection.decision_frame.user_action_required
                    ? "user action"
                    : "no user action"}
                </Badge>
                <Badge
                  variant={
                    projection.decision_frame.agent_action_required
                      ? "success"
                      : "neutral"
                  }
                >
                  {projection.decision_frame.agent_action_required
                    ? "agent action"
                    : "no agent action"}
                </Badge>
              </div>
            </Panel>
            <Panel icon={ShieldCheck} title="Quota Guard">
              <div className="space-y-2 p-4 text-sm">
                <Badge variant={statusTone(text(projection.quota.state))}>
                  {text(projection.quota.state)}
                </Badge>
                <div>{quotaUsed}</div>
                <p>{text(projection.quota.spend_policy)}</p>
              </div>
            </Panel>
            <Panel icon={Clock3} title="Source Freshness">
              <div className="space-y-2 p-4 text-xs">
                {Object.entries(projection.source_refs).map(([key, value]) => (
                  <div className="rounded-md bg-slate-50 p-2" key={key}>
                    <strong>{key}</strong>
                    <div>{text(value)}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel icon={BarChart3} title="Budget & Governance">
            <div
              className="grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-5"
              data-testid="frontstage-budget-governance"
            >
              {[
                [
                  "budget",
                  quotaUsed,
                  `quota state: ${text(projection.quota.state)}`,
                ],
                [
                  "cadence",
                  text(
                    projection.quota.scheduler_rrule ??
                      projection.quota.cadence_class ??
                      "scheduler hint",
                  ),
                  `reset token: ${text(projection.quota.scheduler_reset_token ?? "not projected")}`,
                ],
                [
                  "spend rule",
                  text(projection.quota.spend_policy),
                  "Watch lanes stay monitor state; cadence changes, final checks, and monitor-only polls are no-spend.",
                ],
                [
                  "controls",
                  text(projection.quota.override_policy ?? "preview gated"),
                  text(
                    projection.quota.pause_policy ??
                      "writes require CLI or loopback opt-in",
                  ),
                ],
                [
                  "evidence",
                  text(
                    projection.quota.latest_evidence_ref ??
                      projection.source_refs.latest_run_generated_at ??
                      "run history",
                  ),
                  "Audit through todo ids, run history, and quota spend events.",
                ],
              ].map(([label, value, helper]) => (
                <div
                  className="rounded-md border border-slate-200 bg-slate-50 p-3"
                  key={label}
                >
                  <div className="text-[11px] font-semibold uppercase text-slate-500">
                    {label}
                  </div>
                  <strong className="mt-2 block">{value}</strong>
                  <p className="mt-2 text-xs">{helper}</p>
                </div>
              ))}
            </div>
          </Panel>

          <Panel icon={ListChecks} title="Operator State Legibility">
            <div
              className="grid gap-2 p-4 sm:grid-cols-2 xl:grid-cols-4"
              data-testid="frontstage-operator-state-legibility"
            >
              {operatorSignals.map((signal) => (
                <div
                  className="rounded-md border border-slate-200 bg-slate-50 p-3"
                  data-testid={`frontstage-state-${signal.label}`}
                  key={signal.label}
                >
                  <div className="text-[11px] font-semibold uppercase text-slate-500">
                    {signal.label}
                  </div>
                  <strong className="mt-2 block">{signal.value}</strong>
                  <p className="mt-2 text-xs">{signal.helper}</p>
                  <Badge variant={signal.tone}>{signal.label}</Badge>
                </div>
              ))}
            </div>
          </Panel>

          <div className="grid gap-4 lg:grid-cols-2">
            <div
              className="frontstage-ops-command-strip rounded-lg border border-slate-200 bg-white p-4 shadow-sm lg:col-span-2"
              data-testid="frontstage-ops-command-strip"
            >
              <div
                className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_180px_auto]"
                data-testid="frontstage-todo-discovery"
              >
                <label>
                  <span className="text-[11px] font-semibold uppercase text-slate-500">
                    Search todo projection
                  </span>
                  <span className="relative mt-1 block">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                    <input
                      aria-label="Search projected todos"
                      className="h-9 w-full rounded-md border border-slate-200 pl-9 pr-3 text-sm"
                      data-testid="frontstage-todo-search"
                      onChange={(event) =>
                        void onNavigate({ todoQuery: event.target.value })
                      }
                      value={search.todoQuery}
                    />
                  </span>
                </label>
                <label>
                  <span className="text-[11px] font-semibold uppercase text-slate-500">
                    Lane
                  </span>
                  <Select
                    aria-label="Todo lane filter"
                    className="mt-1 w-full text-sm"
                    data-testid="frontstage-todo-lane-filter"
                    onChange={(event) =>
                      void onNavigate({
                        todoLane: event.target
                          .value as DeprecatedFrontstageOpsSearch["todoLane"],
                      })
                    }
                    value={search.todoLane}
                  >
                    <option value="all">All lanes</option>
                    <option value="user">User todos</option>
                    <option value="agent">Agent todos</option>
                  </Select>
                </label>
                <div
                  className="flex min-h-9 items-center rounded-md border border-slate-200 bg-slate-50 px-3 text-xs font-semibold"
                  data-testid="frontstage-todo-result-count"
                >
                  Showing {visibleTodoCount} of {totalTodoCount} projected todos
                </div>
              </div>
            </div>
            <Panel icon={Users} title="User Todo Lane">
              <div data-testid="frontstage-user-todos">
                {userTodos.map((todo) => (
                  <TodoRow key={todo.todo_id ?? todo.title} todo={todo} />
                ))}
                {!userTodos.length ? (
                  <EmptyLane>
                    No user todos match the current filters.
                  </EmptyLane>
                ) : null}
              </div>
            </Panel>
            <Panel icon={Bot} title="Agent Todo Lane">
              <div data-testid="frontstage-agent-todos">
                {agentTodos.map((todo) => (
                  <TodoRow key={todo.todo_id ?? todo.title} todo={todo} />
                ))}
                {!agentTodos.length ? (
                  <EmptyLane>
                    No agent todos match the current filters.
                  </EmptyLane>
                ) : null}
              </div>
            </Panel>
          </div>
          <Panel icon={Activity} title="Run Timeline">
            <div
              className="divide-y divide-slate-200"
              data-testid="frontstage-timeline"
            >
              {projection.recent_events.map((event, index) => (
                <div
                  className="grid gap-3 px-4 py-3 md:grid-cols-[190px_180px_minmax(0,1fr)]"
                  key={`${event.generated_at ?? "event"}-${index}`}
                >
                  <div className="font-mono text-xs text-slate-500">
                    {event.generated_at ?? "n/a"}
                  </div>
                  <Badge
                    variant={eventClassificationTone(event.classification)}
                  >
                    {event.classification ?? "event"}
                  </Badge>
                  <div className="text-sm">
                    {event.summary ?? "compact event"}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </section>

        <aside className="space-y-4">
          <Panel icon={Users} title="Role Map">
            <div className="space-y-3 p-4" data-testid="frontstage-role-map">
              <div>
                owner ·{" "}
                {projection.decision_frame.user_action_required
                  ? "decision visible"
                  : "no gate"}
              </div>
              <div>
                agent lane ·{" "}
                {projection.decision_frame.agent_action_required
                  ? "active"
                  : "idle"}
              </div>
              <div>claim owners · {claimOwners.join(", ") || "none"}</div>
            </div>
          </Panel>
          <Panel icon={ListChecks} title="Active Claims">
            <div
              className="divide-y divide-slate-200"
              data-testid="frontstage-active-claims"
            >
              {projection.active_leases.map((lease, index) => (
                <div
                  className="px-4 py-3"
                  key={`${lease.todo_id ?? "claim"}-${index}`}
                >
                  <Badge variant="info">{lease.owner_agent ?? "unknown"}</Badge>
                  <Badge variant={leaseStatusTone(lease.status)}>
                    {lease.status ?? "claim"}
                  </Badge>
                  <div className="mt-2 text-xs">{lease.todo_id}</div>
                  {lease.lease_until ? (
                    <div>until {lease.lease_until}</div>
                  ) : null}
                  {lease.write_scope?.map((scope) => (
                    <Badge key={scope} variant="warning">
                      {scope}
                    </Badge>
                  ))}
                </div>
              ))}
            </div>
          </Panel>
          <Panel icon={CircleAlert} title="Open Gates">
            <div
              className="divide-y divide-slate-200"
              data-testid="frontstage-open-gates"
            >
              {projection.open_gates.map((gate) => (
                <div className="px-4 py-3" key={gate.gate_id}>
                  <Badge variant={statusTone(gate.status)}>{gate.status}</Badge>
                  <Badge variant="neutral">{gate.kind}</Badge>
                  <div>{gate.gate_id}</div>
                  {gate.blocks?.map((blocker) => (
                    <Badge key={blocker} variant="warning">
                      {blocker}
                    </Badge>
                  ))}
                </div>
              ))}
              {!projection.open_gates.length ? (
                <EmptyLane>No open gates in this projection.</EmptyLane>
              ) : null}
            </div>
          </Panel>
          <Panel icon={ExternalLink} title="Artifacts">
            <div
              className="divide-y divide-slate-200"
              data-testid="frontstage-artifacts"
            >
              {projection.artifacts.map((artifact, index) => (
                <div
                  className="space-y-2 px-4 py-3"
                  key={`${artifact.kind ?? "artifact"}-${index}`}
                >
                  {Object.entries(artifact).map(([key, value]) => (
                    <div className="rounded-md bg-slate-50 p-2" key={key}>
                      <strong>{key}</strong>
                      <div>{artifactText(value)}</div>
                    </div>
                  ))}
                </div>
              ))}
              {!projection.artifacts.length ? (
                <EmptyLane>No compact artifacts projected.</EmptyLane>
              ) : null}
            </div>
          </Panel>
          <Panel icon={ShieldCheck} title="Truth Contract">
            <div className="space-y-3 p-4 text-sm">
              <Badge
                variant={
                  projection.truth_contract.event_ledger_is_source_of_truth
                    ? "success"
                    : "neutral"
                }
              >
                ledger truth
              </Badge>
              <Badge
                variant={
                  !projection.truth_contract.projection_is_writable
                    ? "success"
                    : "warning"
                }
              >
                read-only
              </Badge>
              <p>{projection.truth_contract.recompute_rule}</p>
              <p>
                write authority: {projection.truth_contract.write_authority}
              </p>
            </div>
          </Panel>
          <Panel icon={ShieldCheck} title="Boundary Warnings">
            <div
              className="space-y-3 p-4"
              data-testid="frontstage-source-warnings"
            >
              {projection.source_warnings.map((warning, index) => (
                <div
                  className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm"
                  key={`${warning.kind}-${index}`}
                >
                  <strong>{warning.kind}</strong>
                  <p>{warningText(warning.message)}</p>
                </div>
              ))}
            </div>
          </Panel>
        </aside>
      </div>
    </main>
  );
}
