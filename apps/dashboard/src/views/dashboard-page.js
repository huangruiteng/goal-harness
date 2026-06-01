import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useMemo, useState } from "react";
import { Bot, CheckCircle2, CircleAlert, Clock3, FileJson2, GitBranch, LayoutDashboard, Moon, Radar, RefreshCw, Sun, Users, } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, } from "recharts";
import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, } from "@tanstack/react-table";
import { dashboardRoute } from "../router";
import { statusPayload } from "../data/status";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow, } from "../components/ui/table";
import { cn } from "../lib/utils";
const laneConfig = [
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
const severityVariant = {
    high: "danger",
    action: "warning",
    watch: "info",
};
const waitingLabel = {
    user_or_controller: "User / Controller",
    controller: "Controller",
    codex: "Codex",
    external_evidence: "Evidence",
};
function laneFor(item) {
    return laneConfig.find((lane) => lane.waitingOn.includes(item.waiting_on));
}
function ShortText({ children }) {
    return _jsx("span", { className: "line-clamp-2 break-words", children: children });
}
function StatusBadge({ value }) {
    return _jsx(Badge, { variant: severityVariant[value] ?? "neutral", children: value });
}
function QueueTable({ items }) {
    const [sorting, setSorting] = useState([]);
    const columns = useMemo(() => [
        {
            accessorKey: "goal_id",
            header: "Goal",
            cell: ({ row }) => _jsx("span", { className: "font-medium text-slate-900 dark:text-zinc-100", children: row.original.goal_id }),
        },
        {
            accessorKey: "status",
            header: "Status",
            cell: ({ row }) => _jsx(Badge, { children: row.original.status }),
        },
        {
            accessorKey: "waiting_on",
            header: "Waiting",
            cell: ({ row }) => waitingLabel[row.original.waiting_on] ?? row.original.waiting_on,
        },
        {
            accessorKey: "severity",
            header: "Severity",
            cell: ({ row }) => _jsx(StatusBadge, { value: row.original.severity }),
        },
        {
            accessorKey: "recommended_action",
            header: "Action",
            cell: ({ row }) => _jsx(ShortText, { children: row.original.recommended_action }),
        },
    ], []);
    const table = useReactTable({
        data: items,
        columns,
        state: { sorting },
        onSortingChange: setSorting,
        getCoreRowModel: getCoreRowModel(),
        getSortedRowModel: getSortedRowModel(),
    });
    return (_jsx("div", { className: "overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-zinc-800 dark:bg-zinc-950", children: _jsxs(Table, { children: [_jsx(TableHeader, { children: table.getHeaderGroups().map((headerGroup) => (_jsx(TableRow, { children: headerGroup.headers.map((header) => (_jsx(TableHead, { children: header.isPlaceholder ? null : (_jsx("button", { className: "flex items-center gap-1 text-left", onClick: header.column.getToggleSortingHandler(), type: "button", children: flexRender(header.column.columnDef.header, header.getContext()) })) }, header.id))) }, headerGroup.id))) }), _jsx(TableBody, { children: table.getRowModel().rows.map((row) => (_jsx(TableRow, { children: row.getVisibleCells().map((cell) => (_jsx(TableCell, { children: flexRender(cell.column.columnDef.cell, cell.getContext()) }, cell.id))) }, row.id))) })] }) }));
}
export function DashboardPage() {
    const search = dashboardRoute.useSearch();
    const navigate = dashboardRoute.useNavigate();
    const [theme, setTheme] = useState("light");
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
    return (_jsx("div", { className: theme === "dark" ? "dark" : "", children: _jsx("div", { className: "min-h-screen bg-slate-100 text-slate-950 dark:bg-zinc-950 dark:text-zinc-50", children: _jsxs("div", { className: "grid min-h-screen lg:grid-cols-[240px_1fr]", children: [_jsxs("aside", { className: "border-b border-slate-200 bg-white lg:border-b-0 lg:border-r dark:border-zinc-800 dark:bg-zinc-950", children: [_jsxs("div", { className: "flex h-16 items-center gap-3 px-5", children: [_jsx("div", { className: "flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-slate-950 text-white dark:border-zinc-800 dark:bg-zinc-50 dark:text-zinc-950", children: _jsx(GitBranch, { className: "h-4 w-4" }) }), _jsxs("div", { children: [_jsx("div", { className: "text-sm font-semibold", children: "Goal Harness" }), _jsx("div", { className: "text-xs text-slate-500 dark:text-zinc-500", children: "Local control plane" })] })] }), _jsx("nav", { className: "flex gap-1 px-3 pb-3 lg:block lg:space-y-1 lg:pb-0", children: _jsxs("a", { className: "flex items-center gap-2 rounded-md bg-slate-100 px-3 py-2 text-sm font-medium dark:bg-zinc-900", href: "/", children: [_jsx(LayoutDashboard, { className: "h-4 w-4" }), "Dashboard"] }) })] }), _jsxs("main", { className: "min-w-0", children: [_jsxs("header", { className: "flex min-h-16 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950 sm:px-6", children: [_jsxs("div", { children: [_jsx("h1", { className: "text-2xl font-semibold", children: "Goal Operations" }), _jsxs("p", { className: "mt-1 text-sm text-slate-500 dark:text-zinc-400", children: [statusPayload.registry, " \u00B7 ", statusPayload.runtime_root] })] }), _jsxs("div", { className: "flex items-center gap-2", children: [_jsx(Button, { size: "icon", variant: "secondary", onClick: () => setTheme(theme === "dark" ? "light" : "dark"), "aria-label": "Toggle theme", children: theme === "dark" ? _jsx(Sun, { className: "h-4 w-4" }) : _jsx(Moon, { className: "h-4 w-4" }) }), _jsxs(Button, { variant: "primary", onClick: () => window.location.reload(), children: [_jsx(RefreshCw, { className: "h-4 w-4" }), "Refresh"] })] })] }), _jsxs("div", { className: "space-y-5 p-4 sm:p-6", children: [_jsxs("section", { className: "grid gap-4 md:grid-cols-2 xl:grid-cols-4", children: [_jsx(MetricCard, { icon: statusPayload.ok ? CheckCircle2 : CircleAlert, label: "Status", value: statusPayload.ok ? "Healthy" : "Blocked", tone: statusPayload.ok ? "success" : "danger" }), _jsx(MetricCard, { icon: GitBranch, label: "Goals", value: String(statusPayload.goal_count), tone: "neutral" }), _jsx(MetricCard, { icon: Clock3, label: "Runs", value: String(statusPayload.run_count), tone: "info" }), _jsx(MetricCard, { icon: FileJson2, label: "Queue", value: String(queue.item_count), tone: "warning" })] }), _jsxs("section", { className: "grid gap-4 xl:grid-cols-[1.3fr_0.7fr]", children: [_jsxs(Card, { children: [_jsx(CardHeader, { children: _jsx("div", { children: _jsx(CardTitle, { children: "Attention Lanes" }) }) }), _jsx(CardContent, { children: _jsx("div", { className: "grid gap-3 lg:grid-cols-3", children: laneConfig.map((lane) => {
                                                                const Icon = lane.icon;
                                                                const items = queue.items.filter((item) => lane.waitingOn.includes(item.waiting_on));
                                                                return (_jsxs("div", { className: cn("min-h-52 rounded-lg border p-3", lane.accent), children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsxs("div", { className: "flex items-center gap-2 text-sm font-semibold", children: [_jsx(Icon, { className: "h-4 w-4" }), lane.label] }), _jsx(Badge, { children: items.length })] }), _jsx("div", { className: "mt-3 space-y-2", children: items.length === 0 ? (_jsx("p", { className: "text-sm opacity-70", children: "Clear" })) : (items.map((item) => (_jsxs("div", { className: "rounded-md border border-current/15 bg-white/65 p-3 text-sm dark:bg-zinc-950/55", children: [_jsxs("div", { className: "flex flex-wrap items-center gap-2", children: [_jsx("span", { className: "font-medium", children: item.goal_id }), _jsx(StatusBadge, { value: item.severity })] }), _jsx("p", { className: "mt-2 text-xs leading-5 opacity-80", children: item.recommended_action })] }, item.goal_id)))) })] }, lane.key));
                                                            }) }) })] }), _jsxs(Card, { children: [_jsx(CardHeader, { children: _jsx("div", { children: _jsx(CardTitle, { children: "Queue Mix" }) }) }), _jsx(CardContent, { children: _jsx("div", { className: "h-64", children: _jsx(ResponsiveContainer, { height: "100%", width: "100%", children: _jsxs(BarChart, { data: chartData, children: [_jsx(CartesianGrid, { strokeDasharray: "3 3", vertical: false }), _jsx(XAxis, { dataKey: "name", tickLine: false }), _jsx(Tooltip, { cursor: { fill: "rgba(148, 163, 184, 0.12)" } }), _jsx(Bar, { dataKey: "count", fill: "#0f766e", radius: [6, 6, 0, 0] })] }) }) }) })] })] }), _jsxs(Card, { children: [_jsxs(CardHeader, { className: "flex-wrap", children: [_jsx("div", { children: _jsx(CardTitle, { children: "Attention Queue" }) }), _jsxs("div", { className: "flex flex-wrap gap-2", children: [_jsxs(Select, { "aria-label": "Lane filter", value: search.lane, onChange: (event) => navigate({
                                                                    search: (current) => ({
                                                                        ...current,
                                                                        lane: event.target.value,
                                                                    }),
                                                                }), children: [_jsx("option", { value: "all", children: "All lanes" }), _jsx("option", { value: "user", children: "User / Controller" }), _jsx("option", { value: "codex", children: "Codex Ready" }), _jsx("option", { value: "watch", children: "Watching Evidence" })] }), _jsxs(Select, { "aria-label": "Severity filter", value: search.severity, onChange: (event) => navigate({
                                                                    search: (current) => ({
                                                                        ...current,
                                                                        severity: event.target.value,
                                                                    }),
                                                                }), children: [_jsx("option", { value: "all", children: "All severity" }), _jsx("option", { value: "high", children: "High" }), _jsx("option", { value: "action", children: "Action" }), _jsx("option", { value: "watch", children: "Watch" })] })] })] }), _jsx(CardContent, { children: _jsx(QueueTable, { items: filteredItems }) })] })] })] })] }) }) }));
}
function MetricCard({ icon: Icon, label, value, tone, }) {
    const toneClass = {
        neutral: "text-slate-700 dark:text-zinc-300",
        success: "text-emerald-700 dark:text-emerald-300",
        warning: "text-amber-700 dark:text-amber-300",
        info: "text-sky-700 dark:text-sky-300",
        danger: "text-rose-700 dark:text-rose-300",
    }[tone];
    return (_jsx(Card, { className: "min-h-32", children: _jsxs(CardHeader, { children: [_jsxs("div", { children: [_jsx(CardTitle, { children: label }), _jsx("div", { className: "mt-3 text-3xl font-semibold", children: value })] }), _jsx(Icon, { className: cn("h-5 w-5", toneClass) })] }) }));
}
