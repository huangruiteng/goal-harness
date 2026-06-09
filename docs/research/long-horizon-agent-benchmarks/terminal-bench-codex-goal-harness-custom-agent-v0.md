# Terminal-Bench Codex Goal Harness Custom Agent V0

Checked at: 2026-06-08T21:12:00+08:00.

This note records the first custom-agent prompt surface for the requested
`codex_goal_harness` treatment arm. The default V0 path is prompt-packet only:
it changes the worker prompt and records counter semantics. The active bridge
follow-up is recorded separately in
`terminal-bench-codex-goal-harness-active-cli-bridge-v0.md`; it adds
`goal_harness_cli_bridge_enabled=true` so the Codex worker receives concrete
Goal Harness CLI command templates. The Harbor import path remains:

```text
goal_harness.terminal_bench_agent:GoalHarnessManagedCodex
```

The new mode is selected through an agent kwarg:

```text
goal_harness_mode=codex_goal_harness
```

This is still no-run/no-submit validation. It does not run Harbor,
Terminal-Bench, Docker, real Codex workers, model APIs, uploads, shares, or
leaderboard paths.

## Prompt Surface

When `goal_harness_mode=codex_goal_harness`, the custom agent injects:

```text
----- GOAL-HARNESS ACCESS PACKET -----
Goal Harness Access Packet V0
mode: codex_goal_harness
goal_harness_interface_surface: prompt_packet_only_no_cli_bridge
goal_harness_cli_bridge_available: false
goal_harness_cli_bridge_contract: terminal_bench_goal_harness_cli_bridge_contract_v0
declared_goal_harness_interface_commands: status, quota_should_run, todo_list, history, check, append_benchmark_run
count_codex_runtime_goal_tools_separately_from_goal_harness_calls: true
do_not_claim_goal_harness_cli_calls_without_bridge_or_trace: true
report_interaction_counters_after_the_case: true
----- END GOAL-HARNESS ACCESS PACKET -----
```

The raw prompt is not recorded in public artifacts. The adapter records only
compact booleans, schema ids, prompt length, and task hash metadata.

## Counter Extraction

The custom agent now exposes
`extract_goal_harness_interaction_counters_from_trace()`. It accepts compact
public trace rows such as:

```text
goal_harness_cli_call/status
goal_harness_cli_call/quota_should_run
goal_harness_state_read
goal_harness_state_write
case_result_writeback/worker_goal_harness_writeback
```

It produces `terminal_bench_goal_harness_interaction_counters_v0` while keeping
Codex runtime goal tools separate from Goal Harness CLI calls:

```text
codex_runtime_goal_tool_calls.total
goal_harness_cli_calls.total
goal_harness_state_reads
goal_harness_state_writes
case_result_writeback
counter_trust_level=compact_trace_audited
raw_trace_recorded=false
raw_task_prompt_recorded=false
```

If no compact trace is available, the adapter records
`counter_trust_level=runtime_metadata_prompt_only_no_cli_bridge` for
`codex_goal_harness` prompt-only runs instead of inventing calls.

## Harbor Command Shape

The command preview for `codex-goal-harness` includes:

```text
--agent-kwarg goal_harness_mode=codex_goal_harness
--agent-kwarg goal_harness_goal_id=<goal-id>
```

This gives the real Harbor custom-agent path the same treatment-arm identity as
the no-run fake-worker fixture, without making official-score or uplift claims.

## Claim Boundary

This slice may claim:

```text
The Harbor custom-agent prompt can carry a prompt-only Goal Harness access packet
and compact interaction-counter extraction contract for codex_goal_harness mode.
```

It must not claim:

- a real benchmark task ran;
- a real worker used Goal Harness interfaces;
- a Goal Harness CLI bridge was available unless
  `goal_harness_cli_bridge_enabled=true` and worker-side compact trace counters
  are present;
- official task success;
- cost or token improvement;
- leaderboard readiness;
- Goal Harness uplift.

## Smoke

```bash
python3 examples/terminal-bench-codex-goal-harness-custom-agent-smoke.py
```

The smoke uses fake Harbor modules, validates packet injection, verifies compact
counter extraction from public trace rows, and confirms the Harbor command
preview carries `goal_harness_mode=codex_goal_harness`.
