<div align="center">

<h1 align="center">LoopX</h1>

<img src="docs/assets/loopx-social-preview.png" alt="LoopX Loop Engineering 展示图" width="560">

**面向长程 AI Agent 工作的本地控制面。**

<sub>Codex、Claude Code、Cursor 或自有 runtime 负责一次次有界执行；LoopX 让目标、gate、todo、证据、quota 和交接跨轮次保持稳定。</sub>

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![Release](https://img.shields.io/github/v/release/huangruiteng/loopx?display_name=tag)](https://github.com/huangruiteng/loopx/releases/latest) [![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml) [![Local first](https://img.shields.io/badge/control--plane-local--first-brightgreen.svg)](docs/public-private-boundary.md) [![Loop Agents](https://img.shields.io/badge/status-loop%20agents%20early-orange.svg)](docs/product/release-readiness.md)

[试用 LoopX](#试用-loopx) · [查看真实 Loop](#证据) · [理解工作原理](#为什么需要-loopx) · [Hosted Frontstage](https://huangruiteng.github.io/loopx/frontstage/) · [用户手册](https://my.feishu.cn/wiki/CaL5wMk9ui17ngkWzeUcMlAYnZg) · [English](README.md)

**把会干活的 Agent，接成可管理、可复盘、可持续改进的数字员工。**

</div>

---

LoopX 是一个轻量 state kernel，也是 agent-agnostic 的本地 Loop Engineering
控制面。它不替代 agent runtime，而是让跨轮次、跨工具、跨 agent 的工作可审阅、
可恢复、可接力。

> 让 Loop 持续向前，让关键判断留在人手里。

## 为什么需要 LoopX

一个 agent 可以在单次会话里完成任务。长程工作更难：目标会变化，用户决策会出现，
证据会过期，平级 agent 会交接，scheduler 也可能在已经没有有效状态迁移时继续消耗。
聊天记忆和定时器不足以治理这些问题。

LoopX 把长期控制状态留在同一层紧凑状态里：

```text
目标 / issue / project
   │
   ▼
LoopX state：objective + gate + todo + scope + evidence + quota
   │
   ├─ 需要人类判断？ ── 是 ─▶ 提出具体问题并等待
   │
   ├─ 有安全侧路？ ─────────▶ 执行一个有界 agent slice
   │
   ▼
Codex / Claude Code / Cursor / shell agent 执行一轮
   │
   ▼
写回证据 + handoff + next todo ─▶ quota 决定下一次 tick
```

![LoopX control-plane board](docs/assets/control-plane-board.svg)

一个形象化理解是：LoopX 是
**[面向长程 Agent 的可执行看板](docs/development/control-plane-course/00-concept-primer.md)**。
卡片带有稳定身份、权限、证据和 continuation；移动卡片要经过 claim、gate、
monitor、validate、writeback 等 typed operator。看板是 projection，LoopX state
才是事实源。

注册 agent 彼此平级。todo claim、lease、任务边界、能力门和 typed continuation
共同决定下一步谁执行，不需要一个长期拥有全局权限的 leader agent。

LoopX 适合：

- 多天或多周的工程、研究、benchmark、实验目标；
- 需要跨轮保留 scope、证据和 review 状态的 issue / PR Loop；
- recurring heartbeat 或 monitor-style agent 工作；
- 带 owner、安全、发布或私有数据 gate 的项目；
- 需要 ownership、lease 和 handoff 的平级 agent team；
- 需要把进展、阻塞和反馈入口清晰呈现给非技术用户的创作、研究或运营工作。

LoopX 不是生产自动化控制器。危险权限、生产写入、公开发布和最终 ownership
仍由人类负责。

<a id="看几个例子"></a>

## 证据

这些不是单轮 demo。OpenViking Issue-Fix 与 Auto ML 两条真实轨迹各自跨越
**200+ 小时自然时长**，持续保留多轮 todo、决策和证据更新。这里的自然时长是
项目从启动到最新证据的 wall-clock 时间，不等于 200 小时连续模型执行，也不代表
无人值守的生产自治。点击原图可以检查 public-safe graph、证据分支和跨轮决策。

### 开源 Issue Fix

**超过 200 小时的公开贡献轨迹：Focused PR 交付与可复用修复知识互相反哺。**

<a href="docs/assets/long-running-loop-openviking-trajectory.png">
  <img src="docs/assets/long-running-loop-openviking-trajectory.png" alt="开源 Issue Fix 轨迹：连接 Focused PR 交付与 LoopX 通用能力沉淀" width="420">
</a>

LoopX 的创建者以
[OpenViking contributor](https://github.com/volcengine/OpenViking/pulls?q=is%3Apr+author%3Ahuangruiteng)
身份把这条路径用于持续的 issue-to-PR 修复。图中公开贡献序列从首个 PR 创建到
最后一次所示 review 或 update，跨越 200+ 小时。
[Issue-Fix 能力说明](docs/capabilities/issue-fix/README.zh-CN.md)把 rolling
repository context、带 revision 的修复知识和 reviewer-facing preference
分开管理；所链接 PR 与当前 checkout 的源码、测试始终具有最高权威。

### Auto ML Experiment

**超过 200 小时的 owner-run 实验轨迹：假设、matched evidence、无效谱系、
运行中复现和 promote / stop gate 留在同一张图中。**

<a href="docs/assets/long-running-loop-ml-experiment-trajectory.png">
  <img src="docs/assets/long-running-loop-ml-experiment-trajectory.png" alt="Auto ML Experiment 轨迹：实验谱系、证据门和晋级决策" width="760">
</a>

这张经过脱敏的 public-safe graph 保留了该 200+ 小时自然时间窗口中的决策谱系；
它是轨迹证据，不代表连续算力执行、独立复现或生产结果。

### Auto Research

**Proposer、executor、evaluator/promoter 并行迭代，todo、quota、证据与
targeted wake 同屏可见。**

<a href="docs/assets/auto-research-multi-agent-showcase.png">
  <img src="docs/assets/auto-research-multi-agent-showcase.png" alt="Auto Research 多 Agent 工作区：proposer、executor、evaluator/promoter、todo、quota、证据与 targeted wake 同屏推进">
</a>

更多可检查入口：

- [Hosted Frontstage](https://huangruiteng.github.io/loopx/frontstage/) 与
  [公开演示脚本](docs/outreach/frontstage-demo-script.md)；
- [Showcase 目录](docs/showcases/README.md)，包括
  [Blocked P0 安全侧路](docs/showcases/cases/0617-blocked-p0-safe-rotation.md)、
  [LoopX 自迭代](docs/showcases/cases/0619-loopx-self-iteration.md)和
  [动态工作流编排](docs/showcases/cases/0619-dynamic-workflow-hardware-agent.html)；
- [跨 runtime 实现审阅演示](docs/product/cross-runtime-impl-review-demo.md)；
- 公开[用户手册](https://my.feishu.cn/wiki/CaL5wMk9ui17ngkWzeUcMlAYnZg)。

<a id="快速开始"></a>

## 试用 LoopX

要求：Python 3.11+、`curl`、`tar`，以及 macOS 或 Linux shell。普通用户不需要
Git；Python package 除标准库外没有 runtime 依赖。

无需 clone，直接安装：

```bash
curl -fsSL https://raw.githubusercontent.com/huangruiteng/loopx/main/scripts/install-from-github.sh | bash
export PATH="$HOME/.local/bin:$PATH"
loopx doctor
```

然后在项目根目录连接：

```bash
cd /path/to/your-project
loopx connect
loopx status
```

如果项目尚未初始化，且 `connect` 明确提示缺少状态，可以走 guided path：

```bash
loopx start-goal --guided --project . --goal-text "你的长程目标"
```

已有 LoopX state 应复用，不要覆盖。确保 `.loopx/`、`.codex/goals/`、`.local/`
不会被提交。

### 从你已经在用的 Agent 启动

| Host | 推荐入口 | Loop driver |
| --- | --- | --- |
| Codex App | 让 agent 在当前项目里连接 LoopX、运行 `loopx doctor`、保留已有状态，并汇报当前 gate 和下一条 todo；然后用 `$loopx <复杂任务>` 或 `/skills` 里的 `loopx`。 | Codex App heartbeat；cadence 跟随 `quota should-run.scheduler_hint` |
| Codex App over SSH | `loopx agent-onboard --agent-type codex-app-ssh --project .` | 返回的可见 `/goal <task_body>` |
| Codex CLI | 在项目里启动 `codex`，让它连接并诊断 LoopX，然后用 `$loopx <复杂任务>` 或 `/skills`。 | 可见 `/goal <task_body>`；默认不走隐藏 headless 执行 |
| Claude Code | 安装 opt-in adapter，然后运行 `/loopx <任务>`，再运行 `/loop`。 | 由 LoopX gate 的原生 Claude Code `/loop` |
| OpenCode | 安装静态 command facade；recurring goal 显式 opt in `--with-goal-bridge`。 | OpenCode command facade 与显式 goal bridge |
| Cursor、shell、自有 runner | 使用同一 installer 和 `loopx doctor`，再手动连接或由 runner 调用。 | 你的 shell、scheduler 或 runner |

可直接粘贴的完整 setup message、host-specific 路由和故障恢复见
[Getting Started](docs/guides/getting-started.md)。Host 集成还可以查看
[Codex App host command registry](docs/reference/protocols/codex-app-host-command-registry-v0.md)、
[Codex CLI packaged install](docs/product/codex-cli-packaged-install.md)和
[Claude Code adapter](loopx/claude_goal_mode/README.md)。

自有 runner 请读
[把 LoopX 嵌入你的 Agent Runner](docs/guides/custom-agent-runner-integration.zh-CN.md)
与 [Worker Bridge Install Contract](docs/worker-bridge-install-contract.md)。
核心 tick 很小：

```text
loopx quota should-run      # 当前注册 agent 是否应该执行？
loopx todo claim            # 谁拥有这个 slice？
loopx todo update           # 发生了什么？
loopx refresh-state         # 下一轮应该看到什么？
loopx quota spend-slot      # 为完成并验证的 slice 记账
```

成功连接后应该满足：

- `loopx doctor` 通过；
- 项目具有 `.loopx/registry.json` 和 active goal projection；
- `loopx status` 能显示当前目标、具体 user gate 和下一条 agent todo；
- 有可见 Loop driver，或 agent 给出精确 activation 指令；
- 本地 runtime state 被 ignore，而不是提交。

Clone 安装只面向需要 live canary wrapper 的贡献者：

```bash
git clone https://github.com/huangruiteng/loopx ~/loopx
~/loopx/scripts/install-local.sh
loopx doctor
```

## 能力

LoopX 把控制面归结为五个用户可以直接行动的问题：

| 问题 | LoopX 保持可见的状态 |
| --- | --- |
| 当前目标是什么？ | Active goal、明确 scope 和当前 authority。 |
| 下一步是什么？ | 有序 user / agent todo、ownership、claim 和 lease。 |
| 哪一步需要人判断？ | 具体 user gate，而不是模糊的“等待 owner”。 |
| 证据发生了什么变化？ | 紧凑 run history、验证、blocker 和已接受 writeback。 |
| Loop 是否可以继续？ | Quota、capability、安全侧路、scheduler hint 和停止条件。 |

### 控制面能力

| Surface | 作用 | 从这里开始 |
| --- | --- | --- |
| Goal state 与 status | 跟踪 active state、todo、claim、gate、evidence、run history 和首屏关注点。 | `loopx status`、`loopx diagnose`、`loopx review-packet` |
| Quota 与 interaction contract | 决定一轮应该执行、提问、等待、自修复还是静默。 | `loopx quota should-run`、[Quota Allocation](docs/quota-allocation.md) |
| Agent runtime bridge | 让 Codex App、Codex CLI、Claude Code 和 generic worker 服从同一 guard。 | `loopx heartbeat-prompt`、`loopx codex-cli-bootstrap-message`、`loopx worker-bridge` |
| Operator surface | 呈现紧凑状态，但不让浏览器成为状态事实源。 | `loopx serve-status`、[Dashboard](apps/presentation/dashboard/README.md)、[Frontstage](https://huangruiteng.github.io/loopx/frontstage/) |
| External projection | 把 todo / gate 投影到协作表面，同时保持 LoopX 权威。 | `loopx lark-kanban`、[Lark Kanban adapter](docs/lark-kanban-control-plane-adapter.md) |
| Domain capability | 打包 Issue Fix、内容运营、value connector、ML 实验、benchmark 与 Explore 等可重复泳道。 | `loopx issue-fix`、`loopx content-ops`、`loopx value-connectors`、`loopx ml-experiment`、`loopx benchmark`、[Explore](docs/capabilities/explore/README.md) |
| 实验性上下文学习 | 通过 ignored、默认关闭的项目配置，为明确注册的 agent 试用 provider-neutral Reward Memory；OpenViking 是 provider 之一，不是全局依赖。 | `loopx reward-memory experiment-status`、[Reward Memory 中文架构](docs/reference/protocols/reward-memory-architecture-v0.zh-CN.md) |
| Governance pattern | 沉淀可复用的 routing、gate、evidence、projection 和 planning 形状。 | [Interaction Pattern Catalog](docs/interaction-pattern-catalog.md)、[State Model](docs/state-interaction-model.md) |

这些能力共同提供 lifetime goal、具体 user gate、经过审计的安全侧路、平级 todo
ownership、quota 与 steering、紧凑 run history、证据化 handoff、read-first 管理面、
项目级价值信号和 public/private boundary check。

### 四种运行责任

| 角色 | 负责什么 |
| --- | --- |
| **Agent** | 通过 host/runtime 完成方案、分析、工具使用和一次有界执行。 |
| **Provider** | 调用外部系统，返回 observation、effect result 与 readback。 |
| **Capability** | 定义调用者结果，归一化并验证 provider 输出，提出 typed transition。 |
| **Kernel** | 持久化 todo、gate、monitor、已接受 writeback、quota、恢复与调度。 |

执行路径是 `Agent -> Capability -> Provider`，控制结果沿
`Provider readback -> Capability transition -> Kernel` 返回。Extension 负责可选
provider 的打包和生命周期，不是另一个控制面 owner。详见
[核心架构](docs/architecture.md)与
[Extension / Capability 参考](docs/reference/extensions.md)。

## 进阶路径

第一次有用的 Loop 不依赖全部可选能力。只有工作真正需要时再开启这些路径。

启用进阶能力前，先只读查看当前目标的能力目录：

```bash
loopx configure-goal --goal-id <goal-id>
```

不带 `--execute` 时，它只报告当前/默认状态、适用条件、边界和可复制命令，
不会修改项目状态。

### Preset 与 Auto Research

安全 preset 覆盖 Daily Triage、Changelog Draft 和 PR Watch。更高级的 CI /
Dependency Sweeper 需要明确授权、隔离 worktree、verifier、quota/cost gate 和人工
review。Auto Research 通过 proposer、executor、evaluator/promoter 协作，同时保持
quota 和证据可见。详见
[入门 Preset 指南](docs/product/beginner-loop-presets.md)和
[Auto Research Command Path](docs/guides/auto-research-command-path.md)。

```bash
loopx preset list
loopx preset show daily-triage
```

查看 preset 是只读操作。对已连接的周期性目标，可运行
`loopx ready-score --goal-id <goal-id> --agent-id <agent-id>`，检查它是否适合重复运行。

### Governed Turn

LoopX 可以根据 validated receipt、fresh quota state 和 provider-neutral budget
生成一次纯函数、有界的 turn decision。当前 Codex CLI 启动路径和 activation contract
见 [LoopX Turn Codex CLI Quickstart](docs/product/loopx-turn-codex-cli-quickstart.md)。

### Explore Graph / Harness

Explore 正式支持、可选、默认关闭。它适合具有可量化 offline eval、baseline、
treatment 和 guardrail 的任务，不替代生产审批。先读
[Explore Capability](docs/capabilities/explore/README.md)及其
[Lark Presentation Mapping](docs/capabilities/explore/README.md#presentation-sink-lark-mapping)。

### 审阅 Agent 工作

`loopx review-packet` 提供 owner-facing 的紧凑视图：决策、证据、验证和未解决 gate。
[Intelligent Management Surface](docs/product/intelligent-management-surface.md)
解释 operator model；[Project-Level Reward Model](docs/product/project-level-reward-model.md)
定义产出数量、质量、token cost 和 user attention cost 的保守价值信号。

### App 与 Projection

- 本地 read-first UI：[Dashboard Guide](apps/presentation/dashboard/README.md)
- Public-safe 产品视图：[Hosted Frontstage](https://huangruiteng.github.io/loopx/frontstage/)
- 飞书投影：[Lark Kanban Adapter](docs/lark-kanban-control-plane-adapter.md)
- 通用 host 集成：[Integration Guide](docs/integration.md)
- 自有 multi-agent runner：
  [Custom Runner 中文指南](docs/guides/custom-agent-runner-integration.zh-CN.md)

可选 projection 让状态更易检查，但不会成为新的事实源。

### 日常操作与恢复

日常检查从这三个命令开始：

```bash
loopx status
loopx history --goal-id your-project-goal
loopx quota should-run --goal-id your-project-goal
```

自动轮次必须先检查 quota，只有完成验证与 writeback 后才记录 spend。静默 skip、
preflight failure 和 dry-run preview 不消耗 quota。一个 lane 被 user gate 阻塞时，
独立审计过的安全侧路可以继续，但不能绕过 gate。

平级 agent 在执行前使用 `loopx todo claim`，验证后使用 `loopx todo update`，
让 ownership 与证据持续可见。

Scheduler cadence 跟随 `quota should-run.scheduler_hint`；Codex App automation
通过 payload 返回的 `ack_hint.cli_args` 确认当前 hint。Collision recovery、monitor、
self-repair 和精确 operator 命令统一维护在
[Getting Started](docs/guides/getting-started.md)、
[Quota Allocation](docs/quota-allocation.md)和
[Long-Task Cadence Policy](docs/long-task-cadence-policy.md)。

公开发布前运行：

```bash
loopx check \
  --scan-path README.md \
  --scan-path docs/ \
  --scan-path examples/
```

## 进阶文档

按你的角色选择入口；[完整文档索引](docs/README.md)仍是权威地图。

### 使用与运维

- [Getting Started](docs/guides/getting-started.md)：安装、连接、诊断、heartbeat、
  dashboard、开发和命令参考。
- [用户手册](https://my.feishu.cn/wiki/CaL5wMk9ui17ngkWzeUcMlAYnZg)：
  公开 onboarding、概念、FAQ 和案例。
- [Showcase Catalog](docs/showcases/README.md)：public-safe 案例和 evidence label。
- [Update Notes](docs/update-notes/README.md)：公开安全的进展记录。
- [Release Readiness](docs/product/release-readiness.md)：安装升级、兼容性 gate、
  release note 和稳定表面。
- [Dashboard](apps/presentation/dashboard/README.md)与
  [Status Data Contract](docs/status-data-contract.md)。

### 理解控制面

- [Architecture](docs/architecture.md)：lifetime-goal invariant 与 kernel。
- [State Interaction Model](docs/state-interaction-model.md)：actor、store、
  interaction contract 与 writeback。
- [Interaction Pattern Catalog](docs/interaction-pattern-catalog.md)：可复用
  routing、gate、evidence、projection 与 planning pattern。
- [Loop Engineering 原则与陷阱（中文）](docs/product/loop-engineering-principles-and-pitfalls.zh.md)
  及[英文版](docs/product/loop-engineering-principles-and-pitfalls.md)。
- [控制面开发者 9 讲](docs/development/control-plane-course/README.md)。
- [Product Vision](docs/product/vision.md)：更广义的 Loop Agent 产品方向。

### 集成与扩展

- [Integration Guide](docs/integration.md)
- [Custom Agent Runner 中文指南](docs/guides/custom-agent-runner-integration.zh-CN.md)
- [Worker Bridge Install Contract](docs/worker-bridge-install-contract.md)
- [Extensions and Capabilities](docs/reference/extensions.md)
- [Codex App Host Command Registry](docs/reference/protocols/codex-app-host-command-registry-v0.md)
- [Heartbeat Automation Prompt](docs/heartbeat-automation-prompt.md)
- [Lark Kanban Adapter](docs/lark-kanban-control-plane-adapter.md)
- [Reward Memory 中文架构](docs/reference/protocols/reward-memory-architecture-v0.zh-CN.md)

### 验证与治理

- [Quota Allocation](docs/quota-allocation.md)
- [Public/Private Boundary](docs/public-private-boundary.md)
- [Benchmark Developer Workflow](docs/benchmark-developer-workflow.md)
- [Project-Level Reward Model](docs/product/project-level-reward-model.md)
- [Project Governance](GOVERNANCE.md)
- [Authors and Contributors](AUTHORS.md)
- [Project History](docs/project/history.md)
- [Name and Marks](TRADEMARKS.md)

## 用户群与反馈

LoopX 还在早期，最需要真实长程 agent 项目里的反馈：控制面帮到了哪里、哪里太重，
哪些 gate、handoff 或 scope 仍然不够清楚。

- 可复现 bug、安装问题、功能建议：请提
  [GitHub Issue](https://github.com/huangruiteng/loopx/issues)。
- 文档修正、showcase 补充、小型 public-safe 示例：欢迎开 PR。
- 中文用户与贡献者可以加入飞书开发群；加入微信群请添加微信 `huangrt00`，
  好友申请备注 `LoopX`。

<p align="center">
  <a href="docs/assets/loopx-lark-developer-group.png"><img src="docs/assets/loopx-lark-developer-group.png" alt="LoopX 开发群二维码" width="320"></a><br>
  <strong>飞书开发群</strong>
</p>

<p align="center">
  <a href="docs/assets/loopx-wechat-contact.png"><img src="docs/assets/loopx-wechat-contact.png" alt="LoopX 微信联系人二维码" width="280"></a><br>
  <strong>微信：<code>huangrt00</code></strong><br>
  添加好友，备注 LoopX 后邀请入群
</p>

<p align="center">
  <img src="docs/assets/loopx-logo.png" alt="LoopX 标志" width="96"><br>
  LoopX 项目标志
</p>

## 贡献

公开、可认领的任务见 [Contributor Tasks](CONTRIBUTOR_TASKS.md)。贡献前请读
[Contributing](CONTRIBUTING.md)，尤其是 public/private 边界、smoke 保留规则和
benchmark 证据边界。

项目角色与维护权限见 [Governance](GOVERNANCE.md)，创建者与贡献者归属见
[Authors and Contributors](AUTHORS.md)，关键公开演进见
[Project History](docs/project/history.md)，名称与标识使用见
[Name and Marks](TRADEMARKS.md)。

不要提交 `.loopx/`、`.codex/goals/`、live `ACTIVE_GOAL_STATE.md`、内部链接、
raw benchmark task/log/trajectory/verifier output、credentials、token、私有路径或
未脱敏的用户与团队信息。

## 当前状态

`0.4.x` 已经是一套可用、但仍处于早期的长程 Agent 本地控制面。LoopX 不是完整
agent platform，不是 agent runtime，也不是自治生产控制器。

目前 LoopX 已交付围绕 goal、typed todo / decision scope、平级 claim / lease、
evidence / writeback、quota-aware scheduling 和跨轮 continuation 的 durable state
kernel。在这套共享控制状态之上，已经提供 guided start、recurring heartbeat、
隔离 Codex CLI Turn、evidence-backed Issue-Fix admission、可选 Explore / auto
research 路径、公开 validation canary，以及 read-first 多项目 dashboard。

不同表面的支持等级仍需明确区分：state 与 CLI contract 是稳定核心；部分 host
integration 和进阶路径仍是 optional、default-off 或 experimental。LoopX 不会自行
获得 credential，不会替用户批准 destructive / production action，不会在未授权时
公开发布，也不会把未经验证的 run 当成成功证据。

下一阶段会继续改善安装与 host packaging、扩展 typed runtime adapter、加强重复公开
Loop 的 terminal acceptance、补足独立采用与 outcome evidence，并打磨管理面。

## License

MIT，见 [LICENSE](LICENSE)。
