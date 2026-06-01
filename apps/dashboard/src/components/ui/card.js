import { jsx as _jsx } from "react/jsx-runtime";
import { cn } from "../../lib/utils";
export function Card({ className, ...props }) {
    return (_jsx("section", { className: cn("rounded-lg border border-slate-200 bg-white text-slate-950 shadow-sm dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-50", className), ...props }));
}
export function CardHeader({ className, ...props }) {
    return _jsx("div", { className: cn("flex items-start justify-between gap-3 p-4", className), ...props });
}
export function CardTitle({ className, ...props }) {
    return _jsx("h2", { className: cn("text-sm font-semibold", className), ...props });
}
export function CardContent({ className, ...props }) {
    return _jsx("div", { className: cn("p-4 pt-0", className), ...props });
}
