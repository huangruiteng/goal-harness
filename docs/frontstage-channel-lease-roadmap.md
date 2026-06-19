# Frontstage Channel And Lease Roadmap

Goal Harness should not become a chat product. Its durable value is the
backstage control plane: registry, active state, append-only event history,
quota, gates, leases, and auditable recovery. The missing product layer is a
frontstage projection that lets people understand and coordinate that control
plane without reading raw CLI dumps.

This note frames the product direction as:

```text
frontstage channel UX + backstage Goal Harness ledger
```

The channel is a view. The ledger is truth.

## Product Boundary

Goal Harness should borrow collaboration language without moving the source of
truth into chat history:

- A **goal can project as a channel**: one timeline with latest state, next
  action, user todos, agent todos, gates, artifacts, quota, and run events.
- An **agent can project as a workspace member**: controller, executor,
  reviewer, monitor, critic, or dreaming/planning proposer, each with scope and
  last action.
- A **task claim should be a per-todo lease**: explicit ownership of one
  `todo_id` with TTL, write scope, idempotency key, and conflict policy.
- A **chat or channel thread is a projection**: useful for human collaboration,
  but never the only durable authority.

The key product lesson is not "add Slack-like chat". It is that humans think in
channels, members, tasks, and approvals, while agents need registry, state,
history, quota, gates, and leases.

## Minimal Schemas

### `goal_channel_projection_v0`

This is a human-facing projection over existing Goal Harness state:

```json
{
  "schema_version": "goal_channel_projection_v0",
  "goal_id": "goal-harness-meta",
  "display_name": "Goal Harness Meta",
  "waiting_on": "codex",
  "latest_status": "terminal_bench_case_running",
  "next_action": "compact-poll the active benchmark job",
  "user_todos": [],
  "agent_todos": [],
  "open_gates": [],
  "active_leases": [],
  "recent_events": []
}
```

It should be derived from `status`, active state, run history, todos, quota,
and review packets. It must not parse raw chats or private logs.

### `agent_member_v0`

This is an identity and permission projection for an actor participating in a
goal:

```json
{
  "schema_version": "agent_member_v0",
  "agent_id": "codex-local-controller",
  "role": "controller",
  "goal_id": "goal-harness-meta",
  "write_scope": ["docs/**", "examples/**", "goal_harness/**"],
  "last_action": "refresh_state",
  "claim_id": null
}
```

Roles should stay product-level and portable: controller, executor, reviewer,
monitor, critic, dreaming_proposer. A role can guide UI copy and default
permissions, but the concrete authority still comes from `goal_boundary`,
leases, and active-state todos.

### `task_lease_v0`

This is the concurrency contract that should eventually back task claim. The
pending key is per todo: `(goal_id, todo_id)`. Do not serialize an entire
goal just because one todo is claimed; independent todos under the same goal
should remain independently claimable when gates and write scopes allow it.
Goal Harness does not have a separate issue object in this runtime model:
`goal_id` names the control-plane boundary, and `todo_id` names the work item
inside that boundary.
The v0.1 control plane still keeps role assignment simple: one
`coordination.primary_agent` owns review/merge/publication for the goal, and
side agents claim scoped todos and work in separate git worktrees. They may
self-merge small AGENTS-eligible validated changes with explicit evidence;
otherwise they add a primary-agent review todo when finishing.

```json
{
  "schema_version": "task_lease_v0",
  "todo_id": "todo_123",
  "owner_agent": "codex-local-controller",
  "goal_id": "goal-harness-meta",
  "lease_until": "2026-06-15T12:30:00Z",
  "write_scope": ["docs/frontstage-channel-lease-roadmap.md"],
  "idempotency_key": "goal-harness-meta:todo_123:20260615T1230Z",
  "conflict_policy": "fail_closed_on_scope_overlap",
  "status": "active"
}
```

The first implementation can be local and file-backed. A later server can own
the same schema with stronger locking, lease renewal, and stale-claim cleanup.
Conflicts should be detected by `(goal_id, todo_id)` plus overlapping
write-scope checks: another agent may claim a different todo in the same goal,
but a second pending claim on the same todo must fail closed, renew, or
explicitly transfer ownership.

## Priority

P1:

- Design and test `task_lease_v0` first. It prevents lost writes and concurrent
  controller confusion, and it naturally extends the existing todo locking
  lane. The durable invariant is per-todo pending: one active pending lease per
  `(goal_id, todo_id)`, not one active lease per goal or project.
- Add a compact channel projection contract to `status` or a new read-only CLI
  command so UI can show a goal as a channel without becoming truth.

P2:

- Add agent-member projection to status/review packets after leases exist, so
  agent identity is useful rather than decorative.
- Build a Raft-style local frontstage view that renders channel timelines and
  member activity from Goal Harness projections.
- Let dreaming/planning proposals appear as a separate channel lane or badge.
- Add bridge adapters that can post channel summaries to collaboration tools,
  while preserving Goal Harness as the ledger of record.

## Non-Goals

- Do not make conversation history the only project state.
- Do not let UI membership labels override `goal_boundary`, operator gates, or
  run permissions.
- Do not require a server for the first schema; the CLI must remain a usable
  fallback/client.
- Do not let background dreaming claim delivery work without the normal
  `quota should-run` and lease path.

## Acceptance Frame

The first successful slice should prove that a human can open one goal view and
see:

- what the goal is;
- who or what is currently responsible;
- which task is claimed and until when;
- which files/surfaces that claim may touch;
- which event made the current state true;
- what the next safe action is.

The corresponding agent should be able to read the machine projection and avoid
double-running, double-spending, or writing outside scope.
