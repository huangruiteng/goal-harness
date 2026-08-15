# SaaS 机会评估

状态：评估目标。本文是战略评估，不是建设承诺。它讨论 LoopX 如何支撑托管、订阅制产品，同时不削弱 LoopX 赖以成立的 local-first、provider-neutral 控制面契约。

## 商业判断

LoopX 最连贯的商业位置是：

> 开源并保持 local-first 的长程 Agent 语义状态契约；收费提供稳定运行这些契约的 Managed Semantic Control Plane。

开源层提供可迁移的 goal、authority、todo、evidence、acceptance、quota、handoff、recovery 和 replan 状态。付费层让这些状态在团队环境中持续可用：可协作、可观测、可恢复、可治理，并有人为其稳定性负责。

这个位置接近两种已经公开商业化的相邻模式。Letta 将持久、有状态的 Agent 包装成托管服务，按 active agent 与执行量计费；Mastra 在开源 Agent 框架之上销售托管运行、留存、团队协作和企业治理。LoopX 不需要复制二者的产品边界。它的差异化位置是跨异构 Agent runtime 的 provider-neutral 语义控制层：完备的状态管理、规划与监督，基于证据的恢复，以及能够跨 run、跨 Agent 继承的人类 authority。

这是产品定位假设，不是收入结论。它仍然需要持续生产使用和付费意愿验证。

## 核心张力

LoopX 的价值主张是 local-first 控制面：operator 可以拥有、检查、导出和恢复 durable state。一个天真的 SaaS 做法——“我们替你在服务器上托管 Agent 状态”——会削弱让产品可信的那个属性。

因此，SaaS 问题不是“LoopX 能否被托管”，而是：

> 哪些控制面职责由专门服务持续运行后更有价值；哪些 authority 与数据边界必须按设计保持可迁移？

协作、跨设备访问、长期留存、共享治理、托管恢复和运维支持适合 hosted 或 BYOC 服务。语义状态契约、导出路径、本地执行选项，以及客户对私有工作区内容的 authority 应当保持开放。

付费产品卖的是运行、可靠性和组织控制，不能把用户自己的状态格式锁住后再卖回访问权。

## 开源层与付费层边界

| 层次 | Community 与 local-first 契约 | Managed 产品价值 |
| --- | --- | --- |
| 语义状态 | goal、todo、gate、decision、evidence、acceptance、quota、handoff、recovery、replan 的开放 schema 与 transition | 高可用状态服务、冲突处理、备份恢复、迁移和托管升级 |
| 执行 | Codex、Claude Code、Cursor、shell agent 与自定义 worker 的 provider-neutral adapter | Agent fleet 注册、health、策略约束的 wake、Supervisor 调度、恢复和 operator 路由 |
| 观测 | 本地 projection、CLI status、导出与可自托管 dashboard surface | 共享 workspace、长期留存、跨 Agent timeline、评测、回放、告警和 review queue |
| 治理 | 可检查的本地 authority、boundary 与 approval contract | 多租户隔离、RBAC、SSO、审计、配额、数据驻留、签名导出和策略管理 |
| 交付 | 文档与可用的 self-host 路径 | BYOC 或 managed deployment、SLA、迁移、集成、incident response 和支持 |

可迁移性是产品契约的一部分。客户应当能够导出语义状态，保留 durable identity 与 evidence lineage，并回到本地或 self-hosted 控制面，而不需要从私有日志中重新推断工作的含义。

## 可行性测试

Managed 产品只有在通过以下全部四条时才值得建设：

1. **持续使用**：operator 与 Agent team 在一周工作过程中持续使用，而不是装一次就结束。
2. **托管优势**：协作、可用性、恢复、留存或治理让托管版本显著优于单机文件。
3. **自然扩张**：收入随 workspace、active managed agent、留存、Supervisor work 或企业控制扩张，而不是依赖一次性 feature。
4. **控制面效果**：客户可以测量人工协调减少、恢复加快、非法 continuation 下降，或 review 与 audit 成本下降。

第四条最重要。无法改善长程工作的 dashboard 只是一个界面 feature，不是可持续的 SaaS 生意。

## 产品阶梯

下面不是四个独立 SaaS，而是一条走向 Managed Semantic Control Plane 的采用与扩张路径。

### 1. AgentOps 观测与治理云

最强的进入楔子，是面向 goal、authority、evidence、recovery、quota 的“Agent loop 版 Datadog / Langfuse”，而不只看 LLM trace。

控制面已经产出原材料：goal 状态、run history、evidence 事件、quota 决策、handoff 记录和 public-safe projection。托管观测层把它们变成团队共享面：

- 跨成员 goal board：谁在跑哪些 Agent，为什么运行；
- quota 与预算视图：把花费映射到 goal，而不只映射到 API 调用；
- 通过 Lark 或等价渠道路由的 gate 与审批队列；
- 在机器损坏或 operator 切换后仍然存在的 recovery 与 handoff timeline；
- 解释发生了什么、continuation 是否合法的 evidence 与 eval 下钻。

这个楔子以读为主，可以消费 public status data contract，而不持有私有 workspace 内容。它先证明日常使用和团队协作，再让 LoopX 承担生产控制状态的 authority。

### 2. Evidence 与 Review 服务

下一层增加不可变 evidence 留存、回放、review-ready handoff 报告、评测历史，以及周期性的“Agent 做了什么、为什么”说明。

观测卖给今天就在运行 Agent 的团队；evidence 与 review 卖给未来需要解释 Agent 决策的组织。当 Agent 进入生产工作流，“给我看 evidence”会成为准入要求。

事件溯源状态模型以及现有 evidence、handoff projection 使这层无需新增 Agent runtime 即可落地。它的信任门槛更高：留存 evidence 必须具备明确 lineage、append-only 语义、删除策略，以及签名或其他可验证导出。

### 3. Managed Semantic Control Plane（优先 BYOC）

产品终局不只是观测，而是一个持续运行的控制面：本地或第三方 runtime 执行 bounded work，Managed Semantic Control Plane 维护完备且一致的 semantic execution state。

基础文档 `server-client-product-shape.md` 已经点名中期形态：服务器持有 durable goal state、event history 和 governed planning lane。同一套架构可以支撑：

- 对权威状态进行幂等、可识别冲突的写入；
- Supervisor 调度、stalled-loop 检测、恢复、handoff 和 replan；
- 从 advisory proposal 到 executable work 的 policy-controlled promotion；
- 跨 runtime 的 identity、claim、quota、evidence 与 acceptance 连续性；
- operator 对每一次 authority 消耗 transition 的可见控制。

Supervisor 不是隐藏的自治管理者。它可以在已记录策略内调度、观察、恢复和提出 proposal，但不会因为被托管就自动取得人类 authority。

更低风险的企业入口是 BYOC：控制面运行在客户自己的云账号里，LoopX 销售 console、managed upgrade、治理、恢复运维和支持。完整多租户托管应当在隔离、删除、备份与 on-call 契约得到证明后再进入。

### 4. Domain Packs 与 Marketplace 收入

Domain capability packs（`docs/product/domain-capability-packs.md`）是扩张层，不是核心生意。它可以增加有领域倾向的评测、review 或运维 workflow，同时保持 Kernel 通用。

当 team tier 或 managed control plane 已经存在后，pack 可以产生 marketplace 或企业集成收入。它不应当领先 SaaS 战略，商业包装也不能把领域 authority 搬进通用 Kernel。

## 计费单位与产品分层

主要计费单位应当跟随 managed control-plane value，而不是转售模型 token。

| 价值面 | 候选计费单位 | 扩张逻辑 |
| --- | --- | --- |
| 团队控制面 | workspace + collaborator seat | 更多团队与 operator 共享同一份 governed state |
| Agent 连续性 | 月 active managed agent 或 active governed goal | 更多长程 worker 依赖 identity、state、quota 与 recovery |
| Evidence 运维 | retained event/evidence volume + retention window | 更长周期或强监管 workflow 需要更持久的历史 |
| Managed supervision | 策略约束的 wake、recovery、replay 或 eval execution | 客户为持续运行的 continuation 付费，而不是为原始模型调用付费 |
| 企业交付 | deployment environment + 治理与支持档位 | BYOC、SSO、RBAC、audit、residency、SLA 与迁移形成组织价值 |

一个可行的产品阶梯是：

- **Community**：local-first Kernel、protocol、CLI、export 和可自托管 projection；
- **Team Cloud**：共享 workspace、中短期留存、审批、告警和协作 review；
- **Managed Control Plane**：durable semantic state、Supervisor 调度、恢复、回放、评测和更长留存；
- **Enterprise / BYOC**：私有部署、治理、审计、数据驻留、迁移、SLA 和专属支持。

这是 packaging model，不是公开价格表。定价前需要先获得 active agent、event volume、retention、Supervisor execution 和支持成本的真实分布。Agent 与其 goal 不能作为同一活动被重复计费；应当用 cohort 数据选择更贴近客户价值的主单位，未活跃的注册 identity 保持免费。

## 什么不该做成 SaaS

- **封闭的语义状态格式**：goal、evidence、authority 和 handoff 必须保持可检查、可导出。产品粘性应来自运行质量，而不是状态绑架。
- **把通用执行托管当核心产品**：LoopX 可以编排外部 runtime，也可以运行 bounded Supervisor work；但转售模型 token 与 sandbox 会让项目在算力毛利上竞争，并模糊“控制面不拥有 domain 行为”的边界。
- **把托管 CLI 文件当产品**：没人会为把本地文件搬到别人的磁盘付费。Managed 层必须增加协作、可靠性、恢复或治理价值。
- **默认获得云端 authority**：托管基础设施不会自动授予读取私有 workspace、通过 gate、发布或执行生产写入的权限。

## 诚实的约束

- **采用与证据缺口**：公开长程 demo 能证明技术可行性，不能证明团队的 recurring demand。SaaS 需要外部生产 workload 对留存、恢复和协作的持续需求。
- **冷启动**：观测云需要足够多运行 LoopX loop 的团队才有东西可观测。免费 CLI 可以扩大基数，但 hosted tier 达成自给自足可能需要很长时间。
- **品牌张力**：local-first 与 SaaS 可能方向相反。可迁移、self-host、明确 opt-in 和收窄的 managed boundary 必须是产品行为，不能只停留在营销表述。
- **信任与安全面**：托管 evidence 与 authority state，会带来比 OSS CLI 更强的隔离、删除、备份、incident response 和合规责任。
- **运营能力**：托管产品包含 on-call、升级、迁移和客户支持义务，当前小型维护团队并不具备完整能力。第一个付费档应当刻意收窄。
- **单位经济性未验证**：如果计费只跟随原始活动量，Supervisor execution、留存和支持可能吞掉毛利，需要与价值对齐的分档或上限。

## 大规模建设前的证据门槛

在 Managed 服务接管客户权威状态之前，LoopX 至少应当证明：

1. 多个独立团队持续在数周级 goal 上使用控制面；
2. 人工上下文重建、非法 continuation、恢复时间或 review 工作量出现可测下降；
3. design partner 愿意为协作、留存、治理或 managed recovery 付费，而不只是购买通用支持；
4. export、restore、deletion、tenancy、backup 与 public/private boundary 行为得到验证；
5. 使用模型能够证明 retention、Supervisor work 与支持成本可以维持可接受毛利。

这些门槛将技术期权与已经兑现的商业价值分开。

## 建议路径

Phase 0 —— 为本地产品补充度量，验证可计费对象。在默认不收集私有内容的前提下，统计 active agent / goal、event / evidence volume、recovery action、review frequency 和 operator attention。

Phase 1 —— opt-in 观测中继。增加 `loopx cloud sync` 路径，把 public-safe status projection 推到托管 dashboard。个人档免费或窄计费，保持短留存。

Phase 2 —— team 与 evidence tier。增加共享 goal board、审批路由、quota budget、更长留存、回放、签名导出和 review-ready summary，并用 design partner 验证 recurring willingness to pay。

Phase 3 —— Managed Semantic Control Plane，优先 BYOC。在客户环境中运行 durable state、Supervisor 调度、恢复和 governed replan，同时提供 managed upgrade 与支持。

Phase 4 —— 完整多租户控制面与 domain marketplace。只在隔离、支持负担和单位经济性得到证明后进入。

每个阶段都可以独立交付，并为下一阶段产生证据；任何阶段都不需要让开源项目提前押注完整 hosted 终态。

## 市场参照

- [Letta pricing](https://www.letta.com/pricing) 展示了围绕 persistent agent state，按 active agent、执行、team 和 enterprise 能力计费的方式。
- [Mastra pricing](https://mastra.ai/pricing) 展示了开源 Agent 开发平台如何按 usage、retention、team 和 enterprise 能力分层。

这些参照说明客户能够理解托管状态、运维和治理的付费价值，但不能直接证明 LoopX 独特的 semantic control-plane contract 已经存在市场需求。

## 与现有文档的关系

- `../foundations/server-client-product-shape.md` 定义了本评估要商业化的 durable control-plane server、client 与 executor 角色。
- `../surfaces/README.md` 与 frontstage 笔记覆盖 hosted workspace 将扩展的 public presentation surface。
- `../domain-capability-packs.md` 定义了 marketplace 或企业集成可能商业化的 pack 边界。
- `../../reference/protocols/event-sourced-state-contract-v0.md` 以及 decision、goal、evidence、quota、handoff contract 定义了不能变成私有锁定的 portable semantic state。

本文刻意不给出定价承诺、发布日期和容量承诺。它定义 recurring value 可能落在哪里，以及 LoopX 在把这项技术期权视作生意之前还需要哪些证据。
