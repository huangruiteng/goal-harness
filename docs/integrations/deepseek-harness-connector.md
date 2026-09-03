# DeepSeek Harness Connector

Status: public-safe v0 connector for using DeepSeek Harness (`dsh`) as a
bounded agent execution host behind LoopX.

DeepSeek Harness is an open-source agent harness by DeepSeek AI. LoopX does not
replace dsh's model loop, tools, sandbox, or session log. Instead, the connector
lets LoopX govern one dsh-backed work segment at a time through the existing
LoopX Turn protocol:

```text
LoopX quota should-run
    -> loopx turn run-once
    -> loopx.dsh_goal_mode adapter (python -m loopx.dsh_goal_mode)
    -> DeepSeek Harness Python SDK / dsh runtime
    -> typed loopx_turn_result_v0
    -> independent validator
    -> LoopX writeback + quota spend
```

## What This Connector Adds

- A thin adapter, now a first-class goal-mode subpackage at
  `loopx/dsh_goal_mode/` (run with `python -m loopx.dsh_goal_mode`; the
  historical `scripts/dsh_turn_host_adapter.py` launcher still works),
  that translates
  `loopx_turn_host_request_v0` into one bounded dsh session prompt and parses
  the model's final JSON result back into `loopx_turn_result_v0`.
- A `deepseek-harness` agent type in LoopX onboarding so users can request the
  exact host instead of the generic `other-agent`.
- Optional dependency `loopx[deepseek-harness]` for the validated
  `deepseek-harness-sdk==0.1.2a3` Python client.

## Install

Install LoopX's optional DeepSeek Harness extra:

```bash
python -m pip install 'loopx[deepseek-harness]'
```

The DeepSeek Harness SDK spawns the bundled `dsh-jsonrpc-agent` runtime. It
uses the explicit adapter configuration plus normal provider environment
variables:

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DSH_HOME
```

The adapter resolves its SDK home in this order: explicit `--dsh-home`, then
`DSH_HOME`, then `<workspace>/.local/.dsh-sessions`. It passes that path as the
SDK's `dsh_home` field; the SDK does not implicitly select `~/.dsh`.

Prepare a dsh `cordis.yml` when the default bundled composition is not
appropriate. See the
[DeepSeek Harness Python SDK reference](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)
for runtime selection and configuration.

## Onboard

```bash
loopx doctor --agent-type deepseek-harness

loopx agent-onboard \
  --agent-type deepseek-harness \
  --project . \
  --goal-id <goal-id> \
  --agent-id deepseek-worker \
  --available-capability shell
```

`deepseek-harness` maps to the generic CLI agent loop and uses
`--runtime-profile generic_cli` in quota/heartbeat commands.

## Run One Governed Turn

```bash
loopx turn run-once \
  --goal-id <goal-id> \
  --agent-id deepseek-worker \
  --host generic-cli \
  --execution-mode isolated-headless \
  --project "$PWD" \
  --host-adapter-command-json '["python3", "-m", "loopx.dsh_goal_mode", "--dsh-home", "/path/to/dsh-home", "--cordis", "/path/to/cordis.yml", "--model", "deepseek-v4-flash"]' \
  --validation-command-json '["python3", "/path/to/verify-postcondition.py"]' \
  --execute
```

The adapter uses `<workspace>/.local/.dsh-sessions/` as its workspace-local
SDK home by default. Override it with `--dsh-home <path>`; the historical
`--session-root` spelling remains an adapter-command compatibility alias.
Session persistence itself is owned by the selected dsh composition and is not
implied by the home-directory name.

## Run One Governed Turn In Process (`--host dsh`)

The built-in host runs the same adapter inside the CLI process:

```bash
loopx turn run-once \
  --goal-id <goal-id> \
  --agent-id deepseek-worker \
  --host dsh \
  --execution-mode isolated-headless \
  --project "$PWD" \
  --dsh-home /path/to/dsh-home \
  --dsh-cordis /path/to/cordis.yml \
  --dsh-model deepseek-v4-flash \
  --validation-command-json '["python3", "/path/to/verify-postcondition.py"]' \
  --execute
```

Unlike the subprocess mode, provider failures reach the Turn journal as typed
`loopx_turn_host_failure_v0` kinds (including the SDK's exception-free
`RunResult.finish_reason == "error"` terminal report), so bounded same-Turn
retry stays available. This mode does not promise cross-turn dsh session
continuity or an outer wake/timer. See the adapter README for the home and
classification precedence, plus the hermetic verification smoke
(`examples/loopx-turn-dsh-builtin-host-e2e-smoke.py`).

## Boundaries

- LoopX keeps the durable goal, todo, claim, gate, quota, evidence, and
  scheduler authority.
- dsh owns model calls, tools, sandboxing, and the raw session log.
- The adapter must not publish raw transcripts, dsh JSONL sessions, credentials,
  local absolute paths, or unbounded tool output into LoopX state.
- `DeepSeekHarness.run()` returns the candidate result; it is not proof of
  completion. An independent validator is required before LoopX writeback.
- The dsh Python SDK is an optional dependency. Core LoopX remains runtime
  dependency-free.
- The adapter derives an owner-local session id, but LoopX does not project or
  validate a DSH Host Session Binding. This surface therefore does not claim a
  managed supervisor or cross-process resume guarantee.

## Hermetic Validation

The repository includes four validation paths. The first three do not require the
DeepSeek Harness SDK or a real dsh runtime:

```bash
python3 examples/dsh-turn-host-adapter-smoke.py
python3 examples/loopx-turn-dsh-e2e-smoke.py
python3 examples/loopx-turn-dsh-builtin-host-e2e-smoke.py
```

The first guards adapter translation and result shaping. The second drives the
full `loopx turn run-once -> adapter -> fake dsh -> validator -> writeback ->
quota spend -> idempotent replay` chain. The third proves the built-in host's
success path plus three bounded provider-capacity attempts, retry-budget
exhaustion without a fourth Host invocation, zero failure spend/writeback, and
provider-prose non-persistence.

The fourth uses the real `deepseek-harness-sdk` and the bundled dsh JSON-RPC
runtime. It still avoids a real model call by serving a local mock OpenAI-compatible
SSE endpoint, so it is hermetic and does not require `DEEPSEEK_API_KEY`:

```bash
python3 examples/loopx-turn-dsh-real-e2e-smoke.py --host generic-cli
python3 examples/loopx-turn-dsh-real-e2e-smoke.py --host dsh
```

The real-dsh smoke clears ambient DSH home variables and proves that both host
paths can supply an explicit SDK home, start the actual dsh runtime, run one
bounded turn through the real JSON-RPC agent loop, parse a typed JSON final
message, and complete LoopX validation/writeback/quota spend.

## Related Contracts

- [DeepSeek Harness control-plane adapter](deepseek-harness-control-plane-adapter.md)
- [Runtime connector catalog](runtime-connector-catalog.md)
- [LoopX Turn v0](../reference/protocols/loopx-turn-v0.md)
- [Host integration surface v0](../reference/protocols/host-integration-surface-v0.md)
- [Embed LoopX In Your Agent Runner](../guides/custom-agent-runner-integration.md)
