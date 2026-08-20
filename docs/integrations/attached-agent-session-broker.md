# Attached Agent Session Broker

The attached Agent session broker represents an already-running host session
inside the owner-local LoopX Chat store. It does not start, resume, or replace
an Agent runtime.

The first bridge stage supports:

- exact `(Goal, registered Agent, host surface, host session)` admission;
- distinct LoopX `agent_id` and executor `executor_endpoint_id` identities;
- one shared ordered queue for Web and Connector messages with `origin`;
- duplicate-safe host claim and completion receipts;
- response readback through the existing Chat turn and Lark reply path; and
- content-free Session list projections.

The host session must already have an exact `bind-agent-thread` registration.
Bind it to Chat with owner-local opaque values:

```bash
loopx worker-bridge attached-session-bind \
  --goal-id <goal-id> \
  --agent-id <registered-agent-id> \
  --host-surface <host-surface> \
  --host-session-id <opaque-host-session-id> \
  --executor-endpoint-id <executor-endpoint-id> \
  --execute
```

Web or Lark `session_queue` input is then claimed by the existing host:

```bash
loopx worker-bridge attached-session-claim \
  --session-id <loopx-chat-session-id> \
  --host-surface <host-surface> \
  --host-session-id <opaque-host-session-id> \
  --claim-id <stable-claim-id> \
  --wait-seconds 30 \
  --format json
```

`--wait-seconds` turns claim into a bounded host subscription. An existing host
bridge can keep one claim request open and wake as soon as the oldest queued
message is available, instead of polling the command in a tight loop. The wait
is capped at 30 minutes and never starts or resumes an Agent runtime. A timeout
returns `claimed=false`; the host chooses whether to subscribe again.

Write the Agent response to an owner-local JSON file containing at least a
`message` field, then complete the exact claim:

```bash
loopx worker-bridge attached-session-complete \
  --session-id <loopx-chat-session-id> \
  --turn-id <loopx-chat-turn-id> \
  --host-surface <host-surface> \
  --host-session-id <opaque-host-session-id> \
  --claim-id <stable-claim-id> \
  --completion-id <stable-completion-id> \
  --response-json <owner-local-response.json>
```

`session_queue`, bounded claim wait, and reply readback are enabled in this
stage. `live_steering` is explicitly reported as unavailable until the host
exposes a push transport for the already-running Turn. LoopX fails closed
instead of starting a managed runtime or silently degrading one event into
another ingress mode.

Opaque host identifiers, message bodies, and response files stay in the local
runtime store. Public Session projections contain only the LoopX Session id,
Goal/Agent binding, executor endpoint label, host surface, capability booleans,
and lifecycle state.
