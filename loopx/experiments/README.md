# LoopX Experiments

This package is LoopX's prototype laboratory. It holds executable features that
are useful to evaluate but are not yet part of the stable product contract.

## Placement Rule

Place a feature in `loopx/experiments/<experiment-id>/` when all of these are
true:

- it is explicitly opt-in and no default LoopX path depends on it;
- its caller contract or lifecycle is still expected to change;
- it has no registered provider-neutral capability owner; and
- deleting the experiment should not require a compatibility migration.

An experiment owns its contract, runtime, and experiment-specific provider
adapters in one package. Put its tests, runnable examples, and manual scripts in
matching paths under `tests/experiments/`, `examples/experiments/`, and
`scripts/experiments/`.

Do not use this package for a built-in capability merely because that
capability is marked experimental. A capability with a real caller outcome,
configuration, and lifecycle belongs in `loopx/capabilities/<capability-id>/`.
Generic extension registration and compatibility mechanics belong in
`loopx/extensions/`; an optional provider belongs there only after it
implements a deliberate product or capability contract independently of one
prototype.

## Dependency And Lifecycle Boundary

- Experiments may import stable LoopX code. Stable LoopX code must not import
  `loopx.experiments`.
- Placement here does not register a CLI command, capability, extension,
  scheduler route, installer entry, or release default.
- An experiment must have focused tests and at least one bounded, non-live
  example. Live probes stay explicit manual commands.
- Compatibility is not promised between experiment revisions. Prefer deleting
  stale entry points instead of keeping wrappers without a demonstrated caller.

## Promotion Or Removal

Promote an experiment only when it has a stable caller outcome, an identified
capability or runtime owner, explicit enable/disable and failure semantics, and
durable validation for the intended lifecycle. Promotion moves the code and
its tests out of `experiments/`; it does not leave the experimental package as
a second implementation route unless a real migration window requires one.

Remove an experiment when evidence no longer justifies the maintenance cost.
Its colocated package, tests, examples, and scripts should be removable as one
reviewable change.
