# RFC: Attached App Session Frontend v0

- Status: Draft
- Decision boundary: attach a LoopX frontend to an already-running Codex App
  session
- Smallest useful slice: one local Codex app-server session, one LoopX goal,
  and one existing automation-prompt or visible-host loop

## Summary

LoopX should support an **attached App Session** product mode. In this mode, a
Codex App or app-server session already exists and already owns its transport,
conversation history, interruption, and resume lifecycle. The LoopX frontend
attaches to that session, projects the relevant Goal and Todo state, and keeps
user interaction on the existing app-server connection.

The existing automation prompt or visible host loop remains the execution
driver. It reads the current LoopX interaction contract, advances the selected
Todo, validates progress, writes state back, and accounts for quota through the
normal LoopX command surface. The frontend must not stop the app-server
transport and resume the same thread through a separately launched CLI merely
to classify the work as governed.

A future frontend may also launch LoopX-managed Turns on Codex CLI, Claude CLI,
or another host adapter. That is a separate product mode with a different
process owner and lifecycle. This RFC deliberately scopes the first delivery to
attachment only.

## Problem

Users may already have a long-running Codex App session with valuable context,
an installed LoopX automation prompt, and an active Goal. A frontend that wants
to show or control that work has two choices:

1. attach to the existing session; or
2. close or bypass it and launch another agent runtime.

The second choice creates the wrong ownership boundary for the short-term
product:

- the frontend can accidentally create two executors for one Goal;
- the visible conversation and the process doing the work may diverge;
- interruption, resume, and sandbox behavior can change across transports;
- a correction message may be recorded in one session but executed in another;
- transport switching becomes coupled to an unreliable interpretation of user
  prose; and
- the existing automation prompt is treated as an incomplete chat path even
  though it is already a supported LoopX execution driver.

The immediate need is therefore not a universal runtime launcher. It is a safe,
explicit way to attach the frontend to work that is already running.

## Decision

The first frontend execution mode is `attached_app_session`.

Its defining properties are:

- **External session ownership.** Codex App or app-server created the session.
  LoopX does not replace its process or opaque upstream thread.
- **Explicit attachment.** The operator chooses a known local session. LoopX
  does not infer attachment from free-form text.
- **One interaction transport.** Questions, corrections, and work instructions
  continue through the attached app-server session.
- **Existing LoopX driver.** An automation prompt, visible host loop, or the
  equivalent host-specific interaction contract drives work in that session.
- **LoopX task truth.** Goal, Todo, gate, claim, quota, evidence, and terminal
  state remain authoritative in LoopX. Chat prose and transcripts are not task
  write receipts.
- **Projection, not duplication.** The frontend projects LoopX state and
  session capabilities without storing a second task lifecycle.
- **No silent fallback.** If the attached session becomes unavailable, the
  frontend reports it as disconnected or stale. It does not silently launch a
  managed CLI Turn.

## Product Flow

### Discover

A host-local broker lists attachable sessions as bounded descriptors. A public
descriptor may include:

- a public-safe session reference;
- host kind and lifecycle state;
- Goal and Agent binding when known;
- workspace identity as an opaque or redacted reference;
- whether message streaming, resume, and interrupt are available; and
- freshness and last-activity timestamps.

The browser must not receive raw app-server process handles, credentials,
environment variables, local absolute paths, or an unrestricted transcript.

### Attach

The operator explicitly selects one descriptor. The broker verifies that the
session is still live and that its Goal, Agent, workspace, and trust boundary
match the requested frontend context. A successful attachment creates a
frontend binding; it does not create a new Agent session.

### Interact

All user messages continue through app-server. The frontend does not maintain
an ordinary-chat-versus-material-chat classifier. The Agent and its installed
LoopX interaction contract decide which canonical LoopX commands or typed
actions are needed.

Read-only answers may leave LoopX task state unchanged. Material progress is
accepted only after the existing driver produces the required validation,
state writeback, and quota receipt. The fact that a message contains words such
as "start", "continue", or "fix" is never execution authority.

### Project

The frontend joins two read models:

1. session state from the attached host; and
2. Goal/Todo/status state from LoopX.

The session supplies conversation and transport liveness. LoopX supplies the
authoritative work frontier and accepted progress. A frontend row may link the
two through public-safe ids, but neither source is copied into the other as a
new canonical lifecycle.

### Detach

Detaching removes the frontend binding only. It does not terminate the Agent
session, delete its automation, complete a Todo, spend quota, or change Goal
state. Terminating the session remains an explicit host action.

## Execution And Accounting Boundary

An attached session is not an unmanaged bypass. Its execution driver must still
obey the current LoopX interaction contract:

```text
fresh LoopX state
  -> quota / gate / selected Todo decision
  -> existing App Session executes one bounded segment
  -> validation and evidence
  -> canonical state writeback
  -> quota spend after validated writeback
  -> next interaction contract
```

This lifecycle is product-equivalent to a managed Turn in the properties the
frontend needs to display: selected work, running/waiting/gated status,
validated progress, accounting, and a next action. It is not implementation-
equivalent to `turn run-once`, and it does not need to share that command's
process ownership or journal representation.

The frontend should consume a bounded projection of these common properties.
This RFC does not introduce a generic executor registry or require both driver
families to share one executor.

## State And Identity Boundaries

Three identities must remain distinct:

| Identity | Owner | Purpose |
|---|---|---|
| App session/thread | Host-local Codex App adapter | Conversation, streaming, interrupt, resume |
| Goal/Agent/Todo | LoopX control plane | Work selection, authority, gates, accounting, termination |
| Frontend attachment | LoopX frontend broker | Link one visible surface to one live host session |

The attachment may reference the other identities but cannot grant new
capabilities or task authority. A stale or mismatched Goal, Agent, workspace,
or trust binding fails closed.

## Safety And Privacy

- Keep opaque upstream session handles and process metadata in owner-local
  storage.
- Do not commit or emit credentials, environment values, local paths, raw
  transcripts, provider payloads, or host logs.
- Require a loopback or otherwise authenticated broker boundary for session
  discovery and attachment.
- Recheck session liveness and binding freshness before each control action.
- Treat attachment as observation and routing authority, not permission to
  bypass the session sandbox or LoopX gates.
- Preserve the original session's approval, sandbox, workspace, and capability
  policy.
- Fail closed when the host cannot prove that the selected descriptor still
  names the same live session.

## Non-Goals

- Launching a new Codex CLI or Claude CLI process from the frontend.
- Implementing or changing `turn run-once`.
- Routing an attached app-server session through a hidden managed Turn.
- Building a universal host-adapter abstraction before a second product mode
  has an accepted implementation slice.
- Inferring material authority from natural-language messages.
- Making the session transcript, frontend database, or app-server state the
  source of truth for Goal/Todo lifecycle.
- Copying private deployment or collaboration context into public fixtures or
  documentation.

## Smallest Useful Implementation Slice

After this RFC is accepted, the first implementation should be limited to:

1. one host-local Codex app-server session descriptor source;
2. explicit attach and detach actions;
3. reuse of the existing app-server message, stream, resume, and interrupt
   transport;
4. a bounded LoopX Goal/status projection beside the session;
5. liveness and binding-freshness checks; and
6. no managed Turn launch path.

The implementation should reuse current Chat Session and status projections
where their ownership matches. It should remove or defer code whose only
purpose is to detach app-server and launch `turn run-once` for the same user
interaction.

## Validation Criteria

The first implementation is acceptable only when a focused test or smoke proves
all of the following:

- attaching to a running session starts no second Agent process;
- three consecutive user messages use the same upstream App session;
- interrupt and resume preserve the attached session identity;
- an automation-prompt-driven bounded work segment updates LoopX state and is
  visible in the frontend without a managed Turn launch;
- a read-only exchange does not create a task transition or quota spend;
- detaching leaves the underlying session and Goal unchanged;
- stale or mismatched descriptors fail closed; and
- public packets and committed fixtures contain no opaque handles, credentials,
  raw transcripts, or local paths.

## Future Compatibility: Managed Turn Mode

A later RFC or accepted extension of this RFC may add `managed_turn`, in which
LoopX launches and owns a Codex CLI, Claude CLI, or another host adapter. That
mode may reuse frontend concepts such as status, selected Todo, interruption,
resume, validation, and receipts.

Compatibility does not require the attached mode to adopt managed Turn process
ownership. The two modes may share public projection algebra while retaining
separate executors and lifecycle contracts.

## Open Questions

1. Which existing host-local registry should own attachable session
   descriptors?
2. What is the minimum public-safe session reference that supports reconnect
   without exposing an upstream thread id?
3. Which app-server events prove liveness, interruption, and terminal state?
4. Should the frontend attach to only sessions already bound to a LoopX Goal,
   or offer an explicit Goal-binding preview for an unbound session?
5. Which existing status projection is the narrowest stable input for the
   attached-session view?
