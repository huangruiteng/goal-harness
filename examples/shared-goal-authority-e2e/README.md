# Shared-goal-authority E2E stage ladder

One incremental end-to-end ladder for
[RFC: LoopX shared control-plane authority and pluggable state providers v0](../../docs/architecture/rfcs/shared-goal-authority-state-provider-v0.md).
Every completed RFC stage claim is one row; every row drives the product
through the real `python -m loopx.cli` (`real_cli`) or runs a retained
store-level probe (`store_direct`). The ladder adds no product path, reads the
candidate only through the production TypeScript `FileAuthorityStore`, and
never reports green while a selected row is unverified.

```bash
python examples/shared-goal-authority-e2e/ladder.py            # exit 1 here: live rows unverified, parity rows pending
python examples/shared-goal-authority-e2e/ladder.py --allow-unverified --allow-pending
python examples/shared-goal-authority-e2e/ladder.py --stage 2c1 --report-json ladder-report.json
python examples/shared-goal-authority-e2e/ladder.py --list
```

The pytest projection is `tests/control_plane/test_shared_goal_authority_e2e.py`;
there, an unverified row skips as `unverified: <reason>` and a POSIX-only row
skips on Windows. Five `s2c1.*` rows whose assertions
`tests/control_plane/test_local_authority_shadow_cli_e2e.py` already pins
through the same product path (configure round trip, default-off isolation,
candidate failure, crash gap, dual runtime root) are skipped in the default CI
projection to stay within the pytest job budget; `LOOPX_LADDER_FULL=1` runs
them in pytest, and the example runner always runs every row.

## Rows

| Row | Stage | Path | Gate | Asserts |
| --- | --- | --- | --- | --- |
| `s0.file_matrix_twelve_rows` | 0 | store_direct | deterministic | `examples/nokv-shadow-provider/live_e2e.py` reports exactly the twelve known file-provider scenario rows, all true |
| `s0.nokv_live_matrix` | 0 | store_direct | env:nokv_legacy | the same twelve rows plus `restored_lineage_fails_closed` are true on a live NoKV stack and file/NoKV outcomes are identical |
| `s1.cli_document_decodes_through_ts_store` | 1 | real_cli | deterministic | three CLI writes (`todo add`, `task-lease acquire`, `todo update`) read back through `FileAuthorityStore`: `loadAuthority` loaded at cursor `3`, paged `scanCommitted` yields the three `observation_id`s in order, `readReceipt` finds the first |
| `s2a.nokv_live_qualification` | 2a | store_direct | env:nokv_authority | runs the merged `examples/nokv-authority-store/live-qualification.ts --execute-live` against an existing workbench with a fresh tenant/goal pair; requires `ok=true`, the single-node store-conformance scope, every check `passed`, NoKV SDK `0.11.0` / API `1`, and no promotion or availability claim; evidence carries check ids, counts, and config and workbench digest prefixes, never a configuration value or the workbench name |
| `s2b.postgresql_conformance_live` | 2b | store_direct | env:postgresql | `postgresql_authority_store.integration.test.ts` under node's TAP reporter: `# pass >= 9`, `# fail 0`, `# skipped 0` |
| `s2c1.configure_enable_disable_roundtrip` | 2c1 | real_cli | deterministic | `configure-goal` preview does not write, enable writes, captured observations for a todo and a lease, read-back summary `enabled/file_one_way`, disable writes and later writes neither observe nor touch candidate bytes |
| `s2c1.every_writer_family_captures` | 2c1 | real_cli | deterministic | handoff-mode set, todo add/update/complete/supersede/capture-followups/archive-completed, task-lease acquire/renew/transfer each carry `outcome in {captured, replayed, ambiguous_reconciled}`, `primary_writeback_preserved=true`, `provider_to_local_writes=false`, `candidate_read_for_decision=false`; an idempotent re-acquire carries no `authority_shadow`; candidate `cursor == captured count`, operation ids equal observation ids, no time-active lease in the head, head todos equal `todo list` |
| `s2c1.default_off_isolation` | 2c1 | real_cli | deterministic | a default-off goal returns the same response fields as an observed goal, carries no `authority_shadow`, and creates no `authority-shadow/` directory |
| `s2c1.candidate_failure_preserves_primary` | 2c1 | real_cli | deterministic | a blocked candidate directory yields `outcome=failed`, `reason_code=shadow_observation_failed`, and the committed todo is in the primary state |
| `s2c1.crash_gap_loses_observation` | 2c1 | real_cli | deterministic (POSIX) | a writer SIGKILLed while the observation lock is held commits its todo but leaves no candidate document; the next write captures the full two-todo snapshot without claiming an outbox or correlation |
| `s2c1.dual_runtime_root_consistency` | 2c1 | real_cli | deterministic | with `common_runtime_root` different from `--runtime-root`, todo add, task-lease acquire, todo update, capture-followups, and a leased completion all observe into one store identity; the head holds both todos and the released lease; the registry root gains neither a candidate lineage nor lease state |
| `s2c1.migration_seeds_new_lineage` | 2c1 | real_cli | deterministic | `migrate-state` dry run plans the seed without writing; execute seeds one fresh `file:` lineage at cursor `1` that carries no legacy identity, revision, source path, or private byte |

Pending rows are declared in the report as `pending`, never counted as pass,
and they block a green exit unless `--allow-pending` is passed. The Stage 2C
parity rows are pending: `s2c2.outbox_prepared_then_committed_entries`, `s2c2.drain_idempotent`,
`s2c2.sigkill_between_primary_write_and_drain`, `s2c2.sigkill_mid_drain`,
`s2c2.rollback_with_pending_entries`, `s2c2.parity_equal`, `s2c2.parity_divergent_detects_foreign_edit`,
`s2c2.migration_seeds_and_drains`, `s2c2.growth_measurement_gate` (until the
Stage 2C parity PRs land).

## Gates and environment variables

| Gate | Requirement | Unverified reason when absent |
| --- | --- | --- |
| `deterministic` | none (needs `node` on `PATH` for the CLI's TypeScript runtime and the read-back probe) | `node_missing` when the probe cannot run |
| `env:postgresql` | `LOOPX_TEST_POSTGRES_URL` plus `node_modules/pg` (`npm ci`) | `postgres_url_missing`, `pg_dependency_missing`, `node_missing` |
| `env:nokv_legacy` | `NOKV_COORDINATION_LIVE=1` and `NOKV_ETCD`, `NOKV_ETCD_PREFIX`, `NOKV_ROOT_ID`, `NOKV_BUCKET`, `NOKV_OBJECT_ENDPOINT`, `NOKV_OBJECT_ROOT`, `NOKV_OBJECT_KEY`, `NOKV_OBJECT_SECRET`; the `nokv` SDK importable | `nokv_live_env_missing`, `nokv_coordination_live_not_enabled`, `nokv_sdk_missing` |
| `env:nokv_authority` | `LOOPX_NOKV_AUTHORITY_LIVE=1` (the probe writes durable test data), `LOOPX_NOKV_AUTHORITY_CONFIG_JSON` (absolute path to the ignored NoKV client configuration), `LOOPX_NOKV_AUTHORITY_PYTHON` (absolute path to the Python executable that resolves NoKV SDK 0.11.0), `LOOPX_NOKV_AUTHORITY_WORKBENCH` (an existing workbench); `node` on `PATH` | `nokv_authority_env_missing`, `loopx_nokv_authority_live_not_enabled`, `nokv_authority_config_missing`, `nokv_authority_python_missing`, `node_missing` |

POSIX-only rows report `unverified/posix_only` on Windows.

## Report and exit policy

The report schema is `loopx_shared_goal_authority_e2e_report_v0`:
`rows[]` (`status in {pass, fail, unverified}`, `reason_code`, public-safe
`evidence`, `duration_ms`), `pending[]`, `summary{pass, fail, unverified,
pending, executed, privacy_violations}`, `bindings{loopx_commit, loopx_tree_dirty, probe_sha256[],
nokv_client_config_sha256, nokv_sdk_version, postgres_url_sha256_prefix,
pg_package_version}` (`null` when unknown), and `exit_policy`.

Exit code is `0` iff `fail == 0` and `privacy_violations == 0` and
(`unverified == 0` or `--allow-unverified`) and (`pending == 0` or
`--allow-pending`): a selected
row that never executed, whether gated or declared pending, is an unmet
obligation, so `--row s2c2.parity_equal` exits 1 with zero executions, and a
mixed selection exits 1 even when its executable rows pass. `--list` only
prints the registry and never claims verification. A privacy scan runs over
the finished report: any occurrence of a temporary root, the home directory,
the repository path, the PostgreSQL URL, a NoKV configuration value, or a NoKV
authority input path rewrites that row to `fail/privacy_violation`; a leak
confined to the `bindings` block nulls every binding, marks
`bindings.privacy_violation`, and still exits `1` through
`summary.privacy_violations`, which no flag relaxes. Evidence therefore
carries counters, cursors, outcome tokens, and sha256 prefixes only.

## Test seams later PRs must provide

The pending `s2c2.*` rows will be implemented against these seams; a Stage 2C
parity PR that does not expose them cannot be ladder-verified:

- a drain lock file at `<runtime>/authority-shadow/outbox/<goal>/drain` so the
  ladder can hold the drain window with `loopx.file_lock.exclusive_file_lock`
  exactly as it holds `<runtime>/authority-shadow/file/<goal>/observation`
  today, then SIGKILL a writer before or during drain;
- one file per outbox entry under `<runtime>/authority-shadow/outbox/<goal>/`
  with a prepared-then-committed marker, so pending entries are countable and
  a rollback with pending entries is observable from disk;
- `drain` and `verify` product commands that emit JSON with `drained_count`,
  `cursor_before`, `cursor_after`, `parity_verdict`, and the source and
  candidate digests, so parity-equal and foreign-edit rows can assert on
  typed fields rather than prose;
- the same commands must resolve the runtime root the way `todo` and
  `task-lease` do (`effective_runtime_root`), so the one-lineage guarantee that
  `s2c1.dual_runtime_root_consistency` proves for the observation hooks also
  holds for drain and verify.
