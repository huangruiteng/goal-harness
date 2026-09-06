import { z } from "zod";
import { parseStatusPayload, type StatusPayload } from "./status";

const directorySchema = z.object({
  ok: z.literal(true),
  schema_version: z.literal("loopx_workspace_directory_v1"),
  registry_revision: z.string(),
  goals: z.array(z.object({
    id: z.string(),
    display_name: z.string(),
    activation_state: z.enum(["active", "stopped"]),
    registry_member: z.literal(true),
  })),
});
export type WorkspaceDirectory = z.infer<typeof directorySchema>;
export type WorkspaceProgress = {
  directory: WorkspaceDirectory;
  snapshots: Record<string, StatusPayload>;
  errors: Record<string, string>;
};

function queryUrl(url: string, fields: Record<string, string>, base: string) {
  const parsed = new URL(url, base);
  parsed.searchParams.delete("goal_activation");
  parsed.searchParams.delete("goal_id");
  parsed.searchParams.delete("view");
  for (const [key, value] of Object.entries(fields)) parsed.searchParams.set(key, value);
  return parsed.toString();
}

export async function fetchWorkspaceDirectory(url: string, base: string): Promise<WorkspaceDirectory | null> {
  const response = await fetch(queryUrl(url, { view: "workspace-directory" }, base), {
    cache: "no-store", signal: AbortSignal.timeout(5_000),
  });
  // Older/read-only status servers retain their original full-payload path.
  if (!response.ok) return null;
  const result = directorySchema.safeParse(await response.json());
  return result.success ? result.data : null;
}

export function directoryStatusPayload(directory: WorkspaceDirectory): StatusPayload {
  return parseStatusPayload({
    ok: true, registry: "", runtime_root: "", goal_count: directory.goals.length,
    run_count: 0, local_dashboard_api: {},
    contract: { ok: true, summary: { errors: 0, warnings: 0, checks: 0 }, errors: [], warnings: [] },
    attention_queue: { available: false, item_count: 0, needs_user_or_controller: 0,
      needs_codex: 0, watching_external_evidence: 0, items: [] },
    run_history: { available: false, goal_count: directory.goals.length, run_count: 0,
      goals: directory.goals, recent_runs: [] },
  });
}

/** Bounded fan-out: a slow/failed Goal cannot block the directory or its peers. */
export async function loadWorkspaceGoalSnapshots(
  url: string,
  base: string,
  directory: WorkspaceDirectory,
  onGoal: (id: string, payload: StatusPayload | null, error: string | null) => void,
  isCurrent: () => boolean,
  preferredGoal: () => string,
  signal?: AbortSignal,
) {
  const pending = [...directory.goals].sort((a, b) =>
    Number(a.activation_state === "stopped") - Number(b.activation_state === "stopped"));
  async function worker() {
    while (pending.length && isCurrent()) {
      const preferred = pending.findIndex((goal) => goal.id === preferredGoal());
      const goal = pending.splice(preferred >= 0 ? preferred : 0, 1)[0];
      try {
        const response = await fetch(queryUrl(url, { goal_id: goal.id }, base), {
          cache: "no-store", signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(30_000)]) : AbortSignal.timeout(30_000),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const raw = await response.json();
        if (raw.workspace_registry_revision !== directory.registry_revision) {
          throw new Error("Goal directory changed; refresh to continue.");
        }
        const payload = parseStatusPayload(raw);
        if (!payload.run_history.goals.some((item) => item.id === goal.id)
          || payload.run_history.goals.some((item) => item.id !== goal.id)) {
          throw new Error("Goal response exceeded its requested scope.");
        }
        if (isCurrent()) onGoal(goal.id, payload, null);
      } catch {
        if (isCurrent()) onGoal(goal.id, null, "Goal status unavailable; refresh to retry.");
      }
    }
  }
  await Promise.all([worker(), worker()]);
}
