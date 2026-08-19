# computer_use_runtime_v0

Status: public-safe research and design contract v0.

Computer-use agents can operate browsers, desktops, and enterprise tools, but
the raw execution loop is usually too low-level for long-horizon work: clicks,
screenshots, focus changes, and modal errors do not by themselves say whether a
goal is allowed, blocked, valuable, or safe to continue.

This contract treats a computer-use provider as an execution surface beside
LoopX, not as a new LoopX product capability. A host already provides enough
computer-use primitives (a browser tool, an accessibility tree, an in-page
action set) through whatever agent runtime is driving it. LoopX does not need
to own or reimplement that pixel-level loop. What LoopX owns is the boundary
around it: the request a capability is allowed to make, the facts a provider
is allowed to report, and the durable state transition that follows.

## Two Things Both Called "Capability"

The word "capability" is overloaded in this area, and that overload is the
source of most naming confusion in earlier drafts of this contract:

- a **LoopX product capability** (`content-ops`, `explore`, `issue-fix`, ...)
  is a stable, provider-neutral contract oriented around a caller-visible
  outcome;
- a **provider-advertised capability** is a runtime declaring which low-level
  primitives it supports -- screenshot, click, type, accessibility tree,
  record/replay.

Computer use is the second kind. It is not itself a LoopX product capability
and should not be registered as one. It is a provider/runtime execution
surface that a real product capability may choose to call, the same way a
capability might choose an API, a CLI, or a human step instead.

## Ownership

```text
outcome capability
  -> bounded action request
CUA provider/runtime
  -> observation + typed receipt (facts only)
capability-local reducer
  -> proposed transition
LoopX Kernel
  -> accepted todo / gate / evidence / quota state
```

| Layer | Owns | Does not own |
| --- | --- | --- |
| Capability (`content-ops`, `explore`, `issue-fix`, ...) | The user-visible outcome, domain policy, which effects are allowed, and how to interpret a provider receipt. | Browser install, the pixel loop, or any one provider's session details. |
| CUA provider/runtime (a host browser tool, `ego-browser`, a Playwright provider, ...) | The session, low-level actions, observation, replay/evidence handles, and a typed stop reason. | Directly completing a LoopX todo, creating a gate, or deciding quota/writeback. |
| Extension/package | Install, doctor, enable/disable, upgrade, and compatibility for an optional provider. | Inventing a "capability" that has no caller outcome. |
| Kernel | Durable todo, gate, quota, evidence, recovery, and final transition authority. | Executing a browser action or understanding the domain semantics of one UI. |

This is a many-to-many relationship. One CUA provider can serve several
capabilities (`content-ops` and `explore` may both drive a browser). One
capability may pick a CUA provider, an API, a CLI, or a human step for the
same outcome. `value-connectors` is currently a compatibility facade for
generic external-value packet plans; it is not the owner of this contract and
should not become one.

The reducer step is deliberately **not** specified by this protocol. It is
capability-local: `unknown_modal` means something different in a publish
workflow than it does in a payment flow or a research crawl, so only the
capability that owns the outcome can turn a receipt into a proposed
transition. This document defines what a reducer is allowed to receive (a
receipt, the original action request, the current gate binding, and its own
domain policy) and what it must never do (author a Kernel writeback itself),
not the reducer's shape.

## Middle-Grained Action Pattern

Computer-use loops often fail at both extremes:

- raw UI primitives are too small for planning and review;
- whole workflows are too large to validate, retry, or hand back to a human.

The boundary should sit at a middle-grained action unit that maps to a todo or
action packet:

```text
goal boundary
  -> bounded computer-use todo
  -> action request
  -> observed UI facts
  -> typed receipt
  -> capability-local reducer decision
  -> LoopX todo/gate/evidence writeback
```

Examples of middle-grained units:

- inspect a settings screen and report whether a toggle exists;
- draft a post but stop before publish;
- fill a form from approved fields and stop at the final submit gate;
- capture a replay handle for a successful navigation path;
- recover from a modal error by returning a blocker packet instead of clicking
  through unknown prompts.

## Runtime Records

This protocol defines three provider-facing records. It does not define a
reducer or writeback record; those stay capability-local.

| Record | Purpose |
| --- | --- |
| `computer_use_runtime_profile_v0` | Public-safe provider capabilities: browser, desktop, accessibility tree, screenshot, replay, sandbox, and write modes. Readiness only, not authority. |
| `computer_use_action_request_v0` | The bounded action a capability is asking the provider to attempt, including its effect class, write scope, and current gate binding. |
| `computer_use_receipt_v0` | What the provider actually attempted and observed. Facts only -- no writeback decision. |

`computer_use_session_v0` and `computer_use_handoff_gate_v0` are deferred
entirely. `computer_use_replay_handle_v0` is deferred as its own standalone
record -- for now its shape lives inline in the receipt's `evidence` field.
All three become useful as separate records only once a real capability
consumer needs their exact shape; see [Related
Contracts](#related-contracts) for how they get promoted.

## Runtime Profile

A provider may advertise readiness before any source access:

```json
{
  "schema_version": "computer_use_runtime_profile_v0",
  "provider_id": "computer_use_runtime",
  "host_kind": "browser_or_desktop_runtime",
  "visibility": "visible_or_replayable",
  "provider_primitives": {
    "screenshots": "host_owned",
    "accessibility_tree": "optional",
    "browser_session": "optional",
    "record_replay": "optional",
    "external_write": "gated",
    "private_source_read": "gated"
  },
  "boundary": {
    "credentials_copied": false,
    "cookies_exported": false,
    "raw_screenshots_copied": false,
    "raw_private_bodies_copied": false,
    "external_write_allowed_without_gate": false
  }
}
```

This profile is a readiness fact, not permission to operate a real account or
read private material. `provider_id` names the runtime; it is not a
`value-connectors` connector id and must not imply that ownership.
`provider_primitives` is deliberately not named `capabilities` -- it declares
the second, provider-advertised sense from [Two Things Both Called
"Capability"](#two-things-both-called-capability), not the first.

## Action Request Shape

```json
{
  "schema_version": "computer_use_action_request_v0",
  "goal_id": "loopx-meta",
  "todo_id": "todo_example",
  "provider_id": "computer_use_runtime",
  "action_unit": "draft_until_review_gate",
  "effect_class": "draft",
  "write_scope": {
    "allowed_actions": [
      "open approved screen",
      "fill approved draft fields",
      "capture compact receipt"
    ],
    "forbidden_effect_classes": ["external_write", "credential_use"]
  },
  "gate_binding": {
    "gate_id": "gate_example_draft_review",
    "revision": 4,
    "status": "open"
  },
  "stop_condition": "stop at final confirmation or unknown modal",
  "validation_target": "draft screen is reachable and final action remains unclicked"
}
```

`effect_class` and `write_scope` are typed fields, not prose. A request whose
`effect_class` is `external_write` or `credential_use` must carry a
`gate_binding` with a current revision, or the provider must refuse it.
Natural-language `stop_condition` text may supplement the typed fields; it
must never be the only enforcement.

The action request should be generated from LoopX todo/gate state and current
provider policy by the owning capability, not from an ad hoc prompt pasted
into the automation runtime.

## Receipt Shape

```json
{
  "schema_version": "computer_use_receipt_v0",
  "goal_id": "loopx-meta",
  "todo_id": "todo_example",
  "provider_id": "computer_use_runtime",
  "attempted_action_unit": "draft_until_review_gate",
  "stop_reason": "stopped_at_gate",
  "observed_facts": {
    "screen_reached": true,
    "draft_present": true,
    "final_action_clicked": false,
    "unknown_modal": false
  },
  "evidence": {
    "handle_kind": "host_replay_or_screenshot_pointer",
    "raw_evidence_copied": false,
    "private_source_redacted": true
  },
  "idempotency_key": "action_request_example_attempt_1",
  "session_reference": "provider_owned_opaque_session_handle"
}
```

`attempted_action_unit` echoes the `action_unit` of the action request this
receipt answers. A todo can see more than one action request over its
lifetime (retries, a resumed attempt after a gate is approved), so the
receipt must say which bounded action it is reporting on rather than leaving
the reducer to infer it from `todo_id` alone.

`stop_reason` is a closed enum: `completed`, `stopped_at_gate`,
`blocked_by_unknown_modal`, or `failed`. A receipt is a fact report. **It must
never contain a writeback decision** -- no `complete_todo`, no
`create_user_gate`, no equivalent command field. A provider that reports such
a field is out of contract; a conformant validator rejects the receipt rather
than forwarding it.

The reducer that turns this receipt into a proposed transition belongs to the
capability that issued the original action request. It combines the receipt
with the action request that carried the current `gate_binding`, plus domain
policy that only the capability knows -- for example, what
`blocked_by_unknown_modal` should mean for a publish workflow versus a
payment flow. The Kernel then validates revision, authority, and quota
before accepting or rejecting the proposed transition. Neither the provider
nor this protocol makes that call.

## Operating Modes

| Mode | Default LoopX behavior | Gate before |
| --- | --- | --- |
| Public web metadata | Allow compact observation and source handle. | Quoting body text, outreach, posting, or trend claims. |
| Private enterprise tool | Emit owner gate and runtime profile only. | Reading private records, changing status, assigning users, exporting content. |
| Local desktop or browser session | Allow install/readiness checks and synthetic fixture runs. | Using logged-in accounts, downloading private files, destructive local actions. |
| Drafting workflow | Allow draft preparation from approved inputs. | Send, publish, submit, purchase, delete, production mutation. |
| Replay or skill capture | Store handle class and safety flags only. | Copying raw replay data, screenshots, credentials, or private UI text into LoopX state. |
| Benchmark or sandbox | Allow bounded sandbox receipts when task/source policy permits. | Raw task text, trajectories, verifier output, uploads, or leaderboard submissions. |

## Human Attention Contract

The provider is useful when it reduces the number of human interventions
while making the remaining interventions clearer. A user should see:

- what the provider is trying to do;
- what it is explicitly forbidden to do;
- what evidence was captured;
- whether the next step needs human review, another agent todo, or no action;
- how to take over the host surface if the provider is stuck.

Surfacing that question is the owning capability's job, using the receipt plus
its own domain policy -- not this protocol's. When a user gate is required,
the projection must name the exact decision:

```text
Review the host-owned draft and approve or reject the final external action.
```

It should not say only "owner gate" or "waiting for user".

## Failure And Recovery

The provider should return a blocker instead of improvising when it sees:

- an unknown modal, captcha, login, payment, permission prompt, or destructive
  confirmation;
- a source whose privacy status is unclear;
- repeated focus or app-lifecycle failures;
- missing replay/evidence handle for a claimed action;
- a stale `gate_binding` revision, or an action request whose `effect_class`
  requires a gate that is not open.

The recovery path is another LoopX todo or user gate, decided by the owning
capability's reducer -- not a longer chain of unbounded UI clicks, and not a
decision the provider makes for itself.

## Smoke Expectations

Initial coverage should use synthetic, declarative fixtures -- a fixture
describes a UI/session state; it does not hand a fake provider the answer it
is expected to produce. The validator must judge each fixture against the
schema and the ownership rules above independently of what the fixture
"wants" to prove, or the test becomes self-proving.

Useful public smokes:

- an action request whose `effect_class` is `external_write` or
  `credential_use` without a current `gate_binding` is rejected;
- a receipt for a fixture with an unrecognized modal present must report
  `stop_reason: blocked_by_unknown_modal` and no state-changing action;
- a receipt is rejected if it carries raw screenshot bytes, cookies,
  credentials, or full private page bodies -- including a compact-looking
  field that smuggles credential-, cookie-, or session-token-shaped content
  even when the provider's own `raw_evidence_copied` flag falsely claims
  `false`;
- a receipt is rejected or handled idempotently if its `gate_binding`
  revision is stale, or if the same `idempotency_key` is replayed;
- a receipt is rejected outright if it contains any writeback-decision-shaped
  field (`complete_todo`, `create_user_gate`, or equivalent) -- a provider
  must never author a Kernel writeback;
- a receipt is rejected if its `goal_id`, `todo_id`, `provider_id`, or
  `attempted_action_unit` do not match the action request it claims to
  answer -- this is an identity check only, not an interpretation of the
  outcome.

Live provider tests may be added later, but they must use the same compact
packet shape and keep raw host evidence in the host or private project store.

## Related Contracts

- A concrete vertical slice belongs inside the capability that owns the
  outcome (for example `content-ops` for a draft-until-gate publish flow, or
  `explore` for long-horizon research browsing), not in this protocol and not
  in `value-connectors`. See the capability's own docs for its
  reducer and CLI surface once that slice lands.
- `computer_use_session_v0`, `computer_use_replay_handle_v0`, and
  `computer_use_handoff_gate_v0` are promoted into this protocol only after a
  second real capability consumer needs the same shape -- extraction follows
  proof, not anticipation.
- [Host integration surface v0](host-integration-surface-v0.md) defines the
  CLI-equivalent read/write baseline for host integrations.
- [Session runtime to LoopX projection v0](session-runtime-loopx-projection-v0.md)
  defines the compact projection discipline for host session facts.
- [Content ops surface v0](content-ops-surface-v0.md) and
  [value connector plan v0](value-connector-plan-v0.md) define adjacent
  publish-gate and external-value patterns; they are examples of capability
  ownership, not the owner of this contract.
