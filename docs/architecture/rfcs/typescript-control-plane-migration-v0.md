# RFC: TypeScript Control-Plane Migration Direction v0

- Status: Draft, under maintainer review
- Proposed by: LoopX maintainers
- Date: 2026-08-15
- Scope: an incremental, contract-first migration strategy for the LoopX
  control-plane core from Python to TypeScript; parity-gated, block-by-block
  replacement
- Source baseline: `d1fe05932`
- Tracking issue: [#3225](https://github.com/huangruiteng/loopx/issues/3225)
- Language note: the
  [Chinese version](./typescript-control-plane-migration-v0.zh-CN.md) and this
  English version are semantic mirrors. A difference between them is a defect.

---

## 0. Example

A host wants to embed LoopX decision-making without requiring a Python
runtime. Today, the Pi extension
(`loopx/pi_goal_mode/loopx-goal.ts`) already runs the quota decision by
shelling out to the Python CLI
(`loopx quota should-run --runtime-profile generic_cli`). The extension
implements its goal loop in TypeScript; only the decision kernel is Python.

The migration question is whether that split can grow into a full TypeScript
control-plane core without a big-bang rewrite: Python and TypeScript calling
each other, one surface at a time, with the user experience unchanged.

This RFC answers yes, but not through in-process mutual calls. It proposes a
contract-first "strangler" migration over three existing seams: the event
store, the parity-fixture layer, and the CLI boundary.

## 1. Problem

- External projects are already porting the LoopX kernel to TypeScript; the
  most complete sketch is
  [Foreman PR #1](https://github.com/needware/foreman/pull/1).
- The frontstage/dashboard surface is already TypeScript.
- A shared runtime would simplify CLI distribution and host integration,
  including an npm package.
- The control-plane core is roughly 343k lines of Python, with more than
  1,200 files under `tests/` and `examples/`. A one-pass rewrite is
  high-risk, effectively un-reviewable, and would strand production behavior
  behind a single cut-over.
- The naive reading of "Python and TypeScript calling each other" —
  in-process imports — is impractical: embedding CPython inside Node and
  V8 inside Python both carry GIL/ABI/packaging costs, and Pyodide/WASM has
  startup, single-thread, filesystem, and process limitations.

The practical question is therefore: which boundary can carry a
dual-language transition with parity guarantees and rollback?

## 2. Decision

Adopt a contract-first, parity-gated, block-by-block migration:

1. Interop happens over a process boundary with JSON contracts
   (stdio JSON-RPC/NDJSON), not in-process imports. Calls are coarse-grained —
   a CLI command, a projection render, or a decision request — so per-call
   latency is acceptable.
2. The event store is the shared fact surface: append-only events with
   versioned schemas (`loopx_state_event_v0`) form the only cross-language
   state contract. Either language can build projections from the same event
   stream.
3. Read paths and projections migrate first (pure, side-effect-free), then
   deterministic decision kernels (quota `should-run`, todo lifecycle
   transitions, scheduler state transitions) validated by parity fixtures and
   decision replay. The event store and write paths migrate last, through a
   dual-read → dual-write → flip sequence with a bounded canary and a recorded
   rollback plan.
4. Python remains the canonical implementation during the transition. A block
   flips only when its parity gate passes and its rollback plan is recorded.

### 2.1 Interop options

| Option | Verdict | Notes |
| --- | --- | --- |
| TS → Python subprocess | ✅ already in production | `pi_goal_mode` uses `execFile("loopx", ...)` with a 30s timeout; simplest and proven for coarse calls |
| Python → TS subprocess | ✅ viable | `node dist/...` with JSON on stdin; same shape when a migrated kernel must be called from Python |
| Long-lived sidecar (JSON-RPC over Unix socket) | ⚠️ optimize later | Amortizes startup for hot paths; requires lifecycle, version, and lock discipline |
| Pyodide / WASM | ❌ not for production CLI | Startup in seconds, single-threaded, filesystem/process limits |
| Rust core + PyO3/napi-rs dual bindings | ⚠️ separate project | True shared core with thin Python/TS bindings (like huggingface/tokenizers), but it is a Rust rewrite, not a TypeScript migration |

## 3. Existing seams that make this viable

The migration is not a leap into the unknown; three seams already exist in the
repository:

- `loopx/pi_goal_mode/loopx-goal.ts` and `pi-goal-loop-runtime.mjs`: a
  production TypeScript surface that delegates quota decisions to the Python
  CLI over a process boundary.
- `loopx/control_plane/testing/quota_should_run_parity.py`: a compact,
  stable parity surface for comparing old and new quota builders; the template
  for every future parity fixture.
- `loopx/control_plane/testing/decision_replay.py`: replays historical
  payloads against a decision builder — the dual-implementation comparison
  harness.
- `loopx/control_plane/testing/cli_output_differential.py`: enforces CLI
  output contracts and growth budgets.
- `loopx/event_sourced_state.py`: append-only, schema-versioned event state
  (`loopx_state_event_v0`).
- `loopx/control_plane/runtime/event_store_migration_bridge.py`: already
  models dual-read parity, bounded canaries, and rollback records for event
  projection promotion.

## 4. Migration phases

### Phase 0 — Contract freeze

Turn the candidate scope in #3225 into typed schemas and a parity-fixture
inventory: append-only event state and idempotent writes; todo lifecycle
(claim, lease, status, revision, completion validation); gates and decision
scope; quota (`should-run`/spend) and scheduler/monitor contracts; the Turn
envelope and transaction semantics; handoff and review-packet projection; CLI
and status/quota JSON parity. No code migration happens in this phase.

### Phase 1 — Read paths and projections

Migrate status JSON, todo list projection, handoff review-packet projection,
and frontstage rendering. These are pure functions with no side effects.
TypeScript implements each surface; Python generates golden fixtures; a
dual-read gate requires the TypeScript projection to match the Python head
before it may serve.

### Phase 2 — Deterministic decision kernels

Migrate `quota should-run`, todo state transitions, and scheduler state
transition rules. These are pure decisions with no I/O, so they are the
natural parity candidates. `decision_replay` replays historical inputs
through both implementations; a block flips only when outputs are identical
field-by-field. After this phase, the Pi extension can drop its Python quota
dependency.

### Phase 3 — Event store and write paths

TypeScript first reads the event store as a projection reader (dual-read),
then dual-writes with idempotency checks, then flips the write path. The
`event_store_migration_bridge` canary and rollback gates apply at each step.

### Phase 4 — Distribution

Publish an npm package and a pip shim (or both). A TypeScript CLI shim
forwards unmigrated commands to Python, so the `loopx` user experience stays
unchanged throughout.

## 5. Interop contract

- Every surface carries a versioned JSON schema (`..._v0`).
- Requests/responses travel as NDJSON over stdio; the long-lived sidecar may
  add content-length framing.
- Errors use a machine-readable envelope (code + message), never raw
  tracebacks.
- Callers set timeouts, following the existing `LOOPX_CLI_TIMEOUT_MS` pattern.
- Writes are idempotent: events carry stable ids and duplicate application is
  a no-op.
- No credentials, raw logs, or private paths cross the boundary.

## 6. Validation

- Parity fixtures per surface: the same input corpus produces identical
  compact JSON output from both implementations.
- Decision replay: historical payloads replay against both implementations.
- Dual-read gate: TypeScript projection must match the Python head before it
  serves traffic.
- Bounded canary: a small canary goal set runs on the new path before flip.
- Rollback record: the flip is flag-gated and the rollback plan is recorded
  before the flip happens.
- CLI output budgets remain enforced by `cli_output_differential`.

## 7. Non-goals

- No behavior change; Python remains canonical during the transition.
- No in-process embedding (CPython inside Node, or V8 inside Python).
- No Pyodide/WASM as the production runtime.
- No fork-first migration; upstream-owned and contribution-friendly.
- No one-pass rewrite of the full control-plane core.

## 8. Open questions

- Runtime choice: Node.js, Bun, or Deno?
- Packaging/distribution: npm package, pip shim, or both?
- Contributor ownership and review lane for the TypeScript track?
- Hot-path budget: which surfaces justify a long-lived sidecar?
- Should the eventual shared core be Rust with thin Python/TypeScript
  bindings instead (a separate RFC)?

## 9. Smallest useful implementation slice

A TypeScript implementation of the `quota should-run` compact parity surface,
run against the same fixture corpus as `quota_should_run_parity.py`, producing
identical JSON. Optionally paired with one read-path probe: a TypeScript todo
list/status projection rendering the same event fixtures as the Python
projection. This validates the entire pipeline — contract, parity fixtures,
dual implementation, and the process boundary — at near-zero production risk.

## 10. Rollout and rollback

Every block follows the same sequence: dual implementation → parity gate →
dual-read (for read paths) → bounded canary → flip behind a flag → recorded
rollback plan. Any parity mismatch blocks the flip. Rollback means flipping
back and keeping both implementations until the block is re-qualified; no
existing user state is migrated twice or left half-migrated.
