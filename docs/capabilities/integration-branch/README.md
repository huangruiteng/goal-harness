# Integration Branch Reconcile

Long-running repository work often has two simultaneous truths:

- each feature or fix stays on its own reviewable branch;
- one local integration branch must contain the latest reviewed form of every
  source branch.

`integration-branch-reconcile` makes the second truth machine-readable. It
stores an ordered plan under ignored `.loopx/` state, compares current refs
with the last successful sync receipt, and rebuilds the integration branch
through a temporary detached worktree.

## Configure

```bash
loopx integration-branch configure \
  --repo-path . \
  --base-ref origin/main \
  --integration-branch codex/local-integration \
  --source-branch codex/feature-a \
  --source-branch codex/fix-b \
  --execute \
  --format json
```

Source order is significant. `configure` validates all refs but writes only
`.loopx/integration-branch.json`. A different existing plan requires explicit
`--replace`, which also clears its old sync receipt.

An alternate `--plan-file` must still resolve below the repository's `.loopx/`
state root. Paths outside that root, traversal, and symlink escapes fail closed.
The selected path must also be untracked and covered by the repository's ignore
rules so the reported local ignored-state boundary remains true.

## Detect review drift

```bash
loopx integration-branch status --repo-path . --format json
```

The first status is `drifted` with `never_synced`. After a successful sync,
LoopX records the exact base, source, and integration SHAs. A later rebase,
review fix, or additional source commit becomes `base_ref_moved`,
`source_ref_moved`, or `integration_head_changed`.

## Preview and sync

```bash
loopx integration-branch sync --repo-path . --format json
loopx integration-branch sync --repo-path . --execute --format json
```

Both paths build the candidate by merging the resolved source SHAs in order
from the resolved base SHA. Preview removes its temporary worktree without
changing refs. Execute updates the local integration branch only after every
merge succeeds, then writes and rereads the receipt.

Rebuilding merge commits can change `candidate_sha` timestamps between preview
and execute. Compare `candidate_tree_sha` for stable content identity; execute
also records it in the receipt.

Preview remains read-only even when the integration branch worktree is dirty.
Execute requires a clean checked-out integration worktree. A dirty worktree,
merge conflict, missing ref, or concurrent plan/input/integration movement
fails closed before candidate publication.

When ordered source heads require an intentional manual conflict resolution,
build and validate that commit outside LoopX, then let LoopX verify and adopt
it through the same receipt boundary:

```bash
loopx integration-branch sync \
  --repo-path . \
  --candidate-ref <resolved-commit> \
  --format json
loopx integration-branch sync \
  --repo-path . \
  --candidate-ref <resolved-commit> \
  --execute \
  --format json
```

The supplied commit must contain the configured base and every exact source
SHA as ancestors. LoopX does not choose or generate the resolution; it only
verifies the immutable result before the normal local publication and
readback flow.

When the supplied commit is already the integration branch head, execute only
records the verified receipt. It does not reset or otherwise touch the checked
out worktree.

## Boundary

The capability is deliberately local:

- it never fetches or pushes;
- it never changes a source branch;
- it never creates, retargets, approves, or merges a PR;
- it never updates a protected base branch;
- v0 uses ordered merge commits and does not squash or rewrite source history.

Fetch or update source refs through the repository's normal workflow before
running `status` or `sync`. Human review and aggregate merge authority remain
outside this capability.
