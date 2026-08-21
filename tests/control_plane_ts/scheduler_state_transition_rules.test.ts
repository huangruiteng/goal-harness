import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  evaluateSchedulerStateTransition,
  SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
  SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
} from "../../loopx/control_plane/scheduler/state_transition_rules.ts";

const fixture = JSON.parse(
  readFileSync(
    new URL(
      "../fixtures/control_plane/scheduler_state_transition_characterization_v0.json",
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

test("pinned Python scheduler transition characterization remains exact", () => {
  assert.equal(
    fixture.schema_version,
    "loopx_scheduler_state_transition_characterization_v0",
  );
  assert.equal(fixture.source_baseline, "3f923c4fe");
  assert.equal(fixture.cases.length, 19);
  for (const item of fixture.cases) {
    const result = evaluateSchedulerStateTransition({
      schema_version: SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
      ...item.request,
    });
    assert.deepEqual(
      result,
      {
        schema_version: SCHEDULER_STATE_TRANSITION_RESULT_SCHEMA,
        ...item.expected_result,
      },
      item.name,
    );
  }
});

test("runtime boundary rejects malformed transition facts", () => {
  assert.throws(
    () => evaluateSchedulerStateTransition({
      schema_version: "unsupported",
      operation: "cadence",
    }),
    /request schema mismatch/,
  );
  assert.throws(
    () => evaluateSchedulerStateTransition({
      schema_version: SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
      operation: "cadence",
      progression_size: 0,
      state_present: false,
    }),
    /must not be empty/,
  );
  assert.throws(
    () => evaluateSchedulerStateTransition({
      schema_version: SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
      operation: "host",
      state_status: "same_identity",
      observed_host_rrule_present: "yes",
    }),
    /must be a boolean/,
  );
});

test("transition decisions do not mutate caller input", () => {
  const request = {
    schema_version: SCHEDULER_STATE_TRANSITION_REQUEST_SCHEMA,
    ...fixture.cases[2].request,
  };
  const before = structuredClone(request);
  evaluateSchedulerStateTransition(request);
  assert.deepEqual(request, before);
});
