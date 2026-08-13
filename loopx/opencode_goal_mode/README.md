# LoopX OpenCode adapter

LoopX exposes two separate OpenCode layers: a static command facade and an
optional executable goal bridge. Ordinary command installation never activates
the runtime bridge.

## Install

The default `all` surface installs only static files under
`~/.config/opencode/commands/`:

```bash
loopx slash-commands --install
```

Enable the goal bridge explicitly:

```bash
loopx slash-commands --install --surface opencode --with-goal-bridge
```

Before writing any OpenCode file, bridge installation validates
`opencode.json`, `opencode.jsonc`, and `package.json`. It fails closed if a
config is invalid or directly registers `opencode-goal-plugin`, because loading
that plugin beside the LoopX wrapper would start two independent goal runtimes.

After preflight succeeds, the installer writes the command facade plus:

- `~/.config/opencode/plugins/loopx-goal.js`;
- `~/.config/opencode/loopx/goal-bridge-runtime.mjs`;
- pinned bridge dependencies in `~/.config/opencode/package.json`.

OpenCode runs `bun install` for config-directory dependencies at startup.
Restart OpenCode after bridge installation so it installs those dependencies
and loads the local plugin.

## Runtime

Run `/loopx <task>`, then activate the returned host packet through
`loopx_goal_activate`. The runtime flow is:

```text
OpenCode idle event -> loopx quota should-run
  -> run_now: continue once
  -> wait: schedule a bounded local recheck without a model call
  -> user input: answer it, resume the goal, keep gating through quota
  -> unchanged-poll limit: pause the visible goal and stop the timer
  -> terminal_no_followup: standby polling instead of completing; new work
     resumes the goal automatically
```

User messages and permission replies never pause the loop. The bridge stops
scheduled timer wakes while the user's message is being answered, probes a
goal resume on the next idle event, and continues quota-gated operation as
usual. Validated terminal closure no longer completes the goal: the bridge
keeps the goal active in standby and re-checks quota every five minutes, so
finishing one task does not end the loop.

Bindings are private per-session JSON files under
`$LOOPX_OPENCODE_STATE_DIR`, or `$XDG_STATE_HOME/loopx/opencode` by default,
and use mode `0600`. OpenCode's one-shot `opencode run` process cannot own
timers after exit; recurring operation requires the visible TUI or a
persistent OpenCode server. OpenCode 2 runs a persistent goal worker instead;
see `loopx/opencode2_goal_mode/README.md`.

Quota probes carry `--record-host-poll`, so LoopX writes a compact poll
receipt beside the goal state file and `loopx global-risks` can flag a loop
whose bridge died mid-wait. Probe failures retry with a bounded exponential
backoff (3 minutes up to 30) and reset on success. A per-session lock file
prevents two OpenCode processes from evaluating the same session at once.

A user message sets `userMessagePending` in the binding so the next idle
evaluation resumes the wrapped goal (which may pause itself on user input)
before continuing quota gating; explicit pause tools still record a typed
`lastPausedReason` and `/goal resume` clears it. The unchanged-poll limit no
longer stops the timer silently: the bridge pauses the visible OpenCode goal
so the stop is visible in the session and in LoopX state.

The wrapped goal plugin also persists private restart state under the active
project's `.opencode/goals/` directory. Add `.opencode/goals/` to the project
ignore rules so goal text, checkpoints, and lifecycle state cannot enter a
public commit.

## Uninstall

Remove only the static command facade:

```bash
loopx slash-commands --uninstall --surface opencode
```

Remove the static facade and LoopX-managed bridge files:

```bash
loopx slash-commands --uninstall --surface opencode --with-goal-bridge
```

Bridge uninstall preserves `package.json` dependencies because user-owned
local plugins may share them.
