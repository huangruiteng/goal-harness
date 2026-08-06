# NoKV canonical-coordination provider reference

This directory contains the small, reviewable NoKV reference for
[RFC: shared-goal authority and pluggable state provider v0](../../docs/architecture/rfcs/shared-goal-authority-state-provider-v0.md).
It is a contract example, not a shipped LoopX runtime integration or a
production deployment claim.

## Scope

The claim-only proof stores one per-goal **canonical coordination aggregate**.
The aggregate contains only the normalized facts needed to validate an
explicitly bootstrapped `claim_work`, the current authority revision,
claim/lease/fence state, and a replayable receipt index. It does not implement
the complete production lease lifecycle or migrate the current LoopX runtime.

The following remain outside this head:

- run artifacts and run-history ledgers;
- status and attention projections or caches;
- quota policy, accounting, and enforcement ledgers;
- host-local routes, scheduler state, locks, and runtime bindings;
- raw evidence, transcripts, credentials, and local absolute paths; and
- Agent IM delivery, wake-up, presence, and offline queues.

Those surfaces have separate ownership and synchronization strategies in the
RFC persistence matrix. A provider does not acquire authority over them merely
because they may be visible from a shared goal.

## Atomic aggregate and receipt replay

The current coordination state and the receipt mapping for a newly accepted
operation are published in the **same head CAS**. The reference does not use a
last-envelope shortcut or a separate `pending -> head -> finalize` receipt
protocol.

The one-head CAS is a physical serialization point, not a goal-wide domain
conflict boundary. Commands name the target todo revision and the compact
authorization, dependency, and gate preconditions they actually observed.
After a CAS miss, the authority reloads and checks those facts again. If an
independent todo advanced the head, it rebases and retries internally; if the
target todo or a named precondition changed, it returns a domain conflict.
`authority_revision` remains a goal-wide commit and audit sequence, not a
required client precondition. In this reference, independent claims use
`write_scopes=[]`; non-empty cross-todo scope overlap is not qualified here.
Internal rebase also assumes the publisher never reuses a target-scoped token
for a different authorization, dependency, or gate snapshot. The deterministic
probe uses static bootstrap inputs and does not qualify that dynamic publisher.

This matters for a historical retry:

1. operation A commits and returns receipt A;
2. operation B advances the goal head;
3. the caller retries A after losing its first response; and
4. the provider returns the original receipt A, field for field, without
   applying A again or moving the current head.

Each receipt-index entry binds the stable operation identity to a digest of the
immutable request. Reusing an operation identity with different immutable
inputs fails closed; it is never classified as an idempotent replay.

The provider contract remains storage-only:

```text
load() -> (aggregate | none, provider_generation)
compare_and_put(expected_provider_generation, aggregate)
    -> applied(provider_generation)
     | conflict(current_provider_generation)
     | ambiguous
     | failed
```

`provider_generation` is the opaque storage CAS token. It is distinct from the
aggregate's `authority_revision` and from each todo's lease epoch; none of these
three version domains is derived from another.

The storage provider deterministically serializes and stores the opaque
aggregate and returns CAS outcomes.
`CoordinationAuthority` remains responsible for request validation, authority
revision, claim/lease transitions, request-digest binding, and the original
domain receipt. The provider must not inspect an operation receipt or invent
lease, gate, quota, or scheduling decisions.

## Files

- `provider.py`: `NoKVCoordinationProvider`, which maps an opaque per-goal
  aggregate to NoKV path generation CAS, plus `CoordinationAuthority`, which
  constructs the aggregate and its receipt index.
- `probes.py`: deterministic contract regressions. Only the checks in the
  [evidence note](../../docs/architecture/rfcs/shared-goal-authority-state-provider-v0-evidence.zh-CN.md)
  are merge evidence for the revised receipt contract.

## Validation boundary

A static compatibility audit is pinned to NoKV
[`90883d13539e31185f0d78131989fb51912dbd7e`](https://github.com/NoKV-Lab/NoKV/commit/90883d13539e31185f0d78131989fb51912dbd7e).
At that baseline, the Python `publish_bytes` surface accepts
`expected_generation` for create-only or replacement CAS and exposes optional
publication `operation_id` and `artifact_revision_id` inputs. This establishes
that the provider mapping has a source-level API seam; it does not prove its
live behavior. The NoKV Python SDK and required services were not available in
the validation environment, so this candidate has no live NoKV execution
result.

Run the merge-relevant deterministic regression from the repository root with:

```bash
python3 examples/nokv-shadow-provider/probes.py contract
```

It must prove all of the following:

- only an explicitly bootstrapped, runnable todo can be claimed;
- A applies, B advances the head, and a reconstructed authority replays A;
- replay returns A's original authority receipt field for field;
- replay leaves the current revision and aggregate unchanged;
- the same operation identity with a different semantic request is rejected;
- transport-only retry metadata does not change operation identity;
- competing claims on the same todo have one winner;
- concurrent claims on independent todos both succeed after internal CAS
  revalidation and rebase, within the reference's empty-write-scope boundary;
- stale target or named preconditions return a domain conflict;
- bounded unrelated contention fails without creating a receipt or pretending
  that the target todo conflicted;
- pre/post-CAS faults and ambiguous results recover success only from a stored
  receipt or a later successful CAS after target revalidation; same-generation
  receipt absence fails unproved.

The six current result tags are
`contract.bootstrap_and_preconditions`,
`contract.a_success_b_advance_replay_a`, `contract.operation_identity`,
`contract.competing_claims`, `contract.crash_windows_and_ambiguity`, and
`contract.version_domains_and_retain_all`.

The probe has no live-stack mode in this candidate. A future live exercise
would require etcd, an S3-compatible object store, `nokv serve`, and the NoKV
Python SDK, plus separately reviewed restart and recovery assertions. An
earlier run against the superseded last-envelope adapter is not evidence that
the revised receipt contract passes. Do not reuse its latency, restart, or
promotion conclusions for this implementation.

The reference does not establish lease renewal/release, multi-host wake
delivery, automatic provider promotion, HA/failover, receipt compaction or GC,
production performance, a dynamic eligibility-projection publisher, non-empty
write-scope overlap enforcement, or a full LoopX state migration.
