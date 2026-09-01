import {
  effectRuntimeErrorPayload,
  EffectRuntimeRequestError,
} from "../effect_runtime_errors.ts";
import {
  executeTaskLeaseAcquire,
  TASK_LEASE_SCHEMA_VERSION,
  type TaskLeaseAcquireEnvelope,
} from "./task_lease_acquire.ts";

async function readRequest(): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const input = Buffer.concat(chunks).toString("utf8");
  if (!input.trim()) {
    throw new EffectRuntimeRequestError(
      "task-lease acquire input must not be empty",
      "empty_request",
    );
  }
  try {
    return JSON.parse(input);
  } catch {
    throw new EffectRuntimeRequestError(
      "task-lease acquire input must be valid JSON",
      "invalid_json",
    );
  }
}

function errorEnvelope(error: unknown): TaskLeaseAcquireEnvelope {
  const failure = effectRuntimeErrorPayload(error);
  return {
    ok: false,
    schema_version: TASK_LEASE_SCHEMA_VERSION,
    action: "acquire",
    error: failure.message,
    error_code: failure.code,
    settlement: {
      effect_id: null,
      receipts: [],
      failure: {
        step: "validation",
        kind: failure.kind,
        code: failure.code,
      },
    },
  };
}

async function main(): Promise<number> {
  let result: TaskLeaseAcquireEnvelope;
  try {
    result = await executeTaskLeaseAcquire(await readRequest());
  } catch (error) {
    result = errorEnvelope(error);
  }
  process.stdout.write(`${JSON.stringify(result)}\n`);
  return result.ok === true ? 0 : 1;
}

process.exitCode = await main();
