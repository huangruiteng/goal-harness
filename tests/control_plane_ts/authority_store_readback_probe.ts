/**
 * Read-only probe over the file-backed AuthorityStore for the E2E stage ladder.
 *
 * The Python ladder writes through `python -m loopx.cli`; this probe proves the
 * resulting candidate bytes decode through the production TypeScript store
 * (`loadAuthority`, paged `scanCommitted`, `readReceipt`). It prints one JSON
 * line and never writes: `storeIdentity()` is deliberately not called because
 * it would mint an identity for a store that has none.
 *
 * Usage:
 *   node --experimental-strip-types tests/control_plane_ts/authority_store_readback_probe.ts \
 *     --directory <store-dir> --goal-id <goal> [--receipt <operation_id>] [--page-size <n>]
 */

import type { JsonObject } from "../../loopx/control_plane/effect_program.ts";
import type { AuthorityStore } from "../../loopx/control_plane/coordination/authority_store.ts";
import { FileAuthorityStore } from "../../loopx/control_plane/coordination/file_authority_store.ts";

interface ProbeArguments {
  directory: string;
  goalId: string;
  receipt: string | null;
  pageSize: number;
}

interface LoadSummary {
  status: string;
  reason_code: string | null;
  cursor: string | null;
  provider_revision: string | null;
  head_handoff_mode: string | null;
  head_todo_ids: string[];
  head_lease_count: number | null;
}

interface ScanSummary {
  status: string;
  reason_code: string | null;
  page_size: number;
  pages: number;
  operation_ids: string[];
  cursors: string[];
}

interface ReceiptSummary {
  status: string;
  reason_code: string | null;
  operation_id: string;
  cursor: string | null;
  provider_revision: string | null;
  receipt_count: number | null;
  observation_id: string | null;
}

class UsageError extends Error {}

function readOption(argv: readonly string[], name: string): string | null {
  const index = argv.indexOf(name);
  if (index === -1) return null;
  const value = argv[index + 1];
  if (value === undefined || value.startsWith("--")) {
    throw new UsageError(`${name} requires a value`);
  }
  return value;
}

function parseArguments(argv: readonly string[]): ProbeArguments {
  const directory = readOption(argv, "--directory");
  const goalId = readOption(argv, "--goal-id");
  if (directory === null || goalId === null) {
    throw new UsageError("--directory and --goal-id are required");
  }
  const rawPageSize = readOption(argv, "--page-size");
  const pageSize = rawPageSize === null ? 2 : Number.parseInt(rawPageSize, 10);
  if (!Number.isSafeInteger(pageSize) || pageSize < 1) {
    throw new UsageError("--page-size must be a positive integer");
  }
  return { directory, goalId, receipt: readOption(argv, "--receipt"), pageSize };
}

function stringList(value: unknown, key: string): string[] {
  if (!Array.isArray(value)) return [];
  const ids: string[] = [];
  for (const entry of value) {
    if (entry !== null && typeof entry === "object") {
      const field = (entry as Record<string, unknown>)[key];
      if (typeof field === "string") ids.push(field);
    }
  }
  return ids;
}

async function summarizeLoad(store: AuthorityStore): Promise<LoadSummary> {
  const loaded = await store.loadAuthority();
  const summary: LoadSummary = {
    status: loaded.status,
    reason_code: null,
    cursor: null,
    provider_revision: null,
    head_handoff_mode: null,
    head_todo_ids: [],
    head_lease_count: null,
  };
  if (loaded.status === "loaded") {
    const head: JsonObject = loaded.head;
    summary.cursor = loaded.cursor;
    summary.provider_revision = loaded.provider_revision;
    summary.head_handoff_mode = typeof head.handoff_mode === "string" ? head.handoff_mode : null;
    summary.head_todo_ids = stringList(head.todos, "todo_id");
    summary.head_lease_count = Array.isArray(head.leases) ? head.leases.length : null;
  } else if (loaded.status !== "missing") {
    summary.reason_code = loaded.reason_code;
  }
  return summary;
}

async function summarizeScan(store: AuthorityStore, pageSize: number): Promise<ScanSummary> {
  const summary: ScanSummary = {
    status: "page",
    reason_code: null,
    page_size: pageSize,
    pages: 0,
    operation_ids: [],
    cursors: [],
  };
  let after: string | null = null;
  for (;;) {
    const page = await store.scanCommitted(after, pageSize);
    if (page.status !== "page") {
      summary.status = page.status;
      summary.reason_code = page.reason_code;
      return summary;
    }
    summary.pages += 1;
    for (const transaction of page.transactions) {
      summary.operation_ids.push(transaction.operation_id);
      summary.cursors.push(transaction.cursor);
    }
    if (!page.has_more || page.next_cursor === after) return summary;
    after = page.next_cursor;
  }
}

async function summarizeReceipt(store: AuthorityStore, operationId: string): Promise<ReceiptSummary> {
  const receipt = await store.readReceipt(operationId);
  const summary: ReceiptSummary = {
    status: receipt.status,
    reason_code: null,
    operation_id: operationId,
    cursor: null,
    provider_revision: null,
    receipt_count: null,
    observation_id: null,
  };
  if (receipt.status === "found") {
    summary.cursor = receipt.cursor;
    summary.provider_revision = receipt.provider_revision;
    summary.receipt_count = receipt.receipts.length;
    const first = receipt.receipts[0] as Record<string, unknown> | undefined;
    summary.observation_id = typeof first?.observation_id === "string" ? first.observation_id : null;
  } else if (receipt.status !== "missing") {
    summary.reason_code = receipt.reason_code;
  }
  return summary;
}

async function main(argv: readonly string[]): Promise<number> {
  let parsed: ProbeArguments;
  try {
    parsed = parseArguments(argv);
  } catch (error) {
    if (error instanceof UsageError) {
      process.stderr.write(`${error.message}\n`);
      return 2;
    }
    throw error;
  }
  const store = new FileAuthorityStore(parsed.directory, parsed.goalId);
  const result = {
    schema_version: "loopx_authority_store_readback_probe_v0",
    goal_id: parsed.goalId,
    load: await summarizeLoad(store),
    scan: await summarizeScan(store, parsed.pageSize),
    receipt: parsed.receipt === null ? null : await summarizeReceipt(store, parsed.receipt),
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  return 0;
}

main(process.argv.slice(2)).then(
  (code) => {
    process.exitCode = code;
  },
  (error: unknown) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  },
);
