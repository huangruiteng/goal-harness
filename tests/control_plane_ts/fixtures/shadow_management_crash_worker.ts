/** Child process for real filesystem/crash recovery tests, never an active goal. */
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { bootstrapManagedShadow, rollbackManagedShadow, shadowManagementStatePath } from "../../../loopx/control_plane/coordination/shadow_management.ts";
import { withShadowSourceLocks, verifyShadowSourceSnapshot } from "../../../loopx/control_plane/coordination/runtime_shadow.ts";
const [kind, raw, stopAt] = process.argv.slice(2);
const request = JSON.parse(raw);
async function barrier(phase: string): Promise<void> {
  process.stdout.write(`ready:${phase}\n`);
  await new Promise<void>(() => { setInterval(() => {}, 1000); });
}
if (stopAt === "bootstrap_manifest_orphan" || stopAt === "rollback_manifest_orphan") {
  const actualOpen = fs.promises.open;
  const statePath = shadowManagementStatePath(request.runtime_root, request.goal_id);
  // writeImmutable(manifest) has completed its actual write, fsync, rename and
  // directory fsync before persistence opens the next state document. Pause
  // before that real open; no filesystem effect or result is substituted.
  fs.promises.open = async (path, flags, mode) => {
    if (String(path).startsWith(`${statePath}.`) && flags === "wx") await barrier(stopAt);
    return await actualOpen(path, flags, mode);
  };
  syncBuiltinESMExports();
}
const dependencies = {
  withPrimaryLocks: async <T>(operation: () => Promise<T>) => kind === "bootstrap-public"
    ? await withShadowSourceLocks(request, operation) : await operation(),
  verifySourceSnapshot: async () => { if (kind === "bootstrap-public") await verifyShadowSourceSnapshot(request); },
  afterEffect: async (phase: string) => {
    if (phase === stopAt) {
      await barrier(phase);
    }
  },
};
const result = kind.startsWith("bootstrap")
  ? await bootstrapManagedShadow(request, dependencies)
  : await rollbackManagedShadow(request, dependencies);
process.stdout.write(`${JSON.stringify(result)}\n`);
