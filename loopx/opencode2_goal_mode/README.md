# LoopX OpenCode 2 adapter

OpenCode 2 ships a new in-process plugin API, and OpenCode 1 plugins do not
run under it. LoopX drives OpenCode 2 sessions through the OpenCode 2 HTTP
API with a persistent out-of-process goal worker instead of a plugin.

The worker owns the loop timers, so recurring operation survives TUI close,
one-shot CLI usage, and client restarts. OpenCode 1 keeps the existing goal
bridge; both surfaces share the same static command facade.

## Install

The static command facade (`/loopx`, `/loopx-global-*`, `/loopx-pr-review`)
installs into the shared OpenCode config directory and serves both OpenCode 1
and OpenCode 2:

```bash
loopx slash-commands --install
```

The worker itself ships with LoopX and needs no OpenCode-side install:

```bash
which opencode2
loopx opencode2-goal-worker --help
```

## Runtime

Run `/loopx <task>` and select `--host-surface opencode2` when starting the
goal, then start the worker from the returned activation packet:

```bash
loopx opencode2-goal-worker \
  --goal-id <goal_id> \
  --directory <project directory> \
  --task-body "<task body>" \
  [--agent-id <agent_id>] [--capability <name>]... \
  [--session-id <existing session>]
```

The loop is:

```text
prompt session -> wait for the assistant turn to complete
  -> loopx quota should-run (generic_cli profile, host poll receipt)
  -> run_now: continue with a quota-gated continuation prompt
  -> wait: backoff ladder, no model calls during quiet waits
  -> terminal_no_followup: visible closure notice, then standby polling
     (the worker stays attached and resumes automatically when new work
     appears instead of pausing after one task)
  -> unchanged-poll limit: visible synthetic pause notice, worker exits
  -> goal_not_found: the worker exits; the goal is no longer registered
```

User messages never pause the loop. The model answers the message and the
worker keeps gating continuation through quota as usual. A stalled session,
turn wait budget, turn budget, or duration budget still pauses visibly.

## State

Worker state is a private per-goal JSON file under
`$LOOPX_OPENCODE2_STATE_DIR`, or `$XDG_STATE_HOME/loopx/opencode2` by
default, with mode `0600`. A lock file with a pid and heartbeat prevents two
drivers from running the same goal; a crashed worker's lock is stolen after
the staleness window.

`quota should-run --record-host-poll` writes a compact receipt beside the
goal state file. `loopx global-risks` flags receipts whose loop expected
continuation but has gone quiet for longer than the staleness window, so a
worker that died mid-wait is visible instead of silently stalling.

## Limits

- Turn wait budget: 120 minutes per assistant turn (worker pauses visibly on
  timeout).
- Turn budget: 10000 turns; duration budget: 30 days. Both stop the loop
  with a visible synthetic notice.

The OpenCode 2 API is in beta; the worker uses only the stable JSON session,
message, prompt, and synthetic endpoints through `opencode2 api`.
