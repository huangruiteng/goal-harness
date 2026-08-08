# Bounded Auto-Research Failure Successors Design

**Status:** Accepted direction; pending written-spec review before implementation.

## Change Contract

**Goal:** Ensure a retired auto-research hypothesis produces one bounded next
control-plane outcome: a single data/measurement remediation, a new
hypothesis-proposer todo, an extension-evolution proposal, or an explicit
research-frontier exhaustion record.

**Acceptance evidence:**

- A negative-evidence fixture cannot finish as an implicit no-follow-up.
- A declared data/measurement gap creates at most one remediation todo for its
  hypothesis lineage and never creates a monitor.
- A non-remediable retirement creates a proposer successor todo through the
  existing role-successor lifecycle.
- A remediated lineage that still fails creates a proposer successor or an
  explicit `frontier_exhausted` outcome.
- Every terminal research evaluation records one local evolution review before
  completion, so an agent cannot silently stop after either a positive or
  negative result.
- A reproducible product-contract violation can create one bounded extension
  evolution proposal without waiting for a user to identify the gap.
- All resulting projections remain public-safe and use no network, scheduler,
  service, or new package dependency.

**Not in scope:**

- Automatically inventing a research hypothesis, changing a strategy, or
  relaxing thresholds.
- Waiting for future data through a `continuous_monitor` todo.
- Automatically editing, installing, enabling, upgrading, or publishing an
  extension.
- Creating a coordinator, a background agent, or a second research database.

**Expected implementation boundary:**

- `loopx/capabilities/auto_research/` owns the completion and role-successor
  semantics.
- `examples/auto-research-*.py` owns focused public regression proof.
- `docs/reference/protocols/auto-research-*.md` owns the public contract.
- A later extension-evolution proposal remains a normal LoopX todo, not a new
  extension runtime.

## Problem

The current auto-research read model recognizes negative evidence and derives
`retirement_candidates`. Its completion status then becomes
`retirement_review_required`. The default evaluator/promoter role profile,
however, declares successors only for positive dev/holdout paths. Once a
retirement review is completed, no deterministic role successor is required.

That lets an agent stop after a valid failed result even when the failure
contains a reusable research constraint or exposes a bounded next question.
The generic autonomous-replan mechanism detects repeated no-progress, but it
does not know whether a specific research failure should repair measurement,
change mechanism, or close the question.

## Placement Rationale

```text
capability_id: auto-research
provider_id: loopx-core
origin: builtin
placement: loopx/capabilities/auto_research/
reason: The existing capability already owns research evidence, completion
        status, worker roles, and role-declared successor todos. The new
        behavior refines that lifecycle; it is not a provider-neutral
        extension capability.
```

The later extension-evolution signal does not make a new extension. It is a
public-safe proposal for a human- or agent-owned product todo. The existing
extension runtime remains responsible only for provider lifecycle.

## Design Principles

1. **Every completed research result is an evolution input.** A terminal
   evaluation must leave a durable constraint, successor, product-gap proposal,
   or explicit exhaustion decision.
2. **Negative evidence is progress.** A retired hypothesis must leave a
   durable constraint and a visible next decision.
3. **Data repair is exceptional and bounded.** A lineage gets at most one
   declared data/measurement remediation. A weak metric does not by itself
   qualify as a data gap.
4. **No disguised parameter search.** A remediation may repair a declared
   source, unit, corporate-action, proxy, split, or measurement defect. It may
   not change thresholds, horizons, assets, or selection criteria to rescue the
   original conclusion.
5. **No future-data monitor.** If no current bounded action exists, the
   research question closes explicitly. Future work can start from a new
   contract when material is later available.
6. **No fake automation.** The control plane creates a todo and enforces the
   permitted outcome. The hypothesis proposer still writes the actual
   evidence-backed proposal; the kernel never invents research content.
7. **No external dependency.** All decisions derive from existing LoopX
   rollout events, todo lineage, and local role-successor writes.

## Completion Evolution Review

Every terminal evaluator/promoter action (`supported`, `contradicted`,
`retired`, `promoted`, or retry exhaustion) must derive and append one
`research_evolution_review_v0` record before its source todo may complete.

```json
{
  "schema_version": "research_evolution_review_v0",
  "goal_id": "example-research",
  "source_todo_id": "todo_distance_cache",
  "hypothesis_id": "hyp_distance_cache",
  "terminal_outcome": "contradicted",
  "constraint_refs": ["research_constraint:distance_cache_regresses"],
  "product_gap": {
    "status": "none",
    "fingerprint": null
  },
  "next_outcome": "propose_failure_successor"
}
```

The review has exactly one `next_outcome`:

| Next outcome | Meaning |
| --- | --- |
| `remediate_data_measurement` | The explicit repair budget remains and the defect is currently repairable. |
| `propose_failure_successor` | A proposer must write a new, mechanism-changing hypothesis or explicit exhaustion. |
| `extension_evolution_proposal` | Research exposed a bounded product or extension contract gap. |
| `constraint_recorded` | A supported or promoted result has no unresolved, safe in-scope successor; its method constraint is still durable knowledge. |
| `frontier_exhausted` | No current safe mechanism, material-preparation action, or product-gap proposal remains. |

The system guarantee is deliberately about the **state transition**, not the
quality of generated research prose: it guarantees that a completed research
item cannot silently close without an evolution-review record and one of the
five visible outcomes. The hypothesis-proposer lane remains accountable for
the semantic content of a newly proposed hypothesis.

## Failure Continuation Contract

Introduce a compact projection and durable lifecycle record:
`research_failure_continuation_v0`.

```json
{
  "schema_version": "research_failure_continuation_v0",
  "goal_id": "example-research",
  "hypothesis_id": "hyp_distance_cache",
  "source_todo_id": "todo_distance_cache",
  "failure_kind": "mechanism_contradicted",
  "failure_evidence_refs": ["research_evidence:hyp_distance_cache"],
  "remediation_attempt_count": 0,
  "remediation_attempt_limit": 1,
  "remediation_allowed": false,
  "monitor_allowed": false,
  "required_next_outcomes": [
    "propose_failure_successor",
    "frontier_exhausted"
  ]
}
```

The record is public-safe. It records compact ids and evidence aliases only;
it cannot contain raw evaluator logs, local paths, credentials, source bodies,
or provider payloads.

### Failure Kinds

| Failure kind | Remediation allowed | Required next outcome |
| --- | --- | --- |
| `mechanism_contradicted` | No | Proposer successor or frontier exhaustion. |
| `overfit_or_nonreplication` | No | Proposer successor with a changed mechanism, or frontier exhaustion. |
| `guardrail_or_protected_boundary` | No | Proposer successor only if a safe new mechanism exists; otherwise exhaustion. |
| `data_or_measurement_gap` | Yes, once | One remediation attempt, then re-evaluate. |
| `unrecoverable_data_gap` | No | Proposer successor with a different currently available information set, or exhaustion. |
| `retry_exhausted` | No | Proposer successor or exhaustion. |

A data/measurement gap must be declared by the evaluator with a compact
failure-evidence ref and a specific measurement scope. The kernel must not
infer this classification merely from a poor score or a failing holdout.
Absent an explicit declaration, the fail-closed default is
`mechanism_contradicted` or the existing negative-evidence classification.

### Repair Budget

The repair count is computed from the parent hypothesis lineage and previous
`research_failure_continuation_v0` records, not from how many times an agent
retries a CLI command.

- At count `0`, exactly one `remediate_data_measurement` successor is allowed
  only for `data_or_measurement_gap`.
- At count `1`, `remediation_allowed=false` permanently for the lineage.
- A remediation retains the original research objective, protected scope, and
  acceptance gates. It may correct only the declared measurement scope.
- Its result must return to evaluation. A second negative result cannot reopen
  remediation; it must produce a proposer successor or explicit exhaustion.

## State Transitions

```text
evaluated
  -> contradicted
  -> failure_continuation_required
       -> remediate_data_measurement      (only explicit gap and count=0)
          -> evaluated
       -> propose_failure_successor       (otherwise)
          -> hypothesis_proposed | frontier_exhausted
```

`continuous_monitor` is not a legal edge in this state machine.

### Completion Rule

The evaluator/promoter may complete a failure-review todo only after one of
these machine-visible deltas exists:

1. an exactly linked `remediate_data_measurement` successor with remaining
   repair budget;
2. an exactly linked `propose_failure_successor` todo owned by the
   hypothesis-proposer lane; or
3. a durable `frontier_exhausted` record with a compact no-follow-up rationale.

If none exists, the worker reports `failure_successor_required` and leaves the
todo open. It must not use `no_followup=true`.

### Proposer Successor Requirements

`propose_failure_successor` is a manual research action, not an automatic
idea generator. The proposer must select exactly one outcome:

- **New hypothesis:** preserve the parent hypothesis and failure refs, name the
  changed mechanism or available information set, and state why the change is
  not a parameter relaxation.
- **Frontier exhaustion:** record that no safe in-scope, currently executable
  mechanism change exists. This closes the question without a monitor.

The new hypothesis must not merely change a percentile cutoff, holding window,
asset, time slice, or ranking threshold while keeping the same failed
mechanism.

## Local Implementation Shape

### Read Model

`research_state.py` derives a compact failure-continuation summary from
retirement candidates and existing rollout evidence:

- failure candidate ids and evidence aliases;
- explicit data/measurement classification when recorded;
- lineage repair count and remaining budget;
- allowed successor actions;
- whether explicit frontier exhaustion is the only permitted closeout.

`build_auto_research_completion_status()` changes the negative path from
`retirement_review_required` to `failure_successor_required` until a permitted
delta is visible.

### Role Profiles and Worker Runtime

The evaluator/promoter profile declares failure successors in addition to its
current positive-evidence successors:

- create `remediate_data_measurement` only when the summary has
  `remediation_allowed=true`;
- otherwise create `propose_failure_successor` for `hypothesis-proposer`.

The worker runtime reuses `apply_role_successor_todos()`. It must create the
linked successor before calling the existing todo-completion helper. This keeps
the behavior local, idempotent, quota-visible, and compatible with the current
role-successor lifecycle.

The hypothesis proposer profile adds `propose_failure_successor` to its
allowed actions and states the three allowed outcomes above. No new coordinator
or scheduler is introduced.

### Durable Record

The continuation decision is appended through the existing rollout-event
mechanism so a later worker can recompute the budget and closeout state. The
record must be idempotent for the same source todo and continuation outcome.

## Extension Evolution Proposal (P1)

P1 adds a separate, bounded product-improvement signal. It is not part of the
P0 failure-successor transition and cannot change an extension automatically.

The completion evolution review classifies a possible gap into one of two
thresholds:

| Gap class | Proposal threshold |
| --- | --- |
| `reproducible_product_contract_violation` | One research lineage is enough when a focused local fixture proves that a published or executable LoopX contract is violated. |
| `repeated_extension_or_provider_gap` | The same public-safe fingerprint must occur in at least two distinct research lineages. |

Eligible fingerprints are:

- a repeated data/measurement validation gap that the current extension
  contract cannot express;
- a repeated provider boundary ambiguity that should fail closed earlier; or
- a repeated missing control-plane successor that forces manual user
  intervention.

Single-source failures remain research constraints unless they prove the
first-row product-contract violation. The proposal todo includes the compact
fingerprint, source evidence refs, affected owner, a bounded contract change,
explicit non-goals, and a focused validation target. It never installs,
enables, upgrades, modifies, or publishes an extension.

This rule covers the current gap: the documented research state machine permits
`contradicted -> hypothesis_proposed`, but the executable evaluator completion
has no matching successor rule. A focused fixture can reproduce that mismatch,
so the evolution review may proactively create an auto-research product
improvement proposal from one completed research lineage.

## Test Plan

Tests are written before implementation and exercise real local functions and
todo lifecycle paths.

1. **Negative evidence requires a delta.** A retired hypothesis produces
   `failure_successor_required`; an evaluator completion without successor or
   exhaustion is rejected.
2. **Every terminal result receives an evolution review.** Supported,
   contradicted, promoted, and retry-exhausted fixtures each emit one
   `research_evolution_review_v0` before their source todo can close.
3. **Default negative path creates proposer work.** A contradicted hypothesis
   creates one linked `propose_failure_successor` todo for the registered
   proposer lane and no monitor.
4. **One repair limit.** An explicitly declared data/measurement gap creates
   one remediation successor at count zero. After that remediation is recorded,
   a second failure creates a proposer successor rather than another repair.
5. **Explicit exhaustion is legal.** A durable `frontier_exhausted` record
   permits no-follow-up without a monitor and remains visible in the frontier.
6. **Parameter-relaxation guard.** A successor proposal lacking a changed
   mechanism or measurement scope is rejected.
7. **One-lineage contract violation can propose a product repair.** A fixture
   showing a documented transition without a legal successor creates one
   `extension_evolution_proposal`; a one-off data outage does not.
8. **Public-safe projection.** Failure continuation and any P1 proposal reject
   paths, URLs, credentials, raw logs, and provider payloads.

## Documentation Changes

Update the existing auto-research lane, state, and role-state-machine protocols
to describe:

- bounded remediation before failure successors;
- no-monitor failure closeout;
- proposer responsibility after retirement; and
- the distinction between a research constraint and a repeated-gap extension
  proposal.

No first-screen product surface changes are part of this work.

## Delivery Plan

1. **P0:** Add the failure-continuation read model, role successors, durable
   record, and focused regression smoke.
2. **P1:** Add repeated-gap aggregation and normal extension-evolution proposal
   todo generation without any provider mutation.
3. **P2:** Update public protocols and compact smoke coverage for the complete
   lifecycle.

Each batch remains reviewable on its own. P0 is the first implementation
segment because it directly prevents silent stopping after negative research
evidence.
