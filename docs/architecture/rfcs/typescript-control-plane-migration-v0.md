# RFC: TypeScript Control-Plane Migration Direction v0

- Status: Draft, first bounded cutover under maintainer review
- Proposed by: LoopX maintainers
- Date: 2026-08-15
- Last revised: 2026-08-21
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
a LoopX-managed TypeScript runtime. The migrated TypeScript module owns the
rule and any migrated internal LoopX effect; Python is only a transport and
legacy-callback adapter. The replaced Python rule and its implementation-only
tests are deleted in the same PR.

After the CLI itself migrates to TypeScript, CLI-only use imports the same
kernel in-process and the Python-to-TypeScript bridge disappears. When the App,
CLI, scheduler, or several hosts need one shared writer, the same kernel may run
inside one optional managed daemon. This is one kernel with two deployment
forms, not one server per control-plane family.

## 1. Problem

LoopX already has TypeScript host and dashboard surfaces, but its canonical
control-plane rules live in Python. A big-bang rewrite is too risky, while a
long-lived dual implementation would be worse: every bug fix would need to be
made twice and parity would become a permanent product feature.

The migration therefore needs intermediate states that satisfy all of these
constraints:

- one semantic owner for every migrated rule;
- no user-visible CLI split and no manual daemon lifecycle;
- real side effects can migrate, not only pure projections;
- correctness is qualified against a pinned pre-migration baseline and
  independently stated invariants;
- latency, packaging, upgrade, rollback, and crash recovery are measured at
  every cutover;
- each PR is a complete, reviewable replacement slice.

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

## 3. Why Effect Program moves first

Effect Program is the bottom contract that already joins ordered steps,
identity, short-circuit failure, replay, receipts, and settlement. Migrating it
first gives later todo, quota, scheduler, and gate work one typed execution
language instead of independently inventing cross-language contracts.

This is not permission to move every state machine into one generic protocol.
Domain transition invariants stay with their domain owner. A family migrates
only when a real caller can switch and the PR deletes corresponding Python
knowledge.

## 4. Migration sequence

### Stage 0 — Pin behavior and authority

For the selected slice, record:

- authoritative schemas and independently reviewed legal/illegal transitions;
- pinned-base characterization fixtures;
- production callers and side effects;
- latency and package/install baseline;
- rollback boundary and state compatibility.

### Stage 1 — Effect Program cutover

Move the Effect algebra and normal-Turn settlement semantics to TypeScript:
ordered programs, settlement identity, bind/short-circuit behavior, replay,
receipt construction, next-action selection, and commit reduction. Add one
native internal effect—atomic Turn-journal checkpointing—to prove that the
runtime owns more than pure projection.

Python callers use the managed runtime and retain only DTO conversion plus
unmigrated external callbacks. Delete the Python semantic implementation and
its implementation-specific tests after parity and invariant coverage exist.

### Stage 2 — Domain slices

Migrate one bounded owner at a time, selected by duplicate-knowledge and
runtime value rather than file size. Candidate order is:

1. todo lifecycle and completion fence;
2. quota settlement/spend reducers and typed receipts;
3. scheduler/monitor state transitions while host mutation remains delegated;
4. gates, capability resolution, and status projections;
5. event-store writer and multi-client authority.

Each slice moves its tests with the rule. The repository does not first rewrite
the entire Python test suite into TypeScript, because tests without a migrated
owner would either call Python indirectly or duplicate implementation
assumptions.

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

## 5. First bounded PR contract

The first PR is intentionally one coherent vertical replacement:

- complete TS ownership of the existing Effect Program and settlement
  semantics used by production callers;
- one managed, idle-exiting loopback runtime with transport separated from a
  typed handler registry;
- centralized runtime decoders for migrated authority inputs; the first slice
  carries no `as unknown as T` or `as never` assertion across its RPC boundary;
- TS-owned Turn-journal interpretation and atomic checkpoint write;
- Python compatibility facades switched to the TS owner, with replaced Python
  rule code and obsolete tests deleted;
- Node readiness and actionable doctor output;
- automatic stale-PID and abandoned-start-lock recovery, stable public-safe
  startup diagnostic codes, and one lifecycle health projection consumable by
  CLI and App surfaces without a second health model;
- wheel and sdist inclusion, clean-environment probes, Windows coverage, crash
  restart, idempotent retry, and upgrade fingerprinting;
- pinned-base characterization, native TS invariant tests, Python caller
  regressions, and end-to-end latency evidence.

It does **not** migrate the full CLI, todo/quota/scheduler domains, publish a
release, or authorize a second PR. It stops at an owner review gate.

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
separately approve the behavior change.

### Performance

Measure cold startup separately from steady-state execution. The first PR must
report:

- managed runtime cold-start p50/p95;
- warm typed request p50/p95;
- representative settlement transaction p50/p95;
- full CLI p50/p95 versus the pinned Python baseline;
- daemon memory after idle and under a bounded request burst.

The default acceptance target is warm internal transitions below 2 ms p95 and
no material full-CLI regression (greater than 5% or an unexplained 25 ms
additive p95). A miss is an owner review gate, not a benchmark that may be
silently relaxed.

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
- No later slice starts until the first PR's owner review accepts correctness,
  performance, packaging, and maintainability evidence.

Stop or replan if the bridge becomes user-managed, a migrated rule still has a
Python semantic owner, the handler boundary becomes chatty, or the first slice
cannot meet its parity/recovery/performance gates without weakening existing
behavior.
