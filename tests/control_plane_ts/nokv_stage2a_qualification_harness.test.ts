import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  exerciseQualificationSequence,
  parseQualificationArguments,
  qualificationHelperArgv,
  QUALIFICATION_SCOPE,
  QUALIFIED_NOKV_API_VERSION,
  QUALIFIED_NOKV_SDK_VERSION,
  QualificationFailure,
  type QualificationTransport,
} from "../../examples/nokv-authority-store/live-qualification.ts";
import type {
  NoKVBlobCasRequest,
  NoKVBlobCasResult,
  NoKVBlobReadResult,
  NoKVStoreIdentityResult,
} from "../../loopx/control_plane/coordination/nokv_authority_store.ts";

interface Backend {
  blob: { bytes: Uint8Array; generation: number } | null;
  ignoreCas: boolean;
  publishCalls: number;
  pretendAppliedWithoutWriteOnCall: number | null;
}

class FakeQualificationTransport implements QualificationTransport {
  readonly backend: Backend;
  closed = false;

  constructor(backend: Backend) {
    this.backend = backend;
  }

  async storeIdentity(workbench: string): Promise<NoKVStoreIdentityResult> {
    return {
      status: "available",
      store_identity: `nokv:${workbench}:${"a".repeat(32)}`,
    };
  }

  async readBlob(_workbench: string, _path: string): Promise<NoKVBlobReadResult> {
    return this.backend.blob
      ? {
        status: "loaded",
        bytes: this.backend.blob.bytes.slice(),
        generation: this.backend.blob.generation,
      }
      : { status: "missing" };
  }

  async casPublishBlob(request: NoKVBlobCasRequest): Promise<NoKVBlobCasResult> {
    this.backend.publishCalls += 1;
    const current = this.backend.blob?.generation ?? null;
    if (!this.backend.ignoreCas && current !== request.expected_generation) {
      return { status: "conflict", current_generation: current };
    }
    const generation = (current ?? 0) + 1;
    if (this.backend.pretendAppliedWithoutWriteOnCall === this.backend.publishCalls) {
      return { status: "applied", generation };
    }
    this.backend.blob = { bytes: request.bytes.slice(), generation };
    return { status: "applied", generation };
  }

  async close(): Promise<void> {
    this.closed = true;
  }
}

const BASE_OPTIONS = {
  python_executable: "/usr/bin/python3",
  client_config: {
    root_id: "0".repeat(32),
    routing: { kind: "etcd" },
    object_store: { kind: "memory" },
  },
  tenant_id: "qualification-tenant",
  goal_id: "qualification-goal",
  workbench: "authority-workbench",
} as const;

test("Stage 2A qualification harness requires explicit write opt-in", () => {
  assert.throws(
    () => parseQualificationArguments([
      "--config-json", "/tmp/client.json",
      "--python-executable", "/usr/bin/python3",
      "--tenant-id", "qualification-tenant",
      "--goal-id", "qualification-goal",
      "--workbench", "authority-workbench",
    ]),
    (error: unknown) => {
      assert.ok(error instanceof QualificationFailure);
      assert.equal(error.reasonCode, "live_opt_in_required");
      return true;
    },
  );
});

test("Stage 2A qualification harness fixes the executable and repository helper", () => {
  const executable = "/opt/loopx-qualification/bin/python";
  const expectedHelper = fileURLToPath(
    new URL("../../loopx/control_plane/coordination/nokv_jsonl_helper.py", import.meta.url),
  );

  assert.deepEqual(qualificationHelperArgv(executable), [executable, expectedHelper]);
  const parsed = parseQualificationArguments([
    "--execute-live",
    "--config-json", "/tmp/client.json",
    "--python-executable", executable,
    "--tenant-id", "qualification-tenant",
    "--goal-id", "qualification-goal",
    "--workbench", "authority-workbench",
  ]);
  assert.equal(parsed.pythonExecutable, executable);
});

test("Stage 2A qualification harness rejects a relative Python executable", () => {
  assert.throws(
    () => qualificationHelperArgv("python3"),
    (error: unknown) => {
      assert.ok(error instanceof QualificationFailure);
      assert.equal(error.reasonCode, "invalid_arguments");
      return true;
    },
  );
});

test("Stage 2A qualification harness names the exact NoKV SDK contract", () => {
  assert.equal(QUALIFICATION_SCOPE, "stage_2a_single_node_store_conformance");
  assert.equal(QUALIFIED_NOKV_SDK_VERSION, "0.11.0");
  assert.equal(QUALIFIED_NOKV_API_VERSION, 1);
});

test("qualification proves create, ambiguous reconciliation, contention, and fresh readback", async () => {
  const backend: Backend = {
    blob: null,
    ignoreCas: false,
    publishCalls: 0,
    pretendAppliedWithoutWriteOnCall: null,
  };
  const opened: FakeQualificationTransport[] = [];
  const report = await exerciseQualificationSequence(BASE_OPTIONS, async () => {
    const transport = new FakeQualificationTransport(backend);
    opened.push(transport);
    return transport;
  });

  assert.equal(report.final_generation, 3);
  assert.equal(report.final_cursor, "3");
  assert.deepEqual(report.checks.map((check) => check.id), [
    "existing_workbench_identity",
    "fresh_authority_target",
    "create_applied",
    "create_generation_one",
    "response_lost_success_reconciled",
    "generation_cas_applied",
    "generation_two_readback",
    "competing_generation_cas_one_winner",
    "competition_did_not_double_advance",
    "independent_transport_readback",
    "ambiguous_commit_receipt_retained",
    "winner_receipt_retained",
    "loser_receipt_absent",
  ]);
  assert.deepEqual(report.checks.map((check) => check.status),
    Array(report.checks.length).fill("passed"));
  assert.equal(opened.length, 3);
  assert.ok(opened.every((transport) => transport.closed));
});

test("qualification rejects a backend that does not enforce generation CAS", async () => {
  const backend: Backend = {
    blob: null,
    ignoreCas: true,
    publishCalls: 0,
    pretendAppliedWithoutWriteOnCall: null,
  };
  await assert.rejects(
    exerciseQualificationSequence(BASE_OPTIONS, async () =>
      new FakeQualificationTransport(backend)),
    (error: unknown) => {
      assert.ok(error instanceof QualificationFailure);
      assert.equal(error.reasonCode, "competition_not_fenced");
      return true;
    },
  );
});

test("qualification rejects an independent transport that cannot read the envelope", async () => {
  const shared: Backend = {
    blob: null,
    ignoreCas: false,
    publishCalls: 0,
    pretendAppliedWithoutWriteOnCall: null,
  };
  let opened = 0;
  await assert.rejects(
    exerciseQualificationSequence(BASE_OPTIONS, async () => {
      opened += 1;
      return new FakeQualificationTransport(
        opened === 3
          ? {
            blob: null,
            ignoreCas: false,
            publishCalls: 0,
            pretendAppliedWithoutWriteOnCall: null,
          }
          : shared,
      );
    }),
    (error: unknown) => {
      assert.ok(error instanceof QualificationFailure);
      assert.equal(error.reasonCode, "independent_readback_failed");
      return true;
    },
  );
});

test("qualification requires durable readback after the injected response loss", async () => {
  const backend: Backend = {
    blob: null,
    ignoreCas: false,
    publishCalls: 0,
    pretendAppliedWithoutWriteOnCall: 2,
  };
  await assert.rejects(
    exerciseQualificationSequence(BASE_OPTIONS, async () =>
      new FakeQualificationTransport(backend)),
    (error: unknown) => {
      assert.ok(error instanceof QualificationFailure);
      assert.equal(error.reasonCode, "generation_cas_failed");
      return true;
    },
  );
});
