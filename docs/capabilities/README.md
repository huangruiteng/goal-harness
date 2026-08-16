# LoopX Product Capabilities

A LoopX capability is a stable, provider-neutral contract for producing one
bounded, verifiable caller outcome from LoopX state. It owns the domain policy,
normalizes provider observations, validates the result, and proposes a typed
transition to the Kernel.

Contributors can move from these product contracts to their implementation,
registry, and validation through the
[capability code map](https://github.com/huangruiteng/loopx/tree/main/loopx/capabilities).
That code tree is a navigation surface, not evidence that a capability is
registered or enabled.

That makes it different from the surrounding boundaries:

- the [Kernel](../architecture.md#runtime-responsibility-model) owns durable
  goal, todo, gate, quota, recovery, and scheduling truth;
- a provider performs a bounded external or local operation and returns
  readback;
- an [extension](../reference/extensions.md) packages and operates an optional
  provider without acquiring Kernel authority;
- host declarations such as `shell` and `network` describe runtime capacity,
  not a product capability or a permission grant.

## Inspect What This Release Can Do

The runtime registry is authoritative. Directories and documentation do not
become shipped capabilities merely by existing:

```bash
loopx capability list --format json
loopx capability show issue-fix --format json
```

`list` reports registered capability and provider readiness. `show` adds the
user value, maturity, entry commands, explicit write boundary, implemented
protocols, and durable validation for one capability. Use that readback before
enabling an advanced path or optional provider.

## Choose By Outcome

The selected documents below explain human usage paths behind registered
capabilities. The CLI remains the source for the complete catalog and for exact
availability and maturity in the installed release.

### Engineering Delivery

| You need to... | Capability path |
| --- | --- |
| Turn public issue and PR signals into a focused, reviewable fix with validation evidence | [issue-fix](issue-fix/README.md) capability ([中文](issue-fix/README.zh-CN.md)) |
| Qualify the exact final diff through bounded review, safe repair, and strict receipts | [Change Quality](change-quality/README.md) |
| Detect source-head drift and safely rebuild a local stack of already reviewed branches | [Integration Branch](integration-branch/README.md) |

### Research And Decision Continuity

| You need to... | Capability path |
| --- | --- |
| Preserve questions, hypotheses, experiments, findings, and composition frontiers across a long exploration | [Explore](explore/README.md) ([中文版](explore/README.zh-CN.md)) |
| Separate current evidence, advisory proposals, and verified outcomes before making a decision | [Decision Context](decision-context/README.md) ([中文](decision-context/README.zh-CN.md)) |
| Recall a settled autonomous turn without manufacturing a new user prompt | [Agent Turn Recall](agent-turn-recall/README.md) |
| Add optional, provider-neutral preference recall without making memory the state authority | [Semantic Preference](semantic-preference/README.md) |

### Operations And Projection

| You need to... | Capability path |
| --- | --- |
| Compose scheduled or progress-triggered reports with source, archive, delivery, and settlement receipts | [Periodic Report](periodic-report/README.md) |
| Turn public/private content signals into reviewable source, angle, draft, feedback, and publish-gate packets | [Content Operations](content-ops/README.md) |
| Inventory, archive, migrate, and rerank a material store without losing raw source authority | [Material Lifecycle](material-lifecycle/README.md) ([中文](material-lifecycle/README.zh-CN.md)) |
| Inspect compatibility routes for public-safe external-value intake while callers migrate to outcome-owned capabilities | [Value Connectors](value-connectors/README.md) |

## From Capability To Provider

The execution and control paths deliberately run in opposite directions:

```text
Agent -> Capability -> Provider -> external system
Provider readback -> Capability transition proposal -> Kernel
```

Start from the caller outcome, not from an extension name. A built-in provider
may already implement the capability. When an optional implementation is
needed, inspect its declared permissions and readiness, then use the explicit
install, doctor, enable, disable, upgrade, and rollback lifecycle documented in
[Extensions and Capabilities](../reference/extensions.md). Installing an
extension does not grant new authority.

## Architecture Rule: Domain Lanes, Not Kernel Columns

An operator surface may render LoopX as an agent-native Kanban. The Kernel
supplies generic lifecycle operators such as claim, gate, monitor, complete,
supersede, quota, and writeback. A capability may add a domain lane that
interprets provider observations, but it must not create parallel todo or
scheduling authority.

For example, Issue Fix can project
`feasibility -> patch -> checks -> review -> merge`, while an experiment path
can project `hypothesis -> execute -> evaluate -> promote/retire`. These labels
come from capability-owned domain state and accepted Kernel transitions; they
are not new core lifecycle statuses. If a domain stage changes permission,
claim eligibility, quota, a user gate, or terminal closure, the capability must
propose a typed transition through the existing Kernel contract.

Keep Kernel control-plane code generic. Put scenario-specific protocols,
implementation modules, CLI entrypoints, and smokes under the capability they
serve. Do not add a capability path until there is at least one real CLI
entrypoint and one durable smoke. Future ideas belong in product planning docs
until they have executable evidence.
