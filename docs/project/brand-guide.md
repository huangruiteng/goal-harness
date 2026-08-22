# LoopX Brand Guide

This guide keeps the public LoopX story coherent while the product and its
community continue to grow. It is editorial and product guidance, not legal
trademark advice; name and mark usage remains governed by
[`Name And Marks`](trademarks.md).

## 1. Brand Position

### One-line description

**LoopX is the dynamic goal control plane for long-running agents.**

LoopX runs on top of agent harnesses and keeps goal state, todos, decision
scope, gates, evidence, quota, handoff, and recovery legible across turns.
The harness still executes bounded work. LoopX governs the state that makes
long-running work reviewable and recoverable.

### Short product description

LoopX is an open, provider-neutral, local-first state kernel for long-running
agent work. It gives maintainers and operators a durable view of what an agent
did, what is blocked, what evidence exists, what can continue, and what needs
human judgment.

### Product boundary

LoopX is not a model, an agent runtime, a full agent platform, or an autonomous
production controller. It does not grant credentials, approve destructive or
production actions, or turn an unverified run into evidence of success.

## 2. Message Pillars

Use these four ideas as the default order for product, documentation, and
community communication:

1. **Long-horizon continuity** — goals and evidence survive sessions, runtime
   changes, handoffs, and bounded turns.
2. **Human judgment at explicit boundaries** — gates and decision scopes make
   waiting, approval, and safe continuation visible.
3. **Evidence-backed progress** — a completed Todo is not the same thing as a
   proved goal outcome; validation and writeback stay connected.
4. **Provider-neutral control** — Codex, Claude Code, and other workers can
   execute the work while LoopX keeps the shared control state.

### Preferred compact phrases

- long-running agent work
- dynamic goal control plane
- durable state kernel
- bounded agent turns
- evidence-backed progress
- human-gated continuation
- provider-neutral and local-first
- source state and projections

## 3. Audience And Reader Path

- **Maintainers and operators** need a clear answer to “what needs attention
  now?” Lead with gates, evidence, ownership, cost, and next action.
- **Agent and platform builders** need the contract boundary. Lead with state,
  receipts, host adapters, and the fact that LoopX does not own execution.
- **Contributors** need a bounded entry point. Link to a task, the owning
  direction, non-goals, and the smallest validation surface.
- **Adopters and users** need a truthful way to describe use. Link to
  [`ADOPTERS.md`](../../ADOPTERS.md) and label self-attested usage separately
  from maintainer-observed ecosystem evidence.

## 4. Voice And Editorial Rules

LoopX communication should follow a technical note rhythm:

- state the judgment before the background;
- explain the mechanism with concrete objects such as `goal`, `todo`, `gate`,
  `evidence`, `quota`, or `receipt`;
- distinguish shipped behavior, public observation, user report, and proposal;
- state what the evidence does not prove;
- keep the language direct, calm, and useful to a maintainer;
- prefer a small reproducible example over a large promise.

Avoid:

- hype such as “fully autonomous”, “zero oversight”, “guaranteed”, or
  “never drifts” without a narrowly defined contract;
- treating a demo, star count, control-plane window, or one passing task as
  proof of product-market fit or universal capability;
- calling a runtime adapter, dashboard, or projection the source of truth;
- presenting an RFC, integration branch, or planned adoption as shipped;
- copying private conversations, internal timelines, local paths, raw runs,
  or user details into public material.

## 5. Claim Labels

Use a label that matches the evidence behind a public statement:

| Label | Use it when | Example boundary |
| --- | --- | --- |
| **Shipped** | The behavior is in `main`, a release, or a stable public contract. | “LoopX ships typed Todo and quota contracts.” |
| **Observed** | A public-safe run, fixture, or repository artifact demonstrates the behavior. | “The public fixture shows a recoverable handoff.” |
| **Reported** | A user or project has made a clearly attributed public report. | “A user reported a four-day unattended run.” |
| **Proposed** | The idea lives in an RFC, issue, discussion, or unpromoted branch. | “The provider-neutral state provider is proposed.” |

Do not silently upgrade a **Reported** or **Proposed** claim into **Shipped**.
For more detailed evidence boundaries, follow the [public/private boundary
policy](../public-private-boundary.md) and the maturity terms in [Current
Technical Directions](technical-directions.md).

## 6. Visual Direction

The current public surfaces use a restrained control-plane visual language:

- **Structure:** light neutral backgrounds, slate text, thin rules, compact
  diagrams, and generous whitespace for documentation and operator views.
- **Emphasis:** blue or indigo for the LoopX state kernel and primary actions;
  use green, amber, and red only for distinct status or gate meaning.
- **Social and showcase surfaces:** the existing dark indigo social preview
  and light control-plane diagrams may be reused; do not introduce a second
  logo or visual identity for a one-off campaign.
- **Typography:** prioritize readable system sans for interfaces and clear
  mixed Chinese/English text in notes. Code and protocol names remain visibly
  distinct from explanatory prose.
- **Diagrams:** show source state, bounded execution, human judgment, evidence,
  and projections as different roles. A projection must never look like the
  authority that owns state.

Reuse the assets in `docs/assets/` where they fit. New artwork should preserve
the same information hierarchy and accessibility contrast rather than chase a
trend or add decorative gradients.

## 7. Naming And Relationship Language

- Write the project name as **LoopX**, never `Loop X`, `loop-x`, or an
  unqualified “autonomous agent platform”.
- Use **Agent Control Plane** when introducing the category to a broad reader;
  use **dynamic goal control plane** when describing the current product
  contract.
- Say that a project **uses**, **integrates**, **extends**, or is **inspired by**
  LoopX only when the public evidence supports that relationship.
- Do not imply sponsorship, certification, endorsement, or official status.
  Modified distributions need their own primary name and must follow the
  project-name guidance in [`trademarks.md`](trademarks.md).

## 8. Review Checklist

Before publishing a new public page, release note, showcase, or adoption row,
ask:

1. Is the first sentence a truthful product or project judgment?
2. Which LoopX object or contract makes the claim concrete?
3. Is the claim shipped, observed, reported, or proposed?
4. Does the text say what is out of scope or not proven?
5. Are the source, operator, user, and privacy boundaries public-safe?
6. Does the visual or link path preserve the same state-versus-projection
   distinction?
