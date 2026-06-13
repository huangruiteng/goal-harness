# Terminal-Bench Next Candidate Selection 2026-06-14

Checked at: 2026-06-14T04:12:00+08:00.

This packet advances the Terminal-Bench P0 after the
`llm-inference-batching-scheduler` verifier-attribution routing repair. It is a
no-run, no-upload, public-safe candidate selection packet. It does not run
Harbor, Terminal-Bench tasks, Docker task containers, Codex workers, model APIs,
uploads, shares, or leaderboard submission.

## Routing Input

The compact verifier-attribution review for
`llm-inference-batching-scheduler` says:

- `treatment_eligible=false`;
- `repeat_allowed=false`;
- `new_candidate_allowed=true`;
- `requires_verifier_preflight_repair=true`;
- `next_allowed_action=repair_verifier_preflight_or_select_new_material_ready_case`.

Therefore the next benchmark action must not run a treatment or same-task
repeat for `llm-inference-batching-scheduler` until its verifier preflight is
repaired. The safe P0 lane is to select a fresh material-ready hard case, or to
repair verifier preflight before returning to that task.

## Source Boundaries

Selection used only compact control-plane surfaces:

- local task ids from the cached official `terminal-bench@2.0` material;
- paired-run directory names to exclude already attempted tasks;
- existing compact candidate-screen summaries;
- strict no-run preflight summaries for candidate names.

The selection did not read task instructions, hidden tests, solution files, raw
logs, Docker logs, Codex transcripts, trajectories, credentials, environment
values, or local private paths. It did not start task containers or workers.

## Candidate State

The local cache exposes 89 official task ids. Existing paired-run directories
exclude 22 previously attempted task ids or repeats. Prior fresh-candidate
screens were also consumed: their ready candidates have already been attempted
except `security-celery-redis-rce`, which was not material-ready in the latest
screen.

Five unused cached candidates were strict-preflighted with the correct paired
baseline shape:

| Candidate | Codex goal-mode baseline | Goal Harness treatment | Notes |
| --- | --- | --- | --- |
| `compile-compcert` | ready | ready | Original backup-queue task; compile/toolchain-heavy. |
| `install-windows-3.11` | ready | ready | System-state recovery; likely high environment friction. |
| `financial-document-processor` | ready | ready | Multi-step document/data processing candidate. |
| `multi-source-data-merger` | ready | ready | Integration/data-merging candidate. |
| `pytorch-model-recovery` | ready | ready | ML debugging/recovery candidate. |

For all five candidates and both arms, the strict preflight summary reported:

- `task_material_readiness_status=ready`;
- `no_upload_boundary=true`;
- `submit_eligible=false`;
- `auth_values_recorded=false`;
- `raw_paths_recorded=false`;
- no real runner, real Codex worker, model API, upload, or leaderboard action.

## Selection

Select `compile-compcert` as the next Terminal-Bench candidate.

Rationale:

- It is already named in the original Terminal-Bench backup queue.
- It is unused in the current paired-run history.
- It is material-ready under strict no-run preflight for both arms.
- It is likely to stress long-horizon build, dependency, toolchain, and verifier
  reasoning, which is closer to Goal Harness's intended value than easy parsing
  or already-solved calibration tasks.
- It avoids the current `llm-inference-batching-scheduler` verifier-preflight
  blocker without discarding that blocker.

If `compile-compcert` becomes blocked before launch, use this fallback order:

1. `install-windows-3.11`;
2. `pytorch-model-recovery`;
3. `financial-document-processor`;
4. `multi-source-data-merger`;
5. repair the `llm-inference-batching-scheduler` verifier preflight.

## Next Allowed Action

Run exactly one private no-upload paired pilot for
`terminal-bench@2.0` / `compile-compcert`:

1. run the Codex goal-mode baseline, with no Goal Harness access packet or
   worker bridge;
2. run the `codex-goal-harness` treatment with the active worker bridge and
   active-user assisted treatment path;
3. ingest only compact Harbor results after completion or compact blocker;
4. write one compact comparison with official score, failure attribution,
   worker writeback, Goal Harness call counters, claim boundary, no-upload
   boundary, and submit-disabled status.

Use the `benchmark_verifier_attribution_review_v0` routing after the run before
any same-task repeat or treatment claim.

## Stop Conditions

Stop before:

- reading raw task instructions, hidden tests, solution files, trajectories,
  raw logs, Docker logs, or Codex transcripts;
- copying credential values or Codex auth material;
- changing benchmark task files, tests, scoring, prompts, or resources;
- uploading, sharing, submitting, or making leaderboard claims;
- publishing paper-style uplift claims from this single candidate;
- relaunching `llm-inference-batching-scheduler` without verifier preflight
  repair or a new explicit attribution hypothesis.

## Smoke

```bash
python3 examples/terminal-bench-next-candidate-selection-smoke.py
```

