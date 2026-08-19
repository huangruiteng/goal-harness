# LoopX DeepSeek Harness (dsh) goal mode

First-class host adapter that turns a DeepSeek Harness session into a
LoopX-governed goal loop. LoopX keeps authority (goal/todo state, quota,
validation); the adapter only translates one governed Turn into one bounded
dsh work segment and shapes the reply into a typed result.

## Surface

The `deepseek-harness` host surface (aliases: `deepseek_harness`,
`DeepSeek Harness`, `dsh`) is an external loop driver:

1. `loopx start-goal --guided --project . --host-surface deepseek-harness`
   returns the host-loop activation packet after todo writeback.
2. Every automatic tick starts from `loopx quota should-run`
   (`--runtime-profile generic_cli`) and stops when it says stop.
3. Each approved tick runs `loopx turn run-once` with this adapter as the
   generic-cli host adapter command.
4. The adapter reads one `loopx_turn_host_request_v0` JSON object on stdin,
   extracts the signed TurnEnvelope authority, asks dsh to execute the bounded
   `primary_action`, and emits exactly one `loopx_turn_result_v0` JSON object
   on stdout.
5. LoopX validates the typed result independently before writing any state or
   spending quota.

## Run the adapter

```bash
python -m loopx.dsh_goal_mode \
  --cordis /path/to/cordis.yml \
  --model deepseek-v4-flash \
  --provider deepseek-official
```

The historical launcher still works and resolves to the same implementation:

```bash
python3 scripts/dsh_turn_host_adapter.py --cordis /path/to/cordis.yml
```

Flags: `--provider`, `--model`, `--max-tokens`, `--workspace`,
`--session-root`, `--cordis`, `--runtime-bin`,
`--request-timeout-seconds`, and `--dsh-runner` (hermetic tests only: path to
a Python module exposing `run_dsh_turn(...)`).

## Requirements

- Optional dependency group `loopx[deepseek-harness]`
  (the `deepseek-harness-sdk` import) or a compatible runner via
  `--dsh-runner`.
- A dsh `cordis.yml` plus any `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL`
  settings for the real runtime.
- Defaults come from `DSH_MODEL` / `DSH_PROVIDER` when set.

## Boundary

Opaque dsh session roots (default `<workspace>/.local/.dsh-sessions`) stay
local and never enter public LoopX evidence. The adapter never reads
goal/todo state, builds prompts from todo ids, writes LoopX state, spends
quota, or validates its own work. A missing or malformed typed result fails
closed as a `wait` result with no quota spend.

See `docs/integrations/deepseek-harness-connector.md` for the full connector
walkthrough and `examples/dsh-turn-host-adapter-smoke.py` plus
`examples/loopx-turn-dsh-e2e-smoke.py` for hermetic smokes.
