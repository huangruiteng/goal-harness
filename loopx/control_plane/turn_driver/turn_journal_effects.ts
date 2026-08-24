import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { isAbsolute } from "node:path";

import type { JsonObject } from "../effect_program.ts";
import {
  EffectRuntimeConflictError,
  EffectRuntimeRequestError,
} from "../effect_runtime_errors.ts";
import {
  atomicWriteJson,
  withFileMutationLock,
} from "../effect_runtime_io.ts";
import { requireNonEmptyString as requiredString } from "../runtime_decode.ts";

function asObject(value: unknown): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function journalEffectId(journal: JsonObject): string | null {
  const plan = asObject(journal.plan);
  const transaction = asObject(plan.transaction);
  const settlement = asObject(transaction.settlement_plan);
  const identity = asObject(settlement.identity);
  const effectId = typeof identity.effect_id === "string"
    ? identity.effect_id.trim()
    : "";
  return effectId || null;
}

function sha256(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, stableValue(child)]),
  );
}

function operationId(journal: JsonObject): string {
  return `sha256:${sha256(JSON.stringify(stableValue(journal)))}`;
}

export async function commitTurnJournal(
  params: JsonObject,
): Promise<JsonObject> {
  const path = requiredString(params.path, "path");
  if (!isAbsolute(path)) {
    throw new EffectRuntimeRequestError("Turn journal path must be absolute");
  }
  const journal = asObject(params.journal);
  if (journal.schema_version !== "loopx_turn_journal_v0") {
    throw new EffectRuntimeRequestError(
      "Turn journal has an unsupported schema",
    );
  }
  const expectedEffectId = typeof params.expected_effect_id === "string"
    ? params.expected_effect_id.trim()
    : "";
  const incomingEffectId = journalEffectId(journal);
  if (expectedEffectId && incomingEffectId !== expectedEffectId) {
    throw new EffectRuntimeRequestError(
      "Turn journal does not carry the expected settlement effect",
    );
  }
  const expectedPreviousSha256 = params.expected_previous_sha256;
  if (expectedPreviousSha256 !== null && typeof expectedPreviousSha256 !== "string") {
    throw new EffectRuntimeRequestError(
      "expected_previous_sha256 must be a string or null",
    );
  }
  const incomingOperationId = operationId(journal);
  return await withFileMutationLock(path, async () => {
    let existing: JsonObject | null = null;
    let existingSha256: string | null = null;
    try {
      const encoded = await readFile(path, "utf8");
      existingSha256 = sha256(encoded);
      existing = asObject(JSON.parse(encoded));
      const existingEffectId = journalEffectId(existing);
      if (
        existingEffectId &&
        incomingEffectId &&
        existingEffectId !== incomingEffectId
      ) {
        throw new EffectRuntimeConflictError(
          "Turn journal belongs to another settlement effect",
          "journal_effect_conflict",
        );
      }
      if (operationId(existing) === incomingOperationId) {
        return {
          ok: true,
          appended: false,
          replayed: true,
          effect_id: incomingEffectId,
          operation_id: incomingOperationId,
        };
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    if (existingSha256 !== expectedPreviousSha256) {
      throw new EffectRuntimeConflictError(
        "Turn journal compare-and-swap precondition failed",
        "compare_and_swap_conflict",
      );
    }
    await atomicWriteJson(path, journal);
    return {
      ok: true,
      appended: true,
      replayed: false,
      effect_id: incomingEffectId,
      operation_id: incomingOperationId,
    };
  });
}
