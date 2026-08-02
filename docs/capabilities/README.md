# LoopX Product Capabilities

This directory groups LoopX product capabilities by real usage path. Keep kernel
control-plane code generic; put scenario-specific protocols, implementation
modules, CLI entrypoints, and smokes under the capability they serve.

## Capabilities Add Domain Lanes, Not Kernel Columns

An operator surface may render LoopX as an agent-native Kanban. In that view,
the Kernel supplies generic lifecycle operators such as claim, gate, monitor,
complete, supersede, quota, and writeback. A capability may add a domain lane
that interprets provider observations, but it must not create a parallel todo
or scheduling authority.

For example, Issue Fix can project
`feasibility -> patch -> checks -> review -> merge`, while an experiment pack
can project `hypothesis -> execute -> evaluate -> promote/retire`. These labels
are derived from capability-owned domain state and accepted Kernel transitions.
They are not new core lifecycle statuses. If a domain stage changes permission,
claim eligibility, quota, a user gate, or terminal closure, the capability must
propose a typed transition through the existing Kernel contract.

Current capability paths:

- [integration-branch](integration-branch/README.md): detect when a reviewed
  feature or fix branch has moved, then preview or safely rebuild one local
  integration branch from exact current source heads.
- [decision-context](decision-context/README.md)
  ([中文](decision-context/README.zh-CN.md),
  [architecture](../reference/protocols/decision-context-architecture-v0.md)):
  separate current evidence, advisory proposals, and verified outcomes through
  default-off provider-neutral packet and incremental source contracts.
- [material-lifecycle](material-lifecycle/README.md)
  ([中文](material-lifecycle/README.zh-CN.md),
  [architecture](../reference/protocols/material-lifecycle-architecture-v0.md)):
  preserve raw source authority while inventorying, archiving, migrating, and
  applying bounded material reranks.
- [periodic-report](periodic-report/README.md): evaluate cadence and material
  progress triggers, then compose deterministic provider-neutral report runs
  with source, artifact, archive, and delivery receipts.
- [issue-fix](issue-fix/README.md) ([中文](issue-fix/README.zh-CN.md)): turn
  public GitHub issue/PR signals into focused fixes, explainable reviewer
  routes, authority-gated PRs, and monitored lifecycle outcomes.
- [content-ops](content-ops/README.md): collect public/private content signals
  into reviewable source, angle, draft, feedback, and publish-gate packets.
- [value-connectors](value-connectors/README.md): install and run public-safe
  external-value connector starters, beginning with body-free GitHub public
  channel metadata probes, plus gated candidate profiles such as X/browser
  social work and finance market snapshots.
- [explore](explore/README.md): record long-running exploration results as a
  compact topology (nodes, edges, findings) and project them into a
  Feishu/Lark Base result board and result card.

Do not add a capability path until there is at least one real CLI entrypoint and
one smoke test. Future ideas belong in product planning docs until they have
executable evidence.
