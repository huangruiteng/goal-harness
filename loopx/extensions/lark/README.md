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
| `lark-periodic-report-announcement` | Deliver a periodic report while mentioning only recipients selected by its typed audience plan | [`presentation/periodic_report.py`](presentation/periodic_report.py) |
| `lark-miaoda-html-report` | Publish an already-rendered periodic report to an operator-selected existing Miaoda app | [`presentation/periodic_report.py`](presentation/periodic_report.py) |

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

For Miaoda, `loopx periodic-report publish-miaoda --request-json <path>` first
previews a typed hosted-delivery intent. Add `--execute` only after checking the
profile-bound sink, request-selected app, and artifact. The command delegates
authentication and the external publish/readback calls to `lark-cli`; LoopX
stores no credentials and does not treat local HTML generation as hosted
delivery.

For a Lark report announcement, the Periodic Report profile owns symbolic
recipients, domains, and typed routing rules. The core compiles the relevance
plan without provider identities. Preview performs no identity lookup or send;
execute resolves only selected recipients and omits unrelated recipients. Raw
`<at>` markup in report content or card metadata cannot bypass that policy.

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

## 创建 LoopX 机器人（推荐权限集）

每个新的 LoopX 企业自建应用（例如 Goal Channel 的发送 bot）应一次性申请
推荐权限集，而不是边用边补。清单见
[`bot_scopes.py`](bot_scopes.py)（`RECOMMENDED_BOT_SCOPES`），按用途分三档：

- 核心（Goal Channel / reviewer / kanban）：`im:message`、`im:chat:read`、
  `im:chat:create`、`im:chat:update`、`im:chat.members:read`、
  `im:chat.members:write_only`、`contact:user.base:readonly`、
  `contact:contact.base:readonly`、`application:application:self_manage`、
  `application:bot.basic_info:read`
- 收件箱（事件订阅收消息，敏感需审核）：`im:message.group_msg`、
  `im:message.p2p_msg:readonly`
- 交互/文档 sink：`cardkit:card:read/write`、`docs:document.comment:read/create/delete`

拿到 App ID（`cli_xxx`）后，可在开发者后台一键批量申请：

```text
https://open.larkoffice.com/page/scope-apply?clientID=<app_id>&scopes=<scope1%2Cscope2...>
```

（`recommended_bot_scope_apply_url(app_id)` 会拼出完整 URL。）随后用
`lark-cli config init --app-id <app_id> --app-secret-stdin --name <profile> --brand lark`
注册 bot profile，再走 `loopx goal-channel setup`。敏感 scope 需企业管理员审核。
