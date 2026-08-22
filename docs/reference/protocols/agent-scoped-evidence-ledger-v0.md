# agent_scoped_evidence_ledger_v0

`agent_scoped_evidence_ledger_v0` defines a thin, chronological read model for
agents that need to replan, hand off, or explain progress without reading raw
rollout logs, private active state, or another agent's detailed working trail.

The contract is a read model. It does not replace `ACTIVE_GOAL_STATE.md`, todo
state, compact run history, status projection, review packets, quota routing, or
the append-only rollout event log.

## Current Sources

LoopX already has useful history and evidence surfaces, but they serve different
jobs:

| Surface | Current job | Gap for agent replan |
| --- | --- | --- |
| `rollout-event-log.jsonl` | Append-only structured events such as todo, quota, refresh, validation, and compact evidence events. | It is a low-level event source, not an agent-facing filtered chronology. |
| `loopx status` | Projects current state, todo index, attention queues, agent lanes, run history, and event summaries. | It answers "what is true now", not "what sequence should this agent review before replanning". |
| `loopx review-packet` | Packages status and attention items for review or handoff. | It is packet-shaped, not a general scoped event ledger. |
| `loopx history` | Reads compact run history and run indexes. | It is run-centric and not equivalent to rollout events. |
| `loopx quota should-run --agent-id ...` | Decides whether a specific agent lane should act and projects a compact coverage ledger plus uncovered frontier from the evidence source. | It does not ask the model to reconstruct history or treat a read receipt as progress. |

The resulting surface is a public-safe, bounded, agent-scoped ledger that the
host can project into a replan action packet and an operator can inspect in full.

## Ownership Boundary

| Layer | Owns | Must Not Own |
| --- | --- | --- |
| Event sources | Durable append-only events, compact run records, ids, timestamps, and public-safe refs. | Prompt-ready planning summaries or cross-agent privacy policy. |
| Status and review packets | Current projections, attention queues, frontier summaries, and operator packets. | Raw chronological replay or write authority. |
| Quota | Lane routing, spend policy, scheduler hints, host context delivery, and the minimal replan action packet. | Storing replan rationale or accepting writeback. |
| Agent-scoped evidence ledger | Thin chronological rows for the current agent plus compressed frontier for other agents. | Replan selection policy, semantic-delta validation, canonical writes, raw logs, raw trajectories, private documents, or full other-agent traces. |
| Replan context policy | Builds the coverage ledger, delivery receipt, and uncovered frontier. | Reimplementing typed progress comparison or terminal-closure truth. |
| Semantic write gate | Validates typed progress, state-grounded successors, fresh vision outcomes, blockers, and coverage-backed terminal results against the current obligation. | Reconstructing the evidence ledger or interpreting classification prose. |
| Acting agent | Selects an uncovered direction from delivered context and submits a typed observation or vision outcome. | Treating context delivery, a manual read, or a legacy ACK alone as progress. |

## Read Model Shape

The CLI payload uses the shipped `agent_scoped_evidence_log_v0` schema (the
protocol name describes the ledger concept rather than a second wire schema):

```json
{
  "schema_version": "agent_scoped_evidence_log_v0",
  "goal_id": "example-goal",
  "agent_id": "codex-evidence-peer",
  "mode": "thin",
  "todo_id": null,
  "since": null,
  "event_kinds": [],
  "limit": 30,
  "matched_count": 1,
  "ledger_count": 1,
  "truncated": false,
  "source_refs": [
    "rollout_event_log.public_safe_view",
    "compact_run_history.public_refs"
  ],
  "ledger": [
    {
      "event_id": "evt_123",
      "recorded_at": "2026-07-05T00:00:00Z",
      "source": "rollout_event_log",
      "event_kind": "todo_update",
      "agent_id": "codex-evidence-peer",
      "todo_id": "todo_123",
      "classification": "implementation_batch",
      "status": "open",
      "summary": "P0 implementation frontier was split into a design contract and a CLI read model."
    }
  ],
  "other_agent_frontier": {
    "schema_version": "other_agent_frontier_v0",
    "policy": "goal_frontier_only",
    "item_count": 1,
    "items": [
      {
        "agent_id": "codex-main-control",
        "source": "run_history",
        "classification": "validated_progress"
      }
    ]
  },
  "boundary": {
    "raw_logs_recorded": false,
    "raw_trajectory_recorded": false,
    "credential_values_recorded": false,
    "absolute_paths_recorded": false,
    "other_agent_event_stream_expanded": false
  }
}
```

The schema is intentionally narrow. It should be cheap to produce, cheap to read
in a prompt, and stable enough for quota/replan tests.

## CLI Contract

The public CLI is read-only:

```bash
loopx --format json evidence-log --goal-id <goal-id> --agent-id <agent-id> --thin --limit 30
```

Supported filters:

| Option | Meaning |
| --- | --- |
| `--todo-id <todo-id>` | Filter rollout events by exact todo id and compact runs by bounded todo mention. |
| `--since <iso8601>` | Return rows recorded after a timestamp. |
| `--event-kind <kind>` | Filter rollout event kinds such as `todo_update`, `quota_should_run`, or `validation`. |
| `--limit <n>` | Bound rows after filtering. Default should be small enough for an agent prompt. |
| `--history-limit <n>` | Bound compact run-history rows scanned before filtering. |
| `--rollout-limit <n>` | Bound rollout-event rows scanned from the tail before filtering. |
| `--thin` | Select the only current public-safe mode; accepted explicitly for readable generated commands. |
| global `--format json\|markdown` | Select JSON or the compact Markdown rendering. |

The command must fail closed on missing `goal_id` or `agent_id`. A vague
surface value such as `codex` should not silently fall into `other-agent`
semantics; callers should pass a registered agent id and, when needed, a
separate host surface such as `codex-app`, `codex-cli`, `opencode`, or `claude-code`.

## Scoping Rules

The current implementation returns detailed rows under these deterministic
rules:

- the event has `agent_id` equal to the requested agent id;
- when `--todo-id` is present, the event has that exact todo id;
- compact run-history rows have the requested agent id and, when filtered by
  todo, mention that todo in one of the bounded run fields;
- `--since` and normalized `--event-kind` filters are applied before the final
  newest-first limit.

Other agents should not be shown row by row by default. They should be compressed
into `other_agent_frontier` from the latest compact run-history row per agent,
with a maximum of three rows. This lets an agent understand the shared direction
without inheriting another lane's private scratchpad.

## Replan Integration

When quota or status projects a replan obligation for an agent, the host folds
the bounded agent-scoped chronology into a compact coverage ledger and delivers
it with the current obligation:

```json
{
  "replan_action_packet": {
    "decision": "replan_required",
    "obligation_id": "replan-opaque-id",
    "uncovered_frontier": {
      "baseline": {"surface_id": "surface-auth", "result_class": "unchanged"},
      "required_any_of": ["new_surface", "new_hypothesis", "new_probe_family"]
    },
    "required_outcome": "semantic_delta",
    "writeback_contract": {
      "schema_version": "typed_progress_observation_v0",
      "transport": "loopx_refresh_state",
      "command_template": "loopx ... refresh-state ... --progress-result-class <typed-class> --progress-evidence-id <evidence-id> <typed-dimension-options>"
    },
    "allowed_terminal": ["exploration_exhausted", "blocked", "no_followup"]
  }
}
```

The full obligation also carries `replan_context_v0`: a bounded
`coverage_ledger`, the same uncovered frontier, and a
`replan_context_delivery_receipt_v0`. The control-plane responsibilities are
deliberately split and causally bound:

- the evidence log remains the durable public-safe chronology;
- quota owns context delivery and does not require a weak protocol-following
  model to discover or execute a read ritual;
- `typed_progress_observation_v0` owns work-slice identity and result semantics;
- quota and `refresh-state` use the same goal-frontier reducer, while the write
  gate closes only the current obligation with an accepted semantic delta.

When a turn identity makes the settlement chain executable,
`interaction_contract.cli_channel.replan_settlement_contract` names its one
causal binding. Its `semantic_obligation.settlement_bound` field is `false`
when a selected Todo owns the receipt: in that case the typed replan delta is
written and spent with `--todo-id` only, while the obligation id stays
available for semantic validation. Combining `--todo-id` and
`--replan-obligation-id` is never a valid settlement identity. Without a
selected Todo, the same contract marks the replan obligation as directly bound
and projects `--replan-obligation-id`. An unscoped diagnostic read keeps only
compact replan guidance; it does not advertise an executable settlement
contract or quota spend without the missing turn identity.

The agent should then write back one of:

- an `advanced` observation with a new surface, hypothesis, or probe family;
- an `advanced` observation naming a successor Todo that is actually runnable
  in current state;
- a new concrete blocker with evidence;
- coverage-backed `exploration_exhausted` or `no_followup`; or
- for a vision-derived duty, a fresh evidence-linked vision path outcome.

An accepted typed semantic ACK settles the corresponding projected obligation
even when the source acceptance gap remains visible. Terminal coverage inputs
fail at the CLI boundary when their required coverage scope is missing;
`exploration_exhausted` additionally requires explicit coverage completion.

Every successful diagnostic `loopx evidence-log` execution appends an
`evidence_log_read` rollout event and returns an
`evidence_log_read_receipt_v0`. The receipt carries the goal id, agent id,
bounded read window, canonical public-safe command, and recorded timestamp.
Receipt events are excluded from an unfiltered ledger view so repeated reads do
not recursively inflate the chronology. They are observability facts only: a
read, a failed read, a prose ACK, or a historical repair-delta ACK does not
close the current obligation. This prevents a receipt for an earlier periodic
review from masking a later vision/frontier duty.

### Effect-program boundary

This flow uses the effect-program separation without adding a second settlement
executor. Host context projection is a repeatable read effect; the typed
progress writeback is a separately validated state transition. The delivery
receipt proves context delivery, while the semantic delta proves use of that
context. Neither receipt is allowed to impersonate the other.

The live behavior qualification tests that causal handoff through an actual
function-tool conversation rather than a testing-only output field. A Doubao
actor receives the shipped Codex App heartbeat body and chooses the quota
command against a hermetic public-safe Goal. The harness runs that command
through the real LoopX CLI, returns its actual context/action packet, and asks
the actor to choose the next real tool action. The actor independently qualifies
the selected typed observation, then executes the real `refresh-state` command.
Evidence-log-only, prose-only, pre-quota, equivalent-fingerprint, and ungrounded
successor actions do not pass. Only temporary fixture state may change, and the
receipt stores bounded command digests and typed outcomes rather than prompts,
packets, or output.

## Privacy Boundary

The ledger must preserve the rollout event boundary:

- no raw task text;
- no raw logs, stdout, stderr, trajectories, or verifier tails;
- no credentials, tokens, headers, or secrets;
- no absolute local paths;
- no private document body or chat transcript;
- no private source payload copied into public-safe rows.

Rows may contain compact ids, relative public artifact refs, redacted summaries,
omission notes, and private source counts. If a source is private, the row should
say that only a compact pointer or count was recorded.

## Current Implementation Status

The CLI, rollout-event/run-history merge, bounded other-agent frontier,
host-projected coverage context, minimal action packet, typed repeat detector,
and shared quota/write-time semantic gate are implemented. Todo and material
projections remain separate current-state surfaces; they are not copied into
this chronological ledger. Historical repair ACKs have a bounded read adapter
for old run rows, but new replan closure has one truth: typed semantic delta.

## Acceptance

A change satisfies this contract only when:

- `loopx evidence-log` returns a bounded JSON packet for a concrete `goal_id` and
  `agent_id`;
- current-agent rows are detailed while other-agent rows are compressed by
  default;
- filters behave deterministically and do not require parsing raw JSONL in agent
  prompts;
- replan-capable quota/status payloads deliver a compact coverage ledger and
  uncovered frontier without requiring a model read ritual;
- the live function-tool qualification proves that the default model selects
  and executes a semantic next action from a production heartbeat/quota
  exchange rather than merely echoing a test field;
- the existing status, history, review-packet, and rollout-event-log surfaces
  keep their current responsibilities; and
- public tests prove the privacy boundary without committing private state,
  local paths, raw logs, or raw trajectories.
