import assert from "node:assert/strict";
import test from "node:test";

import {
  EffectRuntimeConflictError,
  EffectRuntimeLockTimeoutError,
  EffectRuntimeRequestError,
  effectRuntimeErrorPayload,
} from "../../loopx/control_plane/effect_runtime_errors.ts";

test("runtime failures reduce to stable public-safe taxonomy", () => {
  assert.deepEqual(
    effectRuntimeErrorPayload(new EffectRuntimeRequestError("schema mismatch")),
    {
      kind: "request_rejected",
      code: "invalid_request",
      message: "schema mismatch",
    },
  );
  assert.deepEqual(
    effectRuntimeErrorPayload(
      new EffectRuntimeConflictError("compare-and-swap failed"),
    ),
    {
      kind: "conflict",
      code: "state_conflict",
      message: "compare-and-swap failed",
    },
  );
  assert.equal(
    effectRuntimeErrorPayload(new EffectRuntimeLockTimeoutError()).kind,
    "lock_timeout",
  );
});

test("filesystem and unexpected failures do not expose private diagnostics", () => {
  const permanent = new Error("ENOTDIR: private path");
  Object.assign(permanent, { code: "ENOTDIR" });
  assert.deepEqual(effectRuntimeErrorPayload(permanent), {
    kind: "io_permanent",
    code: "io_not_directory",
    message: "Effect runtime filesystem operation failed",
  });

  const transient = new Error("EAGAIN: private path");
  Object.assign(transient, { code: "EAGAIN" });
  assert.equal(effectRuntimeErrorPayload(transient).kind, "io_transient");

  const genericIo = new Error("EIO: private path");
  Object.assign(genericIo, { code: "EIO", syscall: "write" });
  assert.deepEqual(effectRuntimeErrorPayload(genericIo), {
    kind: "io_permanent",
    code: "io_failure",
    message: "Effect runtime filesystem operation failed",
  });

  assert.deepEqual(effectRuntimeErrorPayload(new TypeError("private stack")), {
    kind: "internal_failure",
    code: "unexpected_handler_error",
    message: "Effect runtime handler failed unexpectedly",
  });
});
