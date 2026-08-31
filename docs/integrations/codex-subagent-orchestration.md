# Codex Peer Task Orchestration

LoopX supports two different concepts that must not be conflated:

- durable registered agents are equal peers;
- a host runtime may launch an ephemeral child worker for one bounded task.

No registered identity owns the goal. Claims, leases, task boundaries,
capabilities, and continuation policy decide who acts. When parallel work is
useful, LoopX may choose one temporary task coordinator from the participating
peers. That responsibility ends with the task bundle.

## Peer Runtime Contract

A registered identity uses `agent_model=peer_v1`. It has no rank-bearing role,
implicit review authority, or permanent writeback ownership. A task coordinator
may:

- activate or resume eligible peer lanes;
- issue complete briefs to ephemeral child workers;
- aggregate returned evidence;
- write accepted task-bundle state and account for the completed turn.

It does not own durable goal authority. Repository policy, explicit decision
scopes, and todo continuation still govern review, merge, publication, and
production actions.

## When To Parallelize

The default policy is adaptive orchestration, not a user-selected
`single-agent` or `multi-agent` mode. LoopX projects ready work and hard
boundaries; the task coordinator decides whether parallel execution shortens
the critical path, which todos to delegate, and which qualified host context to
use.

Parallelize when it reduces uncertainty or latency:

- map disjoint code, docs, test, or runtime surfaces;
- implement isolated slices in independent worktrees;
- run an independent review or validation pass;
- inspect separate adapter, evidence, or boundary questions.

Keep tightly coupled decisions in one peer lane. Do not launch workers merely
to make the activity graph look busy, and never let worker count override
quota, user gates, write scope, or repository policy.

### Adaptive Admission

`task_orchestration_contract_v2` admits ephemeral child work only when the
current runtime explicitly reports `subagent_spawn` through observed
capabilities and at least two coordinator-owned or unclaimed ready advancement
todos remain. A host name or scheduler runtime profile is metadata and never
supplies `subagent_spawn` or `subagent_resume`. Each candidate is checked
against:

- `task_domain` and the goal's `allowed_domains`;
- todo status, `resume_ready`, and open user dependencies;
- `required_capabilities` and observed host capabilities;
- canonical `task_repository` identity when declared (otherwise the goal
  repository remains authoritative); and
- goal-authorized, mutually non-overlapping `required_write_scopes`.

Rejected candidates remain visible in `blocked_lanes` with typed reason codes.
Ready lanes beyond `max_children` remain visible as `capacity_deferred`.
To stay inside the TurnEnvelope budget, the signed contract carries one shared
`child_brief_defaults` block plus a bounded per-lane delta. The typed host
request combines them into a complete `subagent_control_plane_handoff_v0`
brief. The coordinator may still keep the work serial; admission is permission
and capacity, not a command to spawn.

Without `subagent_spawn`, LoopX preserves the existing
`task_orchestration_contract_v1` registered-peer activation path. This keeps
long-lived peer identity, leases, worktrees, and multi-round collaboration
explicit instead of turning them into the default child-worker mechanism.

### Execution Topology Selection

Admission and execution topology are separate decisions. This section concerns
subagents that parallelize multiple Todos inside one registered agent lane. It
does not describe orchestration among multiple registered LoopX agents.

The coordinator records or consumes
`multi_agent_execution_topology_v0` before launch:

- `serial` keeps tightly coupled work in the current registered peer;
- `ephemeral_children` uses host children that end with the parent Turn and
  return held evidence or held local work to the same registered agent.

If the selected Todo describes an aggregate batch, the registered agent first
materializes one ordinary LoopX Todo per executable child lane. Host-side prose
decomposition is not a substitute: `task_orchestration_contract_v2` needs real
Todo candidates to admit.

The user or Goal policy defines the allowed envelope: child permission,
maximum concurrency, domains, repositories, scopes, effect classes, and user
gates. Inside that envelope, the coordinator decides whether parallelism is
useful, how many child lanes to run, and whether an admitted lane uses fresh
context, an explicitly allowed parent snapshot, or an existing child session. A
conversational "multi-agent is allowed"
must be converted into a typed current-Turn allowance or reviewed Goal policy;
the host tool's availability is not that authorization.

Capacity and effects are separate fail-closed invariants.
LoopX emits no operation for child lanes above `max_children` and records a
child-local `child_capacity_exceeded` pre-spawn rejection. If the host
nevertheless reports an extra worker, reconciliation classifies it as
`unadmitted_child_spawn` plus `orphaned_worker_result`.
`side_effect_boundary_exceeded` applies when an otherwise aligned child reports
an effect outside the envelope's `allowed_effect_classes`; an isolated
worktree does not make a remote effect permissible.

Prefer ephemeral children for bounded mapping, independent review, validation,
and disjoint local implementation. A child result remains held in its isolated
worktree until the registered agent validates and accepts it. Durable external
effects such as pushing a branch, changing a pull-request state, publishing,
deploying, or starting a monitor remain with that registered agent in v0.

Multiple registered LoopX agents remain equal peers and use the separate
`task_orchestration_contract_v1` path, with their own identities, Todo
ownership, liveness, and explicit peer activation. Subagent cards or host
workers must never be reclassified as peer agents.

The complete decision and reconciliation contract is
[`generic_multi_agent_execution_topology_v0`](../architecture/rfcs/generic-multi-agent-execution-topology-v0.md).
It is a generic kernel contract. Domain capabilities may supply work semantics
and validation, but must not add their own coordinator or scheduler.

## Fresh, Fork, Or Resume

The temporary task coordinator chooses a worker context from the work shape:

| Work type | Context | Required task brief |
| --- | --- | --- |
| Broad mapping, prior-art search, risk discovery | Fresh worker | Objective, authority source, allowed sources, boundary, expected output, non-goals |
| Independent review or adversarial validation | Fresh worker | Claim under review, exact evidence, child evidence expectations, acceptance and merge rules |
| Failed-smoke repair or review-comment follow-up | Resume or fork | Worktree, failing evidence, latest patch, next bounded repair |
| Disjoint local implementation whose result remains held | Fresh worker in an independent worktree | Admitted Todo, allowed paths, write scope, validation, held-result boundary |
| Branch push, PR mutation, publication, deployment, or later follow-up | Registered parent agent | Accepted child evidence, current Todo authority, workspace readback, and controlled writeback |
| Long-running claimed lane | Resume the registered peer task | Agent id, todo or lease, latest accepted evidence |
| Production action or emergency rollback | No automatic worker | Operator approval, stop condition, reversible command plan |

Fresh workers are useful only when the task coordinator can provide a complete
brief. Missing authority, scope, expected output, or validation is a planning
gap, not a reason to launch an under-specified worker.

Before launch, the Turn driver compiles the brief into
`child_execution_task_packet_v0`. The packet makes the delegated unit explicit:

- one Todo, objective, action kind, deliverable, and acceptance list;
- current authority and source-state references;
- allowed capabilities, write scopes, effects, workspace, and execution budget;
- the selected provider-neutral context mode and inheritance contract;
- an output contract and validation/parent-review mode; and
- `child_execution_guard_v0` fallback semantics.

Topology construction records `child_task_packet_incomplete` and emits no host
operation for that child when this packet cannot be formed. Other valid
children and the parent remain runnable; if no child qualifies, the parent
falls back to serial work. Each child receipt must return the exact
`task_packet_digest` and actual `context_mode`; mismatches become
`task_packet_mismatch` or `context_mode_mismatch`.

Context creation itself remains a Harness/host responsibility. LoopX signs the
provider-neutral mode and inheritance semantics, but neither the task packet nor
its digest contains Codex tool names or arguments:

- `fresh` means no parent-conversation inheritance;
- `forked_snapshot` means an explicitly admitted parent-conversation snapshot
  and is available only after the Harness observes `subagent_context_fork`;
- `resume` means continuation of an existing child session and is launchable
  only when the Harness also supplies that provider-owned child-session
  binding.

Fresh remains the default even when fork or resume is available. Todo
completion validation remains registered-parent work: the child packet carries
only a public-safe authority marker and never copies the validation command or
argv into the child handoff.

## Shared Control Plane Handoff

Every child-worker brief starts from the shared control plane. A worker must not
infer current authority from chat history, an old packet, or another worker's
summary.

The existing host-child packet name remains
`subagent_control_plane_handoff_v0` for compatibility. Its lineage fields do
not create durable rank:

- `parent_goal_id`: shared goal lineage, not an owner identity;
- `authority_artifact`: current goal, policy, or review authority;
- `latest_state_ref`: state hash, run id, or generated-at value to read first;
- `quota_gate_snapshot`: current eligibility, wait, or gate state;
- `evidence_boundary`: allowed sources, paths, and public/private rule;
- `writeback_spend_contract`: who may accept evidence and account for the turn;
- `child_guard_policy`: compact policy ref; currently `prevention_first_v0`.

Only then should the brief include todo id, work scope, expected artifact,
validation, and continuation policy. The compact rule is: child worker reports
evidence only; the temporary task coordinator writes accepted state and spends.

```yaml
subagent_control_plane_handoff_v0:
  parent_goal_id: example-peer-task-goal
  authority_artifact: .codex/goals/example-peer-task-goal/ACTIVE_GOAL_STATE.md
  latest_state_ref: state_hash_or_run_id
  quota_gate_snapshot: eligible
  evidence_boundary: public-safe read-only repository map
  writeback_spend_contract: child worker reports evidence only; task coordinator writes accepted state and spends
  child_guard_policy: prevention_first_v0
goal_id: example-peer-task-goal
todo_id: todo_docs_map
work_scope: inspect docs and return evidence paths
validation: cite files and residual risk; do not edit
continuation_policy: independent_handoff
```

After explicit capability admission, the signed Turn host request uses
legitimate host metadata only to map supported native context operations. The
host name does not admit child work. The task coordinator chooses from that
catalog:

- Codex exposes `fresh` and optional `forked_snapshot`; this slice does not
  expose `resume` because it has no provider-owned child-session binding;
- Claude Code exposes `fresh` through its native Task surface;
- generic adapters expose no child capability unless the adapter declares one.

The Harness adapter, outside the generic packet, maps those semantic modes to
native operations. The current Codex adapter maps `fresh` to
`spawn_agent(fork_context=false)`, `forked_snapshot` to
`spawn_agent(fork_context=true)`. A later Codex adapter may map `resume` to
`resume_agent` only after it can pass the required child-session id. The current
Claude adapter maps `fresh` to its native Task surface. These mappings do not
grant write, settlement, or peer authority and cannot change the task-packet
digest.

## Claims, Leases, And Worktrees

Registered peers claim work through LoopX todos and leases. The control plane
allows one pending lease for `(goal_id, todo_id)`. `goal_id` is the shared
control-plane lane; `todo_id` is the work item being claimed. A host child may
carry the claim context in its brief, but it does not become a ranked agent.

Repository-writing peers and child workers use independent worktrees. A
worktree proves filesystem isolation; it does not prove LoopX admission,
identity, claim, lease, session continuity, or external-effect authority.
Overlap is resolved through task boundaries and repository policy, not through
a permanent controller. Completion uses typed continuation:

- `independent_handoff`: leave the successor available to peers;
- `same_agent_non_delivery`: keep a non-delivery follow-up with the same peer.

Review remains `action_kind=review` over `independent_handoff`. Add the author
to `excluded_agents` only when the successor should stay open for eligible peers
but must not be reclaimed by that author.

## Child Execution Receipts And Reconciliation

Every child launch should return one compact
`multi_agent_host_execution_receipt_v0`. The receipt binds the observed host
worker to:

- `bundle_id`, `lane_id`, `goal_id`, and `todo_id`;
- the admitted execution kind;
- the source control-plane state revision;
- the exact `task_packet_digest`;
- the actual `context_mode`;
- an opaque workspace reference;
- typed effect classes and public-safe evidence references; and
- terminal status without raw transcript or tool output.

Child receipts must not invent an `agent_id`, peer claim, lease, or durable
session identity. The registered parent agent and each Todo remain
authoritative outside the receipt.

`multi_agent_control_plane_reconciliation_v0` compares the topology plan with
host receipts. Missing admission, stale lineage, task-packet mismatch,
context-mode mismatch, workspace mismatch, effect-boundary violations, missing
receipts, and orphaned results are typed child drift.

The Guard is fail-local. Aligned output remains candidate evidence until the
registered parent accepts it. Drifted, rejected, cancelled, duplicate, or
orphaned output is quarantined, and the projection recommends stopping only
that child. The reconciliation projection keeps `parent_blocked=false`; the
parent remains runnable and may retry fresh, replace the child, take over
serially, or ignore optional output. A required missing deliverable may leave
the parent's own acceptance unmet, but the child does not acquire authority to
block the parent runtime.

The current runtime enforces complete task packets before emitting a child
operation. It validates receipt-to-packet, context, workspace, and effect
observations, then projects evidence disposition and fallback. It does not yet
enforce evidence acceptance, live tool interception, or automatic host child
termination. Registered-peer session reconciliation remains outside this
child-worker contract.

Accordingly, `quarantined` is currently a typed reconciliation classification,
not proof that every downstream consumer has dropped the compact receipt. The
registered parent must exclude it from accepted evidence until a dedicated
evidence-acceptance owner enforces that transition.

## Enabling Bounded Orchestration

The feature remains opt-in:

```bash
loopx configure-goal \
  --goal-id example-peer-task-goal \
  --multi-subagent-feature enabled \
  --max-children 2 \
  --allowed-domain docs \
  --allowed-domain validation \
  --execute
```

`multi_subagent` remains the compatibility name for host child-worker capacity
and permission policy. It does not ask the user to select a run mode or agent
hierarchy. With observed host child capability, `quota should-run` may project
adaptive `task_orchestration_contract_v2`. Without that capability, it does not
fall back to coordinating registered peers: registration grants Todo ownership,
not cross-agent scheduling authority.

Use `--multi-subagent-feature off` to disable worker spawning. The low-level
`--orchestration-mode` and `--spawn-allowed` flags remain available for host
integrations.

## Explicit Registered-Peer Coordination

Registered peers are independent by default. LoopX never hashes the peer set or
open Todo bundle to auto-elect a coordinator. A host that can really activate
or resume durable peer runtimes may select one coordinator explicitly:

```bash
loopx configure-goal \
  --goal-id example-peer-task-goal \
  --peer-task-coordinator codex-alpha \
  --execute
```

The selected coordinator must then report the observed host capability on each
eligible turn:

```bash
loopx quota should-run \
  --goal-id example-peer-task-goal \
  --agent-id codex-alpha \
  --available-capability peer_agent_activation
```

The contract includes only peer lanes that are currently actionable. Dormant
registered agents and closed, blocked, or deferred todos are not coordinator
candidates. A dormant or non-resumable lane is projected under
`blocked_peer_lanes`; if no peer lane can run, the bundle has
`execution_state=blocked`,
`terminal_outcome=blocked`, and `retry_policy=material_peer_state_change_only`.
That blocked diagnostic does not replace the coordinator's own runnable lane or
re-arm an activation obligation on every heartbeat. If the coordinator also
has no in-scope runnable fallback, the final interaction mode is
`peer_coordination_blocked`: schedulers return the bundle to its owner and stop
the recurring heartbeat until peer capability/readiness, coordinator
configuration, or the coordinator's own work frontier materially changes.

Disable registered-peer coordination without changing peer registration or
child-worker policy:

```bash
loopx configure-goal \
  --goal-id example-peer-task-goal \
  --clear-peer-task-coordinator \
  --execute
```

This opt-in grants neither cross-owner Todo mutation nor broader repository,
publication, credential, or production authority. Read it back with
`loopx configure-goal --goal-id example-peer-task-goal` before relying on it.

## Run History And Observation

Run history should attribute task coordination without persisting rank:

```json
{
  "agent_model": "peer_v1",
  "task_coordinator": "codex-alpha",
  "control_plane_handoff_version": "subagent_control_plane_handoff_v0",
  "peer_lanes": [
    {"agent_id": "codex-beta", "todo_id": "todo_docs_map", "state": "completed"},
    {"agent_id": "codex-gamma", "todo_id": "todo_validation", "state": "running"}
  ],
  "accepted_evidence_count": 1,
  "next_action": "review the remaining validation evidence"
}
```

Useful observation surfaces include task bundle, participant peers, worker
context (`fresh`, `forked_snapshot`, or `resume`), accepted or rejected
evidence, leases, worktrees, quota state, and typed continuation. They must not
reconstruct a durable leader from a temporary coordination event.

The operator view should also distinguish planned from observed topology. Four
visible child cards prove host activity, not four registered LoopX peers. A
compliant view joins each card to its admitted lane and shows whether the work
is `aligned`, `incomplete`, `rejected`, or `drifted`.

## Safety Rules

- Do not spawn when quota or the selected user gate blocks the task.
- Do not spawn without a current admitted child lane, even when the host tool
  itself is available.
- Do not infer permissions from an agent name, profile label, or old prompt.
- Do not launch a fresh worker without a complete task brief.
- Do not put credentials, private links, raw logs, or production material in a
  public handoff packet.
- Keep implementation scopes disjoint and use independent worktrees.
- Keep durable external effects with the registered parent agent unless a later
  reviewed child contract explicitly admits a narrower effect class.
- Reconcile every planned lane and observed worker before aggregate completion
  or spend.
- Let repository policy decide review and merge; peer identity grants neither.
- Let one temporary coordinator accept bundle evidence and write one spend
  event after validated progress.

The result is parallel execution without a permanent leader: durable agents
remain peers, while task coordination and host-child relationships stay bounded
to the work that requires them.
