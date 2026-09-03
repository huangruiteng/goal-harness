import assert from "node:assert/strict";
import { mkdtemp, rm, stat, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test, { type TestContext } from "node:test";

import {
  acquireFileMutationLock,
  claimFileMutationLock,
  mutationLockOwner,
  releaseFileMutationLock,
} from "../../loopx/control_plane/effect_runtime_io.ts";

async function workspace(t: TestContext): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), "loopx-effect-runtime-io-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

test("token-safe release cannot remove a replacement lock", async (t) => {
  const root = await workspace(t);
  const target = join(root, "state");
  const first = await acquireFileMutationLock(target);
  assert.equal(await releaseFileMutationLock(target, first.token), true);

  const replacement = await acquireFileMutationLock(target);
  assert.equal(await releaseFileMutationLock(target, first.token), false);
  assert.deepEqual(await mutationLockOwner(target), {
    pid: process.pid,
    token: replacement.token,
  });
  assert.equal(await releaseFileMutationLock(target, replacement.token), true);
});

test("release cleans its claim when the lock owner is replaced", async (t) => {
  const root = await workspace(t);
  const target = join(root, "state");
  const lockPath = `${target}.ts-effect.lock`;
  const first = await acquireFileMutationLock(target);
  const claim = await claimFileMutationLock(target, first.token);
  assert.ok(claim);

  // Simulate a replacement after fence_close has claimed the old token.  The
  // replacement must remain, while the old caller's claim must be retired.
  await writeFile(
    lockPath,
    JSON.stringify({ pid: process.pid, token: "replacement-token" }),
    "utf8",
  );
  assert.equal(
    await releaseFileMutationLock(target, first.token, claim, true),
    false,
  );
  await assert.rejects(stat(claim!.claimPath), { code: "ENOENT" });
  assert.deepEqual(await mutationLockOwner(target), {
    pid: process.pid,
    token: "replacement-token",
  });

  await rm(lockPath, { force: true });
});

test("malformed stale lock owners are reclaimable without path traversal", async (t) => {
  const root = await workspace(t);
  const target = join(root, "state");
  const lockPath = `${target}.ts-effect.lock`;
  await writeFile(
    lockPath,
    JSON.stringify({ pid: process.pid, token: "   " }),
    "utf8",
  );
  const old = new Date(Date.now() - 60_000);
  await utimes(lockPath, old, old);

  const claim = await claimFileMutationLock(target, "../unsafe/token");
  assert.ok(claim);
  assert.match(claim!.claimPath, /\.claim\.[a-f0-9]{64}$/u);
  await rm(claim!.claimPath, { force: true });

  const acquired = await acquireFileMutationLock(target);
  assert.equal((await mutationLockOwner(target))?.token, acquired.token);
  assert.equal(await releaseFileMutationLock(target, acquired.token), true);
});

test("blank mutation lock tokens are not treated as valid owners", async (t) => {
  const root = await workspace(t);
  const target = join(root, "state");
  const lockPath = `${target}.ts-effect.lock`;
  await writeFile(
    lockPath,
    JSON.stringify({ pid: process.pid, token: "" }),
    "utf8",
  );
  assert.equal(await mutationLockOwner(target), null);
});
