# Quota CLI Hot-Path Compaction v0

`quota_cli_hot_path_compaction_v0` bounds the default agent-facing
`quota should-run` projection without changing the decision computed by the
quota control plane. The full decision is built first. CLI-only projection then
retains action authority on the hot path and moves repeated diagnostic detail
behind explicit `--include-detail` selectors.

## Ownership Boundary

The quota control plane owns decision, precedence, scheduler, interaction,
selected-todo, and user-action semantics. `cli_projection.py` owns only the
serialized view consumed by agents. A compactor must not become a second
decision owner or recompute any route.

The default projection retains:

- `decision`, `should_run`, `effective_action`, and `recommended_action`;
- selected todo and execution obligation;
- interaction mode, user channel, and executable agent/CLI actions;
- scheduler action and autonomous-replan authority;
- the compact vision decision, trigger kinds, required reads, and judge result;
- warning kinds, counts, stable identities, and cold-path references.

Repeated vision audits use `$.vision_continuation_audit` as the canonical
projection. Candidate lists and peer action lists retain counts and point to
`--include-detail agent-todos`. The complete vision audit is available through
`--include-detail vision`; `--include-detail all` restores every supported
detail section.

## Qualification Contract

Deterministic tests own exact full-versus-compact parity, cold-path restoration,
schema shape, and the character budget. The real-scale regression must exceed
the default budget before compaction and remain within it afterward.

Model qualification is one-arm and actual-default. The shipped
`actual_default_model_behavior_portfolio_v0` sends the CLI hot-path projection,
not the unprojected in-memory decision, to the Doubao actor. Its independent
source oracle must still observe the expected selected todo, user gate,
execution obligation, scheduler route, and vision/replan behavior on every
repeat. A dedicated compaction-regression scenario must exceed the JSON hot-path
budget before projection, fit within the budget afterward, preserve the exact
source-derived semantic contract, and preserve the model's route. Two additional
over-budget scenarios repeat clean selected-work and blocking-gate contracts
under omitted diagnostic noise. Bounded contrast results require those pairs to
remain invariant, while blocking versus non-blocking user action and selected
work versus required vision replan remain distinguishable. Exact helper
traversal, omitted counts, warning references, deduplication, and peer-route
shape remain deterministic projection-test responsibilities. The old full
packet is not retained as a permanent second product contract; paired mode is
reserved for explicit differential diagnosis.

Live receipts may retain only bounded scenario outcomes and digests. Packets,
prompts, raw model responses, credentials, and conversations remain outside the
repository.
