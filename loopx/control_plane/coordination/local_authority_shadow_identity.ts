import { createHash } from "node:crypto";
import { canonicalAuthorityBytes } from "./authority_store_codec.ts";

export const OUTBOX_ENTRY_FILE_PATTERN = /^(\d{10})-(local-shadow-tx-[0-9a-f]{64})\.(prepared|committed)\.json$/u;

/** Shared entry identity; independent of capture and history readers. */
export function outboxEntryIdentity(
  goalId: string, partition: string, seq: number, sourceRef: string,
  captureLineageId: string, sourceRootDigest: string,
): string {
  const digest = createHash("sha256").update(canonicalAuthorityBytes({
    goal_id: goalId, partition, seq, source_ref: sourceRef,
    capture_lineage_id: captureLineageId, source_root_digest: sourceRootDigest,
  })).digest("hex");
  return `local-shadow-tx-${digest}`;
}
