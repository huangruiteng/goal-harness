# RFC: TypeScript Control-Plane Migration Direction v0

- Status: Accepted, transaction-payoff phase in progress
- Proposed by: LoopX maintainers
- Date: 2026-08-15
- Last revised: 2026-08-23
- Scope: an incremental, replacement-first migration of the LoopX control-plane
  core from Python to TypeScript without maintaining two semantic
  implementations
- Tracking issue: [#3225](https://github.com/huangruiteng/loopx/issues/3225)
- Language note: the
  [Chinese version](./typescript-control-plane-migration-v0.zh-CN.md) and this
  English version are semantic mirrors. A difference between them is a defect.

---

## 0. Decision in one example

During migration, the Python `loopx` CLI sends one coarse typed transaction to
a LoopX-managed TypeScript runtime. For example, Turn settlement first asks
TypeScript to validate the journal and authorize any still-Python providers;
after Python checkpoints those external outcomes, TypeScript performs the final
reduction and returns one typed result. A replay with no pending provider needs
only the reduction call. Python translates the result into the legacy CLI shape.
It does not call a series of TypeScript leaf helpers or retain parallel enums
and reducers.

The same PR must delete the Python semantic path it replaces. A new TypeScript
module is not migration progress by itself: the payoff is fewer semantic
owners, fewer cross-runtime round trips, and a facade with a credible deletion
condition.

After the CLI itself migrates to TypeScript, CLI-only use imports the same
kernel in-process and the Python-to-TypeScript bridge disappears. When the App,
CLI, scheduler, or several hosts need one shared writer, the same kernel may run
inside one optional managed daemon. This is one kernel with two deployment
forms, not one server per control-plane family.

## 1. Problem

LoopX already has TypeScript host and dashboard surfaces. The Effect Program,
Turn-journal effects, several Todo/quota decisions, and scheduler state now
have TypeScript owners, while much of the CLI composition and compatibility
surface remains in Python. A big-bang rewrite is too risky, but continuing to
translate leaf helpers would leave a chatty bridge and duplicate DTO knowledge:
code would move without simplifying the product.

The migration therefore needs intermediate states that satisfy all of these
constraints:

- one semantic owner for every migrated rule;
- no user-visible CLI split and no manual daemon lifecycle;
- real side effects can migrate, not only pure projections;
- correctness is qualified against a pinned pre-migration baseline and
  independently stated invariants;
- latency, packaging, upgrade, rollback, and crash recovery are measured at
  every cutover;
- each PR is a complete, reviewable replacement slice;
- migration economics improve: old semantic code and temporary scaffolding
  leave faster than bridge code accumulates.

## 2. Architecture decision

### 2.1 One TypeScript kernel

`@loopx/control-plane` is the intended semantic kernel. Domain modules own
typed state, interpretation, transition rules, and the internal effects that
belong to those rules. A transport shell must not become a second business
owner.

```text
Python CLI during migration ─┐
LoopX App / scheduler ───────┼─> one typed runtime boundary ─> TS kernel
future TS CLI ───────────────┘
```

The boundary uses coarse, versioned requests such as “settle this Turn” or
“commit this journal”, not chatty property getters. The runtime has a static
typed handler registry. Adding a domain handler does not create another
server.

### 2.2 Two deployment forms, one implementation

| Product topology | Execution form |
| --- | --- |
| CLI-only after the TS CLI cutover | Import and execute the TS kernel in the CLI process; no daemon |
| App-only | Embed the same kernel in the App runtime |
| App + CLI + scheduler, or concurrent clients | One managed local authority daemon; clients connect to the active writer |
| Migration while Python remains the CLI | One idle-exiting loopback runtime bridges Python to the migrated TS kernel |

If an authority daemon owns a registry/workspace, a CLI process must connect
to it instead of opening a second direct writer. Runtime discovery and startup
are automatic; users do not configure ports or supervise processes.

### 2.3 TypeScript owns migrated effects

The target is not “TypeScript decides, Python always executes”. TypeScript may
own internal LoopX effects such as atomic state checkpoints, event appends,
receipt commits, and idempotent reducer writes. Each effect has a typed request,
stable idempotency identity, typed receipt, and retry policy.

Asynchronous execution does not weaken settlement ordering: an effect receipt
is emitted only after the awaited durability boundary succeeds. It does,
however, permit concurrent requests, so the authority that owns a migrated
write must also own its per-key serialization or compare-and-swap contract.
Caller-side locking is acceptable only as an explicitly transitional guard; a
native TypeScript caller must not bypass the invariant after cutover. Retry
identity is operation-specific: when one Turn effect checkpoints several
successive journal states, the broad Turn effect id alone is not proof that two
write payloads are the same operation.

External authorities remain explicit adapters: model calls, human gates, host
schedulers, credentials, and third-party mutations are not hidden behind a
universal executor. Their receipts return to the Effect Program for
settlement.

### 2.4 Replacement, not production dual-running

Characterization may execute the old and new implementations offline against
the same pinned corpus. Production does not keep two rule engines or dual-write
semantic state. Once a slice passes its gates, callers flip to TypeScript and
the replaced Python rule is removed. A narrow compatibility facade may remain
only for a real public import, persisted schema, or unmigrated callback.

### 2.5 Validate once at every trust boundary

TypeScript types are erased at runtime. Network/RPC payloads, parsed JSON,
persisted state, extension input, and adapter responses therefore enter the
system as `unknown`; a static annotation or `as T` assertion does not prove
that those bytes satisfy the contract. Each migrated domain must decode these
values through a typed decoder or an explicit versioned schema parser before a
domain handler or Effect interpreter consumes them.

After successful decoding, the TypeScript kernel owns the typed value and may
rely on the compiler instead of repeating ad hoc field checks throughout the
domain. Transport checks such as framing, authentication, and size limits stay
separate from schema validation and semantic invariants. An unchecked
`JSON.parse(...) as T` must not establish control-plane authority.

`as unknown as T` is permitted only as a named migration seam: its exact call
site, upstream validator, negative boundary coverage, and removal owner must be
visible in the cutover PR. A migrated domain cannot pass its promotion gate
while public, persisted, RPC, or extension input still reaches its semantic
core through an unvalidated assertion. TypeScript complements runtime
validation; it does not replace it.

## 3. Current baseline and phase transition

Effect Program moved first because it joins ordered steps, identity,
short-circuit failure, replay, receipts, and settlement. That architectural
choice is now implemented rather than hypothetical.

### 3.1 Shipped baseline

| Slice | Canonical TypeScript ownership now shipped | Remaining migration debt |
| --- | --- | --- |
| Effect runtime and Turn journal ([#3416](https://github.com/huangruiteng/loopx/pull/3416)) | Effect algebra, settlement rules, runtime lifecycle, typed Turn-journal interpretation, and durable checkpoint effects | Python settlement facades still expose fine-grained calls and duplicate DTO/enum shapes |
| Todo, quota, and scheduler proof slices ([#3431](https://github.com/huangruiteng/loopx/pull/3431)–[#3434](https://github.com/huangruiteng/loopx/pull/3434)) | Completion fence/state, workspace causality, and scheduler transitions each have one TS rule owner | The cuts are mostly leaf-shaped; Python still composes several product transactions |
| Scheduler durable state ([#3440](https://github.com/huangruiteng/loopx/pull/3440)) | State normalization, persistence, replay, and one coarse transition are TS-owned | The Python compatibility path still pays a cross-runtime transport tax |
| Scheduler heartbeat/state transaction | TypeScript owns ACK and host-failure validation, state construction, failure-cache transitions, replay/CAS fencing, and atomic writes | Python retains only a direct native-command transport and legacy event projection; external host mutation remains Python |
| Quota spend commit transaction | TypeScript owns final spend-transition validation, typed event construction, effect replay/CAS fencing, crash repair, and the JSON/Markdown/index write set | Python still projects `should-run` and settlement readback facts, and holds the legacy cross-writer index lock until the CLI/index writers move in-process |
| Runtime decoders ([#3443](https://github.com/huangruiteng/loopx/pull/3443)) | Stable primitive decoding has one small shared module; domain decoders remain local | No larger schema framework is justified |
| Transaction payoff ([#3464](https://github.com/huangruiteng/loopx/pull/3464), [#3481](https://github.com/huangruiteng/loopx/pull/3481), and Todo completion) | Turn settlement, quota delivery routing, and Todo completion each cross one coarse TS boundary; the Todo transaction owns identity, replay fencing, validation planning/result reduction, continuation/recovery, and completion metadata | Python still executes explicitly external providers and materializes legacy Markdown/event results; other domains still need their own bounded cutovers |

The scheduler facade exit is now a concrete migration stage. A native
`heartbeat_commit_cli.ts` accepts compact scheduler/host facts and owns the
scoped state read, CAS digest, semantic effect identity, validation, replay,
and locked write in one process. The managed `scheduler.heartbeat.commit`
handler and the Python semantic bridge are removed. Python quota code remains
only as a direct subprocess transport plus the compatibility event projection;
the host automation adapter and its TOML/SQLite writes are intentionally still
Python. The final deletion trigger for that retained code is moving the host
adapter and scheduler CLI/projection to the same native transaction boundary.

These slices proved correctness, packaging, Windows lifecycle, crash recovery,
real TS-owned writes, and acceptable warm primitive-call latency. They also
revealed the migration boundary: leaf-by-leaf translation grows TypeScript,
facades, parity fixtures, and bridge traffic before enough Python composition
can be deleted.

### 3.2 Payoff-phase decision

The migration therefore enters a **transaction-payoff phase**. New leaf
migrations are rejected unless they directly unlock a complete transaction
cutover and deletion in the same PR or the immediately stated bounded follow-up.
The unit of progress is now an operator-visible transaction, not a helper,
enum, dataclass, or source file.

A transaction cutover must:

1. move validation, state transition, migrated internal effects, and result
   construction behind one domain-owned TS request/response boundary;
2. delete the replaced Python rule composition, fine-grained API, duplicate
   enums/dataclasses, and implementation-specific tests;
3. leave Python as transport, legacy response projection, and explicit adapter
   for still-external authorities only;
4. avoid leaf-level bridge chatter. A transaction whose effect providers have
   migrated to TypeScript, or a replay with no pending provider, uses one
   request/response. While a real provider remains in Python, use at most two:
   one fail-closed preflight that authorizes named effects and one final
   reduction over their checkpointed outcomes. A model call, human gate, or
   third-party mutation starts a new receipt-bearing transaction rather than an
   implicit callback tunnel;
5. name the exact condition under which its Python facade and bridge operation
   can be removed.

Domain invariants remain with their bounded owner. “Coarser” does not mean one
universal control-plane command or one mega-reducer.

## 4. Migration sequence

### Stage 0 — Pin behavior and authority (complete, repeated per transaction)

For each selected transaction, record authoritative schemas and independently
reviewed legal/illegal transitions, production callers and side effects,
matched latency/install baselines, and rollback/state-compatibility boundaries.
Characterization fixtures are temporary migration evidence, not permanent
specification.

### Stage 1 — Effect Program and managed runtime foundation (shipped)

The TypeScript Effect algebra, settlement semantics, Turn-journal
interpretation, durable checkpoint effect, runtime lifecycle, packaging,
upgrade fingerprint, and boundary decoder foundation are on `main`. This stage
is not complete from a cleanup perspective: its Python fine-grained settlement
surface remains a primary target for the payoff phase.

### Stage 2A — Bounded rule-owner proofs (shipped; do not repeat as a pattern)

Todo completion, quota workspace causality, scheduler transitions, and
scheduler durable state established that a Python caller can safely switch to
a single TS semantic owner. Their characterization and facade layers were
appropriate migration evidence, but copying the same leaf pattern across more
domains would now increase total complexity.

### Stage 2B — Complete transaction cutovers (active)

Select by deletion leverage and runtime traffic, not by ease of translation.
The shipped Turn settlement, quota delivery-routing, Todo-completion,
scheduler-heartbeat, quota-spend commit, and task-lease acquire cutovers
establish the pattern.
Subsequent candidates must name a remaining transaction and its deletion
leverage; remaining quota settlement readback is eligible only when it can
retire or materially shrink the facade rather than add another leaf handler.

For each completed transaction, replace migration-only characterization workers
and Python implementation fixtures with native TS semantic/invariant tests plus
one durable end-to-end adapter contract. Retain a characterization corpus only
while an old authority remains executable or a versioned compatibility window
requires differential proof; record its deletion trigger when introduced.

Current implementation status: Stage 1, the bounded Stage 2A proofs, and the
shipped Stage 2B cutovers are in place:

- Turn settlement/commit: TypeScript owns preflight authorization,
  ordered-prefix and replay validation, provider failure classification,
  receipt construction, terminal closeout joining, and the canonical result.
  A real Python provider uses two coarse reductions; completed replay uses one.
- Quota delivery routing: TypeScript owns continuity-versus-fallback selection
  and the selected Todo's settlement boundary. The in-flight path moved from
  two cross-runtime calls to one; the empty candidate short circuit remains
  zero.
- Todo completion: TypeScript owns completion identity, terminal replay fence,
  validation declaration/effect planning, validation-receipt reduction,
  continuation/recovery, and completion metadata in one transaction. A Todo
  without declared validation, including a replay, uses one reduction. A real
  caller-approved validation command remains an explicit Python provider
  between two reductions. A source snapshot is compared after the mutation
  lock so a receipt for one declaration cannot authorize a changed Todo.
  Materialized and event-projected writes consume the same typed result.
- Scheduler heartbeat/state: TypeScript owns ACK and host-failure validation,
  identity-aware progression, failure-cache retention/counting, replay and CAS
  fencing, preview reduction, and the locked atomic write. Python supplies the
  host outcome and compact scheduler facts, then projects the typed state into
  the legacy event shape. The remaining facade exits when the scheduler CLI and
  host adapter call this transaction natively; until then its state preflight is
  limited to the external-provider boundary.
- Quota spend commit: TypeScript revalidates the compact before/after transition,
  constructs the canonical public-safe spend event, fences the effect with a
  locked index CAS, and commits JSON, Markdown, index, and transaction receipt
  as one repairable operation. Same-effect retries are idempotent, cross-effect
  drift conflicts, and a prepared transaction repairs a partial artifact set.
  The receipt binds the pre-append index digest and byte offset, so a retry can
  repair only its own truncated final JSONL row while unrelated corruption
  still fails closed.
  Python retains `should-run`/settlement fact projection plus one coarse
  transport call and the legacy kernel index lock; it no longer constructs or
  writes the spend event.
- Task-lease acquire: TypeScript owns identity normalization, settlement-plan
  projection, provider failure classification, ordered receipt construction,
  and the canonical result. Python invokes the existing atomic provider between
  one preflight and one final reduction; the provider retains the per-goal lock,
  owner eligibility, conflict, compare-and-swap, idempotency, and lease-file
  durability checks. Invalid identities stop before the provider, while a
  crash/retry after the provider re-enters its same-key idempotent path.

The quota-spend cutover removes the Python spend-event builder and three-file
writer. Its bounded facade exits when the quota CLI and remaining run-index
writers execute the transaction in-process; until then it supplies compact
projection facts and shares the legacy Python index lock with unmigrated
writers. The Todo cutover removes the Python state-evaluation dataclass, local identity
projection, replay helper, and public runtime handlers for those implementation
leaves. The remaining Python Todo facade owns transport, external command
execution, source compare-and-swap, legacy response projection, and the actual
Markdown/event write. It exits when those writers and the CLI move into the
native TS transaction. The remaining fine-grained Turn facade exits after
quota and host-adapter callers move to their own coarse transactions. The
task-lease Python facade now contains only transport, the atomic provider, and
legacy CLI projection; it exits when lease persistence and the task-lease CLI
run in the native TS transaction. Vision checkpointing remains a separate
refresh/writeback transaction because it does not share the delivery-selection
lifecycle phase.

### Stage 3 — CLI and App convergence

Ship a native TS CLI that imports the kernel in-process. Keep one automatically
selected authority path: direct in-process execution for CLI-only use, or the
managed daemon when the App/scheduler already owns the workspace. Remove the
Python bridge and its protocol after no production caller needs them.

### Stage 4 — Distribution cleanup

Package the kernel for npm and LoopX release artifacts, remove the Python
runtime requirement, and decide whether the optional daemon ships as a normal
Node entry point or a LoopX-built single executable. Do not silently depend on
an unofficial third-party Node wheel.

## 5. Payoff-phase PR contract

Every later migration PR includes a **migration economics receipt** in its
description and validation comment:

| Field | Required evidence |
| --- | --- |
| Canonical owner | Owner before and after the cutover; no ambiguous dual authority |
| Legacy semantic code deleted | Product LOC of replaced Python rules, fine-grained APIs, enums/dataclasses, and implementation-only adapters removed |
| Bridge code added | Product LOC added solely for Python↔TS transport or compatibility |
| Cross-runtime calls | Happy-path and recovery-path request/response counts before and after; target one request/response when effects are TS-owned or no provider is pending, otherwise at most one preflight plus one final reduction while a real Python provider remains |
| Product-code net change | Added minus deleted product LOC, reported separately from tests, fixtures, generated files, and docs |
| Migration scaffolding | Characterization/parity helpers added, retained, or deleted, with a concrete removal trigger |
| Facade exit | Facade deleted now, or the exact remaining caller/compatibility contract and deletion condition |
| Correctness and performance | Invariants, negative cases, matched end-to-end baseline, packaging, crash/retry, and host coverage relevant to the changed transaction |

LOC uses the final merge-base diff and classifies production code separately
from tests, fixtures, generated files, and docs. Moved code counts as deletion
plus addition; bridge LOC must name the functions whose only purpose is
cross-runtime transport or compatibility. Round trips are counted on one named
public happy path and its retry/recovery path, not inferred from handler count.

A PR that only relocates code, adds a handler, or increases bridge surface
without deleting authority does not pass this phase. A temporary net increase
may be accepted for one cohesive transaction only when the receipt shows why
the bridge is bounded and which next deletion realizes the gain. That exception
cannot be chained across open-ended leaf migrations.

Stable primitive decoders may be shared through the existing small runtime
decoder module. Domain decoders stay in their bounded contexts; this RFC does
not authorize a generic schema framework.

## 6. Correctness and performance gates

### Correctness

- Independently stated algebra properties: identity, associativity where
  applicable, ordering, short-circuit, replay, and effect-id isolation.
- Exact output parity for the pinned characterization corpus.
- Negative cases for malformed state, cross-effect overwrite, partial commit,
  cancellation, permission denial, and budget rejection.
- Boundary decoders reject missing fields, wrong types, unsupported schema
  versions, and oversized or malformed payloads before domain dispatch. The
  cutover inventory lists any remaining `as unknown as T` seam and proves that
  it is guarded; promotion requires removing unvalidated assertions from the
  migrated domain's authority inputs.
- Awaited writes emit receipts only after their declared durability point;
  concurrent same-key mutations are serialized or use a tested CAS contract,
  and retry identity distinguishes successive checkpoints within one Turn.
- Process crash and retry cannot duplicate a committed internal effect.
- Wheel and sdist are installed into fresh environments and execute deep
  semantic probes from packaged files.

Characterization output is evidence, not specification. If a pinned behavior
contradicts an independently reviewed invariant, the PR must disclose and
separately approve the behavior change. Once the old authority is removed,
promotion also requires deleting characterization machinery that serves only
that implementation comparison; durable regression fixtures may remain when
they express a public or persisted compatibility contract.

### Performance

Measure cold startup separately from steady-state execution. Every transaction
cutover reports:

- managed runtime cold-start p50/p95;
- warm typed request p50/p95;
- representative complete transaction p50/p95 and cross-runtime round trips;
- full CLI p50/p95 versus the pinned Python baseline;
- daemon memory after idle and under a bounded request burst.

The default acceptance target remains warm, non-durable internal transitions
below 2 ms p95 and no material full-CLI regression (greater than 5% or an
unexplained 25 ms additive p95). Durable transactions are compared with a
matched durability baseline rather than the 2 ms kernel budget. A miss, or a
tail regression hidden by a faster microbenchmark, is an owner review gate and
cannot be silently relaxed.

## 7. Install, upgrade, and rollback

The migration must not ask users to manage a service. The Python-transition
release may require Node.js 22.6 or newer, but installer and `loopx doctor`
must detect it before normal control-plane work and provide exact remediation.
The wheel and sdist carry the TS source and versioned schemas.

The runtime is healthy while idle-exited: `stopped` means the next
control-plane request will start it automatically, not that the user must run a
daemon command. CLI and App surfaces consume the same lifecycle projection
(`running`, `stopped`, or `unavailable`) and stable diagnostic code. Raw stderr,
tokens, local paths, and private runtime metadata are not projected.

The runtime fingerprint includes every executed TS module and contract. An
upgrade starts a runtime for the new fingerprint; an old process can finish
in-flight work and exits on idle. Requests carry stable effect identities, so a
transport retry is safe only for handlers that are explicitly idempotent.

Rollback restores the previous artifact and fingerprint. Persisted state is
not rewritten into a TS-only format until a separately qualified state-schema
cutover.

## 8. Non-goals and stop conditions

- No permanent Python and TS semantic twins.
- No server per domain and no generic arbitrary-command executor.
- No big-bang CLI rewrite.
- No dual-write of production semantic state as a migration strategy.
- No performance claim from microbenchmarks alone.
- No more flat migration of leaf helpers merely because the bridge exists.
- No duplicate Python enum/dataclass retained without a named public import,
  persisted wire contract, or unmigrated caller.
- No permanent characterization harness for an implementation that no longer
  exists.

Stop or replan if the bridge becomes user-managed, a migrated rule still has a
Python semantic owner, the handler boundary becomes chatty, two consecutive PRs
increase bridge/scaffolding without retiring a facade, or a transaction cannot
meet its invariant/recovery/performance gates without weakening existing
behavior.
