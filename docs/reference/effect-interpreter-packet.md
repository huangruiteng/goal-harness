# Effect Interpreter Packet

This page documents the canonical read lens for `quota should-run`:

```text
effect_request -> interpretation -> observation -> next_effect
```

It does not add a new runtime contract. It names the existing packet fields
that already play each role.

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
| `scheduler_hint.codex_app.ack_hint.cli_args` | Host ACK effect |
| `scheduler_hint.codex_app.failure_hint.cli_args` | Host failure effect |

## Relationship To State Machines

Each state family is an interpretation table over this lens:

```text
input effect -> interpreter -> decision -> observation -> next effect
```

See the
[Agent Loop Effect Interpreter RFC](../architecture/rfcs/agent-loop-effect-interpreter-v0.md)
and
[Harness Is the Effectful Program](../development/control-plane-course/00-agent-loop-effectful-program.md).
