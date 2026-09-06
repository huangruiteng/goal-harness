# Bounded file outbox correctness

An active shadow captures each mutation of its bound primary once. A cursor is a
position hint: only the actual file provider's committed transaction and receipt
can authorize deletion of an outbox file. Qualification folds the complete
baseline and transaction history, then compares the current Todo, handoff mode,
and lease state. Equal final snapshots alone are insufficient.

This is a pre-promotion `file_outbox_v1` contract. Native canonical Todo keeps its
existing contract. Older file-v0 mirror or mixed histories remain unchanged,
read-only, and ineligible for this qualification; there is no automatic migration.
The separate observation handler remains available within its original scope.

## Operator lifecycle

Enable the existing per-goal `coordination.runtime_shadow` configuration with
`enabled: true` and `provider: file_v0`. Select the intended common runtime root
and state file in the registry before bootstrap. The new history binds that
source; conflicting `--runtime-root`, `--project`, or `--state-file` overrides
cannot establish a second authority for it. Default-off primary writes and the
independent observation path retain their own override behavior.

Use the same registry and Goal throughout:

```bash
loopx --registry registry.json --format json coordination-shadow bootstrap --goal-id goal-a
loopx --registry registry.json --format json coordination-shadow bootstrap --goal-id goal-a --execute
loopx --registry registry.json --format json authority-shadow status --goal-id goal-a
loopx --registry registry.json --format json authority-shadow drain --goal-id goal-a
loopx --registry registry.json --format json coordination-shadow inspect --goal-id goal-a
loopx --registry registry.json --format json coordination-shadow qualify --goal-id goal-a
loopx --registry registry.json --format json coordination-shadow read-candidate --goal-id goal-a --todo-id TODO_ID
```

Bootstrap imports the complete current Todo/handoff and lease baseline. It does
not count as a mutation. Qualification requires three actual primary mutations
by default; replay and proven abandonment also do not count. `read-candidate`
uses that default policy and repeats the same validator, returning from its
verified head rather than trusting a previous successful qualification.

Turning off the configuration does not cancel an already active capture
obligation. Todo/handoff/followup writers and native lease writers must still
prepare before changing their bound primary. A failed durable prepare holds
that mutation. A failure after primary replacement retains recovery evidence;
it cannot truthfully report that the primary was unchanged. No-change, preview,
idempotent retry, and prose-only changes produce no mutation receipt. Event-only
Todo sources retain `event_log_writer_not_bound` and prevent qualification.

To retire the candidate, obtain the exact current `provider_revision` from
inspection and preview the target before execution. If an invalid cursor or
outbox manifest blocks inspection, use `authority-shadow status` and its
read-only provider proof. If the provider itself cannot be proved, preserve the
scene and hold; do not guess a revision.

```bash
loopx --registry registry.json --format json coordination-shadow rollback --goal-id goal-a --provider-revision EXACT_REVISION
loopx --registry registry.json --format json coordination-shadow rollback --goal-id goal-a --provider-revision EXACT_REVISION --execute
```

To terminate a bootstrap interrupted before active publication, use its exact
operation identity from the management result/journal:

```bash
loopx --registry registry.json --format json coordination-shadow rollback --goal-id goal-a --bootstrap-operation-id EXACT_BOOTSTRAP_OPERATION --execute
```

The selectors are mutually exclusive. Neither is an unconditional cleanup.
Rollback preserves the candidate and the complete Goal outbox, including pending
entries, markers, and malformed cursor bytes. It publishes `inactive` only after
the archive matches the immutable manifest. The shared store identity and other
Goals are unchanged. Primary writes then resume; capture reports
`bootstrap_required`. A new bootstrap imports that current state and starts a
new capture lineage, even if its data equals the old baseline.

## Recovery and holds

Management uses `bootstrapping / active / rolling_back / inactive`. The stable
management directory is under `authority-transition/file-v0/`, outside the
outbox being archived. Its immutable manifest and intent bind the operation,
request, source, provider revision, and file hashes. Retrying the same operation
reconciles actual source/archive existence and hashes; a phase string alone
cannot prove completion. Conflicts hold without overwriting or deleting either
copy. A delayed exact old request only returns its historical result. Reusing
its operation ID with different request contents returns an identity mismatch.

During an unfinished management operation, canonical and whole-state prose
writes return a maintenance hold before their first side effect. Management lock
order is M → T → S → L → K. Native lease writers check under their existing K;
ordinary writers release primary locks before drain. Legacy fence engagement
also takes the actual source S and therefore requires its absolute state path
in the internal RPC request.

Canonical FileAuthorityStore Todo updates, including compatibility v0 records
already held by that authority, use the same M and maintenance boundary as
canonical Todo creation. They retain their own transaction receipts and do not
produce legacy shadow captures. A waiting update rechecks management state after
acquiring M; invalid or unfinished management state holds before any commit.

Drain checks the real receipt first, persists the cursor second, and reclaims
each individually verified file last. Missing cursors can be reconstructed from
complete continuous history; malformed or unreadable cursors are never silently
replaced. Unknown files, mismatched bytes, wrong identities, or incomplete proof
preserve the scene. An interrupted primary without a marker is either proven
under the source lock or left `unproved`; an A → B → A history cannot establish
that the first write was abandoned. TS repeats source proof under its own locks
after Python releases its locks to call the native commit operation.

For unresolved evidence, retain the directory for inspection and use exact
rollback when abandoning the candidate. Do not delete the cursor to bypass a
failed history check, copy an old entry into a new lineage, or reseed implicitly.

Qualification explicitly reports bounded scope and
`sustained_parity_verdict=not_evaluated`. The current proof boundary is 10,000
transactions including the baseline; new commits hold at that boundary while
exact receipt replays remain valid. This is a bounded correctness limit, not a
performance result. Drain budgets bound work between operations; they do not
preempt an in-flight filesystem or RPC call.

## Required validation

Install the repository test extra and Node dependencies. Run the long tests
separately without skip or relaxation flags:

```bash
python -m pip install -e '.[test]' 'build==1.6.0'
npm ci --ignore-scripts
python -m pytest -q -m stage2c_e2e --junitxml=stage2c-e2e.xml
python examples/shared-goal-authority-e2e/mutants.py --output .local/stage2c-mutants
python -m build
python examples/shared-goal-authority-e2e/installed.py --artifact dist/*.whl --report-json .local/installed-wheel.json
python examples/shared-goal-authority-e2e/installed.py --artifact dist/*.tar.gz --report-json .local/installed-sdist.json
python -m pytest -q -n 2
npm run test:control-plane
npm run typecheck:control-plane
python -m mypy
python -m ruff check tests loopx/canary loopx/control_plane loopx/domain_packs loopx/presentation
python scripts/generate_coordination_state_contract.py --check
python examples/control_plane/cli-output-budget-regression-smoke.py
loopx --format json canary premerge --from-git-diff
```

The Linux/Python 3.11 CI job uses the exact dependency versions and hashes in
`tests/requirements-stage2c-linux-py311.txt`, including pytest 9.1.1. It builds
the checked-out source wheel, verifies its hash during installation, and removes
its generated build tree before normal pytest discovery. The workflow records
the complete installation sequence and retains normal source discovery.

The full TS suite's PostgreSQL conformance requires `LOOPX_TEST_POSTGRES_URL`
pointing to a disposable test database. Source smoke success does not replace
installed-package evidence: the package runner creates an empty environment,
clears source-path injection, runs outside the checkout, verifies installed
Python/TS/JSON provenance, and reads back through an independent native process.

| Obligation | Retained oracle |
| --- | --- |
| Full baseline, mixed Python/native writers, handoff, followups, monitor successor, one receipt per mutation | `test_runtime_shadow_bounded_e2e.py`, `test_shadow_drain_e2e.py` |
| Cursor attacks, complete proof before bounded cleanup, missing cursor writer-first, dual drainers | `test_shadow_cursor_safety.py`, `test_shadow_drain_adversarial.py`, `shadow_cursor_safety.test.ts` |
| Primary and drain process death, lost ACK, prepared-only A → B → A | `test_shadow_drain_e2e.py`, `test_shadow_management_e2e.py` |
| Every bootstrap/rollback durable window, raw archive fidelity, late requests and other-Goal isolation | `shadow_management.test.ts`, `test_shadow_management_e2e.py` |
| Fence and maintenance boundaries, source override races, whole-file durability, paragraph injection, refresh CAS | `test_shadow_writer_boundaries.py`, `shadow_native_writer_boundary.test.ts`, `test_shadow_drain_adversarial.py` |
| Canonical native/v0 Todo updates through CLI and native RPC, real pending management, M ordering, and unchanged authority on hold | `test_shadow_native_todo_update_e2e.py` |
| History flaws despite equal snapshots, legacy mixed profile, source drift, event-only hold, qualified reads | `coordination_runtime_shadow.test.ts`, `file_outbox_qualification.test.ts`, `test_runtime_shadow_bounded_e2e.py` |
| Installed lifecycle and resource provenance in wheel and sdist | `installed.py` |
| Missing checks, lock placement, duplicate mirror, early marker, cursor regression | `mutants.py` with unchanged GREEN controls and assertion RED results |

The mandatory repair set must have zero failures, skips, pending, or unverified
cases. Broader ladder rows retain their declared pending/environment gates;
these tests grant neither production promotion nor a completed Stage 2C claim.
