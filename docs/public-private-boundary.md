# Public / Private Boundary

Goal Harness is designed to be public, but most useful goal evidence is not.

## Public

These are safe to keep in the public repository:

- schemas,
- runtime directory conventions,
- generic CLI code,
- adapter lifecycle rules,
- controller/sub-agent lifecycle states,
- generic coordination rules,
- validation commands,
- sanitized examples,
- high-level design notes.

## Private

These should stay in project-local ignored files:

- local absolute paths,
- internal repository names,
- raw logs and metrics,
- task ids,
- document links,
- credentials and tokens,
- person or team names from private work,
- active goal state that reveals current user context,
- raw sub-agent prompts and traces,
- child run evidence that contains local paths or private artifacts.

## Sub-Agent Data

Sub-agent orchestration increases leakage risk because child prompts often
contain more context than the final report needs. Public artifacts should keep:

- schema names,
- role names,
- sanitized work-scope examples,
- lifecycle states,
- generic merge rules.

Private project state should keep:

- raw child prompts,
- raw trajectories,
- local task evidence,
- non-public repo names,
- exact command output when it contains project-specific context.

Run summaries are publishable only after sanitization.

## Practical Rule

The public repo should answer: "How does a goal harness work?"

The project repo should answer: "What is this specific goal currently doing?"

The runtime root should answer: "What happened in recent goal ticks?"

If a runtime-only goal is obsolete, archive its directory rather than copying
private run payloads into public notes:

```bash
goal-harness archive-runtime --goal-id old-experiment-goal
goal-harness archive-runtime --goal-id old-experiment-goal --execute
```

The first command is a dry-run. The second moves the local runtime directory
under `<runtime-root>/archived-goals/`; it does not sanitize or publish the
payload.
