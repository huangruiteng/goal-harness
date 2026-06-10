# Terminal-Bench Codex Goal Harness Fake Worker V0

Checked at: 2026-06-08T21:05:00+08:00.

This note records the first executable fixture mode for the true
`codex_goal_harness` treatment arm:

```bash
goal-harness benchmark run terminal-bench --mode codex-goal-harness --fake-worker
```

The mode remains no-run/no-submit. It does not run Harbor, Terminal-Bench,
Docker, real Codex workers, model APIs, uploads, shares, or leaderboard paths.
Its purpose is to prove that a future worker event can carry the Goal Harness
access packet plus compact, nonzero Goal Harness interaction counters.

## Mode Boundary

`codex-goal-harness` is separate from both:

- `codex_goal_mode`, where Codex may call runtime goal tools such as
  `create_goal` or `update_goal`;
- legacy `goal-harness-managed-codex`, which is kept as a compatibility label
  for earlier managed fixtures and sample results.

The fake-worker event reports:

```text
mode=codex_goal_harness_fake_worker_wrapper
worker_mode=codex_goal_harness_cli
goal_harness_inside_case=true
case_semantics_changed_by_harness=true
official_score_comparable_to_native_codex=false
model_plus_harness_pair=true
real_run=false
submit_eligible=false
```

## Interaction Counters

The fake-worker event carries the access packet and declares a compact observed
interaction pattern:

```text
codex_runtime_goal_tool_calls.total=0
goal_harness_cli_calls.status=1
goal_harness_cli_calls.quota_should_run=1
goal_harness_cli_calls.todo_list=1
goal_harness_cli_calls.history=1
goal_harness_cli_calls.check=1
goal_harness_cli_calls.append_benchmark_run=1
goal_harness_cli_calls.total=6
goal_harness_state_reads=4
goal_harness_state_writes=1
case_result_writeback=worker_goal_harness_writeback
counter_trust_level=fake_worker_fixture_observed
```

These are fixture counters, not official benchmark usage metrics. They make the
next fake-worker-to-real-run transition auditable: a future real worker must
derive these counters from runner-visible calls or trace-audited public-safe
metadata.

## Why This Slice Matters

The previous access packet fixture proved that the worker can receive Goal
Harness instructions. This slice proves the runner can represent actual Goal
Harness interface use as first-class benchmark metadata. That gives the
experiment three clean arms:

- native Codex CLI;
- Codex runtime goal mode;
- Codex plus Goal Harness, counted as a model-plus-harness pair.

## Stop Conditions

Stop before:

- treating fixture counters as real benchmark evidence;
- using `create_goal` / `update_goal` as Goal Harness CLI calls;
- claiming official task success, cost reduction, leaderboard readiness, or
  benchmark uplift from this fixture;
- recording raw prompts, raw sessions, credentials, local paths, runner logs,
  Docker logs, or private task artifacts in public notes.

## Smoke

```bash
python3 examples/terminal-bench-codex-goal-harness-fake-worker-smoke.py
```

The smoke runs the fixture CLI in a temporary Goal Harness registry, appends the
compact `benchmark_run_v0` event, validates status reconstruction, and confirms
that interaction counters survive compaction.
