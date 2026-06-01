import { jsx as _jsx } from "react/jsx-runtime";
import { cn } from "../../lib/utils";
export function Table({ className, ...props }) {
    return _jsx("table", { className: cn("w-full caption-bottom text-sm", className), ...props });
}
export function TableHeader({ className, ...props }) {
    return _jsx("thead", { className: cn("border-b border-slate-200 dark:border-zinc-800", className), ...props });
}
export function TableBody({ className, ...props }) {
    return _jsx("tbody", { className: cn("divide-y divide-slate-100 dark:divide-zinc-900", className), ...props });
}
export function TableRow({ className, ...props }) {
    return _jsx("tr", { className: cn("transition-colors hover:bg-slate-50 dark:hover:bg-zinc-900", className), ...props });
}
export function TableHead({ className, ...props }) {
    return (_jsx("th", { className: cn("h-10 px-3 text-left align-middle text-xs font-semibold text-slate-500 dark:text-zinc-400", className), ...props }));
}
export function TableCell({ className, ...props }) {
    return _jsx("td", { className: cn("px-3 py-3 align-middle", className), ...props });
}
