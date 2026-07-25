# Material Lifecycle 架构 v0

## 定位

Material Lifecycle 是 LoopX 内置、默认关闭、goal-scoped 的素材生命周期
capability。它管理可审计的素材引用状态：清点、备份安全迁移、候选/归档
流转和小范围重排；不拥有原始文档、私有来源位置、provider 凭据，也不创造
Core goal authority。

```mermaid
flowchart LR
    RAW["私有原始素材库<br/>文件、消息、网页抓取"]
    BACKUP["不可变快照与备份"]
    ML["Material Lifecycle<br/>清点、流转、小范围重排"]
    DC["Decision Context<br/>带 revision 的决策证据"]
    RM["Reward Memory<br/>经评审的可复用经验"]
    CO["Content Ops / 其他消费者"]
    CORE["LoopX Core<br/>goal、todo、gate、event、vision"]

    RAW --> BACKUP
    BACKUP --> ML
    DC -->|"decision_evidence_ref"| ML
    RM -. "可选排序经验" .-> ML
    ML -->|"素材引用与 receipt"| CO
    ML -->|"仅审计引用"| CORE
```

它与 Decision Context、Reward Memory 同级，但职责不同：

- Decision Context 判断当前决策应相信哪些事实；
- Material Lifecycle 判断哪些素材处于候选、活跃、归档、carryover 状态，
  以及哪些条目可以被小范围重排；
- Reward Memory 保存经过评审、可复用的策略和经验；
- Content Ops 等能力消费选中的素材，不拥有候选/归档真值。

## Stage-0 契约

`material_store_inventory_v0` 是只读、公开安全的素材库清点结果，只记录
不透明的快照、备份、digest、revision、数量、解析错误和验证引用，不携带
原始素材或私有位置。

`material_migration_plan_v0` 固定迁移顺序：

1. 建快照；
2. 清点；
3. 双读；
4. 对账；
5. owner gate；
6. apply；
7. 保持 rollback 可用。

迁移计划本身不授权修改原始素材库。

`material_lifecycle_receipt_v0` 记录 `unread`、`candidate`、`active`、
`carryover`、`archived` 之间带 authority 引用的流转。authority 可以是经
评审的 goal policy、Decision Context outcome 或人工 gate。归档和重新激活
都保留稳定的 material/archive 引用，不把原始内容复制回新队列。

`material_rerank_proposal_v0` 只表达受限增量：

- 一个目标窗口；
- 最大移动条数；
- 最大位移；
- 受保护条目；
- 带 revision 的 Decision Context 证据；
- 显式 no-change。

`material_rerank_apply_receipt_v0` 与 proposal 分离。真正 apply 必须记录
owner gate、验证引用、前后 revision；发生修改时还必须有 rollback 引用。

## 迁移边界

旧 Markdown、数据库、inbox 等存储在以下条件满足前始终是 authority：

- 已建立不可变快照和可验证备份；
- material ID 与来源引用稳定；
- 解析错误可计数；
- 新旧双读的总量和生命周期状态一致；
- rerank proposal 可确定性回读；
- cutover 与 rollback 都经过 owner gate。

通用 capability 不内置某种 Markdown parser 或私有目录结构。provider
adapter 可以与旧存储长期共存，直到完成对账。

## 只读准备路径

`MaterialInventoryProvider` 是 legacy store 的私有 adapter 边界。它只返回
瞬态元数据 `MaterialStoreSnapshot`：不透明 snapshot/backup 引用、revision、
digest、生命周期计数、解析错误引用，以及三个显式验证结果：

- stable material ID 已验证；
- backup 已验证；
- 清点前后的 source digest 一致。

`prepare_material_migration` 把瞬态 snapshot 转成既有的
`material_store_inventory_v0`。只有三个验证均通过且没有解析错误时，才生成
`material_migration_plan_v0`；否则只返回确定性的 readiness blocker，不生成
计划。provider contract 没有 apply 方法，两个 packet 也始终保持
`source_mutation_authorized=false`。

具体 provider 与私有文件布局留在通用 capability 之外。本地 host adapter 可以
解析 Markdown、数据库或其他来源，但必须证明同一组只读与 backup invariant，
LoopX 才会准备迁移。

## 决策驱动的排序与探索

Stage 0 接收 Decision Context 产生的不透明 `decision_evidence_ref`。后续
provider-neutral 阶段可以据此生成小范围重排或探索意图。搜索引擎、联网
客户端、消息和仓库 scanner 都是可替换 provider；其 raw output 不进入
公开 packet。

因此 recurring automation 最终只负责唤醒 goal 和调用 capability。
来源清单、增量 cursor、排序规则与探索预算应位于 ignored 的 goal-scoped
配置和受验证 receipt 中，而不是写进 automation prompt。

## 本阶段不做什么

当前 capability 交付确定性契约、provider-neutral 的只读准备路径、catalog、
架构 CLI、聚焦测试和公开 smoke，不交付：

- 内置 legacy 素材 parser 或迁移 apply；
- 原始素材持久化；
- 联网探索 provider；
- 群聊/关键联系人 source profile；
- 自动重排、自动归档或自动推进 cursor。

这些能力必须经过私有只读 adapter、精确双读对账和显式 owner gate。
