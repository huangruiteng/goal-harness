# Lark Provider

The bundled `loopx-lark` extension supplies optional Lark execution and
presentation providers. It does not replace LoopX goal, todo, gate, quota,
evidence, or recovery authority.

## Provided capabilities

| Capability | Outcome | Primary implementation |
| --- | --- | --- |
| `lark-event-inbox` | Collect, inspect, reply to, and acknowledge bounded project feedback | [`event_inbox.py`](event_inbox.py), [`event_collector.py`](event_collector.py) |
| `lark-reviewer-notification` | Send and verify a reviewer notification through a project-dedicated Lark app | [`reviewer_notification.py`](reviewer_notification.py) |
| `lark-kanban-projection` | Render public-safe LoopX todo and control-plane projections into Lark Base | [`presentation/kanban.py`](presentation/kanban.py) |
| `lark-goal-channel` | Bind one verified Lark group and projection surface to one LoopX goal | [`goal_channel.py`](goal_channel.py), [`goal_channel_setup.py`](goal_channel_setup.py) |
| `lark-explore-projection` | Project canonical Explore results into Lark tables, cards, and whiteboards | [`presentation/explore_results.py`](presentation/explore_results.py) |
| `lark-miaoda-html-report` | Publish an already-rendered periodic report to a profile-owned Miaoda app | [`presentation/periodic_report.py`](presentation/periodic_report.py) |

The [event inbox guide](docs/lark-event-inbox.md) documents the complete
collector, processing, reply, reaction, and acknowledgement lifecycle. The
[Lark Kanban integration guide](../../../docs/integrations/lark-kanban-control-plane-adapter.md)
documents projection configuration and lineage.

## Lifecycle

Install the bundled provider explicitly, then read back its readiness:

```bash
loopx extension install --bundled loopx-lark --execute --format json
loopx extension doctor loopx-lark --execute --format json
loopx capability list --format json
```

Disable or roll back the provider without changing the owning capabilities or
Kernel state:

```bash
loopx extension disable loopx-lark --execute --format json
loopx extension rollback loopx-lark --execute --format json
```

Installation controls discoverability and provider lifecycle only. Every
private chat, app, group, Base, document, or Miaoda target remains in ignored
local configuration. External writes still require the owning capability's
exact authority, gate, revision, idempotency, and readback contract.

## Ownership boundary

- The extension owns Lark authentication checks, provider dispatch, bounded
  payload conversion, delivery receipts, and readback.
- Outcome capabilities such as Issue Fix, Explore, and Periodic Report own the
  domain request and interpret provider receipts.
- The Kernel alone accepts durable todo, gate, quota, evidence, and recovery
  transitions.
- Lark projections are sinks. They never become the control-plane source of
  truth.

The declarative capability and permission surface is maintained in
[`extension.toml`](extension.toml). Provider readiness never grants a new
permission or silently enables an external write.
