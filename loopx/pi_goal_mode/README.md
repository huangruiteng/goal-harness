# LoopX Pi goal mode

The Pi host adapter for LoopX. Pi is a terminal coding agent whose extensions
register commands, tools, and event handlers; this adapter turns a Pi session
into a LoopX-governed visible goal loop.

## Surface

- **`/loopx`** — with no arguments, runs `loopx bootstrap-command-pack --project .`
  and shows the packet as a widget plus a transcript entry. With a goal text
  argument, runs `loopx start-goal --guided --project . --goal-text "<text>"
  --host-surface pi` and places the returned packet in the editor for review.
  `/loopx resume` re-arms auto-continuation after a user-driven pause.
- **`loopx_goal_activate`** — agent-callable tool. Binds the current session to
  a LoopX goal (`goalId`, heartbeat `objective`/task_body, optional `agentId`,
  `registryPath`, `availableCapabilities`), then starts the quota-gated loop.
- **Goal loop** — on every `agent_settled`, the extension probes
  `loopx quota should-run --runtime-profile generic_cli` for the bound goal.
  LoopX decides whether to continue (the heartbeat task_body is injected as a
  follow-up), wait with scheduler-hint backoff (unchanged-poll limits apply), or
  stop at a validated terminal no-follow-up. Probe failures fail closed with a
  bounded retry; the extension never self-declares closure.

## Install / uninstall

```bash
loopx slash-commands --install --surface pi --pi-project .
loopx slash-commands --uninstall --surface pi --pi-project .
```

Installs two LoopX-managed files into the project (loaded after project
trust):

- `.pi/extensions/loopx-goal.ts` — the extension adapter that registers
  `/loopx`, `loopx_goal_activate`, and the `agent_settled` loop wiring.
- `.pi/extensions/pi-goal-loop-runtime.mjs` — the quota/wait/store loop core
  (not auto-discovered as an extension; the adapter imports it directly).

Pi's extension loader aliases `typebox` and the `@earendil-works/*` packages,
so no local `node_modules` are required. The `--pi-project` flag points the
installer at the target project so the command is correct even when run from
another directory; `agent-onboard --agent-type pi --project <path>` emits the
resolved project automatically.

## State

Bindings persist under `<project>/.loopx/pi/` (gitignored), keyed by session.
Override with `LOOPX_PI_STATE_DIR`. Invoke the CLI binary via `LOOPX_BIN`.

Sessions without a session file (`pi --no-session`) are ephemeral: the
adapter uses a unique in-memory identity per extension instance and never
persists its binding, so a later `--no-session` run cannot inherit the
previous run's goal and must activate again through `loopx_goal_activate`.

## Boundary

The extension reads only LoopX public-safe state and never copies raw
transcripts, credentials, or local session paths. Continuation is governed by
LoopX quota; user prompts pause auto-resume; `/loopx resume` or re-activation
re-arms it. No external writes happen without the active LoopX state or owner
authorization.

On `session_shutdown` (session switch, fork, or reload) the extension instance
is atomically disposed: every timer is cancelled and an in-flight quota probe
that returns afterwards stops at the disposed guard, so the old session can
never inject a follow-up or reschedule past the reload / session-replacement
boundary.
