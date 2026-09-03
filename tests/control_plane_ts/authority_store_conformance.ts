import assert from "node:assert/strict";
import test from "node:test";

import type {
  AuthorityStore,
  AuthorityStoreCommit,
} from "../../loopx/control_plane/coordination/authority_store.ts";

export interface AuthorityStoreConformanceFixture {
  store: AuthorityStore;
  contender: AuthorityStore;
}
export type AuthorityStoreConformanceFactory = (
  context: test.TestContext,
) => Promise<AuthorityStoreConformanceFixture>;

export function authorityStoreCommitFixture(
  expectedProviderRevision: string | null,
  operationId: string,
  authorityRevision: number,
  leaseEpoch: number,
): AuthorityStoreCommit {
  return {
    expected_provider_revision: expectedProviderRevision,
    operation_id: operationId,
    events: [{
      schema_version: "loopx_authority_event_v0",
      type: "todo_claimed",
      authority_revision: authorityRevision,
      lease_epoch: leaseEpoch,
    }],
    next_projection: {
      schema_version: "loopx_coordination_head_v1",
      authority_revision: authorityRevision,
      coordination: {
        leases: { "todo-a": { lease_epoch: leaseEpoch } },
      },
    },
    receipts: [{
      schema_version: "loopx_authority_receipt_v0",
      operation_id: operationId,
      accepted_authority_revision: authorityRevision,
      lease_epoch: leaseEpoch,
    }],
  };
}

export function registerAuthorityStoreConformance(
  providerName: string,
  factory: AuthorityStoreConformanceFactory,
): void {
  test(`${providerName} conformance: atomic transition, projection, and receipt`, async (t) => {
    const { store } = await factory(t);
    assert.deepEqual(await store.loadAuthority(), { status: "missing" });

    const applied = await store.commitAuthority(
      authorityStoreCommitFixture(null, "operation-a", 41, 7),
    );
    assert.equal(applied.status, "applied");
    if (applied.status !== "applied") return;
    assert.notEqual(applied.provider_revision, "41");
    assert.notEqual(applied.provider_revision, "7");
    assert.equal(applied.cursor, "1");

    const loaded = await store.loadAuthority();
    assert.equal(loaded.status, "loaded");
    if (loaded.status !== "loaded") return;
    assert.equal(loaded.head.authority_revision, 41);
    assert.deepEqual(loaded.head.coordination, {
      leases: { "todo-a": { lease_epoch: 7 } },
    });
    assert.equal(loaded.provider_revision, applied.provider_revision);
    assert.equal(loaded.cursor, "1");

    const receipt = await store.readReceipt("operation-a");
    assert.equal(receipt.status, "found");
    if (receipt.status === "found") {
      assert.equal(receipt.provider_revision, applied.provider_revision);
      assert.equal(receipt.receipts[0]?.accepted_authority_revision, 41);
      assert.equal(receipt.receipts[0]?.lease_epoch, 7);
    }
  });

  test(`${providerName} conformance: CAS admits one writer`, async (t) => {
    const { store, contender } = await factory(t);
    const results = await Promise.all([
      store.commitAuthority(authorityStoreCommitFixture(null, "operation-a", 1, 1)),
      contender.commitAuthority(authorityStoreCommitFixture(null, "operation-b", 1, 1)),
    ]);
    assert.deepEqual(results.map((result) => result.status).sort(), ["applied", "conflict"]);
    const applied = results.find((result) => result.status === "applied");
    const conflict = results.find((result) => result.status === "conflict");
    assert.ok(applied && applied.status === "applied");
    assert.ok(conflict && conflict.status === "conflict");
    assert.equal(conflict.conflict_kind, "provider_revision_mismatch");
    assert.equal(conflict.current_provider_revision, applied.provider_revision);
    assert.equal(conflict.current_cursor, "1");
  });

  test(`${providerName} conformance: historical replay and operation fencing`, async (t) => {
    const { store } = await factory(t);
    const first = await store.commitAuthority(
      authorityStoreCommitFixture(null, "operation-a", 1, 3),
    );
    assert.equal(first.status, "applied");
    if (first.status !== "applied") return;
    const second = await store.commitAuthority(
      authorityStoreCommitFixture(first.provider_revision, "operation-b", 2, 9),
    );
    assert.equal(second.status, "applied");
    if (second.status !== "applied") return;

    const historical = await store.readReceipt("operation-a");
    assert.equal(historical.status, "found");
    if (historical.status === "found") {
      assert.equal(historical.cursor, "1");
      assert.equal(historical.receipts[0]?.lease_epoch, 3);
    }
    const duplicate = await store.commitAuthority(
      authorityStoreCommitFixture(second.provider_revision, "operation-a", 3, 10),
    );
    assert.deepEqual(duplicate, {
      status: "conflict",
      conflict_kind: "operation_id_exists",
      current_provider_revision: second.provider_revision,
      current_cursor: "2",
    });
    const loaded = await store.loadAuthority();
    assert.equal(loaded.status, "loaded");
    if (loaded.status === "loaded") assert.equal(loaded.head.authority_revision, 2);
  });

  test(`${providerName} conformance: committed scan is ordered and isolated`, async (t) => {
    const { store } = await factory(t);
    const first = await store.commitAuthority(
      authorityStoreCommitFixture(null, "operation-a", 1, 1),
    );
    assert.equal(first.status, "applied");
    if (first.status !== "applied") return;
    await store.commitAuthority(
      authorityStoreCommitFixture(first.provider_revision, "operation-b", 2, 2),
    );

    const firstPage = await store.scanCommitted(null, 1);
    assert.equal(firstPage.status, "page");
    if (firstPage.status !== "page") return;
    assert.equal(firstPage.transactions[0]?.operation_id, "operation-a");
    assert.equal(firstPage.next_cursor, "1");
    assert.equal(firstPage.has_more, true);
    (firstPage.transactions[0]!.projection as { authority_revision: number })
      .authority_revision = 99;

    const secondPage = await store.scanCommitted("1", 1);
    assert.equal(secondPage.status, "page");
    if (secondPage.status === "page") {
      assert.equal(secondPage.transactions[0]?.operation_id, "operation-b");
      assert.equal(secondPage.next_cursor, "2");
      assert.equal(secondPage.has_more, false);
    }
    const loaded = await store.loadAuthority();
    assert.equal(loaded.status, "loaded");
    if (loaded.status === "loaded") assert.equal(loaded.head.authority_revision, 2);
    assert.equal((await store.scanCommitted("3", 1)).status, "failed");
    assert.equal((await store.scanCommitted(null, 0)).status, "failed");
  });

  test(`${providerName} conformance: malformed JSON fails before a write`, async (t) => {
    const { store } = await factory(t);
    const invalidNumber = authorityStoreCommitFixture(null, "operation-nan", 1, 1);
    invalidNumber.next_projection.authority_revision = Number.NaN;
    assert.equal((await store.commitAuthority(invalidNumber)).status, "failed");

    const invalidObject = authorityStoreCommitFixture(null, "operation-date", 1, 1);
    (invalidObject.next_projection as Record<string, unknown>).coordination = new Date();
    assert.equal((await store.commitAuthority(invalidObject)).status, "failed");
    assert.deepEqual(await store.loadAuthority(), { status: "missing" });
  });
}
