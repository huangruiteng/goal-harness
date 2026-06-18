# Benchmark Case Analysis Ledger-Only Migration Audit 2026-06-18

Source boundary: compact `benchmark-run-ledger.json` and
`benchmark-case-analysis.json` only. This audit does not read or copy raw task
text, raw logs, trajectories, verifier output, credentials, uploads, or local
private artifact paths.

Purpose: close the "ledger-only" ambiguity before claiming benchmark case
analysis migration complete. Each row below is explicitly classified as either
ready to promote into `benchmark-case-analysis.json`, useful only as a compact
coverage row, or not worth promoting until a counterpart/probe exists.

## Summary

- Ledger cases checked: 41.
- Existing case-analysis cases: 24.
- Ledger-only cases classified here: 17.
- Promotion-ready case-analysis rows: 7.
- Coverage-only or defer rows: 10.

## Classification Table

| Benchmark | Case | Compact ledger shape | Migration classification | Recommended handling |
| --- | --- | --- | --- | --- |
| `skillsbench@1.1` | `fix-build-agentops` | 2 runs; no official score; baseline/setup repair required | `setup_or_runner_gap_defer` | Keep out of main case-analysis until setup score materializes or a compact setup-blocker row is needed. |
| `skillsbench@1.1` | `suricata-custom-exfil` | paired baseline/treatment both `1.0`; latest decision baseline-solved preserved | `promotion_ready_baseline_solved_non_regression` | Promote as a baseline-solved non-regression asset if SkillsBench coverage rows are expanded. |
| `skillsbench@1.1` | `tictoc-unnecessary-abort-detection` | 1 run; no official score; setup repair required | `setup_or_runner_gap_defer` | Keep out until the baseline reaches solver/scoring or a setup-blocker row is intentionally added. |
| `terminal-bench-worker-materialization@v0` | `nginx-request-logging` | worker-materialization probe only; no solver score | `probe_coverage_only` | Keep as worker-materialization coverage; do not treat as case-analysis effect evidence. |
| `terminal-bench@2.0` | `build-cython-ext` | baseline-only, latest baseline passed after earlier setup/model failures | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control if single-arm Terminal coverage rows are desired. |
| `terminal-bench@2.0` | `cobol-modernization` | paired baseline/treatment both `1.0`; latest decision baseline-solved preserved | `coverage_row_already_in_terminal_current_protocol` | Already represented in terminal current-protocol coverage; deep row optional. |
| `terminal-bench@2.0` | `compile-compcert` | baseline-only pass | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control if single-arm Terminal coverage rows are desired. |
| `terminal-bench@2.0` | `financial-document-processor` | baseline-only, latest pass after setup failure | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control with setup-repair note if useful. |
| `terminal-bench@2.0` | `fix-code-vulnerability` | baseline-only pass | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control if single-arm Terminal coverage rows are desired. |
| `terminal-bench@2.0` | `git-multibranch` | paired baseline/treatment both `1.0`; latest decision baseline-solved preserved | `coverage_row_already_in_terminal_current_protocol` | Already represented in terminal current-protocol coverage; deep row optional. |
| `terminal-bench@2.0` | `headless-terminal` | paired no uplift; all official scores `0.0`; attribution required | `promotion_ready_no_uplift_or_attribution_asset` | Promote as no-uplift/attribution asset if current no-uplift set is expanded. |
| `terminal-bench@2.0` | `install-windows-3.11` | paired `0.0/0.0`; worker/verifier alignment required | `promotion_ready_alignment_required_asset` | Promote as alignment-required infrastructure asset, not treatment effect evidence. |
| `terminal-bench@2.0` | `large-scale-text-editing` | paired baseline/treatment both `1.0`; latest decision baseline-solved preserved | `coverage_row_already_in_terminal_current_protocol` | Already represented in terminal current-protocol coverage; deep row optional. |
| `terminal-bench@2.0` | `merge-diff-arc-agi-task` | baseline-only pass | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control if single-arm Terminal coverage rows are desired. |
| `terminal-bench@2.0` | `path-tracing` | baseline-only pass plus score-missing run | `promotion_ready_baseline_solved_control_with_setup_noise` | Promote only with compact note that one earlier run had missing score/setup noise. |
| `terminal-bench@2.0` | `regex-log` | paired baseline/treatment both `1.0`; latest decision baseline-solved preserved | `coverage_row_already_in_terminal_current_protocol` | Already represented in terminal current-protocol coverage; deep row optional. |
| `terminal-bench@2.0` | `sqlite-db-truncate` | baseline-only pass | `promotion_ready_baseline_solved_control` | Promote as baseline-solved control if single-arm Terminal coverage rows are desired. |

## Routing Decision

Do not claim the migration is fully promoted into `benchmark-case-analysis.json`
yet. This audit closes the ambiguity by classifying all ledger-only rows, but
the main case-analysis table should stay selective:

- promote the 7 promotion-ready rows only when they teach a reusable routing,
  regression, setup, or non-regression lesson;
- keep the 4 terminal current-protocol coverage rows as generated coverage
  until they need deep notes;
- defer setup/runner gaps until compact score materializes or the setup-blocker
  itself becomes useful evidence.

Next safe benchmark step: either promote one high-value subset from this audit
into the machine case-analysis JSON/MD, or continue the approved ALE / Terminal
/ Skills rotation while keeping this audit as the public-safe migration map.
