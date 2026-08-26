# RFC: Provider-Neutral Turn-Start Inbox Hook v0

| Field | Value |
|---|---|
| Status | Implemented behind explicit provider configuration |
| Date | 2026-08-26 |
| Decision boundary | How fresh external inbox evidence reaches an Agent before it selects ordinary Goal work |
| Core owner | Hook admission, ordering, bounded public receipt, and Agent-read obligation |
| Provider owner | External read, provider schema validation, private cursor, and local inbox persistence |
| Agent owner | Semantic triage and durable Goal/Todo/effect writeback |

## Decision

LoopX adds a provider-neutral `turn_start` capability-hook phase. An enabled
provider hook runs before status and quota projection. It may perform bounded
external reads and mutate only declared owner-private inbox/cursor state. The
public result contains counts, booleans, status, and an error code; it cannot
contain message content, provider payloads, credentials, destinations, profile
names, or private cursor values.

The hook is complete only when fresh evidence is routed to Agent reading. A
result with new observations must set `agent_read_required=true`. The same turn
then recomputes inbox urgency, selects the inbox work lane ahead of ordinary
work, and exposes the existing goal-bound private `drain_command`. The Agent
reads the messages and chooses one typed semantic disposition:

- `steer_current_turn`: update the selected work without changing the durable
  Goal frontier;
- `replan_goal`: update Todo/vision/priority state before continuing;
- `record_context`: commit a durable domain effect or evidence record;
- `continue_current_work`: record that the message was considered but does not
  change the current plan; or
- `no_follow_up`: settle irrelevant or duplicate material explicitly.

Provider code never chooses these outcomes. Core never interprets private
message text. The Agent owns semantic judgment and must bind any material result
to a durable effect receipt before inbox ACK.

## Ordering

```text
provider-neutral turn_start dispatch
  -> provider read + owner-private commit/readback
  -> fresh status + quota projection
  -> inbox lane preempts ordinary work when agent_read_required
  -> private drain into the active Agent turn
  -> semantic disposition + durable settlement
  -> ACK and resume the prior lane when appropriate
```

Running the hook after quota selection is incorrect because fresh steering can
arrive after ordinary work has already been chosen. Returning raw content in
the public hook result is also incorrect because shared registries and Turn
journals are public-safe control-plane surfaces. CLI request validation runs
before hook dispatch, so an invalid quota request performs no provider read or
owner-private write; a valid request still dispatches the hook before status
collection and quota selection.

## Failure and replay

- `empty` means a valid provider success envelope was read and no new inbox
  event was accepted.
- `provider_contract_error` means the success envelope did not match its
  declared schema; it must never degrade to `empty`.
- provider permission and availability failures remain typed and isolated.
- duplicate hook identities run once; duplicate messages collapse by provider
  message identity.
- provider-local cursors are single-flight and advance only after inbox and
  cursor readback.
- `partial` multi-route success still requires Agent reading for accepted
  observations while retaining a compact failure code for the incomplete
  routes.

The hook grants no repository, production, outbound-message, or arbitrary
external-write authority. Its only allowed local writes are the registered
owner-private inbox and cursor scopes.
