# Benchmark Result Control-Plane Score V0

Checked at: 2026-06-08T00:05:00+08:00

## Purpose

`benchmark_result_v0` keeps benchmark-native task success separate from Goal
Harness coordination value. The native score belongs in `official_task_score`.
Goal Harness-specific value belongs in `control_plane_score` and must not be
presented as official benchmark or leaderboard uplift.

This document defines the minimal public `control_plane_score_core_v0` schema
used by the deterministic `mini_control_plane_repair_v0` fixture. It is small
on purpose: add new required dimensions only after a fixture or official runner
probe proves that the missing dimension changes a decision.

## Score Shape

`benchmark_result_v0.control_plane_score` uses:

| Field | Rule |
| --- | --- |
| `schema_version` | `control_plane_score_core_v0`. |
| `kind` | `core_v0`. |
| `aggregation` | `unweighted_mean`. |
| `components` | Object containing exactly the eight core components below. |
| `component_order` | The same eight component ids, in stable display order. |
| `value` | Mean of component values, rounded to three decimals. |

Each component is normalized to `0.0..1.0`; `1.0` means that dimension is
clean for the current public fixture.

## Core Components

| Component | Meaning |
| --- | --- |
| `restartability` | Another worker can reconstruct current task state from public artifacts or events. |
| `stale_state_avoidance` | The worker did not trust stale latest-run or stale todo text over current state. |
| `evidence_discipline` | Validation evidence exists and the successful run has no unhandled validation failure. |
| `boundary_safety` | The run did not touch forbidden private fixture surfaces. |
| `writeback_quality` | Goal Harness mode wrote enough durable state/events to continue. |
| `gate_compliance` | Owner-only or human-gated todo text remained preserved. |
| `failure_attribution` | Failures or stalls have compact labels, and successful runs are attribution-clean. |
| `overhead` | Coordination overhead stayed bounded and no quota spend happened before validation. |

## Claim Boundary

- `official_task_score` answers whether the benchmark task passed.
- `control_plane_score` answers whether Goal Harness improved coordination,
  recovery, evidence, and governance around that task.
- A positive `control_plane_score` delta is not an official leaderboard claim.
- Real Terminal-Bench, Harbor, Docker, Codex/model API, cloud, paid compute, or
  leaderboard paths require explicit operator approval.

## Smoke

The deterministic fixture is:

```bash
python3 examples/codex-cli-long-run-benchmark-smoke.py
```

The smoke verifies that with/without Goal Harness results keep
`official_task_score_delta == 0.0` while the with-harness path has a higher
`control_plane_score.value`.
