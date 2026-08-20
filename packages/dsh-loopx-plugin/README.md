# LoopX for DeepSeek Harness

`dsh-loopx-plugin` intentionally has only two host capabilities:

- `/loopx-init` installs or upgrades the LoopX CLI, installs the packaged
  workflow skills into `$DSH_AGENTS_HOME/skills` (default
  `~/.agents/skills`), and verifies the DSH-native `loopx` entry.
- a passive same-session Driver becomes eligible only after the exact current
  Session successfully invokes the exact `loopx` skill. It then asks LoopX
  whether another turn may run and queues the authoritative heartbeat task
  into that live DSH Agent.

Installing the plugin and running `/loopx-init` load and prepare these
capabilities; neither activates the Driver. Until one exact Session contains
valid typed `loopx` invocation evidence, its Driver makes no LoopX CLI,
binding, quota, or heartbeat call, creates no timer, and queues no followup.

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

The command has no arguments. Extra input returns a usage error before any
model work or CLI probe. A valid invocation queues a bounded start followup on
the exact receiving Agent, then probes the current LoopX installation. When the
CLI is missing or lacks the DSH-native skill contract, it runs exactly one
`python3 -m pip install --upgrade loopx`, then installs and reads back the
skills. It never constructs a shell command, edits a registry, or retries the
install mutation.

Unless the command is cancelled, it queues a second bounded followup for the
typed success or failure result. These are ordinary Agent turns, so a valid,
uncancelled invocation normally adds two model calls; cancellation leaves only
the already queued start turn, while invalid input adds none. The prompts do
not authorize tools, commands, or another installation. Followup delivery is
best effort and is not retried. The native `CommandResult` rendered by the
command UI remains authoritative: a followup failure or model reply cannot
change the installation result or repeat its mutation.

On success, restart DSH only when the actual install payload reports a packaged
skill as `created` or `updated`, or the entry skill as `created`, `updated`, or
`upgraded_legacy_managed`. A CLI-only installation or upgrade and an
all-`unchanged` skill result do not require a restart. Missing or unknown skill
status fails initialization instead of being guessed as unchanged.

After initialization, invoke the `loopx` skill with the task text. The skill
uses the exact DSH-managed `$DSH_SESSION_ID`, passes
`--host-surface deepseek-harness-native`, and follows the typed commands
returned by LoopX. The historical external connector remains the distinct
`deepseek-harness` / `dsh` surface.

## Driver activation boundary

Activation is per Session, not per plugin, process, Agent, Goal, or project.
The Driver accepts only either of these durable typed Session facts:

- a `user/message` whose source is exactly `skill-invocation`, whose name is
  exactly `loopx`, and whose form is exactly `instructions`;
- a model `tool/call` named exactly `skill`, with JSON object arguments whose
  `name` is exactly `loopx`, paired by call id with a subsequent successful
  `tool/result`.

A skill catalog, ordinary prose, shell text, `/loopx-init`, plugin-authored
init or heartbeat messages, a failed, malformed, unmatched, or superseded
model call, and the presence of a CLI, registry, Goal, binding, or project file
do not activate the Driver. Recovery folds only the current Session's existing
typed event history in memory and performs no external probe. Replacing or
clearing a Session recomputes from the replacement history; activation never
inherits across that boundary and has no plugin-owned durable store.

Existing Sessions upgraded from an older plugin version remain inactive when
their retained history has no recognizable invocation evidence. Invoke the
installed `loopx` skill once in every Session that should continue
automatically. Activation records intent only: it does not create a binding,
select a Goal or Agent, spend quota, or grant tool authority. After activation,
the existing exact binding, fresh quota, scheduler/heartbeat, reservation, and
pre-step revalidation order remains authoritative.

## Driver retry boundary

DSH's LLM retry plugin owns provider-request retries. This Driver retries only
safe fixed-argv LoopX reads and an idempotent `quota should-run` receipt, at
most twice beyond the first attempt. Every retry uses the same
`--turn-instance-id`. Typed authority denials, incompatible schemas,
cancellation, and human input are never retried. There is no cumulative
eight-failure breaker or plugin-owned durable activation state. The small
process-local activation projection is bound to one exact Session and is
reconstructed only from its typed event history. Exhausting the three attempts
stops that evaluation; it does not create a periodic error-retry loop. Only a
typed LoopX local-scheduler plan can schedule another wakeup, and its limit on
unchanged polls is enforced.

The Driver resolves the current project registry with
`resolve-agent-thread`, requires one exact Goal/Agent match for the live DSH
session, and rechecks binding plus quota before and after downstream pre-step
listeners. A human message removes an unclaimed automatic reservation; a
mixed batch rejects the automatic message and restores the human work.
The Driver queues at most one Driver-owned followup per automatic admission.
Initialization messages use the distinct `dsh-loopx-plugin/init-command`
source and never satisfy a Driver reservation.

## Uninstall

Remove the plugin from the DSH profile:

```bash
dsh plugin --profile web remove dsh-loopx-plugin
```

This stops the Driver and removes `/loopx-init`; it does not remove LoopX or
its skills. To remove only LoopX-managed skills, run
`loopx workflow-skills --uninstall --skills-dir ~/.agents/skills`.
