import type { JsonObject } from "../effect_program.ts";
import type {
  AuthorityStore,
  AuthorityStoreCommit,
  AuthorityStoreCommittedTransaction,
  AuthorityStoreCommitResult,
  AuthorityStoreIdentityResult,
  AuthorityStoreLoadResult,
  AuthorityStoreReadFailure,
  AuthorityStoreReceiptResult,
  AuthorityStoreScanResult,
} from "./authority_store.ts";
import {
  AuthorityStoreProtocolError,
  canonicalAuthorityObject,
  canonicalAuthorityObjectList,
  normalizeAuthorityStoreCommit,
  parseAuthorityCursor,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";

const POSTGRESQL_STORE_IDENTITY_PATTERN = /^postgresql:[0-9a-f]{32}$/;
const POSTGRESQL_PROVIDER_REVISION_PATTERN = /^postgresql:([0-9a-f]{32}):([1-9]\d*)$/;
const POSTGRESQL_SCHEMA_VERSION = "loopx_postgresql_authority_store_v0";

/**
 * Structural subset of a server-owned PostgreSQL driver connection.
 * A node-postgres PoolClient can be wrapped without making `pg` a LoopX-core
 * dependency. The authenticated service owns the pool; Agents never receive it.
 */
export interface PostgreSqlAuthorityConnection {
  query(text: string, values?: readonly unknown[]): Promise<{
    rows: readonly unknown[];
    rowCount: number | null;
  }>;
  release(error?: Error): void;
}

export interface PostgreSqlAuthorityDatabase {
  connect(): Promise<PostgreSqlAuthorityConnection>;
}

export interface PostgreSqlAuthorityStoreOptions {
  tenant_id: string;
  goal_id: string;
}

interface HeadRow extends JsonObject {
  provider_revision: string;
  cursor: string;
  head: JsonObject | null;
}

interface TransactionRow extends JsonObject {
  cursor: string;
  provider_revision: string;
  operation_id: string;
  projection: JsonObject;
  events: JsonObject[];
  receipts: JsonObject[];
}

export const POSTGRESQL_AUTHORITY_STORE_SCHEMA_SQL = `
CREATE SCHEMA IF NOT EXISTS loopx_control_plane;

CREATE TABLE IF NOT EXISTS loopx_control_plane.authority_store_metadata (
  singleton boolean PRIMARY KEY DEFAULT TRUE CHECK (singleton),
  schema_version text NOT NULL,
  store_identity text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT transaction_timestamp()
);

CREATE TABLE IF NOT EXISTS loopx_control_plane.authority_heads (
  tenant_id text NOT NULL,
  goal_id text NOT NULL,
  provider_revision bigint NOT NULL DEFAULT 0 CHECK (provider_revision >= 0),
  cursor bigint NOT NULL DEFAULT 0 CHECK (cursor >= 0),
  head jsonb,
  updated_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  PRIMARY KEY (tenant_id, goal_id),
  CHECK ((cursor = 0 AND provider_revision = 0 AND head IS NULL) OR
         (cursor > 0 AND provider_revision > 0 AND head IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS loopx_control_plane.authority_commits (
  tenant_id text NOT NULL,
  goal_id text NOT NULL,
  cursor bigint NOT NULL CHECK (cursor > 0),
  provider_revision bigint NOT NULL CHECK (provider_revision > 0),
  operation_id text NOT NULL,
  projection jsonb NOT NULL,
  committed_at timestamptz NOT NULL DEFAULT transaction_timestamp(),
  PRIMARY KEY (tenant_id, goal_id, cursor),
  UNIQUE (tenant_id, goal_id, operation_id),
  FOREIGN KEY (tenant_id, goal_id)
    REFERENCES loopx_control_plane.authority_heads (tenant_id, goal_id)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS loopx_control_plane.authority_events (
  tenant_id text NOT NULL,
  goal_id text NOT NULL,
  cursor bigint NOT NULL,
  event_index integer NOT NULL CHECK (event_index >= 0),
  event jsonb NOT NULL,
  PRIMARY KEY (tenant_id, goal_id, cursor, event_index),
  FOREIGN KEY (tenant_id, goal_id, cursor)
    REFERENCES loopx_control_plane.authority_commits (tenant_id, goal_id, cursor)
    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS loopx_control_plane.authority_receipts (
  tenant_id text NOT NULL,
  goal_id text NOT NULL,
  cursor bigint NOT NULL,
  receipt_index integer NOT NULL CHECK (receipt_index >= 0),
  receipt jsonb NOT NULL,
  PRIMARY KEY (tenant_id, goal_id, cursor, receipt_index),
  FOREIGN KEY (tenant_id, goal_id, cursor)
    REFERENCES loopx_control_plane.authority_commits (tenant_id, goal_id, cursor)
    ON DELETE CASCADE
);
`;

const SELECT_HEAD_SQL = `
SELECT provider_revision::text AS provider_revision,
       cursor::text AS cursor,
       head
FROM loopx_control_plane.authority_heads
WHERE tenant_id = $1 AND goal_id = $2
`;

const SELECT_TRANSACTION_COLUMNS_SQL = `
SELECT commit.cursor::text AS cursor,
       commit.provider_revision::text AS provider_revision,
       commit.operation_id,
       commit.projection,
       COALESCE((
         SELECT jsonb_agg(event.event ORDER BY event.event_index)
         FROM loopx_control_plane.authority_events AS event
         WHERE event.tenant_id = commit.tenant_id
           AND event.goal_id = commit.goal_id
           AND event.cursor = commit.cursor
       ), '[]'::jsonb) AS events,
       COALESCE((
         SELECT jsonb_agg(receipt.receipt ORDER BY receipt.receipt_index)
         FROM loopx_control_plane.authority_receipts AS receipt
         WHERE receipt.tenant_id = commit.tenant_id
           AND receipt.goal_id = commit.goal_id
           AND receipt.cursor = commit.cursor
       ), '[]'::jsonb) AS receipts
FROM loopx_control_plane.authority_commits AS commit
`;

function rows(result: { rows: readonly unknown[] }): readonly JsonObject[] {
  return result.rows.map((row) => canonicalAuthorityObject(row, "PostgreSQL row"));
}

function oneRow(
  result: { rows: readonly unknown[] },
  name: string,
): JsonObject | null {
  const values = rows(result);
  if (values.length > 1) {
    throw new AuthorityStoreProtocolError(`${name} returned more than one row`);
  }
  return values[0] ?? null;
}

function requiredRowString(row: JsonObject, field: string): string {
  return requireAuthorityStoreId(row[field], field);
}

function decodeHeadRow(value: JsonObject): HeadRow {
  const providerRevision = requiredRowString(value, "provider_revision");
  const cursor = requiredRowString(value, "cursor");
  if (!/^\d+$/.test(providerRevision) || !/^\d+$/.test(cursor)) {
    throw new AuthorityStoreProtocolError("PostgreSQL head revision or cursor is invalid");
  }
  const parsedCursor = BigInt(cursor);
  const parsedRevision = BigInt(providerRevision);
  if (parsedCursor === 0n && parsedRevision === 0n && value.head === null) {
    return { provider_revision: providerRevision, cursor, head: null };
  }
  if (parsedCursor < 1n || parsedRevision < 1n) {
    throw new AuthorityStoreProtocolError("PostgreSQL initialized head is invalid");
  }
  return {
    provider_revision: providerRevision,
    cursor,
    head: canonicalAuthorityObject(value.head, "PostgreSQL authority head"),
  };
}

function decodeTransactionRow(value: JsonObject): TransactionRow {
  const cursor = requiredRowString(value, "cursor");
  const providerRevision = requiredRowString(value, "provider_revision");
  parseAuthorityCursor(cursor);
  if (!/^[1-9]\d*$/.test(providerRevision)) {
    throw new AuthorityStoreProtocolError("PostgreSQL provider revision is invalid");
  }
  return {
    cursor,
    provider_revision: providerRevision,
    operation_id: requiredRowString(value, "operation_id"),
    projection: canonicalAuthorityObject(value.projection, "transaction projection"),
    events: canonicalAuthorityObjectList(value.events, "transaction events"),
    receipts: canonicalAuthorityObjectList(value.receipts, "transaction receipts"),
  };
}

function providerRevisionToken(storeIdentity: string, revision: string): string {
  if (!POSTGRESQL_STORE_IDENTITY_PATTERN.test(storeIdentity)) {
    throw new AuthorityStoreProtocolError("PostgreSQL store identity is invalid");
  }
  if (!/^[1-9]\d*$/.test(revision)) {
    throw new AuthorityStoreProtocolError("PostgreSQL provider revision is invalid");
  }
  return `${storeIdentity}:${revision}`;
}

function parseExpectedRevision(value: string | null): {
  store_identity: string;
  revision: string;
} | null {
  if (value === null) return null;
  const match = POSTGRESQL_PROVIDER_REVISION_PATTERN.exec(value);
  if (!match) {
    throw new AuthorityStoreProtocolError("expected PostgreSQL provider revision is invalid");
  }
  return { store_identity: `postgresql:${match[1]!}`, revision: match[2]! };
}

function readFailure(error: unknown): AuthorityStoreReadFailure {
  if (error instanceof AuthorityStoreProtocolError || error instanceof SyntaxError) {
    return {
      status: "failed",
      reason_code: "provider_protocol_violation",
      reason: error.message,
    };
  }
  return {
    status: "unavailable",
    reason_code: "provider_read_unavailable",
    reason: "PostgreSQL authority store is unavailable",
  };
}

async function rollback(connection: PostgreSqlAuthorityConnection): Promise<void> {
  try {
    await connection.query("ROLLBACK");
  } catch {
    // A failed connection also causes PostgreSQL to discard an uncommitted
    // transaction. No COMMIT was attempted at this point.
  }
}

async function requireStoreIdentity(
  connection: PostgreSqlAuthorityConnection,
): Promise<string> {
  const metadata = oneRow(await connection.query(
    `SELECT schema_version, store_identity
     FROM loopx_control_plane.authority_store_metadata
     WHERE singleton = TRUE`,
  ), "PostgreSQL store metadata");
  if (
    metadata === null || metadata.schema_version !== POSTGRESQL_SCHEMA_VERSION ||
    !POSTGRESQL_STORE_IDENTITY_PATTERN.test(String(metadata.store_identity))
  ) {
    throw new AuthorityStoreProtocolError("PostgreSQL store metadata is not initialized");
  }
  return String(metadata.store_identity);
}

/**
 * Administrative schema installation. Call this only from the authenticated
 * service deployment path with a newly minted database-incarnation identity.
 */
export async function installPostgreSqlAuthorityStoreSchema(
  database: PostgreSqlAuthorityDatabase,
  storeIdentity: string,
): Promise<void> {
  if (!POSTGRESQL_STORE_IDENTITY_PATTERN.test(storeIdentity)) {
    throw new AuthorityStoreProtocolError(
      "PostgreSQL store identity must match postgresql:<32 lowercase hex>",
    );
  }
  const connection = await database.connect();
  let commitStarted = false;
  try {
    await connection.query("BEGIN");
    await connection.query(POSTGRESQL_AUTHORITY_STORE_SCHEMA_SQL);
    await connection.query(
      `INSERT INTO loopx_control_plane.authority_store_metadata
         (singleton, schema_version, store_identity)
       VALUES (TRUE, $1, $2)
       ON CONFLICT (singleton) DO NOTHING`,
      [POSTGRESQL_SCHEMA_VERSION, storeIdentity],
    );
    const metadata = oneRow(await connection.query(
      `SELECT schema_version, store_identity
       FROM loopx_control_plane.authority_store_metadata
       WHERE singleton = TRUE
       FOR UPDATE`,
    ), "PostgreSQL store metadata");
    if (
      metadata === null || metadata.schema_version !== POSTGRESQL_SCHEMA_VERSION ||
      metadata.store_identity !== storeIdentity
    ) {
      throw new AuthorityStoreProtocolError(
        "PostgreSQL store identity does not match the installed database incarnation",
      );
    }
    commitStarted = true;
    await connection.query("COMMIT");
  } catch (error) {
    if (!commitStarted) await rollback(connection);
    throw error;
  } finally {
    connection.release();
  }
}

/** PostgreSQL Stage 2B store; domain decisions remain in LoopX authority. */
export class PostgreSqlAuthorityStore implements AuthorityStore {
  readonly database: PostgreSqlAuthorityDatabase;
  readonly tenantId: string;
  readonly goalId: string;

  constructor(
    database: PostgreSqlAuthorityDatabase,
    options: PostgreSqlAuthorityStoreOptions,
  ) {
    this.database = database;
    this.tenantId = requireAuthorityStoreId(options.tenant_id, "tenant id");
    this.goalId = requireAuthorityStoreId(options.goal_id, "goal id");
  }

  private async connect(): Promise<PostgreSqlAuthorityConnection> {
    return await this.database.connect();
  }

  async storeIdentity(): Promise<AuthorityStoreIdentityResult> {
    let connection: PostgreSqlAuthorityConnection | null = null;
    try {
      connection = await this.connect();
      return { status: "available", store_identity: await requireStoreIdentity(connection) };
    } catch (error) {
      const failure = readFailure(error);
      return failure.status === "failed"
        ? { ...failure, reason_code: "store_identity_invalid" }
        : { ...failure, reason_code: "store_identity_unavailable" };
    } finally {
      connection?.release();
    }
  }

  async loadAuthority(): Promise<AuthorityStoreLoadResult> {
    let connection: PostgreSqlAuthorityConnection | null = null;
    try {
      connection = await this.connect();
      const storeIdentity = await requireStoreIdentity(connection);
      const value = oneRow(
        await connection.query(SELECT_HEAD_SQL, [this.tenantId, this.goalId]),
        "PostgreSQL authority head",
      );
      if (value === null) return { status: "missing" };
      const head = decodeHeadRow(value);
      if (head.head === null) return { status: "missing" };
      return {
        status: "loaded",
        head: structuredClone(head.head),
        provider_revision: providerRevisionToken(storeIdentity, head.provider_revision),
        cursor: head.cursor,
      };
    } catch (error) {
      return readFailure(error);
    } finally {
      connection?.release();
    }
  }

  async commitAuthority(commit: AuthorityStoreCommit): Promise<AuthorityStoreCommitResult> {
    let normalized: AuthorityStoreCommit;
    let expectedRevision: ReturnType<typeof parseExpectedRevision>;
    try {
      normalized = normalizeAuthorityStoreCommit(commit);
      expectedRevision = parseExpectedRevision(normalized.expected_provider_revision);
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_commit_request",
        reason: error instanceof Error ? error.message : "invalid commit request",
      };
    }

    let connection: PostgreSqlAuthorityConnection;
    try {
      connection = await this.connect();
    } catch {
      return {
        status: "failed",
        reason_code: "provider_connection_unavailable",
        reason: "PostgreSQL connection was unavailable before the transaction",
      };
    }

    let commitStarted = false;
    try {
      await connection.query("BEGIN");
      const storeIdentity = await requireStoreIdentity(connection);
      await connection.query(
        `INSERT INTO loopx_control_plane.authority_heads
           (tenant_id, goal_id, provider_revision, cursor, head)
         VALUES ($1, $2, 0, 0, NULL)
         ON CONFLICT (tenant_id, goal_id) DO NOTHING`,
        [this.tenantId, this.goalId],
      );
      const rawHead = oneRow(await connection.query(
        `${SELECT_HEAD_SQL} FOR UPDATE`,
        [this.tenantId, this.goalId],
      ), "locked PostgreSQL authority head");
      if (rawHead === null) {
        throw new AuthorityStoreProtocolError("PostgreSQL authority head lock disappeared");
      }
      const current = decodeHeadRow(rawHead);
      const currentRevision = current.head === null ? null : current.provider_revision;
      if (
        currentRevision !== (expectedRevision?.revision ?? null) ||
        (expectedRevision !== null && expectedRevision.store_identity !== storeIdentity)
      ) {
        await rollback(connection);
        return {
          status: "conflict",
          conflict_kind: "provider_revision_mismatch",
          current_provider_revision: currentRevision === null
            ? null
            : providerRevisionToken(storeIdentity, currentRevision),
          current_cursor: current.head === null ? null : current.cursor,
        };
      }

      const existing = oneRow(await connection.query(
        `SELECT cursor::text AS cursor, provider_revision::text AS provider_revision
         FROM loopx_control_plane.authority_commits
         WHERE tenant_id = $1 AND goal_id = $2 AND operation_id = $3`,
        [this.tenantId, this.goalId, normalized.operation_id],
      ), "PostgreSQL operation identity");
      if (existing !== null) {
        await rollback(connection);
        return {
          status: "conflict",
          conflict_kind: "operation_id_exists",
          current_provider_revision: currentRevision === null
            ? null
            : providerRevisionToken(storeIdentity, currentRevision),
          current_cursor: current.head === null ? null : current.cursor,
        };
      }

      const nextRevision = (BigInt(current.provider_revision) + 1n).toString();
      const nextCursor = (BigInt(current.cursor) + 1n).toString();
      await connection.query(
        `INSERT INTO loopx_control_plane.authority_commits
           (tenant_id, goal_id, cursor, provider_revision, operation_id, projection)
         VALUES ($1, $2, $3::bigint, $4::bigint, $5, $6::jsonb)`,
        [
          this.tenantId,
          this.goalId,
          nextCursor,
          nextRevision,
          normalized.operation_id,
          JSON.stringify(normalized.next_projection),
        ],
      );
      for (const [index, event] of normalized.events.entries()) {
        await connection.query(
          `INSERT INTO loopx_control_plane.authority_events
             (tenant_id, goal_id, cursor, event_index, event)
           VALUES ($1, $2, $3::bigint, $4, $5::jsonb)`,
          [this.tenantId, this.goalId, nextCursor, index, JSON.stringify(event)],
        );
      }
      for (const [index, receipt] of normalized.receipts.entries()) {
        await connection.query(
          `INSERT INTO loopx_control_plane.authority_receipts
             (tenant_id, goal_id, cursor, receipt_index, receipt)
           VALUES ($1, $2, $3::bigint, $4, $5::jsonb)`,
          [this.tenantId, this.goalId, nextCursor, index, JSON.stringify(receipt)],
        );
      }
      const updated = await connection.query(
        `UPDATE loopx_control_plane.authority_heads
         SET provider_revision = $3::bigint,
             cursor = $4::bigint,
             head = $5::jsonb,
             updated_at = transaction_timestamp()
         WHERE tenant_id = $1 AND goal_id = $2 AND provider_revision = $6::bigint`,
        [
          this.tenantId,
          this.goalId,
          nextRevision,
          nextCursor,
          JSON.stringify(normalized.next_projection),
          current.provider_revision,
        ],
      );
      if (updated.rowCount !== 1) {
        throw new AuthorityStoreProtocolError("locked PostgreSQL head revision changed");
      }
      commitStarted = true;
      await connection.query("COMMIT");
      return {
        status: "applied",
        provider_revision: providerRevisionToken(storeIdentity, nextRevision),
        cursor: nextCursor,
      };
    } catch (error) {
      if (commitStarted) {
        return {
          status: "ambiguous",
          reason_code: "commit_outcome_unknown",
          reason: "PostgreSQL COMMIT outcome is unknown; reconcile by operation receipt",
        };
      }
      await rollback(connection);
      return {
        status: "failed",
        reason_code: error instanceof AuthorityStoreProtocolError
          ? "provider_protocol_violation"
          : "provider_transaction_failed",
        reason: error instanceof AuthorityStoreProtocolError
          ? error.message
          : "PostgreSQL transaction failed before COMMIT",
      };
    } finally {
      connection.release();
    }
  }

  async readReceipt(operationId: string): Promise<AuthorityStoreReceiptResult> {
    let normalized: string;
    try {
      normalized = requireAuthorityStoreId(operationId, "operation id");
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_operation_id",
        reason: error instanceof Error ? error.message : "invalid operation id",
      };
    }
    let connection: PostgreSqlAuthorityConnection | null = null;
    try {
      connection = await this.connect();
      const storeIdentity = await requireStoreIdentity(connection);
      const value = oneRow(await connection.query(
        `${SELECT_TRANSACTION_COLUMNS_SQL}
         WHERE commit.tenant_id = $1 AND commit.goal_id = $2 AND commit.operation_id = $3`,
        [this.tenantId, this.goalId, normalized],
      ), "PostgreSQL authority receipt");
      if (value === null) return { status: "missing" };
      const transaction = decodeTransactionRow(value);
      return {
        status: "found",
        cursor: transaction.cursor,
        provider_revision: providerRevisionToken(storeIdentity, transaction.provider_revision),
        receipts: structuredClone(transaction.receipts),
      };
    } catch (error) {
      return readFailure(error);
    } finally {
      connection?.release();
    }
  }

  async scanCommitted(
    afterCursor: string | null,
    limit: number,
  ): Promise<AuthorityStoreScanResult> {
    let offset: bigint;
    try {
      offset = parseAuthorityCursor(afterCursor);
      if (!Number.isSafeInteger(limit) || limit < 1) {
        throw new AuthorityStoreProtocolError("scan limit must be a positive safe integer");
      }
    } catch (error) {
      return {
        status: "failed",
        reason_code: "invalid_scan_request",
        reason: error instanceof Error ? error.message : "invalid scan request",
      };
    }
    let connection: PostgreSqlAuthorityConnection | null = null;
    try {
      connection = await this.connect();
      const storeIdentity = await requireStoreIdentity(connection);
      const current = oneRow(
        await connection.query(SELECT_HEAD_SQL, [this.tenantId, this.goalId]),
        "PostgreSQL authority head",
      );
      if (current === null) {
        return { status: "page", transactions: [], next_cursor: afterCursor, has_more: false };
      }
      const head = decodeHeadRow(current);
      if (offset > BigInt(head.cursor)) {
        return {
          status: "failed",
          reason_code: "scan_cursor_out_of_range",
          reason: "scan cursor is ahead of the provider head",
        };
      }
      const result = rows(await connection.query(
        `${SELECT_TRANSACTION_COLUMNS_SQL}
         WHERE commit.tenant_id = $1 AND commit.goal_id = $2 AND commit.cursor > $3::bigint
         ORDER BY commit.cursor
         LIMIT $4`,
        [this.tenantId, this.goalId, offset.toString(), (BigInt(limit) + 1n).toString()],
      )).map(decodeTransactionRow);
      const hasMore = result.length > limit;
      const page = result.slice(0, limit);
      const transactions: AuthorityStoreCommittedTransaction[] = page.map((value) => ({
        cursor: value.cursor,
        provider_revision: providerRevisionToken(storeIdentity, value.provider_revision),
        operation_id: value.operation_id,
        events: structuredClone(value.events),
        projection: structuredClone(value.projection),
        receipts: structuredClone(value.receipts),
      }));
      return {
        status: "page",
        transactions,
        next_cursor: transactions.at(-1)?.cursor ?? afterCursor,
        has_more: hasMore,
      };
    } catch (error) {
      return readFailure(error);
    } finally {
      connection?.release();
    }
  }
}
