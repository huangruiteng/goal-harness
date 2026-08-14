# Read-Only Turn Journal Interpretation Design

## Goal

Add a read-only `interpret_turn_journal` lens that maps an existing fenced
LoopX Turn journal onto `EffectTurn`. The lens reports whether effect-free
replay is legal, explains identity and phase-order violations as structured
data, and preserves terminal journal tombstones without executing or mutating
anything.

## Scope

The change will:

- add `interpret_turn_journal` to
  `loopx.control_plane.effect_program`;
- compare goal, owner, and Turn-key identity across the journal trace;
- verify that `completed_phases` is an ordered prefix of
  `TRANSACTION_PHASES`;
- expose terminal `committed`, `stopped`, and `failed` journal state as a
  retained tombstone;
- distinguish `replay_legal` from `replay_blocked` without authorizing
  execution;
- add focused semantic tests and update the Effect Interpreter Packet
  reference.

The change will not add a journal loader, executor, scheduler path, write
operation, schema migration, model call, quota spend, or second settlement
ledger.

## Ownership And Placement

- Capability outcome: read an existing Turn journal as an Effect Program
  observation.
- Capability owner: the existing Turn / Effect Program contract.
- Provider: built into LoopX core; no extension provider is involved.
- Implementation home: `loopx/control_plane/effect_program.py`, beside
  `interpret_quota_should_run_packet` and `interpret_turn_result_packet`.

The nearest existing owner is sufficient because this is another packet lens
over an already shipped Turn contract. A new capability package, journal
adapter, or interpreter protocol would add structure without a separate caller
contract.

## Public API

```python
def interpret_turn_journal(
    journal: Mapping[str, Any],
    *,
    goal_id: str | None = None,
    agent_id: str | None = None,
    turn_key: str | None = None,
    capabilities: Sequence[str] = (),
) -> EffectTurn:
    ...
```

The supplied identity arguments are expectations, not authority grants. The
function reads the supplied mapping and returns an `EffectTurn`; it does not
open a path, acquire a lock, write a journal, or invoke replay.

## Identity And Phase Interpretation

The lens reads identity from the existing trace locations:

- journal: `goal_id` and `turn_key`;
- stored plan envelope: `goal_id` and `agent_id`;
- transaction plan: `turn_key`;
- typed settlement identity: `goal_id` and `agent_id`;
- host result and receipt: any present `turn_key`.

All present values for one identity dimension must agree with each other and
with the corresponding explicit expectation when one is supplied. Missing
required journal, envelope, transaction, or settlement identity is reported as
structured invalid identity rather than raising an exception. Optional host
result and receipt fields are compared only when present because an
in-progress trace may not have reached those stages.

`completed_phases` is valid only when it is a list whose string values equal
the same-length prefix of `TRANSACTION_PHASES`. An empty list is a valid
ordered prefix, but it does not make an in-progress journal eligible for
effect-free replay.

## Replay And Tombstone Semantics

An effect-free replay is legal when:

1. goal, owner, and Turn-key identity match;
2. completed phases form an ordered transaction prefix; and
3. the journal has a terminal status currently treated as a replay tombstone:
   `committed`, `stopped`, or `failed`.

This describes the existing default replay boundary. It does not authorize a
`retry_failed=True` recovery, which remains executor-owned and may perform
effects.

The input journal is never modified. Terminal status is projected as
`tombstone_retained=True` with its original `journal_status`; no tombstone is
created, deleted, or rewritten. Non-terminal state is visible but has
`replay_legal=False` and `tombstone_retained=False`.

## EffectTurn Mapping

`EffectRequest`:

- `kind="turn_journal"`;
- `source="turn_journal"`;
- expected `goal_id`, `agent_id`, and capabilities remain visible;
- `context` contains:
  - `replay_legal`;
  - `goal_matches`;
  - `owner_matches`;
  - `turn_key_matches`;
  - `phases_form_ordered_prefix`;
  - `journal_status`;
  - `tombstone_retained`;
  - normalized `completed_phases`;
  - an ordered tuple of typed violation values.

`EffectInterpretation`:

- `route="turn_journal_replay"`;
- `obligation="observe_fenced_replay"`;
- `interaction_mode="read_only"`.

`EffectObservation`:

- `decision` is `replay_legal` or `replay_blocked`;
- `should_run` is always `False`, so the lens cannot be mistaken for
  execution permission;
- `effective_action` is `observe_replay` or `block_replay`;
- `recommended_action` gives a compact, domain-neutral readback;
- `protocol_summary` summarizes legality without embedding raw journal data.

`EffectNext` is empty. The structured `request.context["replay_legal"]` field,
not `should_run`, is the replay-legality signal.

## Structured Violations

Implementation will define a typed `StrEnum` for stable violation values and
project their string values into `EffectRequest.context`. The initial values
cover:

- `goal_identity_missing`;
- `goal_mismatch`;
- `owner_identity_missing`;
- `owner_mismatch`;
- `turn_key_identity_missing`;
- `turn_key_mismatch`;
- `completed_phases_invalid`;
- `completed_phases_not_ordered_prefix`;
- `journal_not_terminal`;
- `journal_status_unsupported`.

Violations are accumulated in deterministic order so one trace can expose all
independent problems in a single read. Classification is based on typed fields
and exact equality, not substring heuristics.

## Error Handling And Compatibility

Semantic mismatches return `EffectTurn` with `decision="replay_blocked"`.
They do not raise. The function accepts any `Mapping`; malformed nested values
are treated as missing or invalid structured fields.

Existing `EffectTurn` dataclasses and existing interpreter behavior remain
unchanged. No journal or Turn wire schema changes. Callers that do not use the
new lens observe no behavior change.

## Testing

Focused tests will derive expectations from the Turn transaction contract and
cover:

1. a terminal journal with matching trace identity and ordered phases;
2. owner, goal, and Turn-key mismatches accumulated as structured violations;
3. a non-prefix phase sequence blocked even when the journal is terminal;
4. retained `committed`, `stopped`, and `failed` tombstone status;
5. a non-terminal journal that remains observable but not replay-legal;
6. malformed or missing identity fields returning a blocked result rather
   than raising;
7. input immutability and empty `EffectNext` fields.

Validation will include focused pytest coverage, the existing fake-host Turn
walkthrough, the documented `loopx check` scans, and the repository's
risk-based premerge canary for the final diff.
