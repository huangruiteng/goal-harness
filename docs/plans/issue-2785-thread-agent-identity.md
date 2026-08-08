---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
---

# Fix Codex App Thread Agent Identity Reuse

## Goal

Make Codex App `/loopx` reuse the agent ID previously selected by the same stable host thread, while failing closed when the thread identity is absent or conflicting.

## Requirements

- Accept an optional stable, opaque host-provided thread ID.
- Persist a binding between host surface, goal ID, thread ID, and agent ID.
- Reuse an existing binding on later `/loopx` invocations.
- Propagate the resolved agent ID through `start-goal`, heartbeat, quota, refresh-state, and Todo commands.
- Never infer identity from registry order, the only registered agent, or task text.
- Missing thread IDs or missing bindings must require explicit lane selection.
- Conflicting bindings must fail closed without partial writes.
- Explicit new-peer intent must register and bind a fresh agent ID.
- Existing explicit `--agent-id` continuation behavior remains compatible.
- Preserve public-boundary and privacy guarantees for thread IDs.
- Add unit, contract, and synthetic end-to-end coverage.

PR #2773 only established fresh-agent defaults and is not a complete solution for this issue.

## Scope

### In scope

- Thread-ID validation and binding persistence.
- Project/global registry synchronization.
- Guided `start-goal` identity resolution.
- Codex App handoff packet and generated skill instructions.
- Identity-aware command propagation.
- Explicit binding/new-peer mutation flow.
- Unit tests and Codex App synthetic smoke coverage.

### Out of scope

- Changes to the Codex App host itself.
- Deriving identity from conversation text or registry ordering.
- Raw transcripts, credentials, filesystem paths, or private host metadata.
- Cross-runtime identity transfer.
- Automatic binding cleanup or expiration UI.

## Assumptions

- Codex App can expose a stable opaque thread/session identifier.
- Existing registry locking and global synchronization can carry the binding safely.
- Preview packets remain read-only; binding mutations require explicit execution.
- A binding is unique for `(host_surface, goal_id, thread_id)`.
- If Codex App cannot expose a stable thread ID, explicit `--agent-id` remains the safe fallback.

## Key Technical Decisions

### 1. Store bindings as structured registry metadata

Add a normalized `coordination.thread_agent_bindings` collection. Each record contains:

- `thread_id`
- `host_surface`
- `goal_id`
- `agent_id`
- schema/version metadata as needed

Use deterministic ordering and existing source/global registry synchronization.

### 2. Resolve identity before the current selection gate

Resolution order:

1. Validate and honor explicit `--agent-id`.
2. Resolve a matching thread binding.
3. If no binding exists, return a fail-closed selection gate.
4. Permit fresh registration only through explicit new-peer intent.

An existing binding must not be silently replaced. Conflicts produce a machine-readable error/gate.

### 3. Keep thread identity optional and host-owned

Add an optional `--thread-id` input and handoff field. Validate bounded opaque values and reject control characters or unsafe values. Do not synthesize IDs locally.

### 4. Separate binding preview from mutation

Guided start remains non-mutating. Add or extend an explicit command for binding a selected registered agent to a thread. Fresh registration plus binding must verify source and global readback before continuation.

### 5. Make new-peer intent explicit

The existing `register-agent --require-new` path remains the authority for fresh IDs. Natural-language task text and generic selection gates must never imply new-peer intent.

## Implementation Units

### U1. Add thread binding model and persistence

- **Files**
  - `loopx/agent_registry.py`
  - `loopx/global_registry.py`
  - `loopx/cli_commands/registry_admin.py`
  - `loopx/cli_commands/registry_admin_peer.py`
  - New: `loopx/thread_agent_binding.py`
- **Changes**
  - Validate and normalize opaque thread IDs.
  - Implement lookup, idempotent upsert, conflict detection, and removal helpers.
  - Scope bindings by goal and host surface.
  - Reuse existing lock and global-sync paths.
  - Default missing binding collections safely for legacy registries.
- **Acceptance**
  - Invalid IDs are rejected.
  - Repeating an identical bind is idempotent.
  - Conflicting binds fail without partial source/global writes.
  - Existing registries without bindings remain readable.

### U2. Make host-loop identity resolution thread-aware

- **Files**
  - `loopx/host_loop_activation.py`
  - `loopx/bootstrap_command_pack.py`
  - `loopx/agent_onboarding.py`
- **Changes**
  - Pass thread context into identity resolution.
  - Resolve an existing binding before emitting `selection_required`.
  - Add machine-readable binding source/state/conflict fields.
  - Update gate copy to state that users must select an existing lane and must not register a new one unless explicitly requesting a new peer.
  - Include bind-thread continuation actions where required.
- **Acceptance**
  - A bound thread selects its existing agent without a gate.
  - Missing thread ID or missing binding remains fail-closed.
  - Explicit valid `--agent-id` remains authoritative.
  - Conflicts prevent activation.

### U3. Propagate thread identity through CLI and packets

- **Files**
  - `loopx/cli_commands/starter_bootstrap_registration.py`
  - `loopx/cli_commands/starter_bootstrap.py`
  - `loopx/bootstrap_command_pack.py`
  - `loopx/project_prompt.py`
- **Changes**
  - Add optional `--thread-id` to guided `start-goal` and relevant binding/onboarding paths.
  - Preserve thread ID through rerun commands and packet builders.
  - Ensure generated heartbeat, quota, refresh-state, and Todo commands retain resolved `--agent-id`.
  - Keep legacy command output unchanged when no thread ID is supplied.
- **Acceptance**
  - JSON and Markdown packets agree.
  - Rerun commands preserve goal, host, thread, and agent identity.
  - Existing callers without `--thread-id` remain compatible.

### U4. Add explicit binding mutation flow

- **Files**
  - `loopx/cli_commands/registry_admin.py`
  - `loopx/cli_commands/registry_admin_peer.py`
  - `loopx/cli_commands/starter_bootstrap_registration.py`
  - Relevant registry-admin tests
- **Changes**
  - Add a clearly named bind-thread command or equivalent explicit registration subcommand.
  - Require the target agent to already be registered.
  - Support preview and `--execute` modes.
  - Make fresh registration plus binding collision-safe and verify source/global readback.
- **Acceptance**
  - Existing-lane selection binds without creating an agent.
  - Explicit new-peer flow creates and binds a fresh ID.
  - Preview never mutates.
  - Registration and binding results report verified synchronization.

### U5. Update Codex skill and host protocol

- **Files**
  - `skills/loopx-project/SKILL.md`
  - `docs/reference/protocols/codex-app-host-command-registry-v0.md`
  - `docs/reference/protocols/loopx-goal-command-v0.md`
  - `docs/guides/getting-started.md`
- **Changes**
  - Document the optional host-provided opaque thread ID.
  - Require same-thread invocations to reuse the stored agent ID.
  - Require identity propagation on heartbeat, quota, refresh, and Todo commands.
  - Clarify fail-closed behavior when identity is unavailable.
  - Document explicit new-peer behavior and privacy limits.
- **Acceptance**
  - No documentation implies takeover from registry order.
  - Handoff schema and skill guidance agree.
  - Existing skill metadata/install tests remain valid.

### U6. Add focused tests

- **Files**
  - New: `tests/test_thread_agent_binding.py`
  - `tests/control_plane/test_start_goal_compact_projection.py`
  - `tests/test_host_loop_activation.py`
  - `tests/test_register_agent_fresh_identity.py`
- **Changes**
  - Cover valid/invalid IDs, missing bindings, binding reuse, missing thread IDs, explicit overrides, conflicts, idempotent binding, fresh registration, packet parity, and command identity propagation.
- **Acceptance**
  - Tests assert machine-readable payloads and user-visible gate text.
  - Existing fresh-identity tests from PR #2773 continue passing.

### U7. Add synthetic Codex App end-to-end smoke

- **Files**
  - New: `examples/codex-app-thread-agent-identity-smoke.py`
  - `loopx/canary/quality_surface_catalog.py` if required by catalog conventions
- **Changes**
  - Build a temporary project with two registered agents.
  - Bind `thread-a` to agent A through explicit selection.
  - Invoke a second `/loopx` for `thread-a` without `--agent-id`; assert agent A is reused and no registration gate appears.
  - Invoke an unbound thread; assert fail-closed existing-lane guidance and no implicit registration.
  - Exercise explicit new-peer registration and assert a fresh bound ID.
  - Verify generated heartbeat, quota, refresh, and Todo commands contain the selected ID.
- **Acceptance**
  - Runs without Codex credentials or real host mutation.
  - Proves positive same-thread reuse and negative fail-closed behavior.

### U8. Complete validation

- **Files**
  - No production files; validation only.
- **Changes**
  - Run focused tests, smoke tests, full suite, compile checks, diff checks, and public-boundary checks.
  - Run optional real-host validation only if a stable Codex App thread ID is available.
- **Acceptance**
  - All targeted and full tests pass.
  - No generated command loses `--agent-id`.
  - Existing host and onboarding behavior does not regress.
  - Any unavailable real-host capability is explicitly documented.

## Verification Contract

Run at minimum:

```bash
pytest -q \
  tests/test_thread_agent_binding.py \
  tests/test_host_loop_activation.py \
  tests/control_plane/test_start_goal_compact_projection.py \
  tests/test_register_agent_fresh_identity.py

python examples/codex-app-thread-agent-identity-smoke.py
python examples/bootstrap-command-pack-smoke.py
python examples/control_plane/agent-onboard-host-loop-activation-smoke.py

pytest -q
python -m compileall loopx
git diff --check
```

The synthetic smoke must prove:

- Same-thread repeated `/loopx` calls reuse the first agent.
- A different thread does not inherit that binding.
- Missing thread identity does not create a new lane.
- Explicit new-peer intent creates and binds a fresh ID.
- All generated state and accounting commands remain agent-scoped.

## Dependencies

- U2 depends on U1.
- U3 depends on U1 and U2.
- U4 depends on U1.
- U5 depends on finalized U2/U3 packet fields.
- U6 depends on U1–U4.
- U7 depends on U1–U5.
- U8 depends on all implementation units.

## Risks

- **Codex App capability:** Without a stable host thread ID, automatic reuse cannot be guaranteed.
- **Registry migration:** Legacy registries may lack the new collection and must default safely.
- **Collision safety:** Reused or malformed IDs could select the wrong lane; conflicts must fail closed.
- **Concurrency:** Registration and binding must share one bounded lock transaction.
- **Privacy:** Thread IDs must not expose transcripts, paths, credentials, or private host metadata.
- **Compatibility:** Optional CLI fields must not alter explicit-agent or legacy unscoped behavior.
- **Global synchronization:** Source and global registries must not diverge after a successful bind.

## Definition of Done

- Thread-aware bindings are persisted and synchronized safely.
- Same-thread Codex App `/loopx` calls reuse the selected agent without a new identity gate.
- Missing or conflicting identity fails closed with explicit guidance.
- Explicit new-peer requests create and bind fresh IDs.
- Skill, protocol, packet, CLI, unit tests, and synthetic smoke are updated.
- Focused tests, full suite, smoke tests, compile checks, and diff/public-boundary checks pass.
- No unrelated behavior or scope is changed.