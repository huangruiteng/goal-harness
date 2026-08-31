# Agent-Lane Subagent Execution Topology v0

Status: Draft

## TL;DR

- **Scope:** this contract governs ephemeral subagents that parallelize
  multiple admitted Todos inside one registered agent lane.
  This contract does not coordinate multiple registered LoopX agents. A host
  child never becomes a LoopX peer.
- **Delegation:** the registered parent chooses serial or parallel execution
  inside the human- or Goal-approved envelope. LoopX emits a child operation
  only after objective, acceptance, authority and state refs, capabilities,
  write/effect/workspace boundaries, budget, context, output, validation
  ownership, and fallback form a complete typed task packet.
- **LoopX versus Harness:** LoopX signs provider-neutral task, context, and
  authority semantics and reconciles compact receipts. The Harness owns native
  `spawn_agent`, Task, fork, and resume operations. `fresh` is the default;
  `forked_snapshot` is capability-gated; `resume` is unavailable until the
  provider supplies the required child-session binding.
- **Authority:** the registered parent keeps LoopX identity, Todo completion
  validation, evidence acceptance, durable remote effects, writeback, quota,
  and settlement responsibility. Child packets never copy parent-owned
  validation commands or argv.
- **Drift handling:** prevention starts before launch. An incomplete,
  unsupported, or over-capacity child is not started. A receipt that disagrees
  with its packet, context, workspace, or effect boundary quarantines only that
  child's evidence; valid siblings and the parent remain runnable.
- **Current enforcement:** v0 enforces pre-spawn packet qualification and
  validates receipt bindings. Stop/quarantine/fallback are projected for the
  parent; live tool interception, automatic child termination, and automatic
  evidence-acceptance enforcement still require a consuming Host or settlement
  adapter. The contract stays domain-neutral rather than creating an Auto
  Research, Deep Research, issue-fix, or benchmark-specific runtime.

## Decision

Adopt one domain-neutral, prevention-first child execution contract for
parallel work inside a registered agent lane, while keeping registered-peer
orchestration and Host-native lifecycle mechanics in their existing owners.

## Problem

LoopX already has the two distinct orchestration layers:

- `task_orchestration_contract_v2` admits bounded ephemeral child lanes;
- `task_orchestration_contract_v1` describes explicitly coordinated registered
  peers;
- Todo claims and task leases own durable work;
- session-runtime projections identify visible runtime sessions;
- controlled writeback preserves LoopX as the durable authority;
- independent worktrees isolate repository-writing lanes.

This RFC concerns only the first layer. The missing seam is end-to-end
accountability for child workers inside one agent lane. A host can still launch
children directly, assign broad work, and later let the registered agent
summarize all results under one aggregate Todo. The code changes may be valid
and the worktrees may be isolated, but LoopX cannot prove:

- that child execution was admitted by the current quota decision;
- which Todo and state revision each worker received;
- which workspace and external effects belong to each lane;
- whether every returned result was accepted, rejected, or left orphaned; or
- whether the aggregate completion describes the work that actually happened.

That is work/control-plane drift. It is not fixed by adding more agents, a
research-specific scheduler, or a second task store.

Registered-peer coordination is a separate concern. It uses
`task_orchestration_contract_v1`, registered `peer_v1` identities, Todo
ownership, session liveness, and explicit peer activation. A host child never
becomes a LoopX peer merely because it appears as another card or process.

## Placement

- **Capability id:** none. This is a kernel execution contract, not a
  user-facing capability.
- **Control-plane owner:** existing child admission and
  `loopx/control_plane/turn_driver/` task-packet, receipt, and reconciliation
  code. The relocated `demo/multi_agent/` package is a source-checkout showcase
  and does not own this shipped Turn contract.
- **Provider owner:** each host adapter owns child lifecycle and emits
  observations. A provider that supports live tool interception also enforces
  the packet's tool/effect boundary, but it does not own Goal, Todo, quota, or
  acceptance truth.
- **Domain capabilities:** may supply task semantics, expected artifacts, and
  validation, but must not define their own coordinator, scheduler, or child
  lifecycle.

The nearest existing owner is sufficient. No `auto-research`,
`deep-research`, issue-fix, or benchmark-specific orchestration module is
needed.

## Agent-Lane Execution Topologies

The registered agent selects the least complex topology that can advance its
current Todo frontier without losing attribution or authority.

| Topology | Use when | Control-plane identity | Allowed effects |
| --- | --- | --- | --- |
| `serial` | Fewer than two independent ready lanes exist, scopes overlap, or coordination cost exceeds the expected gain. | Current registered peer and selected Todo. | Existing Todo and Turn boundaries. |
| `ephemeral_children` | At least two independent Todos belong to the same agent lane and can finish inside the parent Turn or return held work for parent acceptance. | One registered agent identity plus one admitted child lane per Todo; children are not LoopX agents. | Effects admitted by the child contract. In v0, durable remote effects stay with the registered agent after child result acceptance. |

Examples:

- repository mapping and an independent validation Todo in the same agent lane
  can use ephemeral children;
- two disjoint implementation Todos can use separate child worktrees while the
  registered agent retains final validation, push, review-request, and
  writeback ownership;
- a child that cannot finish returns held evidence or a held patch; the
  registered agent resumes the Todo or performs the authorized durable effect;
- multiple registered LoopX agents cooperating on separate long-lived lanes
  use the peer orchestration contract, not this topology.

## Boundary Versus Strategy

Human or Goal policy defines the execution envelope:

- whether child spawning is allowed;
- maximum concurrency and cost;
- allowed task domains, repositories, write scopes, and effect classes;
- whether a current-turn allowance expires with the Turn or persists on the
  Goal; and
- which actions still require a user gate.

Inside that envelope, the coordinator owns strategy:

- whether parallelism is useful now;
- how many lanes to run;
- which admitted lane remains local;
- whether an eligible child uses fresh context, an explicitly allowed parent
  snapshot, or an existing child session; and
- when to stop, retry, reject, or reconcile.

A natural-language statement that multi-agent work is acceptable is not itself
a host launch receipt. The command or UI boundary should convert explicit user
intent into a typed current-Turn allowance or a reviewed Goal policy update.
Until that typed envelope exists, the host may advertise `subagent_spawn`, but
LoopX still admits no child lane.

## Topology Plan

`multi_agent_execution_topology_v0` is the compatibility schema name used by
the current host observation slice. Semantically it is a read model for
subagent execution inside one registered agent lane. It does not model
registered-peer orchestration, replace admission, or create new authority.

```json
{
  "schema_version": "multi_agent_execution_topology_v0",
  "goal_id": "example-goal",
  "bundle_id": "bundle_7d2f",
  "coordinator_agent_id": "codex-maintainer",
  "source_state_ref": "sha256:current-control-plane-state",
  "topology": "ephemeral_children",
  "execution_envelope": {
    "source": "goal_policy_or_current_turn_authorization",
    "expires_with_turn": true,
    "max_children": 2,
    "allowed_effect_classes": ["local_read", "held_workspace_write"]
  },
  "rationale_codes": [
    "parallel_independent_todos"
  ],
  "lanes": [
    {
      "lane_id": "lane-review",
      "todo_id": "todo_review",
      "execution_kind": "ephemeral_child",
      "admission_ref": "task_orchestration_contract_v2:todo_review",
      "effect_boundary": "held_evidence_only",
      "allowed_effect_classes": ["local_read"],
      "workspace_requirement": "not_required",
      "workspace_ref": null,
      "task_packet_digest": "sha256:child-task-packet",
      "task_packet": {
        "schema_version": "child_execution_task_packet_v0",
        "todo_id": "todo_review",
        "objective": "Review one admitted pull-request head.",
        "action_kind": "review",
        "target_key": null,
        "deliverable": "public_safe_evidence",
        "acceptance": [
          "report completed scope and evidence",
          "do not write LoopX state or spend quota"
        ],
        "context_refs": [
          "quota_should_run.goal_boundary",
          "quota_should_run.action_signature.source_hash",
          "sha256:current-control-plane-state"
        ],
        "task_domain": "review",
        "task_repository": null,
        "allowed_capabilities": [],
        "allowed_write_scopes": [],
        "allowed_effect_classes": ["local_read"],
        "forbidden_effect_classes": [
          "credential_use",
          "external_write",
          "held_workspace_write",
          "monitor",
          "network_read",
          "production_action"
        ],
        "workspace_requirement": "not_required",
        "workspace_ref": null,
        "context": {
          "mode": "fresh",
          "inheritance": "none"
        },
        "execution_budget": {
          "timeout": "bounded_by_host_turn",
          "cancel": "task_coordinator_or_host_timeout"
        },
        "output_contract": "public_safe_evidence",
        "acceptance_mode": "parent_review_only",
        "validation": {
          "declared": false,
          "authority_ref": null,
          "execution_owner": "registered_parent",
          "command_disclosed": false,
          "label": null,
          "policy": "child reports evidence; parent runs declared todo gate"
        },
        "guard": {
          "schema_version": "child_execution_guard_v0",
          "pre_spawn": "require_complete_task_packet",
          "on_deviation": "project_stop_and_quarantine_child",
          "evidence_disposition": "candidate_until_parent_accepts",
          "parent_blocked": false,
          "parent_continuation": "continue",
          "fallback_actions": [
            "retry_fresh",
            "replace_child",
            "serial_takeover",
            "ignore_optional_result"
          ]
        }
      }
    }
  ]
}
```

The plan must reference, not copy, the authoritative admission:

- an aggregate Todo must first materialize one existing Todo per executable
  lane; free-form decomposition inside the host is not an admitted bundle;
- an ephemeral lane references an admitted
  `task_orchestration_contract_v2` child;
- a serial lane references the selected Turn Todo;
- the execution envelope references typed user/Goal policy rather than inferred
  chat permission; and
- absence of the required admission makes the lane non-executable.

`task_orchestration_contract_v1` remains the separate contract for registered
peer agents. Its lanes must not be inserted into this child topology.

The coordinator may choose a more conservative topology than the plan permits.
It may not choose a more powerful one.

## Child Execution Guard

Drift prevention starts when the registered agent delegates the Todo, not when
the child finishes. Before launch, LoopX must compile one
`child_execution_task_packet_v0` from the admitted Todo and shared handoff
defaults. The packet is launchable only when it contains:

- one `todo_id`, objective, `action_kind`, deliverable, and acceptance list;
- current authority and source-state references;
- explicit allowed capabilities, write scopes, effect classes, workspace
  requirement, and execution budget;
- a provider-neutral selected context mode and inheritance contract;
- an output contract plus either a public-safe marker for parent-owned Todo
  completion validation or `acceptance_mode=parent_review_only`; and
- `child_execution_guard_v0` with local failure handling and parent fallback.

Missing or contradictory fields produce a child-local pre-spawn rejection with
`child_task_packet_incomplete`; no host operation is emitted for that child.
Other valid children and the parent Turn remain runnable. When every child is
rejected, the topology falls back to `serial`. Capacity overflow is handled the
same way with `child_capacity_exceeded`. Each accepted packet is hashed, and
the exact `task_packet_digest` must be returned in the child receipt. A
mismatched digest is `task_packet_mismatch`.

Context creation is a Harness/host capability, not a LoopX control-plane
implementation. LoopX signs only the provider-neutral context contract and
validates the observation:

- `fresh` is the default and means `inheritance=none`;
- `forked_snapshot` is exposed only when the runtime reports
  `subagent_context_fork` and means
  `inheritance=parent_conversation_snapshot`;
- `resume` means `inheritance=existing_child_session`, but a Harness adapter
  may expose it only when it also has the provider-owned child session binding
  required by the native resume operation.

The Harness adapter owns the native mapping outside the task packet. The Codex
adapter currently maps `fresh` to `spawn_agent(fork_context=false)` and
`forked_snapshot` to `spawn_agent(fork_context=true)`. It does not currently
advertise `resume`, because this slice has no child-session binding to pass to
`resume_agent`. Another host may use different primitives without changing the
packet digest.

Todo completion validation remains a registered-parent responsibility. The
task packet carries only a public-safe validation marker, an opaque authority
reference derived from the Todo id, and `command_disclosed=false`; it never
copies the private command or argv into the child handoff.

The receipt records the actual `context_mode`. A mismatch between planned and
observed context is `context_mode_mismatch` and quarantines that child's
evidence.

The Guard is intentionally fail-local:

- aligned output remains candidate evidence until the parent accepts it;
- drifted, rejected, cancelled, duplicate, or orphaned output is quarantined;
- the recommended child disposition may be `stop_child` or `wait_for_child`;
- `parent_blocked` remains `false` and `parent_continuation` remains
  `continue`; and
- the parent may `retry_fresh`, `replace_child`, `serial_takeover`, or
  `ignore_optional_result`.

The current runtime enforces task-packet completeness before emitting each
child operation. It validates receipt-to-packet, context, workspace, and effect
observations, then projects evidence disposition and fallback to the parent.
It does not yet enforce evidence acceptance, live tool interception, or
automatic host child termination; those require a consuming host or settlement
adapter and are not claimed by this slice.

In this slice, `evidence_disposition=quarantined` is a reconciliation
classification. The normalized host result still retains the compact receipt;
the registered parent must not accept that evidence, but automatic removal from
every downstream consumer waits for an explicit evidence-acceptance owner.

## Host Execution Receipt

Every launched child returns one
`multi_agent_host_execution_receipt_v0`:

```json
{
  "schema_version": "multi_agent_host_execution_receipt_v0",
  "bundle_id": "bundle_7d2f",
  "lane_id": "lane-review",
  "goal_id": "example-goal",
  "todo_id": "todo_review",
  "execution_kind": "ephemeral_child",
  "runtime_id": "codex_app",
  "worker_ref": "opaque-host-worker-ref",
  "source_state_ref": "sha256:current-control-plane-state",
  "task_packet_digest": "sha256:child-task-packet",
  "context_mode": "fresh",
  "workspace_ref": "opaque-workspace-ref",
  "status": "completed",
  "effect_classes": ["local_read"],
  "evidence_refs": ["artifact:review-summary"],
  "raw_transcript_copied": false
}
```

The registered parent agent is identified by the topology plan and current
Turn. The child receipt has no `agent_id`, peer claim, lease, or durable
session identity; `worker_ref` is only a host observation and grants no LoopX
identity.

Receipts contain compact refs and typed effect classes, never raw prompts,
transcripts, tool output, credentials, private links, or local absolute paths.

## Reconciliation

`multi_agent_control_plane_reconciliation_v0` compares the topology plan with
host receipts and projects which child evidence may be shown to the registered
parent for acceptance.

The read model classifies each lane as:

- `aligned`: admitted execution, current lineage, expected packet,
  workspace/effects, and candidate evidence;
- `incomplete`: admitted work is still running or has no terminal receipt;
- `rejected`: the registered agent inspected the result and did not accept it;
- `cancelled`: the child was intentionally stopped and its evidence remains
  quarantined;
- `drifted`: observed execution contradicts the admitted topology or authority.

Required drift reason codes:

- `unadmitted_child_spawn`;
- `aggregate_todo_not_decomposed`;
- `child_capacity_exceeded`;
- `execution_kind_mismatch`;
- `missing_todo_lineage`;
- `source_state_stale`;
- `task_packet_mismatch`;
- `context_mode_mismatch`;
- `workspace_mismatch`;
- `side_effect_boundary_exceeded`;
- `worker_receipt_missing`;
- `orphaned_worker_result`;
- `aggregate_settlement_without_lane_evidence`.

The reconciliation result is an evidence-admission and child-recovery read
model, not a second work ledger. Existing Todos, parent reasoning, and Turn
settlement remain authoritative. A child result never becomes accepted evidence
without parent review.

Capacity and effect limits are independent parts of the execution envelope.
Capacity fails closed before launch: topology construction emits no operation
for child lanes above `max_children` and records
`child_capacity_exceeded`. A host-reported extra worker is instead
`unadmitted_child_spawn` plus
`orphaned_worker_result`. An otherwise aligned receipt that reports an effect
outside `allowed_effect_classes` becomes child-local drift and its evidence is
quarantined.

## Existing Owner Map

The first runtime implementation should extend these owners rather than create
a parallel orchestration stack:

| Concern | Existing owner | Required change |
| --- | --- | --- |
| Child admission | `control_plane/quota/task_orchestration_admission.py` | Supply compact shared Guard policy and Todo-derived task facts; keep domain names out. |
| Task-packet guard | `control_plane/turn_driver/child_execution_topology.py` | Reject only the invalid child before launch unless objective, acceptance, context, scope, effects, budget, output, and fallback are complete; bind packet and context observations to the receipt. |
| Host operation planning | `control_plane/turn_driver/driver.py` | Emit only Guard-qualified provider-neutral operations, default to clean child context, and carry stable bundle/lane/task-packet correlation. |
| Harness adapter mapping | `control_plane/turn_driver/child_host_adapter.py` plus each concrete host runner | Translate supported semantic modes into host-native operations and arguments without changing the generic task packet; expose `resume` only with a provider-owned child-session binding. |
| Parent work ownership | Existing Todo, workspace guard, and continuation contracts | Keep final acceptance and durable effects with the registered agent; do not recreate ownership in child adapters. |
| Child execution | Host adapters | Execute the packet, return opaque worker/workspace facts and typed effects, and enforce live tool boundaries when supported. |
| Reconciliation projection | `control_plane/turn_driver/child_execution_topology.py` | Join planned lanes and observed receipts, quarantine drifting evidence, and project child-local recovery without mutating Todo state. |
| Parent continuation | Registered parent agent plus existing Todo/Turn owners | Continue independently of child drift; accept evidence, retry, replace, take over serially, or ignore optional output. |
| Operator display | `agent_management_projection_v0` and the local Agent workspace | Render planned versus observed topology and drift; never become a dispatcher or source of truth. |

This Guard does not add a global child barrier to TypeScript settlement.
Parent completion remains governed by the parent's own Todo acceptance and
evidence. A parent that still needs a child deliverable has an unmet acceptance
condition; the child does not acquire authority to block the parent runtime.

## Failure And Repair

When drift is detected:

1. stop or quarantine only the affected child when the host supports that
   lifecycle action;
2. do not launch an incomplete task packet or retroactively register a child as
   a peer;
3. retain only compact receipts and quarantine the child's evidence refs;
4. independently read back any durable external effect before accepting it;
5. keep the registered parent and unaffected children runnable;
6. let the parent retry fresh, replace the child, take the Todo back serially,
   ignore optional output, or explicitly hand off long-lived work through the
   separate peer contract; and
7. complete the parent Todo only when the parent's own acceptance is satisfied,
   not because every child produced a successful result.

An already-valid repository result may remain useful after independent
readback. That does not make the original execution topology compliant.

## Generalized Four-Lane Case

A registered agent owns one aggregate pull-request repair Todo and should first
materialize four child-eligible Todos. It then launches four host children in
separate worktrees:

- two children validate exact heads and return evidence;
- two children rebase and repair branches but leave the resulting commits held
  in their worktrees;
- the registered agent validates the returned evidence and commits, performs
  any authorized remote branch or pull-request effects, and settles each Todo.

The worktree isolation is real, and the code outcomes may be valid. The
topology is still drifted when:

- the Goal projects `spawn_allowed=false` or no
  `task_orchestration_contract_v2`;
- the aggregate Todo was not decomposed into four LoopX Todo lanes before
  launch;
- no child lane is bound to an admitted Todo;
- child briefs permit durable remote effects outside the admitted child
  boundary; and
- only the aggregate completion appears in LoopX.

The correction is not to call the children LoopX agents. The aggregate work
must become four Todos in the same agent lane, each child must reference one
admitted Todo and return a receipt, and durable remote effects remain with the
registered agent. If a Todo truly needs an independent long-lived LoopX agent,
that Todo leaves this subagent topology and enters the separate peer
orchestration contract.

## Implementation Slices

### Slice 0: contract and characterization

- document topology selection and reconciliation;
- add a public synthetic four-lane fixture or contract smoke;
- record the real incident only in ignored/local LoopX evidence.

This slice itself introduced no runtime behavior.

### Slice 1: observation and prevention-first Guard

- let host adapters emit compact child execution receipts;
- require a complete typed task packet before launch;
- make clean child context explicit and inherited context capability-gated;
- bind receipts to the exact task-packet digest and context mode;
- quarantine drifting evidence while keeping the parent runnable;
- join receipts to the current topology, Todo, workspace, and state revision;
- expose drift in status and the local Agent workspace;
- do not add a parent settlement barrier.

### Slice 2: live host containment

- enforce tool, write-scope, effect, timeout, and cancellation boundaries in
  host adapters;
- stop a deviating child before it can continue spending work;
- preserve typed fallback to retry, replacement, or serial takeover; and
- never convert host containment into parent-agent authority.

### Slice 3: operator experience

- show planned versus observed child lanes, workspace, status,
  effects, candidate evidence, quarantined evidence, and parent fallback;
- allow the operator to inspect or cancel through existing typed actions;
- keep the UI a projection, never a dispatcher or second source of truth.

## Non-Goals

- a research-specific coordinator or worker protocol;
- registered-peer orchestration, session activation, or peer recovery;
- a second scheduler, task store, evidence store, or Agent hierarchy;
- automatic coordinator election for registered peers;
- raw host transcript ingestion;
- direct UI mutation of Todos or settlement;
- a broad TypeScript rewrite before a second runtime consumer exists.

## Acceptance

The design is ready for runtime implementation only when:

1. a host cannot claim compliant child execution without a current admitted
   child lane;
2. every child lane belongs to one registered agent lane and one admitted Todo;
3. every launched child has a complete typed task packet; clean context is the
   default; and every receipt binds its exact digest and context mode;
4. every observed worker maps to exactly one planned child lane;
5. stale state, missing receipts, task-packet mismatch, workspace mismatch, and
   effect-boundary violations quarantine only the affected evidence;
6. child drift never blocks the registered parent from fallback or unrelated
   work, and child output still requires parent acceptance;
7. Auto Research, Deep Research, Issue Fix, and future products can supply
   domain Todos without importing or forking child orchestration mechanics;
   registered-peer coordination remains separately owned; and
8. the public projection remains compact and contains no raw transcript,
   credential, private link, or local absolute path.
