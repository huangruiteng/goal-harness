export declare const rootRoute: import("@tanstack/react-router").RootRoute<import("@tanstack/react-router").Register, undefined, {}, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, unknown, unknown, unknown, unknown, undefined>;
export declare const dashboardRoute: import("@tanstack/react-router").Route<unknown, import("@tanstack/react-router").RootRoute<import("@tanstack/react-router").Register, undefined, {}, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, unknown, unknown, unknown, unknown, undefined>, "/", "/", string, "/", (search: Record<string, unknown>) => {
    lane: "user" | "codex" | "watch" | "all";
    severity: "watch" | "high" | "action" | "all";
}, import("@tanstack/router-core").ResolveParams<"/">, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, unknown, unknown, unknown, unknown, undefined>;
export declare const router: import("@tanstack/router-core").RouterCore<import("@tanstack/router-core").Route<import("@tanstack/react-router").Register, any, "/", "/", string, "__root__", undefined, {}, {}, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, readonly [import("@tanstack/react-router").Route<unknown, import("@tanstack/react-router").RootRoute<import("@tanstack/react-router").Register, undefined, {}, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, unknown, unknown, unknown, unknown, undefined>, "/", "/", string, "/", (search: Record<string, unknown>) => {
    lane: "user" | "codex" | "watch" | "all";
    severity: "watch" | "high" | "action" | "all";
}, import("@tanstack/router-core").ResolveParams<"/">, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, import("@tanstack/router-core").AnyContext, {}, undefined, unknown, unknown, unknown, unknown, undefined>], unknown, unknown, unknown, undefined>, "never", false, import("@tanstack/history").RouterHistory, Record<string, any>>;
declare module "@tanstack/react-router" {
    interface Register {
        router: typeof router;
    }
}
