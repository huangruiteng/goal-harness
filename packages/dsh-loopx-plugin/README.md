# LoopX for DeepSeek Harness

`dsh-loopx-plugin` intentionally has only two host capabilities:

- `/loopx-init` installs or upgrades the LoopX CLI, installs the packaged
  workflow skills into `$DSH_AGENTS_HOME/skills` (default
  `~/.agents/skills`), and verifies the DSH-native `loopx` entry.
- the same-session Driver asks LoopX whether another turn may run and queues
  the authoritative heartbeat task into the exact live DSH Agent.

The package does not expose LoopX model tools, a service facade, a coordinator,
receipts, a binding sidecar, or its own Goal/Todo state. Models use the
installed LoopX skills and call the LoopX CLI directly. LoopX remains the only
authority for Goal, Agent, Todo, quota, and durable thread binding data.

## Install

Requirements are Node.js 22.19+ and `pnpm`. LoopX itself is deliberately not a
prerequisite:

```bash
cd packages/dsh-loopx-plugin
./install.sh
```

Then open DSH and run:

```text
/loopx-init
```

The command has no arguments. It first probes the current LoopX installation.
When the CLI is missing or lacks the DSH-native skill contract, it runs exactly
one `python3 -m pip install --upgrade loopx`, then installs and reads back the
skills. It never invokes a model, constructs a shell command, edits a registry,
or retries the install mutation.

After initialization, invoke the `loopx` skill with the task text. The skill
uses the exact DSH-managed `$DSH_SESSION_ID`, passes
`--host-surface deepseek-harness-native`, and follows the typed commands
returned by LoopX. The historical external connector remains the distinct
`deepseek-harness` / `dsh` surface.

## Driver retry boundary

DSH's LLM retry plugin owns provider-request retries. This Driver retries only
safe fixed-argv LoopX reads and an idempotent `quota should-run` receipt, at
most twice beyond the first attempt. Every retry uses the same
`--turn-instance-id`. Typed authority denials, incompatible schemas,
cancellation, and human input are never retried. There is no cumulative
eight-failure breaker or process-local activation state. Exhausting the three
attempts stops that evaluation; it does not create a periodic error-retry loop.
Only a typed LoopX local-scheduler plan can schedule another wakeup, and its
unchanged-poll limit is enforced.

The Driver resolves the current project registry with
`resolve-agent-thread`, requires one exact Goal/Agent match for the live DSH
session, and rechecks binding plus quota before and after downstream pre-step
listeners. A human message removes an unclaimed automatic reservation; a
mixed batch rejects the automatic message and restores the human work.

## Uninstall

Remove the plugin from the DSH profile:

```bash
dsh plugin --profile web remove dsh-loopx-plugin
```

This stops the Driver and removes `/loopx-init`; it does not remove LoopX or
its skills. To remove only LoopX-managed skills, run
`loopx workflow-skills --uninstall --skills-dir ~/.agents/skills`.
