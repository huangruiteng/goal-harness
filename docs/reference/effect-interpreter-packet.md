# Effect Interpreter Packet

This page documents the canonical read lens for `quota should-run`:

```text
effect_request -> interpretation -> observation -> next_effect
```

It does not add a new runtime contract. It names the existing packet fields
that already play each role.

## Code Lens

`loopx.control_plane.effect_program.interpret_quota_should_run_packet` maps an
existing `quota should-run` packet onto the canonical slots, and
`interpret_turn_result_packet` maps an existing `loopx_turn_result_v0` packet:

- `EffectRequest`
- `EffectInterpretation`
- `EffectObservation`
- `EffectNext`
- `EffectTurn`

Both functions are intentionally read-only. They do not replace quota
decision or turn-settlement logic; they give refactor and test code one
stable abstraction for reading the effect program shape across packet
families.

## Canonical Example

### 1. Effect Request

The agent or host proposes the next bounded turn. The inputs include:

- `goal_id`
- `agent_id`
- `available_capabilities`
- host surface and scheduler execution context
- current host RRULE where relevant

### 2. Interpretation

The harness interprets the request through:

| Packet field | Role |
|---|---|
| `work_lane_contract.lane` | Route: advancement, monitor, gate, or wait |
| `work_lane_contract.obligation` | What the selected route must do |
| `interaction_contract.mode` | The host-facing interaction mode |
| `capability_gate.action` | Capability decision when a gate is present |
| `scheduler_hint.cadence_class` | Timing decision for the next host wake |

### 3. Observation

The decision is returned as:

| Packet field | Role |
|---|---|
| `decision` | Run, skip, observe, or repair |
| `should_run` | Whether compute is allowed |
| `effective_action` | Machine-visible effective action |
| `recommended_action` | Next concrete action text |
| `protocol_action_packet.summary` | Compact actor-facing summary |

### 4. Next Effect

The observation points back into the loop:

| Packet field | Role |
|---|---|
| `interaction_contract.cli_channel.next_cli_actions` | Next CLI effects |
| `execution_mode` | Execution strategy (`serial` / `parallel` / `interleaved`) for an ordered effect program |
| `scheduler_hint.action` | Scheduler around decision |
| `scheduler_hint.cadence_class` | Cadence for the next host wake |
| `scheduler_hint.codex_app.ack_hint.cli_args` | Host ACK effect |
| `scheduler_hint.codex_app.failure_hint.cli_args` | Host failure effect |

`EffectTurn.next_effect` is the code lens for this slot. It keeps the
data-encoded handler visible: the host invokes the CLI actions and settles
success or failure through the ACK/failure hints instead of LoopX holding a
callable across turns. `execution_mode` is the data-encoded strategy when the
next effect is an ordered effect program; it defaults to `None` when the
packet does not declare one.

## Around Semantics

`capability_gate`, `interaction_contract`, `work_lane_contract`, and
`scheduler_hint` are around decisions over the canonical effect step, not
separate feature modules:

| Around layer | Can short-circuit | Can rewrite |
|---|---|---|
| `capability_gate` | `ask_owner`, `repair_bridge`, `unsupported` | Repair todo and next CLI actions |
| `interaction_contract` | `action_required`, `mode` | Primary/protocol action and notification |
| `work_lane_contract` | Monitor/inbox preemption, `must_attempt_work=false` | Lane, obligation, `next_lane` |
| `scheduler_hint` | Pause/delete heartbeat, no-spend quiet | RRULE, cadence, stateful backoff |

The ordering and effect semantics are contracts. A capability gate must not be
collapsed into a generic exception handler: `owner_missing`,
`repair_missing`, and `decision_owner` stay visible because `ask_owner` and
`repair_bridge` lead to different next effects.

A CLI packet is a higher-density effect than a single tool call: one command
can carry permission, budget, validation, execution, failure semantics, ACK,
and writeback. Vendor serial or interleaved tool APIs are execution modes
inside the interpreter, not new state machines.

## Ordered Effect Program

`loopx.control_plane.effect_program.effect_program_from_ordered_steps` maps an
existing `guided_transaction.ordered_steps` value onto `EffectProgram`:

- `EffectStep` keeps `step_id`, `kind`, `command`, and `purpose`;
- `EffectProgram` keeps ordered steps and an optional `execution_mode`.

This is still a read-only lens. The executor remains host-driven until a
LoopX runtime caller owns multi-step execution.

## Relationship To State Machines

Each state family is an interpretation table over this lens:

```text
input effect -> interpreter -> decision -> observation -> next effect
```

See the
[Agent Loop Effect Interpreter RFC](../architecture/rfcs/agent-loop-effect-interpreter-v0.md)
and
[Harness Is the Effectful Program](../development/control-plane-course/01-agent-loop-effectful-program.md).
The public framing comes from 齐梦星空,
[主线一：Agent Loop 是 effectful program(1)](https://www.xiaohongshu.com/discovery/item/6a01d501000000003700c5de?source=webshare&xhsshare=pc_web&xsec_token=ABqpNuladcxhev099wLKw8M3ilhKBua0BQXNpxnBZEGkc=&xsec_source=pc_share).
