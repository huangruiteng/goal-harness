import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DELIVERY_WORKSPACE_CAUSALITY_REQUEST_SCHEMA,
  evaluateDeliveryWorkspaceCausality,
} from "../../loopx/control_plane/quota/settlement_workspace_causality.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../fixtures/control_plane/delivery_workspace_causality_characterization_v0.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as {
  schema_version: string;
  source_baseline: string;
  cases: Array<{
    name: string;
    request: Record<string, unknown>;
    expected_result: Record<string, unknown>;
  }>;
};

test("pinned Python workspace-causality characterization remains exact", () => {
  assert.equal(
    fixture.schema_version,
    "loopx_delivery_workspace_causality_characterization_v0",
  );
  assert.equal(fixture.source_baseline, "0c59d47f6");
  assert.equal(fixture.cases.length, 10);
  for (const item of fixture.cases) {
    assert.deepEqual(
      evaluateDeliveryWorkspaceCausality(item.request),
      item.expected_result,
      item.name,
    );
  }
});

test("runtime boundary rejects malformed authority input", () => {
  assert.throws(
    () => evaluateDeliveryWorkspaceCausality({
      schema_version: "v1",
      operation: "classify",
    }),
    /schema mismatch/,
  );
  assert.throws(
    () => evaluateDeliveryWorkspaceCausality({
      schema_version: DELIVERY_WORKSPACE_CAUSALITY_REQUEST_SCHEMA,
      operation: "classify",
      normalized_todo_contract: {
        todo_id: "todo_write",
        task_repository: null,
        required_write_scopes: "loopx\/**",
        required_capabilities: [],
        continuation_policy: null,
        source: "selected_todo_contract",
      },
    }),
    /required_write_scopes must be an array of strings/,
  );
});

test("causality decisions do not mutate caller input", () => {
  const request = fixture.cases[0].request;
  const before = structuredClone(request);
  evaluateDeliveryWorkspaceCausality(request);
  assert.deepEqual(request, before);
});
