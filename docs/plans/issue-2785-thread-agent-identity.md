---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# Fix Codex App Thread Agent Identity Reuse

## Goal

Make repeated Codex App `/loopx` calls in one stable host thread reuse the
agent identity already selected by that thread. A task, worktree, or new Todo
must not create a new peer by itself.

## Decisions

- The binding key is `(host_surface, goal_id, thread_id)` and maps to one
  already registered `agent_id`.
- Codex App `start-goal` consumes its ambient `CODEX_THREAD_ID` when an
  explicit `--thread-id` is absent. Other hosts may pass an opaque thread ID.
- Identity resolution prefers a verified thread binding. An exact agent from
  the current host task's active interaction contract is a valid initial
  selection and must then be bound before Todo writeback.
- A stable unbound thread is a new host session and defaults to fresh
  registration. Registry order and a single registered lane are not identity
  evidence for takeover.
- A missing thread ID or conflicting binding fails closed. `--new-peer` carries
  explicit fresh-session intent when the host cannot provide a stable ID; task
  text, a new Todo, or a worktree never implies it.
- Binding is an explicit, idempotent mutation. Source/global registry sync and
  binding readback must succeed before planning or Todo writeback continues.

## Boundaries

In scope:

- bounded opaque thread-ID validation and project/global registry persistence;
- guided `start-goal` identity resolution and command propagation;
- generated `/loopx` and project-skill guidance;
- unit, CLI, and synthetic public-smoke coverage.

Out of scope:

- Codex App host changes or synthesized thread IDs;
- identity inference from conversation text or registry ordering;
- cross-runtime identity transfer, expiration, or binding-management UI;
- raw transcripts, credentials, paths, or private host metadata.

## Required Transaction

For an unbound Codex App thread:

1. inspect the connected goal and registered lanes;
2. default to fresh registration, or select an existing lane only for explicit
   takeover;
3. register the fresh identity when selected, then execute
   `bind-agent-thread --execute`;
4. require `ok=true`, `global_sync.ok=true`, and
   `registration_readback.verified=true`;
5. only then plan and write Todo state, refresh, activate, and run quota.

Later calls with the same binding directly reuse the bound agent across
`start-goal`, heartbeat, quota, refresh-state, and Todo commands. They do not
repeat the binding mutation.

## Verification

Focused validation must cover:

- invalid, missing, idempotent, and conflicting bindings;
- ambient Codex App thread-ID resolution;
- an ordered bind/readback step before Todo writeback;
- a real first-call bind followed by a second call without `--agent-id`;
- a stable unbound thread that defaults to fresh registration while preserving
  explicit existing-lane takeover;
- a missing thread ID that stays fail closed unless `--agent-id` or
  `--new-peer` is explicit;
- generated Skill text that reuses active task identity and never treats a
  worktree, Todo, or argument-bearing call as a new peer;
- standalone and official-runner execution of the public smoke.

Minimum commands:

```bash
pytest -q \
  tests/test_thread_agent_binding.py \
  tests/control_plane/test_start_goal_compact_projection.py \
  tests/test_slash_command_install.py
python3 examples/codex-app-thread-agent-identity-smoke.py
python3 examples/run-smokes.py --suite full-public \
  --script examples/codex-app-thread-agent-identity-smoke.py --json
git diff --check
```

## Definition of Done

- Repeated `/loopx` calls in one Codex App task reuse one stable agent lane.
- The first explicit lane selection is durably bound and read back before any
  Todo write.
- Missing thread IDs and conflicting bindings remain fail closed without
  accidental peer creation.
- Fresh peer registration is explicit, verified, and separately attributable.
- CLI, packet, Skill, protocol, and tests express the same identity rule.
