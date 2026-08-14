# SaaS 机会评估

状态：评估目标。本文是战略评估，不是建设承诺。它讨论 LoopX 的哪些部分可以支撑一个托管、订阅制产品，同时不削弱 LoopX 赖以成立的 local-first 控制面契约。

## 核心张力

LoopX 的价值主张是 local-first 控制面：goal 状态、evidence、quota 和 handoff 都由 operator 完全自持。一个天真的 SaaS 做法——“我们替你在服务器上托管 agent 状态”——会摧毁让产品可信的那个属性。

所以 SaaS 问题不是“LoopX 能否被托管”，而是：

> 哪些层放到云上会变得*更有价值*，哪些层必须按设计留在本地？

需要协作、跨设备持久访问或共享事实源的东西，适合托管层；作为 operator 事实源的任何东西——本地 goal 状态、私有工作区内容、与凭据相邻的材料——都留在本地。

## 可行性测试

托管产品只有在通过以下全部三条时才值得建设：

1. **持续使用**：operator 每天回来使用，而不是装一次就完。
2. **云化提升**：协作、共享或持久性让托管版本严格优于“单机文件”。
3. **自然扩张**：收入随席位、托管 agent、留存或集成增长，而不是靠一次性功能。

下面每个候选方向都用这三条测试衡量。

## 候选方向（按优先级排序）

### 1. AgentOps 观测与治理云

最强候选：面向 goals、evidence、quota 的“Agent loops 版 Datadog / Langfuse”，而不是面向 LLM trace。

控制面已经产出原材料：goal 状态、run history、evidence 事件、quota 决策和 handoff 记录。托管观测层把它变成团队共享面：

- 跨成员 goal board：谁在跑哪些 agent、针对什么目标；
- quota 与预算视图：把花费映射到 goal 而不是 API 调用；
- 通过 Lark 或等价渠道路由的 gate 与审批队列；
- 在机器损坏或 operator 交接后仍然存活的 evidence 下钻。

为什么契合：观测是持续消费的；没有团队规模的协作它就毫无价值；收入随席位和托管 agent 扩展。dashboard 前端已存在（`apps/presentation/dashboard`），status data contract（`docs/status-data-contract.md`）是公开投影面，托管读模型可以消费它而完全不触碰私有状态。

定价草图：单 operator 免费档 + 短留存；团队档按席位加托管 agent 计费；治理功能（审批路由、留存、导出）放在团队档。

### 2. Evidence 与 Review SaaS

更窄、偏合规的产品：不可变 evidence 留存、review-ready handoff 报告，以及周期性的“agent 做了什么、为什么”摘要。

这是方向 1 换个契约卖：观测卖给今天就在跑 agent 的团队；evidence 与 review 卖给未来需要向 stakeholders 解释 agent 决策的组织。当 agent 进入生产工作流，“给我看 evidence”会从锦上添花变成准入要求。

事件溯源状态模型和现有 evidence/handoff 投影让它无需新运行时机制即可落地。限制因素是信任：客户必须相信留存 evidence 完整且未被修改，这推动 append-only 存储和签名导出。

### 3. 托管控制面（优先 BYOC）

基础文档 `server-client-product-shape.md` 已经点名中期形态：服务器持有 durable goal 状态、事件历史和 governed planning lanes。该架构已经隐含 SaaS 管道在这里是自然的：

- per-goal quota 与花费策略已存在；
- 写入幂等、事件 append-only；
- public/private 边界分类器是一等运行时概念。

这些正是多租户控制面需要的机制。风险不在技术契合，而在运营重力：托管客户生产 agent loop 的权威状态，会让 LoopX 进入客户关键路径，并承担相应的 SLA 负担。

更低风险的入口是 BYOC：控制面跑在客户自己的云账号里，LoopX 卖 console、升级和支持。这保留了 local-first 承诺——客户仍然拥有状态——同时创造订阅收入面。完整多租户托管是后续决策，不是前提。

### 4. Domain Packs 与 Marketplace 收入

Domain capability packs（`docs/product/domain-capability-packs.md`）是变现层，不是独立 SaaS。单独卖是一次性购买；挂到带 marketplace 抽成的托管平台上才变成订阅。这个方向依赖方向 1 或 3 先存在，不能作为起点。

## 什么不该做成 SaaS

- **执行托管**（“我们替你跑 agent”）：会在算力毛利上和前沿模型厂商竞争，且违背“控制面不拥有 domain 行为”的架构原则。
- **托管 CLI 状态作为产品**：没人会花钱把本地文件搬到别人的磁盘上。云层必须增加协作或治理价值，而不只是迁移状态。

## 诚实的约束

- **冷启动**：观测云需要足够多跑 LoopX loop 的团队才有东西可观测。现实的路径是：免费 CLI 采用扩大基数，云档再转化涌现出的团队。SaaS 层实现自给自足之前，预期需要很长的周期。
- **品牌张力**：local-first 与 SaaS 拉扯方向相反。做得好是差异化（“你的状态还是你的；协作层托管”）；做得草率就会被解读为 bait-and-switch。
- **维护面**：托管产品带来 on-call、数据留存和客户支持义务，这是单维护者 OSS 项目目前没有的。第一个付费档应当刻意收窄。

## 建议路径

Phase 0 —— opt-in 观测中继：一个 `loopx cloud sync` 命令，把 public-safe status 投影推到托管 dashboard。个人免费、短留存。这是最小的楔子：`status_server` 和 dashboard 已存在，新增面只有账号系统和托管读模型。

Phase 1 —— 团队档：共享 goal board、Lark 路由审批、跨席位 quota 预算。按席位加托管 agent 计费。

Phase 2 —— evidence 与 review 档：长留存、签名 evidence 导出、review-ready 摘要。卖给组织而不是团队。

Phase 3 —— BYOC 托管控制面与 domain-pack marketplace 收入。

每个阶段可独立交付，各自为下一阶段提供资金；任何阶段都不需要押注完整多租户终态。

## 与现有文档的关系

- `../foundations/server-client-product-shape.md` 命名了本评估依赖的 durable 控制面服务器角色。
- `../surfaces/README.md` 与 frontstage 笔记覆盖托管 dashboard 会扩展的公开展示面。
- `../domain-capability-packs.md` 定义了方向 4 变现的 pack 边界。

本文刻意不给出定价承诺、发布日期和容量承诺。它是 SaaS 收入可能落在哪里的地图，在 CLI 采用漏斗足以支撑托管档时再重新审视。
