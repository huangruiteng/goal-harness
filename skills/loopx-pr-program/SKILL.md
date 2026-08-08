---
name: loopx-pr-program
description: "Use when LoopX must manage a multi-PR or multi-MR delivery program across one or more repositories: inventory current change requests, reconcile new/merged/closed or retargeted work, preserve requirement and dependency priorities, maintain a roadmap document, or monitor material lifecycle/check/review changes over time. Use provider-neutral snapshots and one grouped continuous monitor; do not use for deep per-PR code review, approval, commenting, or merge actions."
---

# LoopX PR Program

Manage a delivery program as durable LoopX state instead of rebuilding a queue
from chat memory. Keep source acquisition provider-local, normalize observations
into one public contract, and write back only material transitions.

## Route The Request

Use this workflow when the user asks to manage, prioritize, reconcile, document,
or monitor several pull requests or merge requests. Route a deep review of each
selected PR to `loopx-pr-review`. Route approval, comments, reruns, branch
retargeting, closing, or merging to the normal provider-specific workflow and
require the corresponding authority.

Treat document maintenance and monitor creation as writes. A request to update
the roadmap or keep monitoring the program authorizes those scoped writes; an
ordinary status question remains read-only.

## Start From LoopX State

Start or join the project goal before material work. Represent the program with
one advancement todo for the current reconciliation and one
`continuous_monitor` todo for recurring observation. Do not create one monitor
todo per change request.

Use a stable monitor identity:

```text
task_class=continuous_monitor
action_kind=pr_program_reconcile
target_key=pr-program-<stable-program-id>
cadence=<user cadence or 30m>
```

Preserve `claimed_by`, `last_checked_at`, `next_due_at`, `result_hash`,
`consecutive_no_change`, and `material_change`. Quiet monitor polls keep
liveness but do not count as delivery progress, rewrite roadmap documents, or
spend progress quota.

## Acquire A Complete Snapshot

Use any authorized source-control read interface available in the current
environment. Prefer one batch query for inventory and targeted reads for the
items that changed. Never encode a private transport command, executable name,
credential, internal hostname, or document token in this skill, repository
examples, committed fixtures, or public evidence.

Normalize observations using
[`references/snapshot-contract.md`](references/snapshot-contract.md). Mark
`result_completeness.complete=true` only after proving the requested repository,
author, state, and time-window inventory is exhaustive. An incomplete current
snapshot must not make absent rows look closed or removed.
Persist the structured scope fingerprint with the baseline. Do not advance the
durable baseline or grouped-monitor `result_hash` from an incomplete snapshot
or when the previous and current scope fingerprints differ; otherwise a partial
page or narrowed query can create false remove/re-add transitions on the next
poll.

Store raw and normalized snapshots under an ignored owner-local directory such
as `.local/loopx/pr-program/<program-id>/`. Verify the path with
`git check-ignore` before writing. If no ignored path is available, use a
temporary directory and keep only a redacted evidence summary in LoopX state.

## Reconcile Material Changes

Run the bundled delta helper before manually comparing rows:

```bash
python skills/loopx-pr-program/scripts/diff_snapshot.py \
  --previous <previous.json> \
  --current <current.json> \
  --output <delta.json>
```

Omit `--previous` for the first baseline. The helper treats lifecycle, draft,
target branch, head revision, checks, review, work item, requirement, theme,
priority, and dependency changes as material. Timestamp-only movement is
observation noise. Read the actual description, latest review context, checks,
and changed-file evidence for every added or materially changed row before
updating the program judgment.

Do not infer motivation or priority from title, number, author, age, or green CI
alone. Product requirements set priority. Correctness dependencies and real
merge gates determine order within a priority. Record a requirement gap
explicitly when no change request implements part of the requested behavior;
do not call the requirement complete because a neighboring parameter or feature
landed.

## Compose With An Integration Branch

When several selected change requests belong to one repository, compose this
program view with LoopX's `integration-branch-reconcile` capability. Keep the
ownership split explicit:

- this skill decides which changes belong in the candidate and why;
- the integration-branch plan records their ordered local source refs and
  proves what exact code is composed.

Do not populate the plan from every open or P0 change request automatically.
Select sources from explicit program scope, dependency order, and current
review intent. Refresh the local refs through the authorized host workflow,
then verify that each selected ref resolves to the observed `head_sha` before
configuring or syncing the integration branch. A mismatch is source evidence
drift, not permission to merge a stale local ref.

Use the same grouped program monitor to read both the normalized change-request
delta and `loopx integration-branch status --format json`. Treat base/source
movement, an unexpected integration head, and merge conflict as material
program evidence. A monitor poll remains read-only: it may report that the
candidate needs reconciliation, but it must not run `sync --execute` by itself.
That command is a separate, explicit local write and never grants authority to
push, retarget, approve, or merge a remote change request.

## Project The Program

Keep one canonical program projection with three sections:

1. completed work, grouped by product theme;
2. pending work, grouped by product theme, with archived or superseded
   development stacks nested under the surviving change request;
3. merge priority, ordered first by explicit product priority, then dependency,
   correctness risk, and current merge gate.

Keep links at the end of each compact row. Preserve the target document's
existing heading, color, callout, and strike-through conventions. Update only
the affected blocks, refetch them after writing, and verify that unrelated
content and resource blocks remain unchanged.

For every priority row, distinguish these facts:

- shipped behavior and requirement coverage;
- dependency or recommended merge order;
- current checks, review, and external work-item gates;
- missing implementation or validation that no existing change request covers.

## Write Back And Continue

After a validated material change:

1. update the grouped monitor `result_hash` and reset
   `consecutive_no_change=0`;
2. update the roadmap and refetch the changed sections;
3. complete the reconciliation todo with compact evidence and create a
   successor only when concrete follow-up remains;
4. refresh LoopX state with the actual delivery classification and outcome;
5. spend quota only after the state and document writeback are validated.

After a quiet poll, update monitor scheduling metadata and increment
`consecutive_no_change`; do not produce a synthetic progress event.

## Public And Private Boundary

Commit only the provider-neutral contract, algorithm, and redacted fixtures.
Keep private provider adapters, source commands, raw comments, internal URLs,
document ids, snapshots, and organization-specific prioritization outside the
public repository. Before staging changes to this skill or its resources, scan
the exact paths for private hostnames, executable names, credentials, local
absolute paths, and raw operating context.
