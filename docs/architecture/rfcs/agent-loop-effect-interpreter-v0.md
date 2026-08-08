# RFC: Agent Loop Effect Interpreter

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-08-08 |
| Author | LoopX maintainers |
| Scope | Public control-plane docs, packet contracts, refactor direction, test strategy |

## Summary

LoopX harness should be explained, designed, and tested as **the effectful
program around an agent loop**, not as a collection of disconnected state
machines.

The canonical shape is:

```text
model -> effect request -> harness interprets effect -> observation -> model
```

The agent loop is the loop. The harness is the effectful program that
interprets each effect request and returns an observation to the next model
step.

The framing builds on the public lecture series by 齐梦星空, especially
[主线一：Agent Loop 里的小魔法：函数的组合(3)](https://www.xiaohongshu.com/discovery/item/6a057524000000003701f6aa?source=webshare&xhsshare=pc_web&xsec_token=CBDnukhtey6qJ1aXATVJtv4edjVUnZB1_yebMpqJdNLfc=&xsec_source=pc_share).

LoopX's job is the middle two steps: it receives an effect request from an
agent or host, decides whether and how to interpret it, writes back an
observation, and returns control to the next loop iteration.

This RFC establishes the mental model, defines canonical packet semantics,
and gives a milestone plan for aligning documentation, code, and tests with
that model over time.

## Why This Matters

Today, LoopX has many correct but hard-to-explain pieces:

- todo lifecycle and handoff state;
- quota decision and spend state;
- scheduler and heartbeat state;
- capability gates and user gates;
- vision, monitor, and replan state;
- evidence and run history.

Each piece has a state machine. The difficulty is not that these state
machines exist. It is that a reader cannot immediately see what effect each
state machine interprets, what observation it produces, and how that
observation returns to the next loop.

The agent-loop-as-effectful-program lens fixes this by asking the same
question everywhere:

> Who interprets this effect request, and what observation comes back?

## Core Mental Model

### Agent Loop

The underlying loop is:

```text
model -> effect request -> harness interprets effect -> observation -> model
```

The model proposes the next action. The harness decides whether the action is
allowed, how to execute it, how to handle failure, and how to encode the
result for the next model step.

### Effectful Program

A pure computation is:

```text
A => B
```

An effectful computation is:

```text
A => F[B]
```

`F` captures the external world: persistence, permissions, budgets, timing,
notifications, scheduling, evidence, and failure.

LoopX harness is best understood as that `F` around a long-running agent loop:

```text
GoalState => F[QuotaDecision]
```

## Mapping LoopX Concepts

| Article concept | LoopX equivalent |
|---|---|
| Agent loop | Every automation heartbeat, PR monitor, and sustained refactor turn |
| Effect request | `todo add`, `quota spend`, `refresh-state`, `notify`, `monitor poll`, `bind-agent-thread` |
| Harness interprets effect | `quota should-run` + `interaction_contract` + `capability_gate` + `work_lane_contract` + `scheduler_hint` |
| Observation | Quota packet, run history, evidence log, state writeback |
| Middleware mount points | User gate, capability bridge, scheduler ACK, cooldown, external evidence poll |
| `A => B` | Idealized `GoalState => GoalState` |
| `A => F[B]` | Real `GoalState => F[QuotaDecision]` |

## Canonical Packet Semantics

Every important control-plane packet should be explainable through four
semantic slots:

1. `effect_request`
2. `interpretation`
3. `observation`
4. `next_effect`

Example for `quota should-run`:

```json
{
  "effect_request": "agent proposes next bounded turn",
  "interpretation": {
    "route": "advancement_task",
    "capability_gate": "repair_bridge",
    "scheduler_hint": "active_work"
  },
  "observation": {
    "decision": "run",
    "recommended_action": "...",
    "state_writeback": "validated_progress"
  },
  "next_effect": "execute bounded turn, then refresh-state"
}
```

These slots should not be a second schema. They are a documentation and
naming discipline over existing packet fields. A new packet may add an
`effect_interpretation` envelope only when a real caller needs one canonical
place to read all four slots.

## State Machine As Interpretation Table

Instead of teaching state machines as a list of enum values, teach each state
machine as an interpretation table:

```text
Input effect | Interpreter | Decision | Observation | Next effect
```

Example for monitor scheduling:

```text
Monitor cadence or due horizon
  -> scheduler interpreter
  -> host RRULE / initial interval
  -> scheduler_hint packet
  -> next heartbeat or monitor poll
```

This preserves the existing state machines while making their purpose
visible.

## Milestones

### M0: RFC and Lecture 0

**Goal**: Publish this RFC and add a lecture that tells the story before any
state machine detail.

Steps:

1. Merge this RFC.
2. Add `Lecture 0: Harness Is the Effectful Program` to
   `docs/development/control-plane-course/`.
3. Rewrite `docs/product/core-control-plane/state-machine.md` to include an
   interpretation-table section for each state family.
4. Update `docs/README.md` and course navigation to point to the RFC.

Acceptance criteria:

- A new contributor can explain LoopX in one paragraph using the canonical
  loop shape.
- Every existing state machine doc links back to the interpretation-table
  pattern.
- No runtime behavior changes.

### M1: Canonical Packet Example

**Goal**: Pick `quota should-run` as the canonical example and make the four
semantic slots visible in docs and smokes.

Steps:

1. Add a public-safe documentation section describing the four slots for
   `quota should-run` (`docs/reference/effect-interpreter-packet.md`).
2. Add a focused pytest or smoke that asserts the mapping from raw inputs to
   the canonical interpretation fields.
3. Keep the existing payload fields unchanged.

Acceptance criteria:

- A reader can trace one real packet from effect request to observation.
- No CLI output budget regression.
- No new runtime contract without a real caller.

### M2: Bounded Context Alignment

**Goal**: Align existing refactors with the effect-interpreter boundary.

Steps:

1. Continue splitting `status.py`, `quota.py`, and `goal_frontier.py` into
   read-model, projection, and decision modules.
2. Name the boundaries in terms of the loop:
   - read model = current `A` (state);
   - projection = observation;
   - decision = effect interpreter.
3. Keep re-export compatibility for existing public imports.
4. Do not create a generic effect abstraction until at least two real
   callers need the same envelope.

Acceptance criteria:

- Module names and docstrings make the effect-interpreter role explicit.
- Public import compatibility tests remain green.
- Maintainability and line-budget smokes remain green.

### M3: Focused Test Families

**Goal**: Convert large control-plane smokes into focused pytest modules by
effect family.

Steps:

1. Create focused pytest modules for:
   - work-lane contract;
   - quota decision;
   - scheduler/monitor interpretation;
   - state-machine interpretation tables.
2. Keep thin end-to-end smokes that prove the CLI still works.
3. Add regression tests for failure, cancellation, gate, and observation
   writeback paths.

Acceptance criteria:

- Each effect family has a focused pytest module.
- No large smoke is deleted before its focused replacement passes.
- Full public smoke suite stays green.

### M4: Architecture Documentation

**Goal**: Update architecture and product docs to use the same story.

Steps:

1. Reframe `docs/architecture.md` around the canonical loop.
2. Update the control-plane course so each lecture references the same
   `effect_request -> interpretation -> observation` flow.
3. Update README product language where it currently says "state machine"
   without explaining the interpretation role.

Acceptance criteria:

- The public docs no longer present LoopX as a pile of unrelated state
  machines.
- Technical readers can identify the loop boundary, effect request,
  interpreter, and observation in each documented workflow.

### M5: Steady-State Review

**Goal**: Keep the RFC as a living contract.

Steps:

1. Add a canary smoke or docs smoke that checks the canonical packet
   documentation exists.
2. Review new state machines and packet fields against the four semantic
   slots.
3. Update this RFC when a new effect family requires a new canonical slot.

Acceptance criteria:

- The RFC is referenced by maintainer docs and course material.
- New control-plane features state which effect they interpret.

## Test Strategy

Tests should be organized by effect family, not by source-file size:

```text
effect_request -> interpretation -> observation -> next_effect
```

Each focused pytest module should cover:

- positive routing;
- gate and capability decisions;
- failure and cancellation;
- observation writeback;
- compatibility of public imports.

Large smokes remain only as thin end-to-end checks.

## Non-Goals

- Do not merge all state machines into one giant enum.
- Do not create a generic `Effect` abstraction without two real callers.
- Do not rewrite `quota should-run` for the sake of naming.
- Do not remove existing public compatibility routes without a migration
  window.

## Risks

- Naming drift: we may use "effect" as decoration without changing semantics.
  Mitigation: every RFC milestone must produce a real doc or test change.
- Over-abstraction: a generic effect envelope could become unused scaffolding.
  Mitigation: only add a shared envelope when a second caller needs it.
- Test churn: converting large smokes too fast can reduce e2e confidence.
  Mitigation: keep thin e2e until focused tests cover the same behavior.

## Open Questions

- Should `effect_interpretation` be a first-class field in the hot quota
  packet, or only a documented lens?
- Should each capability own an interpretation table, or should the tables
  stay in central docs?
- When should a new state machine be considered a new effect family?

## Success Metrics

- A new technical reader can explain LoopX in one paragraph.
- Each major control-plane packet can be traced through the four semantic
  slots.
- Focused pytest coverage grows while large smoke files shrink.
- Public docs and course material use the same loop vocabulary.
- Existing CLI output budgets and public compatibility contracts remain green.

## Conclusion

LoopX harness is not "a set of state machines". It is the effectful program
and effect interpreter around a long-running agent loop. This RFC makes that
story explicit and gives the refactor and test work a stable target.

## References

- 齐梦星空, *主线一：Agent Loop 是 effectful program(1)*.
- 齐梦星空, *主线一：Tool Calling 是 Kleisli arrow(2)*.
- 齐梦星空, [*主线一：Agent Loop 里的小魔法：函数的组合(3)*](https://www.xiaohongshu.com/discovery/item/6a057524000000003701f6aa?source=webshare&xhsshare=pc_web&xsec_token=CBDnukhtey6qJ1aXATVJtv4edjVUnZB1_yebMpqJdNLfc=&xsec_source=pc_share).
