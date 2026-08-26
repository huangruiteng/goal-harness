# Integration Branch Reconcile

Long-running repository work often has two simultaneous truths:

- each feature or fix stays on its own reviewable branch;
- one local integration branch must contain the latest reviewed form of every
  source branch.

`integration-branch-reconcile` makes the second truth machine-readable. It
stores an ordered plan under ignored `.loopx/` state, compares current refs
with the last successful sync receipt, and reconciles the integration branch
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

Remote-tracking refs do not move until Git observes the publisher's update. To
make that observation part of the same typed operation, opt in to a
remote-read-only refresh:

```bash
loopx integration-branch status \
  --repo-path . \
  --refresh-remotes \
  --format json
```

LoopX fetches only the remote-tracking refs named by the configured base or
source refs, plus the integration branch's configured upstream when one
exists, then resolves exact SHAs. It does not prune unrelated refs or replace
existing `FETCH_HEAD` evidence. This observes another worker's published
branch intent; it does not guess unpushed work, read private review text, or
infer that a draft is approved for integration.

## Preview and sync

```bash
loopx integration-branch sync --repo-path . --format json
loopx integration-branch sync \
  --repo-path . \
  --refresh-remotes \
  --execute \
  --format json
```

After the first sync, a source branch that only advances to a descendant is
merged onto the last verified integration head. This preserves earlier merge
and conflict-resolution decisions while incorporating the reviewed update. If
the base, source set, integration head, or source ancestry no longer matches
the receipt, LoopX rebuilds from the resolved base and all source SHAs in
order. Preview removes its temporary worktree without changing refs. Execute
updates the local integration branch only after every merge succeeds, then
writes and rereads the receipt.

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

The supplied commit must contain the configured base, every exact source SHA,
and any observed integration upstream head as ancestors. LoopX does not choose
or generate the resolution; it only verifies the immutable result before the
normal local publication and readback flow.

When the supplied commit is already the integration branch head, execute only
records the verified receipt. It does not reset or otherwise touch the checked
out worktree.

## Periodic or event-driven reconcile

Use the same command for timer-driven and provider-event-driven checks:

```bash
loopx integration-branch sync \
  --repo-path . \
  --refresh-remotes \
  --execute \
  --format json
```

For LoopX-managed work, register that operation as a `continuous_monitor` Todo
with a project-selected cadence and `next_due_at`. A host can wake on that
deadline, run the command, and write back the returned exact-SHA evidence. A Git
provider webhook may invoke the same command after a ref event for lower
latency. Webhook authentication and event delivery belong to the provider
extension, not to this repository-neutral capability.

## Boundary

The capability keeps a deliberately narrow write boundary:

- by default it does not contact remotes; `--refresh-remotes` is read-only
  against the remote repository and updates only configured base, source, and
  integration-upstream remote-tracking refs;
- it never pushes;
- it never changes a source branch;
- it never creates, retargets, approves, or merges a PR;
- it never updates a protected base branch;
- v0 uses ordered merge commits and does not squash or rewrite source history.

Without `--refresh-remotes`, fetch or update source refs through the
repository's normal workflow before running `status` or `sync`. Human review
and aggregate merge authority remain outside this capability.

## Validate

```bash
python3 examples/integration-branch-cli-smoke.py
python3 -m pytest -q tests/capabilities/test_integration_branch.py
```

The public CLI smoke and focused pytest cover ignored plan state, read-only
preview, ordered source updates, reviewed-candidate adoption, and local-only
fail-closed dirty/conflict cases. They do not fetch, push, rewrite source
branches, or change protected bases.
