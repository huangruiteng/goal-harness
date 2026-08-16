# Terminal-Bench Case-Level Failure Triage 2026-06-18

This note triages the current `terminal-bench@2.0` case-level failure backlog
from the compact benchmark run ledger. It uses only public-safe ledger fields:
case id, arm, compact failure class, latest decision, score delta, and compact
run ids. It does not use raw task text, raw logs, raw trajectories, verifier
output, credentials, uploads, leaderboard submission state, or local artifact
paths.

## Source

- Machine source: `benchmark-run-ledger.json`
- Human source: `benchmark-run-ledger.md`
- Routing todo: `todo_63144b063867`

## Case Triage

| Case | Compact evidence | Current interpretation | Next safe action |
| --- | --- | --- | --- |
| `pytorch-model-recovery` | Latest decision is `paired_no_score_uplift_exception_research_required`; both selected arms are `agent_exception_before_solution_completion`; score delta is `0.0`. | This is a case-exception research item, not a clean treatment rerun candidate. The immediate question is what compact exception attribution can be made without reading raw artifacts. | Keep blocked from repeat runs until a compact exception-attribution hypothesis exists. Prefer a reducer/ledger taxonomy improvement over a new benchmark launch. |
| `headless-terminal` | Ledger now has a latest `paired_no_score_uplift` decision with score delta `0.0`, while older rows include `score_failure_unattributed` and `worker_bridge_connected_official_score_failure`. | This is not a current positive candidate. It is useful as an attribution-contract regression/control: the treatment connected to the bridge but did not change the official outcome. | Do not relaunch as a treatment candidate. Use only if improving attribution cleanup or validating that bridge-connected no-uplift cases are classified distinctly. |
| `make-doom-for-mips` | Latest decision is `paired_result_requires_attribution`; earlier rows are mostly `agent_timeout_before_solution_completion`, with some setup-timeout and unattributed score-failure rows. The current managed run is still `official_verifier_solution_failure`. | This is the strongest remaining case-level candidate because timeout and timeout-tier policy are plausibly control-plane-addressable, but it still needs a compact attribution boundary before another run. | Promote a timeout-tier policy/attribution slice before any rerun: decide whether the next intervention is timeout budget, continuation cadence, or setup-vs-solver separation. |

## Routing Decision

The next benchmark action should not be a blind rerun of all three cases.

1. Prefer `make-doom-for-mips` for a compact timeout-tier policy slice if the
   evidence can separate setup timeout from solver timeout.
2. Keep `pytorch-model-recovery` in research mode until compact exception
   attribution is more specific than generic agent exception.
3. Keep `headless-terminal` as an attribution/no-uplift control, not a launch
   candidate.

This triage keeps the benchmark lane executable while avoiding reward leakage
or raw-material inspection. The next implementation-shaped slice should update
the ledger taxonomy or reducer so these three states are machine-distinct:
`case_exception_research`, `bridge_connected_no_uplift`, and
`timeout_tier_policy_candidate`.
