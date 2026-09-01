import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { Pool, type PoolClient } from "pg";

import {
  installPostgreSqlAuthorityStoreSchema,
  PostgreSqlAuthorityStore,
  type PostgreSqlAuthorityConnection,
  type PostgreSqlAuthorityDatabase,
} from "../../loopx/control_plane/coordination/postgresql_authority_store.ts";
import {
  authorityStoreCommitFixture as commit,
  registerAuthorityStoreConformance,
} from "./authority_store_conformance.ts";

const connectionString = process.env.LOOPX_TEST_POSTGRES_URL;
const pool = connectionString ? new Pool({ connectionString, max: 12 }) : null;
const STORE_IDENTITY = `postgresql:${"b".repeat(32)}`;

function wrapClient(client: PoolClient): PostgreSqlAuthorityConnection {
  return {
    query: async (text, values) => await client.query(text, values ? [...values] : undefined),
    release: (error) => client.release(error),
  };
}

function databaseFromPool(value: Pool): PostgreSqlAuthorityDatabase {
  return { connect: async () => wrapClient(await value.connect()) };
}

const database = pool ? databaseFromPool(pool) : null;
const installed = database
  ? installPostgreSqlAuthorityStoreSchema(database, STORE_IDENTITY)
  : null;

async function cleanScope(tenantId: string, goalId: string): Promise<void> {
  if (!pool) return;
  await pool.query(
    `DELETE FROM loopx_control_plane.authority_heads
     WHERE tenant_id = $1 AND goal_id = $2`,
    [tenantId, goalId],
  );
}

if (database && installed) {
  registerAuthorityStoreConformance("PostgreSQL provider", async (t) => {
    await installed;
    const tenantId = `tenant-${randomUUID()}`;
    const goalId = `goal-${randomUUID()}`;
    t.after(() => cleanScope(tenantId, goalId));
    return {
      store: new PostgreSqlAuthorityStore(database, {
        tenant_id: tenantId,
        goal_id: goalId,
      }),
      contender: new PostgreSqlAuthorityStore(database, {
        tenant_id: tenantId,
        goal_id: goalId,
      }),
    };
  });

  test("PostgreSQL provider scopes identical goals and operations by tenant", async (t) => {
    await installed;
    const goalId = `goal-${randomUUID()}`;
    const firstTenant = `tenant-${randomUUID()}`;
    const secondTenant = `tenant-${randomUUID()}`;
    t.after(async () => {
      await cleanScope(firstTenant, goalId);
      await cleanScope(secondTenant, goalId);
    });
    const first = new PostgreSqlAuthorityStore(database, {
      tenant_id: firstTenant,
      goal_id: goalId,
    });
    const second = new PostgreSqlAuthorityStore(database, {
      tenant_id: secondTenant,
      goal_id: goalId,
    });

    const results = await Promise.all([
      first.commitAuthority(commit(null, "shared-operation", 1, 1)),
      second.commitAuthority(commit(null, "shared-operation", 1, 1)),
    ]);
    assert.deepEqual(results.map((result) => result.status), ["applied", "applied"]);
    assert.equal((await first.readReceipt("shared-operation")).status, "found");
    assert.equal((await second.readReceipt("shared-operation")).status, "found");
  });

  test("PostgreSQL provider rolls back head, events, and receipts together", async (t) => {
    await installed;
    const tenantId = `tenant-${randomUUID()}`;
    const goalId = `goal-${randomUUID()}`;
    t.after(async () => {
      await pool!.query(
        "DROP TRIGGER IF EXISTS authority_commit_test_failure ON loopx_control_plane.authority_commits",
      );
      await pool!.query(
        "DROP FUNCTION IF EXISTS loopx_control_plane.reject_test_authority_commit()",
      );
      await cleanScope(tenantId, goalId);
    });
    await pool!.query(`
      CREATE OR REPLACE FUNCTION loopx_control_plane.reject_test_authority_commit()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.operation_id = 'force-rollback' THEN
          RAISE EXCEPTION 'injected transaction failure';
        END IF;
        RETURN NEW;
      END;
      $$
    `);
    await pool!.query(`
      CREATE TRIGGER authority_commit_test_failure
      BEFORE INSERT ON loopx_control_plane.authority_commits
      FOR EACH ROW EXECUTE FUNCTION loopx_control_plane.reject_test_authority_commit()
    `);
    const store = new PostgreSqlAuthorityStore(database, {
      tenant_id: tenantId,
      goal_id: goalId,
    });
    const result = await store.commitAuthority(commit(null, "force-rollback", 1, 1));
    assert.equal(result.status, "failed");
    assert.deepEqual(await store.loadAuthority(), { status: "missing" });
    assert.deepEqual(await store.readReceipt("force-rollback"), { status: "missing" });
  });

  test("PostgreSQL COMMIT response loss is ambiguous and receipt-recoverable", async (t) => {
    await installed;
    const tenantId = `tenant-${randomUUID()}`;
    const goalId = `goal-${randomUUID()}`;
    t.after(() => cleanScope(tenantId, goalId));
    let loseCommitResponse = true;
    const lossyDatabase: PostgreSqlAuthorityDatabase = {
      connect: async () => {
        const client = await pool!.connect();
        return {
          query: async (text, values) => {
            const result = await client.query(text, values ? [...values] : undefined);
            if (text === "COMMIT" && loseCommitResponse) {
              loseCommitResponse = false;
              throw new Error("simulated response loss after PostgreSQL commit");
            }
            return result;
          },
          release: (error) => client.release(error),
        };
      },
    };
    const store = new PostgreSqlAuthorityStore(lossyDatabase, {
      tenant_id: tenantId,
      goal_id: goalId,
    });
    const result = await store.commitAuthority(commit(null, "operation-ambiguous", 1, 4));
    assert.equal(result.status, "ambiguous");
    const receipt = await store.readReceipt("operation-ambiguous");
    assert.equal(receipt.status, "found");
    if (receipt.status === "found") assert.equal(receipt.receipts[0]?.lease_epoch, 4);
    const loaded = await store.loadAuthority();
    assert.equal(loaded.status, "loaded");
  });

  test("PostgreSQL database incarnation binds revisions and cannot be rebound", async (t) => {
    await installed;
    const tenantId = `tenant-${randomUUID()}`;
    const goalId = `goal-${randomUUID()}`;
    t.after(() => cleanScope(tenantId, goalId));
    const store = new PostgreSqlAuthorityStore(database, {
      tenant_id: tenantId,
      goal_id: goalId,
    });
    const first = await store.commitAuthority(commit(null, "operation-a", 1, 1));
    assert.equal(first.status, "applied");
    if (first.status !== "applied") return;
    const foreignRevision = first.provider_revision.replace(
      STORE_IDENTITY,
      `postgresql:${"c".repeat(32)}`,
    );
    const crossLineage = await store.commitAuthority(
      commit(foreignRevision, "operation-b", 2, 2),
    );
    assert.equal(crossLineage.status, "conflict");
    assert.equal((await store.readReceipt("operation-b")).status, "missing");

    await assert.rejects(
      installPostgreSqlAuthorityStoreSchema(
        database,
        `postgresql:${"c".repeat(32)}`,
      ),
      /database incarnation/,
    );
  });
} else {
  test("PostgreSQL authority-store integration (set LOOPX_TEST_POSTGRES_URL)", { skip: true }, () => {});
}

test.after(async () => {
  await pool?.end();
});
