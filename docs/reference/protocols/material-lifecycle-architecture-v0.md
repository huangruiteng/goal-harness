# Material Lifecycle Architecture v0

## Position

Material Lifecycle is a built-in, default-off, goal-scoped LoopX capability.
It owns the auditable lifecycle of material references: inventory, backup-safe
migration, candidate/archive transitions, and bounded rerank proposals. It does
not own raw documents, private source locations, provider credentials, or Core
goal authority.

```mermaid
flowchart LR
    RAW["Private raw material store<br/>files, messages, web captures"]
    BACKUP["Immutable snapshot + backup"]
    ML["Material Lifecycle<br/>inventory, lifecycle, bounded rerank"]
    DC["Decision Context<br/>revisioned evidence"]
    RM["Reward Memory<br/>reviewed reusable lessons"]
    CO["Content Ops / other consumers"]
    CORE["LoopX Core<br/>goal, todo, gate, event, vision"]

    RAW --> BACKUP
    BACKUP --> ML
    DC -->|"decision_evidence_ref"| ML
    RM -. "optional ranking lesson" .-> ML
    ML -->|"material refs + receipts"| CO
    ML -->|"audited refs only"| CORE
```

The capability is a sibling of Decision Context and Reward Memory:

- Decision Context answers which current facts should influence a decision.
- Material Lifecycle answers which material references are candidates, active,
  archived, carried over, or eligible for a bounded rerank.
- Reward Memory stores reviewed reusable policies or lessons.
- Content Ops and other domain capabilities consume selected material; they do
  not own the candidate/archive source of truth.

## Stage-0 Contracts

`material_store_inventory_v0` is a read-only, public-safe inventory. It records
opaque snapshot, backup, digest, revision, count, parse-error, and verification
references. Raw material and private locations are excluded.

`material_migration_plan_v0` fixes the migration order:

1. snapshot;
2. inventory;
3. dual read;
4. reconcile;
5. owner gate;
6. apply;
7. keep rollback ready.

The plan never authorizes source mutation by itself.

`material_lifecycle_receipt_v0` records authority-referenced transitions among
`unread`, `candidate`, `active`, `carryover`, and `archived`. The authority may
be a reviewed goal policy, Decision Context outcome, or human gate. Archive and
reactivation preserve the stable material and archive references instead of
copying raw content into another queue.

`material_rerank_proposal_v0` carries only a bounded delta:

- one target window;
- maximum moved items;
- maximum rank displacement;
- protected material references;
- revisioned Decision Context evidence;
- an explicit no-change result.

`material_rerank_apply_receipt_v0` remains separate from the proposal and
requires an owner-gate reference, validation reference, before/after revisions,
and rollback reference for applied changes.

## Migration Boundary

Legacy Markdown, databases, inboxes, and other stores remain authoritative
until a provider-specific adapter proves:

- an immutable source snapshot and verified backup;
- stable material IDs and source references;
- parse-error accounting;
- equal item counts and lifecycle state under dual read;
- deterministic rerank proposal readback;
- owner-gated cutover and rollback.

The generic capability never embeds a legacy parser or a private file layout.
Adapters may coexist with the old store for as long as reconciliation requires.

## Read-Only Preparation Path

`MaterialInventoryProvider` is the private adapter boundary for legacy stores.
It returns transient metadata as `MaterialStoreSnapshot`: opaque snapshot and
backup references, revision and digest, lifecycle counts, parse-error
references, and three explicit verification results:

- stable material IDs were verified;
- the backup was verified;
- the source digest remained unchanged across inspection.

`prepare_material_migration` converts that transient snapshot into the existing
`material_store_inventory_v0` packet. It creates
`material_migration_plan_v0` only when all three verifications pass and no parse
errors remain. Otherwise it returns deterministic readiness blockers and no
plan. The provider contract has no apply method, and both emitted packets keep
`source_mutation_authorized=false`.

Provider implementations and private file layouts stay outside the generic
capability. A host adapter may parse Markdown, a database, or another source,
but it must prove the same read-only and backup invariants before LoopX will
prepare migration.

## Decision-Driven Ranking and Exploration

Stage 0 accepts an opaque `decision_evidence_ref` from Decision Context. A
later provider-neutral stage may derive a bounded rerank or exploration intent
from that evidence. Search engines, web clients, messaging providers, and
repository scanners remain replaceable providers; their raw output cannot enter
public packets.

This keeps recurring automation thin. A scheduler should wake the goal and
invoke the configured capability. Source lists, incremental cursors, ranking
rules, and exploration budgets belong in ignored goal-scoped configuration and
validated receipts, not in an automation prompt.

## Stage Boundary

The capability now ships deterministic contracts, a provider-neutral read-only
preparation path, catalog visibility, an architecture CLI, focused tests, and
a public smoke. It does not ship:

- a built-in legacy material parser or migration apply path;
- raw-material persistence;
- an exploration provider;
- a messaging or contact source profile;
- automatic reranking, archive moves, or cursor advancement.

Those require a private read-only adapter, exact dual-read reconciliation, and
an explicit owner gate.
