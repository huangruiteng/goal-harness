import { jsx as _jsx } from "react/jsx-runtime";
import { Outlet, createRootRoute, createRoute, createRouter, } from "@tanstack/react-router";
import { z } from "zod";
import { DashboardPage } from "./views/dashboard-page";
const searchSchema = z.object({
    lane: z.enum(["all", "user", "codex", "watch"]).optional().default("all"),
    severity: z.enum(["all", "high", "action", "watch"]).optional().default("all"),
});
export const rootRoute = createRootRoute({
    component: () => _jsx(Outlet, {}),
});
export const dashboardRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    validateSearch: (search) => searchSchema.parse(search),
    component: DashboardPage,
});
const routeTree = rootRoute.addChildren([dashboardRoute]);
export const router = createRouter({ routeTree });
