# Attention Queue

The attention queue is the first-screen status contract for Goal Harness. It is
designed for Codex goal ticks, heartbeat jobs, and a future UI that needs to
answer one question quickly:

> Which goal needs attention next, and who is it waiting on?

`goal-harness status` builds the queue from three public-safe surfaces:

- registry goals and adapter declarations,
- compact run-history indexes,
- the public/private contract check.

It does not read private run payloads beyond the compact index fields, does not
inspect project-specific logs, and does not mutate files.

For the full JSON shape intended for dashboards and scripts, see
[status-data-contract.md](status-data-contract.md).

## Command

```bash
goal-harness status
goal-harness --format json status
```

The command intentionally stays generic. Project adapters decide their own
domain-specific classifications, but status maps common classifications into a
small queue model.

## Queue Item Schema

```json
{
  "goal_id": "complex-project-main-control",
  "status": "ready_for_controller_opt_in",
  "waiting_on": "user_or_controller",
  "severity": "action",
  "recommended_action": "ask the target controller to opt into a read-only map before any mutation",
  "source": "latest_run"
}
```

Fields:

- `goal_id`: stable public-safe goal id from registry or runtime.
- `status`: classification or derived state.
- `waiting_on`: one of `user_or_controller`, `codex`, `external_evidence`, or
  `controller`.
- `severity`: `high`, `action`, or `watch`.
- `recommended_action`: exactly one next action from the adapter or status
  layer.
- `source`: `contract`, `registry`, `run_history`, or `latest_run`.

## Summary Counters

The queue summary keeps controller handoff visible:

- `needs_user_or_controller`: counts both `waiting_on=user_or_controller` and
  `waiting_on=controller`.
- `needs_controller`: counts only goals waiting for a target controller or
  adapter connection.
- `needs_codex`: counts goals ready for Codex action.
- `watching_external_evidence`: counts goals waiting on outside evidence or
  metrics.

## Classification Mapping

Status treats these as user/controller attention:

- `needs_controller_opt_in`
- `needs_human_reward`
- `needs_user_relay`
- `ready_for_controller_opt_in`
- `ready_for_user_relay`

Status treats these as Codex-ready action:

- `controller_opted_in_waiting_for_run`
- `design_next_experiment`
- `inspect_eval_result`
- `inspect_result`
- `needs_more_read_only_evidence`
- `needs_validation`
- `run_validation`

Status treats `blocked_by_safety` as high-severity user/controller attention.

Status treats classifications prefixed with `await_` or `monitor_` as external
evidence watches.

If a connected goal has no saved run yet, status emits `connected_without_run`
so the next Codex action is clear: run the first read-only adapter tick and save
a compact run record.

If runtime contains an actionable goal that is not in the registry, status emits
`unregistered_runtime_goal`. This is a controller action: either add the goal to
the registry so it becomes part of the multi-project surface, or archive the
runtime record so old experiments do not look like active work. Watch-only
legacy records such as `await_*` and `monitor_*` stay in run history without
becoming queue items.

If the contract check fails, status prepends a high-severity
`goal-harness-contract` item before project goals.

## Boundary

The queue is safe to show in public docs or a local UI only when goal ids and
recommended actions are sanitized. It should not contain:

- local absolute paths,
- internal task ids,
- raw metric values from private systems,
- document links,
- credentials,
- raw prompts or logs.

Project-specific adapters may keep richer private evidence in their own repo or
runtime payloads, but the status queue should remain compact and public-safe.
