import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm, stat } from "node:fs/promises";
import { dirname } from "node:path";

import type { JsonObject } from "./effect_program.ts";
import { EffectRuntimeLockTimeoutError } from "./effect_runtime_errors.ts";

const MUTATION_LOCK_TIMEOUT_MS = 5_000;
const MUTATION_LOCK_POLL_MS = 25;
const INVALID_LOCK_STALE_MS = 10_000;

interface MutationLockOwner {
  pid: number;
  token: string;
}

function processIsAlive(pid: number): boolean {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

async function readMutationLockOwner(path: string): Promise<MutationLockOwner | null> {
  try {
    const payload: unknown = JSON.parse(await readFile(path, "utf8"));
    if (
      typeof payload === "object" &&
      payload !== null &&
      !Array.isArray(payload) &&
      typeof (payload as Record<string, unknown>).pid === "number" &&
      typeof (payload as Record<string, unknown>).token === "string"
    ) {
      return payload as MutationLockOwner;
    }
  } catch {
    // A partially written or concurrently released lock is retried below.
  }
  return null;
}

async function reclaimStaleMutationLock(path: string): Promise<void> {
  const owner = await readMutationLockOwner(path);
  if (owner && processIsAlive(owner.pid)) return;
  if (!owner) {
    try {
      if (Date.now() - (await stat(path)).mtimeMs < INVALID_LOCK_STALE_MS) return;
    } catch {
      return;
    }
  }
  const stalePath = `${path}.stale.${randomUUID()}`;
  try {
    await rename(path, stalePath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    return;
  }
  await rm(stalePath, { force: true });
}

async function releaseMutationLock(path: string, token: string): Promise<void> {
  const owner = await readMutationLockOwner(path);
  if (owner?.token === token) await rm(path, { force: true });
}

export async function withFileMutationLock<T>(
  targetPath: string,
  operation: () => Promise<T>,
): Promise<T> {
  await mkdir(dirname(targetPath), { recursive: true, mode: 0o700 });
  const lockPath = `${targetPath}.ts-effect.lock`;
  const token = randomUUID();
  const deadline = Date.now() + MUTATION_LOCK_TIMEOUT_MS;
  while (true) {
    try {
      const handle = await open(lockPath, "wx", 0o600);
      try {
        try {
          await handle.writeFile(
            JSON.stringify({ pid: process.pid, token }),
            "utf8",
          );
          await handle.sync();
        } finally {
          await handle.close();
        }
      } catch (error) {
        await rm(lockPath, { force: true });
        throw error;
      }
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      await reclaimStaleMutationLock(lockPath);
      if (Date.now() >= deadline) {
        throw new EffectRuntimeLockTimeoutError();
      }
      await new Promise((resolve) => setTimeout(resolve, MUTATION_LOCK_POLL_MS));
    }
  }
  try {
    return await operation();
  } finally {
    await releaseMutationLock(lockPath, token);
  }
}

async function atomicWriteTextFile(
  path: string,
  content: string,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    try {
      await handle.writeFile(content, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporary, path);
  } finally {
    await rm(temporary, { force: true });
  }
}

export async function atomicWriteText(
  path: string,
  content: string,
): Promise<void> {
  await atomicWriteTextFile(path, content);
}

export async function atomicWriteJson(
  path: string,
  payload: JsonObject,
): Promise<void> {
  await atomicWriteTextFile(path, `${JSON.stringify(payload, null, 2)}\n`);
}

export async function appendJsonLine(
  path: string,
  payload: JsonObject,
): Promise<void> {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const handle = await open(path, "a", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(payload)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
}
