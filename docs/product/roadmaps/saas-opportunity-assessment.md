# SaaS Opportunity Assessment

Status: assessment target. This note is a strategic evaluation, not a
commitment to build. It asks which parts of LoopX could support a hosted,
recurring-revenue product without weakening the local-first control-plane
contract that LoopX is built on.

## The Core Tension

LoopX's value proposition is a local-first control plane: durable goal state,
evidence, quota, and handoffs that the operator owns outright. A naive SaaS
move — "we host your agent state on our servers" — destroys the exact property
that makes the product trustworthy.

So the SaaS question is not "can LoopX be hosted?" It is:

> Which layers become *more* valuable when they live in the cloud, and which
> layers must stay local by design?

Anything that requires collaboration, durable cross-device access, or a
shared source of truth benefits from a hosted layer. Anything that is the
operator's ground truth — local goal state, private workspace content,
credential-adjacent material — stays local.

## Viability Test

A hosted offering is worth building only if it passes all three:

1. **Continuous use**: operators return to it daily, not once per install.
2. **Cloud-improved**: collaboration, sharing, or durability make the hosted
   version strictly better than files on one machine.
3. **Natural expansion**: revenue grows with seats, managed agents, retention,
   or integrations — not with one-off features.

These tests are applied to each candidate below.

## Candidate Directions, Ranked

### 1. AgentOps Observation And Governance Cloud

The strongest candidate: a "Datadog / Langfuse for agent loops" focused on
goals, evidence, and quota rather than on LLM traces.

The control plane already produces the raw material: goal state, run history,
evidence events, quota decisions, and handoff records. A hosted observation
layer turns this into a shared team surface:

- a cross-member goal board: who is running which agents, on what objectives;
- quota and budget views that map spend to goals rather than to API calls;
- gate and approval queues routed through Lark or equivalent channels;
- evidence drill-downs that survive a machine wipe or an operator switch.

Why it fits: observation is consumed continuously, is useless without
collaboration at team scale, and revenue scales with seats and managed agents.
The dashboard frontend already exists (`apps/presentation/dashboard`), and the
status data contract (`docs/status-data-contract.md`) is a public projection
surface that a hosted read model can consume without ever touching private
state.

Pricing sketch: free tier for a single operator with short retention; team
tier priced per seat plus per managed agent; governance features (approval
routing, retention, export) gated to the team tier.

### 2. Evidence And Review SaaS

A narrower, compliance-adjacent product: immutable evidence retention,
review-ready handoff reports, and periodic "what did the agents do and why"
summaries.

This is the same product as direction 1 sold under a different contract.
Observation sells to the team that runs agents today; evidence and review
sells to the organization that must justify agent decisions to stakeholders
later. As agents enter production workflows, "show me the evidence" moves
from a nice-to-have to an admission requirement.

The event-sourced state model and the existing evidence/handoff projection
make this realistic without new runtime machinery. The limiting factor is
trust: customers must believe retained evidence is complete and unmodified,
which pushes toward append-only storage and signed exports.

### 3. Hosted Control Plane, Preferably BYOC

The foundations note `server-client-product-shape.md` already names the
medium-term shape: the server owns durable goal state, event history, and
governed planning lanes. That architecture carries a quiet proof that SaaS
plumbing is natural here:

- quota and spend policy already exist per goal;
- writes are idempotent and events are append-only;
- the public/private boundary classifier is a first-class runtime concept.

Those are exactly the mechanisms a multi-tenant control plane needs. The
risk is not technical fit; it is operational gravity. Hosting the authoritative
state for a customer's production agent loops makes LoopX part of their
critical path, with matching SLA burden.

The lower-risk entry is BYOC: the control plane runs in the customer's cloud
account, and LoopX sells the console, upgrades, and support. This preserves
the local-first promise — the customer still owns the state — while creating a
recurring-revenue surface. Full multi-tenant hosting is a later decision, not
a prerequisite.

### 4. Domain Packs With Marketplace Revenue

Domain capability packs
(`docs/product/domain-capability-packs.md`) are a monetization layer,
not a standalone SaaS. Sold individually, they are one-time purchases.
Attached to a hosted platform with a marketplace take rate, they become
recurring. This direction depends on direction 1 or 3 existing first; it
cannot lead.

## What Should Not Be SaaS

- **Execution hosting** ("we run your agents"): it competes with frontier
  model vendors on compute margins and contradicts the architectural rule
  that the control plane does not own domain behavior.
- **Hosted CLI state as the product**: nobody pays to move local files to
  someone else's disk. The cloud layer must add collaboration or governance
  value, not just relocate state.

## Honest Constraints

- **Cold start**: an observation cloud needs enough teams running LoopX loops
  to have something to observe. The realistic loop is: free CLI adoption
  grows the base, then a cloud tier converts the teams that emerge. Expect a
  long horizon before the SaaS layer is self-sustaining.
- **Brand tension**: local-first and SaaS pull in opposite directions. Done
  well this is differentiation ("your state stays yours; the collaboration
  layer is hosted"). Done carelessly it reads as a bait-and-switch.
- **Maintenance surface**: hosted products carry on-call, data retention, and
  customer-support obligations that a single-maintainer OSS project does not
  currently have. The first paid tier should be deliberately narrow.

## Suggested Path

Phase 0 — opt-in observation relay: a `loopx cloud sync` command that pushes
public-safe status projections to a hosted dashboard. Free for individuals,
short retention. This is the smallest possible wedge: `status_server` and the
dashboard already exist, so the new surface is an account system and a hosted
read model.

Phase 1 — team tier: shared goal boards, Lark-routed approvals, and quota
budgets across seats. Priced per seat plus per managed agent.

Phase 2 — evidence and review tier: long retention, signed evidence exports,
review-ready summaries. Sold to organizations rather than teams.

Phase 3 — BYOC hosted control plane and domain-pack marketplace revenue.

Each phase is independently shippable and each funds the next; no phase
requires betting on the full multi-tenant end state.

## Relation To Existing Docs

- `../foundations/server-client-product-shape.md` names the durable
  control-plane server role this assessment builds on.
- `../surfaces/README.md` and the frontstage notes cover the public
  presentation surfaces that a hosted dashboard would extend.
- `../domain-capability-packs.md` defines the pack boundary that direction 4
  monetizes.

This note intentionally avoids pricing commitments, launch dates, and
capacity promises. It is a map of where SaaS revenue could plausibly live,
to be revisited when the CLI adoption funnel justifies a hosted tier.
