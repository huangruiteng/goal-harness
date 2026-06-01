import { useMemo, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  FileJson2,
  GitBranch,
  LayoutDashboard,
  Moon,
  Radar,
  RefreshCw,
  Sun,
  Users,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";

import { dashboardRoute } from "../router";
import { QueueItem, statusPayload } from "../data/status";
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
    label: "User / Controller",
    icon: Users,
    waitingOn: ["user_or_controller", "controller"],
    accent: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-100",
  },
  {
    key: "codex",
    label: "Codex Ready",
    icon: Bot,
    waitingOn: ["codex"],
    accent: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-100",
  },
  {
    key: "watch",
    label: "Watching Evidence",
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
  user_or_controller: "User / Controller",
  controller: "Controller",
  codex: "Codex",
  external_evidence: "Evidence",
};

function laneFor(item: QueueItem) {
  return laneConfig.find((lane) => lane.waitingOn.includes(item.waiting_on));
}

function ShortText({ children }: { children: string }) {
  return <span className="line-clamp-2 break-words">{children}</span>;
}

function StatusBadge({ value }: { value: string }) {
  return <Badge variant={severityVariant[value] ?? "neutral"}>{value}</Badge>;
}

function QueueTable({ items }: { items: QueueItem[] }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<QueueItem>[]>(
    () => [
      {
        accessorKey: "goal_id",
        header: "Goal",
        cell: ({ row }) => <span className="font-medium text-slate-900 dark:text-zinc-100">{row.original.goal_id}</span>,
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <Badge>{row.original.status}</Badge>,
      },
      {
        accessorKey: "waiting_on",
        header: "Waiting",
        cell: ({ row }) => waitingLabel[row.original.waiting_on] ?? row.original.waiting_on,
      },
      {
        accessorKey: "severity",
        header: "Severity",
        cell: ({ row }) => <StatusBadge value={row.original.severity} />,
      },
      {
        accessorKey: "recommended_action",
        header: "Action",
        cell: ({ row }) => <ShortText>{row.original.recommended_action}</ShortText>,
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
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
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
            <TableRow key={row.id}>
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

export function DashboardPage() {
  const search = dashboardRoute.useSearch();
  const navigate = dashboardRoute.useNavigate();
  const [theme, setTheme] = useState<"light" | "dark">("light");
  const queue = statusPayload.attention_queue;
  const filteredItems = queue.items.filter((item) => {
    const lane = laneFor(item)?.key ?? "all";
    const laneMatches = search.lane === "all" || search.lane === lane;
    const severityMatches = search.severity === "all" || search.severity === item.severity;
    return laneMatches && severityMatches;
  });
  const chartData = [
    { name: "User", count: queue.needs_user_or_controller },
    { name: "Codex", count: queue.needs_codex },
    { name: "Watch", count: queue.watching_external_evidence },
  ];

  return (
    <div className={theme === "dark" ? "dark" : ""}>
      <div className="min-h-screen bg-slate-100 text-slate-950 dark:bg-zinc-950 dark:text-zinc-50">
        <div className="grid min-h-screen lg:grid-cols-[240px_1fr]">
          <aside className="border-b border-slate-200 bg-white lg:border-b-0 lg:border-r dark:border-zinc-800 dark:bg-zinc-950">
            <div className="flex h-16 items-center gap-3 px-5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-950 text-white dark:border-zinc-800 dark:bg-zinc-50 dark:text-zinc-950">
                <GitBranch className="h-4 w-4" />
              </div>
              <div>
                <div className="text-sm font-semibold">Goal Harness</div>
                <div className="text-xs text-slate-500 dark:text-zinc-500">Local control plane</div>
              </div>
            </div>
            <nav className="flex gap-1 px-3 pb-3 lg:block lg:space-y-1 lg:pb-0">
              <a className="flex items-center gap-2 rounded-md bg-slate-100 px-3 py-2 text-sm font-medium dark:bg-zinc-900" href="/">
                <LayoutDashboard className="h-4 w-4" />
                Dashboard
              </a>
            </nav>
          </aside>

          <main className="min-w-0">
            <header className="flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6">
              <div>
                <h1 className="text-2xl font-semibold">Goal Operations</h1>
                <p className="mt-1 text-sm text-slate-500 dark:text-zinc-400">
                  {statusPayload.registry} · {statusPayload.runtime_root}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="icon" variant="secondary" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label="Toggle theme">
                  {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                </Button>
                <Button variant="primary" onClick={() => window.location.reload()}>
                  <RefreshCw className="h-4 w-4" />
                  Refresh
                </Button>
              </div>
            </header>

            <div className="space-y-5 p-4 sm:p-6">
              <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard icon={statusPayload.ok ? CheckCircle2 : CircleAlert} label="Status" value={statusPayload.ok ? "Healthy" : "Blocked"} tone={statusPayload.ok ? "success" : "danger"} />
                <MetricCard icon={GitBranch} label="Goals" value={String(statusPayload.goal_count)} tone="neutral" />
                <MetricCard icon={Clock3} label="Runs" value={String(statusPayload.run_count)} tone="info" />
                <MetricCard icon={FileJson2} label="Queue" value={String(queue.item_count)} tone="warning" />
              </section>

              <section className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
                <Card>
                  <CardHeader>
                    <div>
                      <CardTitle>Attention Lanes</CardTitle>
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
                                <p className="text-sm opacity-70">Clear</p>
                              ) : (
                                items.map((item) => (
                                  <div className="rounded-md border border-current/15 bg-white/65 p-3 text-sm dark:bg-zinc-950/55" key={item.goal_id}>
                                    <div className="flex flex-wrap items-center gap-2">
                                      <span className="font-medium">{item.goal_id}</span>
                                      <StatusBadge value={item.severity} />
                                    </div>
                                    <p className="mt-2 text-xs leading-5 opacity-80">{item.recommended_action}</p>
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <div>
                      <CardTitle>Queue Mix</CardTitle>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="h-64">
                      <ResponsiveContainer height="100%" width="100%">
                        <BarChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} />
                          <XAxis dataKey="name" tickLine={false} />
                          <Tooltip cursor={{ fill: "rgba(148, 163, 184, 0.12)" }} />
                          <Bar dataKey="count" fill="#0f766e" radius={[6, 6, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </CardContent>
                </Card>
              </section>

              <Card>
                <CardHeader className="flex-wrap">
                  <div>
                    <CardTitle>Attention Queue</CardTitle>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Select
                      aria-label="Lane filter"
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
                      <option value="all">All lanes</option>
                      <option value="user">User / Controller</option>
                      <option value="codex">Codex Ready</option>
                      <option value="watch">Watching Evidence</option>
                    </Select>
                    <Select
                      aria-label="Severity filter"
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
                      <option value="all">All severity</option>
                      <option value="high">High</option>
                      <option value="action">Action</option>
                      <option value="watch">Watch</option>
                    </Select>
                  </div>
                </CardHeader>
                <CardContent>
                  <QueueTable items={filteredItems} />
                </CardContent>
              </Card>
            </div>
          </main>
        </div>
      </div>
    </div>
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
