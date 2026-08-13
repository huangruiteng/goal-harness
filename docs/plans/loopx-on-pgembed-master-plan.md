# loopx on pgembed 母计划（Master Plan）

> **文档定位**：分步骤开发的战略纲领 + 硬门槛。它不是实现手册——不写逐文件代码改动、不写字段级 DDL、不写接口签名实现。那些留给基于本计划生成的各阶段深度计划。
> **权威依据**：本计划严格遵循《架构裁决纪要》（下称"裁决纪要"）。凡与《原始设计文档》冲突处，一律以裁决纪要为准。
> **第一阶段范围**：裁决步骤 1–12，终点是**至少一个完整真实 goal 的 `bounded_canary`**，不是全局 promotion。步骤 13–14（全局 promotion）单列为 Phase 5。观察契约/DuckDB 是并行非阻塞 track；未来 nooa 适配与 collector 生产化单列 Phase 6。
> **最终目标**：PostgreSQL 成为 LoopX 控制面状态的唯一生产权威；Markdown/JSONL 保留为兼容导出，而不是第二事实源。LoopX 与 nooa/DBOS 各自保留独立存储与 authority，跨系统只通过版本化 public-safe observation contract 关联。

---

## 1. 背景与目标

### 1.1 为什么要做 loopx on pgembed

LoopX 控制面当前以文件为权威（`ACTIVE_GOAL_STATE.md` + 三类 JSONL + `runs/index.jsonl`）。这套形态在并发、可靠性和一致性上存在四个结构性缺陷，正是本次改造要解决的核心问题：

| 核心问题 | 现状 | 后果 |
|---|---|---|
| **文件双写不一致** | Todo 的 Markdown 行级直编与事件追加是两条并行路径 | 状态与事件存在不一致窗口；无法保证单一事实源 |
| **无 fencing** | 仅靠 `fcntl` 文件锁保护文件临界区，没有 lease 或 fencing token | 过期/并发 Agent turn 可能覆盖更新状态；长期 turn 写回无防护 |
| **幂等分裂** | 各子系统自定义幂等键 | 无法统一返回首次命令结果，重试协调不可靠 |
| **quota 非原子** | `runs/index.jsonl` 记录 classification，quota 由 Python 全量重扫重算 | 没有原子、可重试的 spend receipt；重算漂移、可能重复收费 |

### 1.2 嵌入形态：两套独立 local-first PostgreSQL + pgembed 栈

默认部署不是一个 daemon 管全系统数据库，而是 **LoopX-on-pgembed** 与 **nooa-on-DBOS** 两套完全独立的 local-first PostgreSQL 栈。两边各自有独立 pgembed PostgreSQL 实例、规范化 `pgdata` 根、`PostgresServer` handle、endpoint、角色/数据库、migration head、cleanup 和 upgrade gate。LoopX daemon 只持有 LoopX PG；nooa/DBOS owner 只持有 nooa PG。禁止 cross-system SQL、直接读取对方私有表、共享 migration 或跨系统事务。

pgembed 只负责每个实例的 PG 进程生命周期（通过 `get_server(data_dir)`），不承担 schema migration、readiness、daemon lifetime singleton 或业务 worker。LoopX 普通 CLI 连接 LoopX daemon 发布的 PostgreSQL URI；LoopX schema 由 Alembic 在 session advisory lock 下迁移。紧凑 co-location profile 可以让两个 pgembed 实例位于同一主机，但不能合并 data root、handle、端口/socket URI、角色/数据库或 lifecycle gate。实际实现还必须尊重 pgembed 的 normalized-pgdata handle 复用、全局 init inter-process lock、Unix-socket/平台 TCP endpoint、可能哈希化的 socket 路径、PG major mismatch 硬边界和显式 `cleanup_mode`。

LoopX 必须另外实现并在 daemon 整个存活期持有 per-normalized-data-root owner lock；它与短期 bootstrap lock、pgembed 全局 init lock 是三个不同机制。owner generation 与 readiness 必须绑定该 lifetime lock，transient endpoint failure 不能触发第二 daemon。正常持久化 root 只使用经当前 pgembed 版本集成验证的非破坏 cleanup mode；`delete` 仅限显式 ephemeral/test root，或独立且二次确认、带备份与路径校验的 destructive reset。

### 1.3 改造方式

不采用一刀切替换，而采用**按完整 goal 分阶段、单一权威端切换**的渐进迁移，经历四个逻辑阶段：

```text
dual_read_shadow  →  bounded_canary  →  promotion_candidate  →  postgres_primary
```

任一时刻**每个 goal 只有一个写入权威端**（文件或 PG，绝不双权威）。所谓"双写"仅指**权威端向非权威端做镜像/导出**，绝不表示两个后端都可接受业务写入。

---

## 2. 核心架构决策一览

以下为裁决纪要八项裁决的最终结论。详细论证与各附录见裁决纪要对应章节。

| # | 裁决 | 结论（一两句） | 裁决纪要出处 |
|---|---|---|---|
| **A** | **迁移策略** | 渐进迁移、四阶段、单一权威端切换，**不做双权威双写**。canary 粒度必须是**完整 goal**；未支持的 command 在 canary 中返回明确错误，不得隐式回落旧路径。 | §3.2-A、§5.2 |
| **B** | **事件模型** | **一张物理表** `loopx_ledger.events`，用 `event_class` 区分 `state`/`rollout`/`supervisor` 三种逻辑事件。只有 `state` 中的 `baseline`/`transition` 更新 projection 并参与 replay；三类事件**不共享**聚合版本语义。 | §3.2-B、§3.4 |
| **C** | **Zleap 借鉴** | 实现**最小真实机制**（command_receipts、transactional outbox、`FOR UPDATE SKIP LOCKED`、`lock_token+locked_until`、insert-only 版本化、immutable snapshot、canonical JSON+SHA-256 fingerprint），**不照搬** Zleap 未实现的理想描述。 | §3.2-C |
| **D** | **调度** | 采用 **LoopX 自有常驻 scheduler/outbox worker**；`LISTEN/NOTIFY` 只作低延迟唤醒，定时轮询作可靠兜底。**pg_cron 不进入业务主路径**（第一阶段不启用、不改 preload）。 | §3.2-D |
| **E** | **嵌入形态** | 每个栈的常驻 owner 只持有自己的 PG；默认 LoopX 与 nooa/DBOS 使用两套独立实例和 data root。LoopX 以独立 per-root lifetime owner lock + owner generation/readiness 保证 daemon ownership；pgembed init lock 不是 lifetime singleton。持久 root 使用已验证的非破坏 cleanup mode。LoopX schema 由 **Alembic** 管理，startup readiness 未达 required head 不接受写入。 | §3.2-E |
| **F** | **MVP 边界** | 第一阶段固定为 **18 张 LoopX 业务表**（含 monitor、lease、outbox、scheduler）。**TigerFS 不进入 MVP**。 | §3.2-F、§3.3 |
| **G** | **跨系统 ownership/contract** | LoopX=control/authority/settlement；nooa=agent semantics/evidence；DBOS=workflow/step durability/recovery；pgembed=各栈 substrate/lifecycle。稳定集成面是版本化 typed public-safe observation envelope，不是 SQL；DBOS completion 不是 LoopX settlement。 | §3.2-G |
| **H** | **DuckDB observation layer** | DuckDB 是本地 analytical read model/observation entry point，不是 authority。collector 是唯一打开 collector-private live read/write DB 的进程；分析在进程内/受控本地 API 执行，或读取 immutable DuckDB snapshots/Parquet datasets。checkpoint 持久化、幂等 staging、文件可重建；PG `ATTACH` 仅限 ad-hoc/debug。 | §3.2-H |

---

## 3. 架构不变量（不可违反）

以下来自裁决纪要 §3.1 与 §3.2-G/H，是所有深度计划与实现都不得违反的硬约束：

1. **每个 goal 在任一时刻只有一个写入权威端**：文件或 PG，不能双权威。
2. **所有业务写入先形成统一 `CommandEnvelope`**；Agent、Dashboard、CLI、scheduler、provider callback 都不能直接改状态表或文件。
3. **生命周期状态的事实源是事件账本，当前状态由 projection 提供**；goal 配置、run summary、quota policy/spend 各有明确的自身权威表。
4. **host execution 在数据库事务外执行**；最终 validated result 以 revision 和 fencing token 提交。
5. **状态事件、projection、run/evidence、quota spend、scheduler/export intent 在同一个短 PG 事务内提交**。
6. **outbox 采用 at-least-once**；所有 handler 必须幂等，不承诺外部系统 exactly-once。
7. **不用通用 ORM/CRUD 层**；只增加窄的 command、ledger、projection、runtime、quota、scheduler store 接口。
8. **LoopX 与 nooa/DBOS 存储、schema 和 transaction 独立**；任何 co-location 也不得合并 data root、handle、URI、role/database 或 lifecycle gate。
9. **LoopX daemon lifetime ownership 独立于 pgembed init lock**：同一规范化 LoopX root 必须有一个全生命周期 owner lock，owner generation/readiness 与之绑定；endpoint 失败不等于 owner 消失。持久 root 正常 stop/upgrade/recovery 必须非破坏，`delete` 只用于显式 ephemeral/test 或独立确认的 destructive reset。
10. **跨系统 observation 只相关、不转移 authority**；DBOS/nooa `succeeded`/`completed` 不等于 LoopX `settled`。event dedupe 使用 `event_id` 与 `(producer_id, source_stream_id, source_cursor)` 双 identity；业务 idempotency 字段只作 command correlation。
11. **DuckDB 只做可重建 read model**；collector 独占 live read/write 文件，外部分析只能走受控本地查询或 immutable publications；不得写 LoopX authority、成为权限边界、阻塞 `bounded_canary` 或演化成第二事实源。
12. **public-safe observation only，且双侧 fail closed**：producer 在 serialization/staging 前验证，collector 在 persistence/checkpoint advancement 前重验；只允许 compact typed metadata 与 allowlisted typed evidence pointers，禁止 raw prompts、trajectories、logs、verifier tails、credentials/credential-bearing query tokens、任意 URI/query string、local absolute paths 和 private planning context。`payload_hash` 只做 equality/corruption detection，不是 authenticity/authorization。

`TRANSACTION_PHASES` 保持七阶段名称不变，但事务边界重新划分：`host_execute`/`typed_result`/`validation` 在事务外；`durable_writeback`/`quota_spend`/`scheduler_apply` 合并到一个短 PG 事务（`scheduler_apply` 只写 schedule/outbox intent）；`scheduler_ack` 是 outbox handler 成功后的独立幂等确认。

---

## 4. 修正后的 18 表 MVP 一览

技术表 `alembic_version` 不计入业务表数量。六个 schema 分权：`loopx_control` / `loopx_ledger` / `loopx_state` / `loopx_runtime` / `loopx_quota` / `loopx_scheduler`。

| # | Schema | 表 | 第一阶段职责 |
|---:|---|---|---|
| 1 | `loopx_control` | `projects` | 项目/仓库边界与稳定身份 |
| 2 | `loopx_control` | `goals` | goal 稳定身份、状态和当前版本指针 |
| 3 | `loopx_control` | `goal_versions` | objective、scope、authority、guard、validation 等不可变版本 |
| 4 | `loopx_control` | `execution_snapshots` | 固定 run 开始时的 goal/policy/capability 执行边界和 fingerprint |
| 5 | `loopx_ledger` | `events` | 三类事件的统一 append-only 账本 |
| 6 | `loopx_ledger` | `command_receipts` | command 幂等、首次结果和稳定错误 |
| 7 | `loopx_ledger` | `outbox` | 导出和 scheduler intent 的事务性可靠投递 |
| 8 | `loopx_state` | `goal_states` | goal 当前状态 projection |
| 9 | `loopx_state` | `todos` | todo 当前状态、revision、claim 信息 |
| 10 | `loopx_state` | `gates` | operator gate 当前状态和决定 |
| 11 | `loopx_state` | `monitors` | monitor 目标、观察结果、resume condition，引用 schedule |
| 12 | `loopx_state` | `leases` | turn/todo lease、过期和 fencing token |
| 13 | `loopx_runtime` | `runs` | Agent turn/bounded execution 的结构化 summary |
| 14 | `loopx_runtime` | `evidence` | todo/run 的证据、校验状态、外部 artifact 引用/hash |
| 15 | `loopx_quota` | `quota_policies` | quota policy 的 insert-only 版本 |
| 16 | `loopx_quota` | `quota_spends` | append-only quota 消费 receipt |
| 17 | `loopx_scheduler` | `schedules` | heartbeat/monitor/one-shot 的计时权威 |
| 18 | `loopx_scheduler` | `schedule_runs` | occurrence 去重、调度状态和恢复 |

**第一阶段延后的 13 张表**：`actors`、`goal_memberships`、`capability_definitions`、`goal_capability_bindings`、`event_private_payloads`、`run_steps`、`tool_calls`、`artifacts`、`todo_edges`、`handoffs`、`human_rewards`、`domain_records`、`memory_entries`。第一阶段 actor 仍使用现有文本 ID，由既有 authority validator 校验；不引入数据库身份体系、RLS 或多租户隔离。

---

## 5. 阶段总览表（Roadmap）

| Phase | 名称 | 包含裁决步骤 | 结束标志（done-when 核心） |
|---|---|---|---|
| **1** | 奠基 | 1–2 | 直接 writer 全部登记、内部状态变更全走统一 command seam、行为/输出 parity 不变；内部 Markdown 行级直写为零 |
| **2** | 数据库地基 | 3–5 | per-root lifetime owner lock 保证同一 LoopX root 只有一个 daemon owner，transient endpoint failure 不产生第二 owner；persistent cleanup 非破坏；18 表 schema 由 Alembic 建成；`receipt+events+projection` 单事务落地且并发/幂等/重放测试通过 |
| **3** | 迁移与影子 | 6–7 | 同一 snapshot 重跑为 no-op、冲突可定位；`dual_read_shadow` 下 PG 不可用只增 mirror lag、不改 legacy 可见结果 |
| **4** | PG 垂直切片与 canary | 8–12 | 一个完整真实 goal 的读写/quota/lease/export/heartbeat/monitor 全走 PG，文件仅导出；任何 mismatch/failure 暂停 canary 不回落。**第一阶段到此结束** |
| **O** | 观察契约与本地 read model（并行、非阻塞） | O1–O2 | command seam 稳定且 nooa/DBOS identity/recovery 语义确认后共同冻结 `loopx.nooa.observation.v1`；O2 用 fixtures 验证 collector-private live DB、checkpoint/冲突规则与 immutable publications；不成为 authority、不阻塞 canary |
| **5** | 全局 promotion | 13–14 | 全部活动 goal 通过全量 rebuild/parity、无未解释 gap/dead-letter、完成备份；切换 `postgres_primary` 并硬拒绝旧 writer |
| **6** | 未来跨项目 nooa adapter/collector 接入 | O3（`labs-OO-Agents`） | nooa/DBOS emission、collector 生产接入和双方 compatibility/readback 完成；本 branch 不包含 nooa-side 实现 |

---

## 6. Phase 1：奠基（裁决步骤 1–2）

### 目标
在不改变任何生产行为的前提下，先固化现状基线（characterization），再把 legacy backend 上所有分散的文件写入口收敛到统一 command seam，为后续接入 PG 铺平道路。

### 范围 / 不做什么
- **做**：建立 characterization 基线；新增 `CommandEnvelope`/`CommandResult`/稳定错误码/`CommandRouter`/`LegacyCommandExecutor`；把 todos、goals、gates、monitors、leases、run finalization 的写入口统一改为 command。
- **不做**：不引入任何 PG 代码、daemon 或 schema；不改变任何外部可观测行为与输出格式；不新建迁移路由（扩展现有 `event_store_migration_bridge.py`，但本阶段不动它）。
- **硬边界**：完成后内部直接 Markdown 行级写入必须为零。

### 关键交付物
- **Characterization 基线**：固化 `ACTIVE_GOAL_STATE.md`、三类 JSONL、`runs/index.jsonl` 的当前输出；记录三类事件的 `append_sequence` 作用域、起始值、gap 与重复行为；枚举所有直接 writer、run classification 和现有 transaction phase。
- **Writer inventory**：所有直接写 `ACTIVE_GOAL_STATE.md`、三份 JSONL、`runs/index.jsonl` 的具体源码文件清单（裁决 §2.4 未确认事实 #1/#2/#4 在此步确认）。
- **统一 command seam（legacy 实现）**：不可变 `CommandEnvelope`、`CommandResult`、稳定 `CommandErrorCode`、`CommandRouter`（默认全部路由到 `LegacyCommandExecutor`）。
- **行为 parity 测试套件**：证明所有旧 command 行为和输出与基线一致。

### 依赖
- 无前置 Phase。外部条件：能访问当前仓库与现有 authority/transition/validation 校验器、Markdown parser/renderer、三类 JSONL payload 语义。

### 进入 / 退出硬门槛（done-when）
- **进入**：本计划批准；裁决纪要已确认。
- **退出**（全部满足才视为完成）：
  1. 所有直接写 `ACTIVE_GOAL_STATE.md`、三份 JSONL、`runs/index.jsonl` 的调用点已登记在案（writer inventory 完整）。
  2. 内部状态变更**全部**经过统一 command seam。
  3. Markdown parser/renderer、事件序列、run classification 已有 characterization tests。
  4. 所有旧 command 行为与输出 parity 不变（对照基线）。
  5. 内部直接 Markdown 行级写入为零。

### 主要风险与缓解
| 风险 | 缓解 |
|---|---|
| 遗漏隐藏写入口，导致后续双权威 | 用代码搜索 + characterization tests + 损坏/并发 fixture 穷举 writer；以"行级直写为零"为可判定门槛 |
| 收敛过程中行为漂移 | 基线 golden-file parity；任何输出变化即视为回归 |
| 误判 `append_sequence` 作用域 | 本步必须实测确认其作用域（全文件/goal/run/stream），不靠设计猜测 |

### 对应裁决步骤
**步骤 1、2**。

---

## 7. Phase 2：数据库地基（裁决步骤 3–5）

### 目标
把 LoopX PG 运行底座立起来：LoopX 常驻 daemon 只持有 LoopX 自己的 pgembed instance，Alembic 在 advisory lock 下建成 18 表 schema，并实现 ledger/receipt/projection rebuild 的原子写入能力——任何 PG state command 都能让 `receipt + events + projection` 在一个事务内完成。nooa/DBOS PG 不在本 Phase 的 ownership 或 migration 范围内。

### 范围 / 不做什么
- **做**：实现统一规范化 data root、短期 bootstrap lock、daemon 全生命周期 per-root owner lock、owner generation、endpoint/readiness、health check、显式 start/stop、多 CLI 并发启动与 ownership transfer 协议；验证并固定 cleanup policy；引入 Alembic 建六 schema、18 业务表、索引、唯一约束、事件不可变保护；实现统一 events、stream append、aggregate version、command receipts、source provenance、projection rebuild。
- **不做**：不把 pgembed 全局 init lock 当作 daemon singleton；不以 endpoint 失败或 readiness 超时单独判定 owner 消失；不做 legacy 数据导入（属 Phase 3）；不启用 shadow/canary；不实现 run/snapshot/quota/outbox/scheduler 的业务逻辑（属 Phase 4）。
- **硬边界**：迁移失败不发布 ready、不回退文件写；CLI 不每次调用 `get_server()`；persistent root 的正常 shutdown/upgrade/recovery 禁止 destructive cleanup；业务数据导入**不得**放入 Alembic。

### 关键交付物
- **LoopX 常驻 daemon / runtime 封装**：daemon 持有 LoopX `get_server(data_dir)` 返回的 handle，并在整个存活期持有该规范化 root 的独立 owner lock；CLI 连接 daemon 发布且匹配当前 owner generation 的标准 URI，可按需拉起 daemon（拉起即启动常驻 owner，而非临时持有）。
- **启动与 ownership 协议**：规范化 `data_dir` → 尝试连接匹配当前 owner generation 的 endpoint → 失败则取得短期 bootstrap `fcntl` 锁 → 检查 lifetime owner lock；若旧 owner 仍持锁则等待/retry 或返回 unavailable，绝不启动第二 daemon。只有成功取得 lifetime owner lock 才可清 stale readiness；在 bootstrap lock 保护下完成 ownership transfer → 启动 PG/健康检查/迁移 → 以新 owner generation 原子发布 readiness。正常停止先撤销 readiness、停止 PG，再释放 lifetime lock；crash takeover 也必须先取得该锁。
- **cleanup policy**：以当前 pgembed 版本的集成测试确认 `cleanup_mode` 准确语义；persistent roots 固定使用符合 daemon 生命周期的非破坏模式。`delete` 只允许显式 ephemeral/test root，或独立 destructive reset 命令在二次确认、规范化路径校验和备份后执行。
- **Alembic schema（`env.py` + `versions/0001_*~0003_*`）**：六 schema、18 表、索引、唯一约束、immutable 保护；迁移持 session advisory lock。
- **数据库基础模块**：`config.py`（统一 data root/URI/超时）、`runtime.py`（daemon 生命周期）、`session.py`（psycopg 短事务、advisory lock、数据库时间、连接生命周期）。
- **ledger 与 state store**：`ledger.py`（receipts、事件 append、stream sequence、aggregate version、source import 去重、outbox intent 的写入面）、`state.py`（goal/todo/gate/monitor/lease projection 读写、revision、rebuild）。

### 依赖
- Phase 1 完成（command seam 就位，PG executor 有挂载点）。
- 外部条件：确认 `get_server(data_dir)` 的 normalized-root handle 复用、停止/崩溃复用、global init lock、endpoint/hashed socket path、PG major mismatch 与各 `cleanup_mode` 的准确语义（裁决 §2.4 #3）；`pyproject.toml`/lockfile 增加 pgembed、psycopg 3、Alembic（**不**引入 ORM、TigerFS、pg_cron 运行依赖）。

### 进入 / 退出硬门槛（done-when）
- **进入**：Phase 1 退出门槛全部满足。
- **退出**（按子步骤判定）：
  1. **daemon（步骤 3）**：同一规范化 LoopX data root 只有一个持有 lifetime owner lock 的 daemon owner，CLI 不再每次调用 `get_server()`；pgembed global init lock 已被验证为短期库初始化机制而非 lifetime singleton；bootstrap lock、ownership transfer、owner generation 与 readiness 一致，transient endpoint failure 或 stale metadata 不会越过仍持有的 owner lock 启动第二 daemon；daemon crash、端口/socket URI 变化、哈希 socket path、PG 子进程残留、DiskList 与 PG major mismatch 均有明确处理。已用集成测试确认当前 pgembed 版本的 cleanup 语义：persistent root 的正常 stop/upgrade/recovery 不删除数据；`delete` 只在显式 ephemeral/test policy 或独立二次确认的 destructive reset 下可达。
  2. **schema（步骤 4）**：空库、并发启动、重复 upgrade、DB revision 新旧不匹配均有明确结果；未达 required head 不发布 ready、不启动 worker。
  3. **ledger/receipt/projection（步骤 5）**：任何 PG state command 满足 `receipt + events + projection` 单事务；并发 stale revision、相同/冲突幂等键、多 aggregate 锁顺序、事件重放测试全部通过。

### 主要风险与缓解
| 风险 | 缓解 |
|---|---|
| LoopX daemon/PG 启动竞态（transient endpoint failure、多 CLI 起多实例/连 stale endpoint） | 短期 bootstrap lock + daemon 全生命周期 per-root owner lock + owner generation/readiness；只有取得 lifetime lock 才能接管或清 stale metadata。pgembed init lock 与 DiskList 不承担 lifetime singleton；不同栈虽可 co-locate，仍使用独立 data root/handle/URI |
| destructive cleanup 误删 persistent root | 先验证当前 pgembed 版本的精确 `cleanup_mode` 语义；正常 persistent lifecycle 固定非破坏模式；`delete` 仅显式 ephemeral/test 或独立二次确认、路径/备份校验后的 reset |
| schema 未就绪被写入 | Alembic advisory lock；未达 required head 不 ready、不启动 worker；失败返回 `schema_migration_failed`/`database_unavailable` |
| 三种序列语义混淆 | 严格区分 `sequence_id`（内部 identity，可有空洞）/`append_sequence`（保留原 stream 序列与 gap）/`aggregate_version`（仅 projection 型 state event，行锁+事务保证连续） |
| 跨线程共享连接 | scheduler 与 outbox worker 各自使用独立 psycopg 连接，禁止跨线程共享 |

### 对应裁决步骤
**步骤 3、4、5**。

---

## 8. Phase 3：迁移与影子（裁决步骤 6–7）

### 目标
把历史数据安全搬进 PG 并建立可信的"影子"：实现 legacy importer 与确定性 baseline，然后启用 `dual_read_shadow`——文件仍是权威，PG 作为可重放镜像做语义 parity 校验。

### 范围 / 不做什么
- **做**：按文件锁取一致快照，导入三类 JSONL 与 runs；从 Markdown 当前状态生成 baseline projection/event；启用 `dual_read_shadow`（legacy command 后异步镜像 PG，周期 tailer 用文件 hash/JSONL 高水位补偿崩溃窗口）；比较 canonical projection、事件高水位、quota decision。
- **不做**：不把任何 goal 的权威切到 PG（属 Phase 4）；旧 state event 默认标记为审计历史，**不宣称可重放**。
- **硬边界**：导入重复、截断、非法 JSON、sequence gap、source hash 冲突均**不得静默跳过**；PG 不可用只增加 mirror lag，不影响 legacy 用户可见结果。

### 关键交付物
- **legacy importer（`legacy_import.py`）**：导入三类 JSONL、Markdown baseline、runs/quota；带 `source_stream_key + source_position + source_hash`，相同来源重跑为 no-op，内容冲突可定位并阻止 promotion。
- **baseline 机制**：以当时 `ACTIVE_GOAL_STATE.md` 快照创建确定性 `baseline` state event 并建立对应 projection；baseline 之后的 PG state events 才构成该 goal 的可重放生命周期账本。
- **dual_read_shadow**：扩展 `event_store_migration_bridge.py`；异步镜像 + 周期 tailer 补偿崩溃窗口。
- **parity 校验（`parity.py`）**：canonical projection hash、事件高水位、quota parity、projection rebuild parity。
- **status 可观测**：status 按 migration mode 读权威 projection，展示 mirror lag、projection mismatch、dead-letter、schema readiness。

### 依赖
- Phase 2 完成（schema、ledger、projection rebuild 就绪）。
- Phase 1 的 writer inventory 与 characterization 基线（作为导入与 parity 的对照）。

### 进入 / 退出硬门槛（done-when）
- **进入**：Phase 2 退出门槛全部满足。
- **退出**（全部满足）：
  1. **importer/baseline（步骤 6）**：同一 snapshot 重跑为 no-op；导入重复、截断、非法 JSON、sequence gap、source hash 冲突均可定位、不静默跳过、可阻止 promotion。
  2. **dual_read_shadow（步骤 7）**：文件仍为权威；PG 不可用只增加 mirror lag，不改变 legacy 用户可见结果；canonical projection、事件高水位、quota decision 可比较且有结果。

### 主要风险与缓解
| 风险 | 缓解 |
|---|---|
| 旧事件不可完整重放导致错误当前状态 | 旧事件标记 audit-only；以 Markdown 快照建 baseline；baseline 后才承诺 replay |
| 文件与 PG 无跨介质原子事务（文件已提交 PG 未镜像） | 异步 mirror + source hash + semantic parity + 重试；不假装跨介质原子 |
| 导入静默吞错 | 所有异常（重复/截断/非法/gap/hash 冲突）显式可定位，且能阻止 promotion |
| `append_sequence` 作用域误配 | `stream_key` 必须准确表达原文件实际序列作用域，不能简单用 `event_class` 代替 |

### 对应裁决步骤
**步骤 6、7**。

---

## 9. Phase 4：PG 垂直切片与 canary（裁决步骤 8–12）

### 目标
把单个完整 goal 的全部生命周期垂直迁到 PG：先做 state vertical slice 与 fencing，再把 run/snapshot/quota 做成原子事务，落地真实 transactional outbox 与兼容 exporter，接入 LoopX scheduler，最终让一个完整真实 goal 在 `bounded_canary` 下全量跑在 PG 上（文件仅作导出）。**第一阶段到此结束。**

### 范围 / 不做什么
- **做**：迁移一个完整 todo 生命周期（claim、lease、evidence、complete、defer/block），再覆盖 gate、monitor 及其他现有状态命令；run 启动事务创建 `execution_snapshot + run + lease`，host 执行在事务外，最终 validated command 原子提交 durable writeback + run result + 唯一 quota spend + scheduler intent；实现真实 outbox（pending/processing/delivered/dead-letter、claim token、超时回收、退避、条件 ack、NOTIFY+轮询）与幂等兼容 exporter；实现 LoopX scheduler（schedules、schedule_runs、due claim、deterministic trigger、interval/at、coalesce/skip）；进入完整 goal 的 `bounded_canary`。
- **不做**：不做全局 promotion（属 Phase 5）；scheduler 只支持 `heartbeat`/`monitor`/`one_shot`、`interval`/`at`、`coalesce`/`skip`、默认 `max_concurrency=1`；不实现 pg_cron/TigerFS/详细 runtime trace/capability registry/memory/vector。
- **硬边界**：canary 粒度必须是**完整 goal**；未支持的 command 返回明确错误，不得隐式回落旧路径；任何 mismatch、required dead-letter、人工文件编辑或 schema/storage failure 都**暂停 canary，不回落文件写**。

### 关键交付物
- **PG state vertical slice + fencing**：`state.py` 全量读写；revision + lease expiry + fencing token 防 stale write。
- **run/snapshot/quota 原子事务**：`runtime_store.py`（execution snapshot、fingerprint、run summary、evidence）、`quota_store.py`（classification → 唯一 `quota_spends`，替换 JSONL Python 重扫）；同步修改 `turn_driver/transaction.py` 阶段映射。
- **transactional outbox + 兼容 exporter**：`legacy_export.py`（PG projection → `ACTIVE_GOAL_STATE.md`、PG events → 三类兼容 JSONL），整体渲染、幂等、人工编辑冲突检测。
- **LoopX scheduler**：`heartbeat/**`、`scheduler/**` 接入统一 command 与 run 流；`schedule_id + scheduled_for_utc` 生成 deterministic `trigger_key`，`UNIQUE(schedule_id, trigger_key)` 防重复 occurrence。
- **CLI 迁移命令**：`cli_commands/**` 增加 `db start/status/stop/migrate`、`storage shadow/canary`、outbox status/retry；写命令统一走 router。
- **bounded_canary 运行记录**：合成 goal → 低风险真实 goal 的 canary 过程与结论。

### 依赖
- Phase 3 完成（baseline 与 shadow parity 已建立可信对照）。
- 同一 Phase 内的子依赖：state slice（8）→ run/quota（9）→ outbox/exporter（10）→ scheduler（11）→ canary（12）。其中步骤 5、9、10 标记为 `[原子]`，须整体落地。

### 进入 / 退出硬门槛（done-when）
- **进入 `bounded_canary` 的硬门槛**（裁决 §5.2，全部同时满足）：
  1. 目标 goal 已完成幂等 baseline；
  2. projection 可从 baseline + state transitions 全量 rebuild，结果与在线 projection 相同；
  3. 该 goal 的全部现有 command type 已有 PG handler；
  4. legacy/PG semantic projection、事件高水位、quota 结果一致；
  5. outbox exporter 和 scheduler handler 已具备重试、去重、过期 claim 恢复；
  6. 没有未解释的 source sequence/hash 冲突；
  7. 不允许 PG 失败后回落文件写。
- **各子步骤验收**：
  - **state slice（8）**：旧 turn、过期 lease、重复 command、取消后的最终写回均 fail closed。
  - **run/snapshot/quota（9）**：全部现有 run classification 与旧 quota 结果一致；重复 finalization 不重复收费。
  - **outbox/exporter（10）**：commit 后崩溃、外部导出成功但 ack 失败、重复投递、NOTIFY 丢失均可恢复。
  - **scheduler（11）**：重复 occurrence、worker 崩溃、misfire、多 worker、调度通知丢失均不产生重复业务命令。
- **Phase 退出（步骤 12，即第一阶段终点）**：一个完整真实 goal 的所有读写、quota、lease、export、heartbeat/monitor 均走 PG，文件仅导出；出现任何 mismatch/required dead-letter/人工文件编辑/schema 或 storage failure 时 canary 暂停且不回落文件写。

### 主要风险与缓解
| 风险 | 缓解 |
|---|---|
| 双权威/分裂写入 | 按完整 goal 切换；任何时刻只有一个 authority；canary/primary PG 故障 fail closed |
| stale turn 写回 / 重复消费 quota | projection revision + lease fencing token；最终写回再次校验；quota `UNIQUE(run_id)`/receipt key 同事务提交 |
| outbox 重复或确认过期 | `SKIP LOCKED` + `lock_token` + `locked_until` + handler dedupe key + at-least-once 幂等 |
| NOTIFY 丢失致 worker 未唤醒 | NOTIFY 只作唤醒；定期扫描 outbox/due schedules 作可靠兜底 |
| quota 重算漂移 | policy version + insert-only spend + 同一事务提交 |
| 人工编辑文件造成冲突 | exporter 做人工编辑冲突检测；冲突即暂停 canary |

### 对应裁决步骤
**步骤 8、9、10、11、12**。

---

## 10. 并行 Track O：观察契约与 DuckDB 本地 read model（O1–O2，非阻塞）

### 目标
在 LoopX command seam 已稳定、且 nooa/DBOS 项目已确认 workflow/branch/lineage/commit identity 与 recovery 语义后，由双方共同冻结 `loopx.nooa.observation.v1`；不要求尚未实现的 nooa adapter contract 先行冻结。随后 O2 使用 contract fixtures/test producers 建立可重建的本地 DuckDB analytical read model。该 track 可以与 Phase 2–4 的迁移工作并行，但不得阻塞 `bounded_canary`、写 LoopX authority、参与 settlement 或成为第二事实源。

### 范围 / 不做什么
- **O1 做**：定义 versioned typed public-safe envelope；固定 LoopX goal/todo/turn identity、`turn_instance`/`turn_key`/`effect_id`，nooa `workflow_id`/`branch_id`/`lineage_id`/`commit_seq`，显式稳定 `producer_id`、producer/runtime versions、稳定 `source_stream_id`、`source_cursor`、全局唯一 `event_id`、`occurred_at` 和 `payload_hash`；明确独立 authority、双 identity uniqueness、canonical hash、checkpoint 与 retry/recovery 规则。
- **O1 做**：`event_id` 唯一，`(producer_id, source_stream_id, source_cursor)` 也唯一。任一 identity 已存在时，两者必须解析到同一不可变 observation 且 canonical hash 相同，否则返回 `observation_payload_conflict`；不得覆盖旧记录或推进 checkpoint。`business_idempotency_scope`/`business_idempotency_key` 仅作业务 command correlation，不作 observation dedupe。
- **O1 做**：区分四类行为：same-envelope redelivery 保持 event/source/correlation identity 与 hash 全部不变；transport reconnect 从已确认 checkpoint 后续传；DBOS workflow recovery 保持原 `turn_instance`/`turn_key`/`effect_id`/`nooa_workflow_id` 稳定，但为新 recovery/step 变化发布新 `event_id` 和后续 cursor；new business attempt 生成新的 `turn_instance`/`turn_key`/`effect_id`/`nooa_workflow_id` 及新 event identity。
- **O1 做**：冻结连续 no-skip high-water 协议，或具有 producer predecessor/commit token 与 compare-and-advance 的等价 opaque checkpoint 协议；collector 不得跨 gap、identity conflict、hash conflict 或 public-safety rejection 推进。
- **O2 做**：以 fixtures/test producers 验证 collector；collector 是唯一打开 live read/write DuckDB 文件的进程，live 文件与目录 collector-private。分析只能在 collector 进程内、通过受控 owner-local query API，或针对原子发布的 immutable DuckDB snapshots/Parquet datasets 执行；外部 reader/agent 不得打开 live 文件。持久化每个 `(producer_id, source_stream_id)` checkpoint，使用幂等 batch ingestion、Parquet/JSONL staging 和 rebuildable DuckDB file。
- **做**：提供相关但不混淆的统一 timeline：LoopX `intent/dispatch/validation/settlement` 与 nooa/DBOS `accepted/started/step/recovery/succeeded/failed`。
- **不做**：不以 PostgreSQL `ATTACH` 作为主摄入。支持的 `ATTACH` 仅限 owner-authorized、read-only、approved public-safe data 的 ad-hoc/debug 查询；不得写任一 PG、读取私表/跨栈数据、向 collector live model 供数，或绕过双侧 validation 与 immutable publication。也不做共享 migration、跨系统事务，不把 DuckDB 暴露为共享 multi-tenant service 或当作 auth/role permission boundary。
- **不做**：本 branch 不实现 production nooa/DBOS emission、nooa adapter 或 collector 接入；这些属于未来 `labs-OO-Agents` Phase 6。

### 关键交付物与 done-when
1. **O1 contract frozen**：双方在 nooa/DBOS identity/recovery 语义确认后共同冻结字段、版本演进、authority domain、双 identity uniqueness/cross-resolution、business correlation、cursor/checkpoint、canonical hash coverage 和四类 retry/recovery 规则。`payload_hash` 为 SHA-256 over versioned canonical serialization，覆盖除 hash 字段自身外的 contract、producer、source、identity、correlation、kind/status/domain、public payload 与 typed evidence pointers；它只用于 equality/corruption detection，不证明 authenticity、authorization 或 evidence access。
2. **O1 public-safety gate frozen**：producer 在 serialization/staging 前 fail closed；collector 在 persistence/checkpoint advancement 前独立重验。evidence pointers 只能是 typed/allowlisted public-safe identifiers、必要 hash/classification 与非敏感 locator；禁止 raw prompts/trajectories/logs/verifier tails、credentials、credential-bearing/query tokens、任意 URI/query strings、local absolute paths 和 private planning context。
3. **O2 fixture-based read model ready**：无需 production nooa adapter，collector 即可用 fixtures 验证 same-envelope no-op、双 identity immutable resolution、`observation_payload_conflict`、连续 no-gap 或等价 opaque checkpoint、重启续传、乱序 pending、gap/conflict 不推进，以及从 validated envelopes + Parquet/JSONL staging 重建。
4. **O2 supported analysis topology ready**：只有 collector 打开 live DB；in-process/controlled API analysis 可用，immutable DuckDB snapshot/Parquet publication 具有 generation/manifest/hash 且不原地修改；外部 reader 对 live 文件无访问权。
5. **边界验证**：DBOS completion 不会产生 LoopX settlement；DuckDB 不写 LoopX authority；统一 timeline 只相关不混淆；Phase 4 `bounded_canary` 的全部 gate 在 collector 不存在或故障时仍可独立判定。

### 官方事实来源与设计选择
DuckDB 的嵌入式连接/架构、并发访问模式、PostgreSQL extension/`ATTACH`、Parquet 与 JSON 能力以裁决纪要 §3.2-H 中的 DuckDB 官方 canonical links 为事实依据。collector-private live file、in-process/controlled API analysis、immutable publications、strict filesystem permissions、checkpoint ledger、staging-first 和 rebuildable-file 是本架构的设计选择；不得把它们误写成 DuckDB 自带的 server auth/roles，也不得从官方“单进程读写/多进程只读”能力推导出 live writer 与外部 reader 并存。

---

## 11. Phase 5：全局 promotion（裁决步骤 13–14）

### 目标
在所有活动 goal 上完成全量验收后，把控制面整体切换为 `postgres_primary`，关闭旧权威写入路径，让 PostgreSQL 成为唯一生产权威。

### 范围 / 不做什么
- **做**：对所有活动 goal 执行全量 rebuild/parity；确认无未解释 mirror gap、projection mismatch、quota 差异或 required outbox dead-letter；切换前暂停写入、drain outbox、完成备份；原子更新 migration mode 到 `postgres_primary`；硬拒绝旧 direct writer 与人工 Markdown 摄入路径。
- **不做**：不在本 Phase 引入 actors/capability registry/详细 runtime trace/memory/vector/TigerFS 等扩展（见 §13 延后项），它们不得阻塞核心切换。
- **硬边界**：历史上真实存在的 sequence gap 可保留；硬门槛要求的是**没有未解释的新 gap、重复或 hash 冲突**。旧 binary 若没有只读兼容模式，不得直接回滚上线。

### 关键交付物
- **promotion_candidate 验收报告**：全量 rebuild/parity 结果、事件账本重建、quota 重算、status projection 校验、七个 `TRANSACTION_PHASES` 边界的崩溃注入测试结果。
- **逻辑备份**：切换前的 PG 逻辑备份或等价安全备份。
- **postgres_primary 切换**：原子更新 migration mode；所有读路径默认从 PG projection 读取；Markdown/JSONL exporter 仍运行但仅作兼容输出；legacy importer 仅保留为显式迁移/冲突处理工具。
- **旧路径关闭**：旧 direct writer 硬拒绝；`cli_commands/**` 提供 `storage promote`。

### 依赖
- Phase 4 完成（至少一个完整真实 goal 已在 `bounded_canary` 下稳定运行于 PG）。

### 进入 / 退出硬门槛（done-when）
- **进入 `promotion_candidate`（步骤 13）**（裁决 §5.2，全部同时满足）：
  1. 所有活动 goal 均已完成 baseline/canary；
  2. 所有现有 run classification、状态命令、schedule type 均通过 parity；
  3. required outbox 无 pending 或 dead-letter；
  4. 无 projection mismatch、mirror gap、人工编辑冲突；
  5. 七个 `TRANSACTION_PHASES` 边界均有崩溃注入测试；
  6. 事件账本重建、quota 重算、status projection 全部通过；
  7. 已完成 PG 逻辑备份或等价安全备份。
- **进入 `postgres_primary`（步骤 14，即 Phase 退出）**（全部满足）：
  1. 暂停切换期间的 goal 写入并 drain 必要 outbox；
  2. 原子更新 migration mode；
  3. 禁止旧 writer 和人工 Markdown 摄入路径；
  4. 所有读路径默认从 PG projection 读取；
  5. Markdown/JSONL exporter 仍可运行，但只作为兼容输出；
  6. 旧 binary 若没有只读兼容模式，不得直接回滚上线。

### 主要风险与缓解
| 风险 | 缓解 |
|---|---|
| 切换窗口写入丢失或双写 | 暂停写入 + drain outbox + 原子更新 migration mode |
| 旧版本回滚写文件覆盖新 PG 状态 | promotion 后文件只读导出；旧写入口硬拒绝；切换前做逻辑备份 |
| 未解释的 gap/重复/hash 冲突被带入生产 | 以"无未解释新 gap/重复/hash 冲突"为进入 promotion 的硬门槛；历史真实 gap 可保留 |

### 对应裁决步骤
**步骤 13、14**。

---

## 12. Phase 6：未来跨项目 nooa adapter/collector 接入（O3）

### 目标与归属
在 `labs-OO-Agents` 的后续独立分支/PR 中，实现生产 nooa/DBOS observation adapter 与 public-safe emission，并把 collector 接到这些真实 producer；实现必须遵循 Track O 已用 fixtures 冻结的版本化 contract，而不是反过来重新定义它。LoopX 侧只消费 public contract，不读取 nooa/DBOS 私表。本 `feat/loopx-on-pgembed` 分支只更新规划文档，不包含也不声称已经实现 nooa-side code、DBOS emission 或 production collector integration。

### 前置与退出门槛
- **前置**：LoopX command seam 已稳定；nooa/DBOS workflow/branch/lineage/commit identity 与 recovery 语义已经确认；双方已据此完成 O1 contract freeze，O2 已用 fixtures/test producers 验证 identity、checkpoint、public-safety 与 collector-private live DB topology。
- **退出**：nooa adapter/DBOS emission 实现已冻结 contract，producer-side validation 在 serialization/staging 前 fail closed；collector 对真实 producer 独立重验并遵守双 identity、canonical hash 与 no-gap checkpoint。两套独立 pgembed 栈在独立运行与可选 co-location profile 下均通过 compatibility/readback；same-envelope redelivery、transport reconnect、DBOS recovery/new observations、new business attempt 测试通过；统一 timeline 保持双 authority 语义。
- **硬边界**：该 Phase 不改变 LoopX `bounded_canary` 或 `postgres_primary` gate；DBOS completion 仍不是 LoopX settlement；collector 仍不是 authority；外部分析不打开 collector live DuckDB 文件。

---

## 13. 明确延后项

以下内容**不属于本母计划范围**，留待 `postgres_primary` 稳定后单独规划，且不得阻塞核心迁移：

| 延后项 | 说明 |
|---|---|
| **TigerFS** | 增加 companion 进程与挂载生命周期；可写 mount 可能绕过 command envelope；当前 Markdown/JSONL exporter 已足够提供兼容；`.build/` workspace 文件兼容不是控制面 ledger 迁移的前置条件 |
| **pg_cron 业务调度** | 第一阶段不启用、不改 preload；未来最多用于数据库 housekeeping 或分钟级 liveness nudge，不能承载 heartbeat/monitor 业务语义 |
| **pgvector / memory** | 记忆/向量检索属第二/三阶段增强，不进入核心调度路径 |
| **capability registry / bindings** | 完整能力注册表与绑定延后 |
| **详细 runtime trace** | `event_private_payloads`、`run_steps`、`tool_calls`、`artifacts` 等详细执行轨迹表延后 |
| **actors / RLS / 多租户** | 第一阶段 actor 用现有文本 ID + 既有 authority validator；不引入数据库身份体系、RLS、多租户隔离、事件分区 |
| **通用消息总线 / webhook / 外部 exactly-once** | outbox 只承诺 at-least-once |

---

## 14. 附录：三份文档的关系

| 文档 | 角色 | 相对路径 |
|---|---|---|
| **原始设计文档** | **背景来源（本 worktree 当前未跟踪）**。31 表/6 schema/统一 command envelope/MVP 裁剪的原始设想与表设计参考。若未来重新纳入仓库，凡与裁决纪要冲突处（如对 Zleap 的误读、events 幂等约束、pg_cron 角色、MVP 表数）以裁决纪要为准。 | `./loopx-on-pgembed-design.md` |
| **架构裁决纪要** | **权威依据**。八项裁决结论、修正后的 18 表 MVP、统一 events 表约束、双栈 ownership、版本化 observation contract、DuckDB read-model 边界、TRANSACTION_PHASES 新边界、14 步实施顺序与 O1–O3 并行/跨项目 track、风险与硬门槛、file-by-file impact。本母计划严格遵循，不得与其冲突。 | `./loopx-on-pgembed-architecture-decisions.md` |
| **本母计划** | **执行纲领**。以裁决 14 步为核心迁移骨架组织 Phase 1–5，以 Track O 组织非阻塞观察工作，并将 nooa adapter/collector 的未来跨项目实现列为 Phase 6；给出各 Phase/track 的目标、边界、交付物、依赖、硬门槛与风险。 | `./loopx-on-pgembed-master-plan.md`（本文） |

**给深度计划生成者的指引**：每个 Phase 的深度计划应以本计划对应章节的"范围/不做什么"为边界、以"进入/退出硬门槛"为完成判据展开；涉及具体 file-by-file 改动、表 DDL、接口签名时，回到裁决纪要 §4（file-by-file impact）与 §3.4（events 约束）取权威定义，不得发明与之冲突的设计。
