import { createHash } from "node:crypto";
import { join } from "node:path";

export const LEGACY_COORDINATION_TODO_LOCK_KEY = "legacy-todo-writer";
export const LEGACY_COORDINATION_LEASE_LOCK_KEY = "legacy-task-lease-writer";

export function legacyCoordinationTodoLockPath(root: string, goalId: string): string {
  const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
  return join(root, "authority-transition", "file-v0", `${LEGACY_COORDINATION_TODO_LOCK_KEY}-${digest}`);
}

export function legacyCoordinationLeaseLockPath(root: string, goalId: string): string {
  const digest = createHash("sha256").update(goalId, "utf8").digest("hex").slice(0, 16);
  return join(root, "authority-transition", "file-v0", `${LEGACY_COORDINATION_LEASE_LOCK_KEY}-${digest}`);
}

export function taskLeaseLockPath(request: { runtime_root: string; goal_id: string }): string {
  return join(request.runtime_root, "goals", request.goal_id, "task-leases", ".task-leases");
}
