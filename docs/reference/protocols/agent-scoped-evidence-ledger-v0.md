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
| `loopx quota should-run --agent-id ...` | Decides whether a specific agent lane should act and materializes the evidence source requested by `replan_novelty_policy`. | A standalone required-read hint has insufficient prompt salience and is not a replan control mechanism. |

The resulting surface is a public-safe, bounded, agent-scoped ledger that an
agent can read before replanning.

## Ownership Boundary

| Layer | Owns | Must Not Own |
| --- | --- | --- |
| Event sources | Durable append-only events, compact run records, ids, timestamps, and public-safe refs. | Prompt-ready planning summaries or cross-agent privacy policy. |
| Status and review packets | Current projections, attention queues, frontier summaries, and operator packets. | Raw chronological replay or write authority. |
| Quota | Lane routing, spend policy, scheduler hints, and required read hints. | Reconstructing history itself or storing replan rationale. |
| Agent-scoped evidence ledger | Thin chronological rows for the current agent plus compressed frontier for other agents. | Replan selection policy, repair-delta validation, canonical writes, raw logs, raw trajectories, private documents, or full other-agent traces. |
| Replan novelty policy | Makes evidence preflight and uncovered-direction selection prompt-visible. | Reimplementing blocker fingerprints, successor validation, or terminal-closure truth. |
| Repair delta | Validates the durable replan writeback, including repeated-blocker rejection and coverage-backed `exploration_exhausted`. | Reconstructing the evidence ledger. |
| Acting agent | Executes projected required reads, selects an uncovered direction, and submits the resulting repair delta. | Treating a read receipt alone as progress or inferring hidden context from another agent's private lane. |

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

When quota or status projects a replan obligation for an agent, the interaction
contract should include required reads:

```json
{
  "effective_action": "autonomous_replan",
  "required_reads": [
    {
      "kind": "agent_scoped_evidence_log",
      "command": "loopx --format json evidence-log --goal-id loopx-meta --agent-id codex-evidence-peer --thin --limit 24",
      "reason": "Read this agent's own material chronology before writing a replan delta."
    }
  ]
}
```

The control-plane responsibilities are deliberately split and causally bound:

- `replan_novelty_policy` is the baseline: it names
  `agent_scoped_evidence_log` as its evidence source and makes uncovered-
  direction selection visible in the primary recommended action;
- quota materializes that requested source as `required_reads[0]`, which carries
  the exact command. A generic replan without the novelty policy does not
  recreate the old standalone hint;
- `repair_delta` remains the only writeback truth for repeated blockers,
  successor novelty, and coverage-backed exhaustion.

The agent should then write back one of:

- a bounded replan delta that cites the ledger digest;
- a successor todo or handoff route;
- a concrete blocker or user todo;
- a no-follow-up rationale when the ledger proves the lane is intentionally
  closed.

LoopX cannot infer from an acknowledgement alone that a shell read happened.
Accordingly, the evidence-log read is not a second settlement mechanism: the
obligation clears only through a valid bounded repair delta, while the
prompt-visible novelty policy prevents the preflight command from being buried
as an unused packet field.

The live behavior qualification tests that causal handoff through an actual
function-tool conversation rather than a testing-only output field. A Doubao
actor receives the shipped Codex App heartbeat body and chooses the quota
command against a hermetic public-safe Goal. The harness runs that command
through the real LoopX CLI, returns its actual replan packet, and requires the
actor to call the exact evidence-log command from that packet. The evidence
command is also executed through the real read-only CLI and its goal/agent
readback is checked before the run passes. Prose such as "read the log next", a
generic read action, a command for another agent, or an evidence-log call made
before quota does not pass. Only temporary fixture state may change, and the
receipt stores bounded command digests rather than prompts, packets, or output.

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

The read-only CLI, rollout-event/run-history merge, bounded other-agent
frontier, policy-owned quota/review-packet required reads, and public boundary
smokes are implemented. Todo and material projections remain separate current-
state surfaces; they are not copied into this chronological ledger. Replan
novelty selection is owned by `replan_novelty_policy`, while durable acceptance
is owned by the repair-delta control path rather than expanded inside the ledger
builder.

## Acceptance

A change satisfies this contract only when:

- `loopx evidence-log` returns a bounded JSON packet for a concrete `goal_id` and
  `agent_id`;
- current-agent rows are detailed while other-agent rows are compressed by
  default;
- filters behave deterministically and do not require parsing raw JSONL in agent
  prompts;
- replan-capable quota/status payloads can point agents to the required ledger
  read;
- the live function-tool qualification proves that the default model selects
  that exact read from a production heartbeat/quota exchange rather than merely
  echoing a test field;
- the existing status, history, review-packet, and rollout-event-log surfaces
  keep their current responsibilities; and
- public tests prove the privacy boundary without committing private state,
  local paths, raw logs, or raw trajectories.
