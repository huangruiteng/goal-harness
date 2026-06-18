# Project Agent Todo Contract

Project agents should keep operator-facing work out of long chat replies,
review documents, and overloaded `Next Action` paragraphs. Goal Harness uses
separate fields so the dashboard and quota guard can show the right work to the
right actor.

## Field Roles

- `Next Action` is one routing sentence for the next bounded step. It is not a
  reading queue, blocker dump, or checklist.
- `User Todo / Owner Review Reading Queue` is the human-facing checklist. Use
  it for concrete user, owner, or controller input that the agent cannot
  complete by itself.
- `Agent Todo` is the project-agent checklist. Use it for safe follow-up work
  the agent can do after health, operator gates, evidence, and quota allow
  execution.
- Production blockers, missing write approvals, and safety risks are gates or
  stop conditions. Do not count them as user todos unless a specific human
  action can clear them.

## Write Contract

When read-only analysis, a review packet, a gate checklist, or P0/P1 steering
finds a concrete user or owner action, write it immediately with the todo CLI:

```bash
goal-harness todo add \
  --goal-id <goal-id> \
  --role user \
  --text "<public-safe user or owner action>"
```

Use `--role agent` for project-agent follow-up work:

```bash
goal-harness todo add \
  --goal-id <goal-id> \
  --role agent \
  --text "<public-safe agent action>"
```

Executable agent work should register its lane instead of relying on text
classification. Use `advancement_task` for a bounded implementation,
validation, benchmark, blocker-writeback, or repair segment:

```bash
goal-harness todo add \
  --goal-id <goal-id> \
  --role agent \
  --text "<public-safe executable agent action>" \
  --task-class advancement_task \
  --action-kind run_eval
```

Use `continuous_monitor` only for watch-only surfaces where an unchanged poll
must stay quiet:

```bash
goal-harness todo add \
  --goal-id <goal-id> \
  --role agent \
  --text "<public-safe monitor action>" \
  --task-class continuous_monitor \
  --action-kind monitor
```

`--action-kind` is a public-safe token. Known generic tokens such as
`run_eval`, `validate`, `rebuild`, `writeback`, `monitor`, and `poll` help the
CLI project the lane consistently, but explicit `--task-class` is the authority
when both are present. If an exact todo already exists, `todo add` updates or
inserts the metadata comment instead of creating a duplicate checkbox.
`--task-class user_gate` and `--task-class blocker` are non-executable control
lanes for owner input and concrete blockers; quota/executor code must not treat
them as advancement work.

The command resolves the active state from the project registry, creates the
canonical section when needed, updates `updated_at`, and avoids duplicate exact
todo text. If a dashboard or controller needs the new checklist immediately,
refresh the status projection after the write:

```bash
goal-harness refresh-state --goal-id <goal-id>
```

## Lifecycle Contract

Agents should not patch active-state checkboxes directly to move work forward.
Use the lifecycle commands so Goal Harness can preserve `todo_id`, status,
classification metadata, timestamps, and idempotency in one write.

Todo lifecycle should stay simple. Do not add a separate feature state machine
such as `slice_done`, `rolled_out`, or `proven_in_product_path` unless the
product has a concrete UI/runtime need for it. For ordinary project work, use
**todo succession** instead: complete the implementation slice, then create the
next concrete todo for rollout, product-path audit, benchmark proof, docs,
telemetry, or operator decision.

A non-trivial feature todo is done only as a slice. Before or during completion,
the agent should do one of two things:

- create the next public-safe agent or user todo with `--next-agent-todo`,
  `--next-user-todo`, or a follow-up `todo add`;
- record a compact no-follow-up rationale in the completion note, explaining why
  the feature is truly finished and does not need rollout, audit, docs, or
  product-path proof.

This keeps the active checklist honest without making Goal Harness a heavyweight
project-management state machine.

Complete the current todo and atomically register the next executable todo:

```bash
goal-harness todo complete \
  --goal-id <goal-id> \
  --todo-id <todo_id> \
  --evidence "<public-safe artifact or result>" \
  --next-agent-todo "<public-safe next executable action>" \
  --next-task-class advancement_task \
  --next-action-kind run_eval
```

Use `todo update` for lower-level status changes:

```bash
goal-harness todo update \
  --goal-id <goal-id> \
  --todo-id <todo_id> \
  --status blocked \
  --reason "<public-safe blocker>" \
  --task-class blocker
```

Use `todo supersede` when the current open todo should be retired and replaced:

```bash
goal-harness todo supersede \
  --goal-id <goal-id> \
  --todo-id <todo_id> \
  --reason "<public-safe reason>" \
  --next-agent-todo "<replacement executable action>"
```

`todo complete` and `todo supersede` are intentionally idempotent for repeated
heartbeats: if the old todo is already complete and the next todo already
exists with the same metadata, the command returns `changed=false` and does not
duplicate the next checkbox. `todo archive-completed` is only a hygiene command:
it moves already-completed active todos into `Completed Work Archive`; it does
not mark open todos as done.

## Parsed Schema

Projects may keep writing ordinary Markdown checkboxes, but readers should use
the structured projection emitted by status/quota when available. Todo summaries
carry `schema_version=todo_summary_v0`; individual items carry
`schema_version=todo_item_v0`, `todo_id`, `role`, `status`, `priority`,
`title`, `archive_state`, `source_section`, `index`, `text`, `task_class`, and
optional `action_kind`. The `todo_id`
is first-class when written by the CLI. Legacy Markdown without metadata still
gets a parser-derived compatibility id from local section/index/text, and the
first lifecycle command will materialize that id back into metadata. Future
timestamp, dependency, and evidence-link fields should extend this item shape
instead of adding another todo format.
In Markdown, lane metadata is stored as an indented HTML comment directly under
the checkbox, for example:

```markdown
- [ ] Run one validated benchmark case and write back result or blocker.
  <!-- goal-harness:todo todo_id=todo_8e280be49441 status=open task_class=advancement_task action_kind=run_eval -->
```

Plain checkbox text remains a compatibility fallback. New automation-facing
work should prefer the CLI metadata path so quota and dashboard consumers do
not need project-specific word lists.

## Execution Order

1. Run the quota guard against the shared global registry before spending
   automatic delivery compute.
2. If the guard or review packet exposes open user todos, surface them to the
   user instead of reporting "no new user action".
3. If the guard sets `notify_user_on_open_todo=true`, treat the open todos as a
   blocker-push notification: ask at most three items, skip delivery work, and
   skip quota spend unless the same blocker was already surfaced recently.
4. Do not execute `agent_command`, adapter work, write-control, or production
   actions while the relevant gate is still unresolved.
5. After the user todo is completed or explicitly deferred, the project agent
   may continue only through the safe path allowed by the current guard or
   review packet.

## Public Smokes

Two dependency-free public fixtures cover this contract:

```bash
python3 examples/todo-cli-smoke.py
python3 examples/todo-lifecycle-cli-smoke.py
python3 examples/project-agent-adoption-smoke.py
```

The first verifies the todo CLI writes canonical active-state sections. The
second verifies lifecycle transitions by `todo_id`, including complete,
supersede, idempotent next-todo insertion, and non-executable blocker lanes.
The third verifies an executor-facing path from quota guard hint, to user todo
write, to status projection, to approved project-agent handoff.
