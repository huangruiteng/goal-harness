import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DELIVERY_WORKSPACE_CAUSALITY_REQUEST_SCHEMA,
  evaluateDeliveryWorkspaceCausality,
  resolveMissingDeliveryWorkspace,
  resolveSettlementWorkspaceRequirement,
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

test("missing workspace resolution preserves all three typed requirements", () => {
  const causality = (requirement: string) => ({
    schema_version: "delivery_workspace_causality_v0",
    todo_id: `todo_${requirement}`,
    requirement,
    source: "selected_todo_contract",
    reason: `fixture_${requirement}`,
  });

  assert.equal(
    resolveMissingDeliveryWorkspace(causality("required"))?.decision,
    "require_snapshot",
  );
  assert.equal(
    resolveMissingDeliveryWorkspace(causality("not_required"))?.decision,
    "omit_snapshot",
  );
  assert.deepEqual(resolveMissingDeliveryWorkspace(causality("unknown")), {
    schema_version: "delivery_workspace_resolution_v0",
    todo_id: "todo_unknown",
    decision: "repair_contract",
    requirement: "unknown",
    reason: "todo_delivery_contract_not_explicit",
    accepted_resolutions: [
      "declare_repository_or_write_contract",
      "declare_explicit_non_delivery_contract",
    ],
  });
});

test("typed settlement identity distinguishes replan from unknown Todo causality", () => {
  assert.deepEqual(
    resolveSettlementWorkspaceRequirement(null, "autonomous_replan"),
    {
      schema_version: "settlement_workspace_requirement_v0",
      settlement_binding_kind: "autonomous_replan",
      requirement: "not_required",
      source: "typed_settlement_identity",
      reason: "autonomous_replan_is_non_repository_control_plane_work",
    },
  );
  assert.deepEqual(resolveSettlementWorkspaceRequirement(null, "todo"), {
    schema_version: "settlement_workspace_requirement_v0",
    settlement_binding_kind: "todo",
    requirement: "unknown",
    source: "typed_settlement_identity",
    reason: "todo_delivery_contract_not_available",
  });
  assert.equal(
    resolveSettlementWorkspaceRequirement(
      {
        schema_version: "delivery_workspace_causality_v0",
        todo_id: "todo_write",
        requirement: "required",
        source: "selected_todo_contract",
        reason: "declared_repository_or_write_contract",
      },
      "autonomous_replan",
    ).requirement,
    "required",
  );
});

test("legacy Todo compatibility requires exact committed settlement receipts", () => {
  const effectId = "goal:agent:todo_legacy:turn-1";
  const completeEvidence = {
    schema_version: "legacy_settlement_receipt_evidence_v0",
    settlement_effect_id: effectId,
    delivery_workspace_present: false,
    receipts: [
      { step_kind: "validation", status: "committed", effect_id: effectId },
      { step_kind: "durable_writeback", status: "committed", effect_id: effectId },
    ],
  };
  assert.deepEqual(
    resolveSettlementWorkspaceRequirement(null, "todo", completeEvidence),
    {
      schema_version: "settlement_workspace_requirement_v0",
      settlement_binding_kind: "todo",
      requirement: "not_required",
      source: "legacy_settlement_receipts",
      reason: "pre_causality_settlement_already_committed",
    },
  );
  assert.equal(
    resolveSettlementWorkspaceRequirement(null, "todo", {
      ...completeEvidence,
      delivery_workspace_present: true,
    }).requirement,
    "unknown",
  );
  assert.equal(
    resolveSettlementWorkspaceRequirement(null, "todo", {
      ...completeEvidence,
      receipts: completeEvidence.receipts.slice(0, 1),
    }).requirement,
    "unknown",
  );
  assert.equal(
    resolveSettlementWorkspaceRequirement(null, "todo", {
      ...completeEvidence,
      receipts: completeEvidence.receipts.map((receipt, index) =>
        index === 1 ? { ...receipt, effect_id: "other-effect" } : receipt
      ),
    }).requirement,
    "unknown",
  );
});
