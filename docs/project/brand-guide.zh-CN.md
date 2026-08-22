# LoopX 品牌指南

这份指南用于保持 LoopX 的公开叙事一致。它是产品与编辑约定，不是法律意义上的
商标意见；名称和标识仍遵循[名称与标识使用说明](trademarks.md)。

## 1. 品牌定位

### 一句话描述

**LoopX 是面向长程 Agent 的动态目标控制面。**

LoopX 运行在 agent harness 之上，让 goal state、todo、decision scope、gate、
evidence、quota、handoff 和 recovery 跨轮次保持清晰。harness 继续执行有界工作，
LoopX 负责让长程工作可审阅、可恢复。

### 简短产品描述

LoopX 是开放、provider-neutral、local-first 的长程 Agent 状态内核。它为维护者和
operator 保留一份持久状态：Agent 做了什么、哪里受阻、已有何种证据、什么可以继续、
什么需要人判断。

### 产品边界

LoopX 不是模型、agent runtime、完整 agent platform，也不是自治生产控制器。它不
授予 credential，不批准 destructive 或 production action，也不会把未经验证的运行
结果变成成功证据。

## 2. 四个核心叙事

产品、文档和社区沟通默认按以下顺序组织：

1. **长程连续性**：goal 和 evidence 跨 session、runtime、handoff 与有界 turn 保持。
2. **显式的人类判断边界**：gate 和 decision scope 让等待、批准与安全侧路可见。
3. **证据驱动的进展**：Todo 完成不等于 Goal 已被证明；validation 与 writeback 必须
   连接起来。
4. **Provider-neutral 控制面**：Codex、Claude Code 或其他 worker 执行工作，LoopX
   保持共享的控制状态。

### 优先使用的短语

- long-running agent work / 长程 Agent 工作
- dynamic goal control plane / 动态目标控制面
- durable state kernel / 持久状态内核
- bounded agent turns / 有界 Agent turn
- evidence-backed progress / 有证据支撑的进展
- human-gated continuation / 人类 gate 控制的继续执行
- provider-neutral and local-first
- source state and projections / source state 与 projection

## 3. 读者路径

- **维护者和 operator** 关心“现在需要判断什么”：先写 gate、evidence、owner、成本和
  next action。
- **Agent 与平台开发者** 关心契约边界：先写 state、receipt、host adapter，以及 LoopX
  不拥有 executor。
- **贡献者** 需要有界入口：链接到 task、所属方向、non-goal 和最小验证面。
- **采用者和用户** 需要一条诚实的使用说明：可在 [`ADOPTERS.md`](../../ADOPTERS.md)
  登记，并把自报使用与维护者观察到的生态证据分开。

## 4. 语气与编辑规则

LoopX 的公开表达应保持技术笔记的节奏：

- 先给判断，再交代背景；
- 用 `goal`、`todo`、`gate`、`evidence`、`quota`、`receipt` 等具体对象解释机制；
- 区分 shipped behavior、公开观察、用户报告和 proposal；
- 说明证据没有证明什么；
- 语言直接、克制，对维护者有用；
- 用小型可复现例子替代宏大承诺。

避免：

- 没有窄化契约时使用“完全自治”“零人工介入”“保证”“永不漂移”等 hype；
- 把 demo、star 数、控制面时间窗口或一次通过的任务写成 PMF 或通用能力证明；
- 把 runtime adapter、dashboard 或 projection 写成 source of truth；
- 把 RFC、integration branch 或计划中的采用写成已交付；
- 把私聊、内部时间线、本地路径、raw run 或用户细节带入公开材料。

## 5. 证据标签

公开表述应使用与证据匹配的标签：

| 标签 | 使用条件 | 边界示例 |
| --- | --- | --- |
| **Shipped** | 行为已进入 `main`、release 或稳定公开契约。 | “LoopX 已交付 typed Todo 与 quota 契约。” |
| **Observed** | 公开安全的运行、fixture 或仓库产物展示了该行为。 | “公开 fixture 展示了可恢复的 handoff。” |
| **Reported** | 用户或项目发布了明确归属的公开报告。 | “某用户报告了连续四天的无人运行。” |
| **Proposed** | 内容仍在 RFC、issue、discussion 或未晋级分支。 | “provider-neutral state provider 仍是 proposal。” |

不得把 **Reported** 或 **Proposed** 默默升级成 **Shipped**。更详细的证据边界见
[public/private boundary](../public-private-boundary.md)与[当前技术方向](technical-directions.zh-CN.md)。

## 6. 视觉方向

当前公开表面采用克制的 control-plane 视觉语言：

- **结构**：文档和 operator view 使用浅色中性背景、slate 正文、细分隔线、紧凑图表
  和留白。
- **强调**：使用蓝色或靛青色表达 LoopX state kernel 与主要动作；绿色、琥珀色和红色
  只用于不同的状态或 gate 含义。
- **社交与 showcase**：可以复用 `docs/assets/` 中现有的深靛色 social preview 与浅色
  control-plane 图，不为一次活动再造一套 logo 或视觉身份。
- **排版**：界面优先使用清晰的系统 sans；技术笔记保证中英文混排可读。代码和协议名
  应与解释性正文有明显区分。
- **图表**：把 source state、有界执行、人类判断、evidence 和 projection 画成不同角色；
  projection 不能看起来像状态权威。

新增视觉素材应保持同样的信息层级和可访问性对比度，不追逐流行风格或装饰性渐变。

## 7. 命名与关系表述

- 项目名称写作 **LoopX**，不要写成 `Loop X`、`loop-x` 或不加边界的“自治 Agent 平台”。
- 面向广泛读者介绍类别时可用 **Agent Control Plane**；描述当前产品契约时优先使用
  **dynamic goal control plane**。
- 只有公开证据支持时，才说某项目 **uses**、**integrates**、**extends** 或 **is inspired
  by** LoopX。
- 不暗示赞助、认证、背书或官方关系。修改版发行应使用自己的主名称，并遵循
  [名称与标识使用说明](trademarks.md)。

## 8. 发布前检查

发布公开页面、release note、showcase 或采用登记前，检查：

1. 首句是否是诚实的产品或项目判断？
2. 哪个 LoopX 对象或契约让这个判断变得具体？
3. 这是 shipped、observed、reported 还是 proposed？
4. 是否说明了范围外内容或尚未证明的部分？
5. source、operator、用户和隐私边界是否 public-safe？
6. 视觉和链接路径是否保留 state 与 projection 的区分？
