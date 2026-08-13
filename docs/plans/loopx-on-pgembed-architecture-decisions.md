# loopx on pgembed 架构裁决纪要

> **状态**：已裁决，供母计划引用  
> **范围**：持久化迁移、事件账本、可靠投递、调度、pgembed 生命周期、第一阶段 MVP  
> **最终目标**：PostgreSQL 成为 LoopX 控制面状态的唯一生产权威；Markdown/JSONL 保留为兼容导出，而不是第二事实源。

## 1. Summary

LoopX 不采用一刀切替换，而采用**按 goal 分阶段、单一权威端切换**的渐进迁移：先通过统一 command boundary 收敛现有文件写入口，在 `dual_read_shadow` 中以文件为权威、PG 为可重放镜像并进行语义 parity 校验，再将完整 goal 切换到 PG，最终全局进入 `postgres_primary`。三层 JSONL 合并为一张物理 `loopx_ledger.events` 表，但保留 `state`、`rollout`、`supervisor` 三种逻辑语义，并独立维护 `append_sequence`、`aggregate_version` 与 command receipt 幂等性。第一阶段实现真正可工作的最小 outbox、`FOR UPDATE SKIP LOCKED`、insert-only goal/quota 版本、带 fingerprint 的 execution snapshot 和自有 scheduler；pg_cron、TigerFS、详细 runtime trace、capability registry、memory/vector 等延后。**默认部署是完全独立的 LoopX-on-pgembed 与 nooa-on-DBOS 两套栈**：各有自己的 pgembed PostgreSQL 实例、规范化数据根和 lifecycle owner；LoopX daemon 只持有 LoopX 自己的 PG，绝不拥有 nooa/DBOS 存储。各自 schema 独立迁移；第一阶段明确为 18 张 LoopX 业务表，阶段终点是至少一个完整 goal 的 bounded canary，不是全局 promotion。

---

## 2. Current-state analysis

### 2.1 当前权威与写入路径

| 范畴 | 当前事实 | 架构影响 |
|---|---|---|
| Goal 当前状态 | `ACTIVE_GOAL_STATE.md` 是权威源，不是导出物 | 不能直接假设旧事件可以完整重建状态 |
| 状态事件 | `events.jsonl` | 记录不覆盖所有 Markdown 状态变更 |
| Rollout 事件 | `rollout-event-log.jsonl`，现有 22 类事件 | 有独立事件语义和序列约束 |
| Supervisor 事件 | `supervisor-events.jsonl` | 既包含观察，也可能关联后续状态变化 |
| Todo 写入 | Markdown 行级直编与事件追加两条并行路径 | 存在状态与事件不一致窗口 |
| Run/quota | `runs/index.jsonl` 记录 run classification，quota 由 Python 重扫重算 | 没有原子、可重试的 spend receipt |
| 并发 | `fcntl` 文件锁 | 只能保护文件临界区，没有 lease 或 fencing token |
| 幂等 | 各子系统自定义键 | 无法统一返回首次命令结果，也无法可靠协调重试 |
| 事务阶段 | `loopx/control_plane/turn_driver/transaction.py` 已定义 `TRANSACTION_PHASES` | 应保留阶段语义，但重新划分数据库事务边界 |
| 迁移扩展点 | `event_store_migration_bridge.py` 已有 `dual_read_shadow → bounded_canary → promotion_candidate` | 应扩展现有 bridge，不另建迁移路由 |
| pgembed | `get_server(data_dir)` 只管理 PG 进程生命周期 | schema migration、readiness 和业务 worker 必须由 LoopX 负责 |

### 2.2 当前端到端控制流

```text
CLI / heartbeat / supervisor / provider callback
  → 读取 Markdown、JSONL 和运行状态
  → host_execute
  → typed_result
  → validation
  → durable_writeback
      → ACTIVE_GOAL_STATE.md
      → events.jsonl / rollout-event-log.jsonl / supervisor-events.jsonl
  → quota_spend
      → runs/index.jsonl
      → Python 循环重算
  → scheduler_apply
  → scheduler_ack
```

其中 `host_execute` 可能包含长时间的 provider、工具或文件操作，不能持有数据库行锁或长事务。真正需要原子化的是验证完成后的短写回阶段：状态转移、run 结果、quota spend 和 scheduler/export intent。

### 2.3 可复用代码与必须消除的阻塞点

必须复用：

- `loopx/control_plane/turn_driver/transaction.py` 的七阶段名称和已有遥测语义；
- `event_store_migration_bridge.py` 的迁移状态机；
- 现有 authority、transition、validation、public/private boundary 校验器；
- Markdown parser/renderer；
- 三类 JSONL 的 payload 和原有 `append_sequence` 语义；
- 现有 run classification 与 quota 规则；
- `fcntl`，但仅用于迁移期间获取一致文件快照或保护兼容导出。

必须消除：

- Todo 的 Markdown 直写与事件追加双路径；
- 以不完整旧 state event 重建当前状态的假设；
- 每个子系统独立定义幂等键；
- 无 fencing 的长期 turn 写回；
- 以 `runs/index.jsonl` 和 Python 全量扫描作为新系统的 quota 权威；
- 将 `events` 直接当作可 claim/ack 的任务队列。

### 2.4 迁移前必须确认或在集成期验证的事实

以下事实不改变本纪要的裁决。第 1、2、4 项必须在实施第 1 步确认；第 3 项已经对当前 pgembed 源码完成静态核验，并在实施第 3 步验证 LoopX 集成行为：

1. 三份 JSONL 中 `append_sequence` 的实际作用域是全文件、goal、run 还是其他 stream。
2. 所有直接写 `ACTIVE_GOAL_STATE.md`、三份 JSONL 和 `runs/index.jsonl` 的具体源码文件。
3. 已确认 `get_server(data_dir)` 按规范化 `pgdata` 复用 handle、不同实例共享全局 init inter-process lock、endpoint 可为 Unix socket 或平台 TCP 且 socket 路径可能哈希化、PG major mismatch 是硬边界、`cleanup_mode` 必须显式选择；实施第 3 步仍需验证 LoopX daemon 的持有、停止、崩溃复用、stale endpoint 和 cleanup 行为。
4. 现有完整 command type、run classification 和 scheduler type 清单。

验证方式是代码搜索、现有行为 characterization tests、损坏/并发 fixture 和 pgembed 进程集成测试，不通过设计猜测补齐。

---

## 3. Design

### 3.1 不可违反的架构不变量

1. **每个 goal 在任一时刻只有一个写入权威端**：文件或 PG，不能双权威。
2. **所有业务写入先形成统一 `CommandEnvelope`**；Agent、Dashboard、CLI、scheduler 和 provider callback 都不能直接改状态表或文件。
3. **生命周期状态的事实源是事件账本，当前状态由 projection 提供**；但 goal 配置、run summary、quota policy/spend 各有明确的自身权威表。
4. **host execution 在数据库事务外执行**；最终 validated result 以 revision 和 fencing token 提交。
5. **状态事件、projection、run/evidence、quota spend、scheduler/export intent 在同一个短 PG 事务内提交**。
6. **outbox 采用 at-least-once**；所有 handler 必须幂等，不承诺外部系统 exactly-once。
7. **不用通用 ORM/CRUD 层**；只增加窄的 command、ledger、projection、runtime、quota、scheduler store 接口。

---

### 3.2 八项最终裁决

#### A. 迁移策略：选择渐进迁移，不做双权威双写

采用以下四个逻辑阶段：

```text
dual_read_shadow
  → bounded_canary
  → promotion_candidate
  → postgres_primary
```

| 阶段 | 权威写入端 | 读返回端 | 另一端职责 | 故障行为 |
|---|---|---|---|---|
| `dual_read_shadow` | 文件 | 文件 | PG 异步镜像、projection rebuild、parity 校验 | PG 失败只形成 mirror lag，不影响文件结果 |
| `bounded_canary` | 按完整 goal 切换到 PG | 该 goal 读 PG | Markdown/JSONL 由 PG 导出 | PG 失败必须失败关闭，禁止回退写文件 |
| `promotion_candidate` | PG | PG | 文件仅作导出和最终校验 | 导出冲突、projection mismatch 或 required outbox dead-letter 阻止 promotion |
| `postgres_primary` | PG | PG | 文件是兼容导出 | 直接编辑文件不再自动摄入 |

这里的“双写”只表示**权威端向非权威端做镜像或导出**，不表示两个后端都可接受业务写入。

**Canary 粒度必须是完整 goal**。不能让同一个 goal 的 `complete_todo` 走 PG、`defer_todo` 走 Markdown；未支持的 command 在 canary 中应返回明确错误，不得隐式回落旧路径。

旧数据迁移规则：

- 旧三层 JSONL 全部导入统一事件表，但迁移前的 state event 默认标记为审计历史，不宣称可重放。
- 以当时的 `ACTIVE_GOAL_STATE.md` 当前快照创建一个确定性的 `baseline` state event，并建立对应 projection。
- 从 baseline 之后，PG state events 才构成该 goal 的可重放生命周期账本。
- 导入必须带 `source_stream_key + source_position + source_hash`，相同来源重跑为 no-op，内容冲突阻止 promotion。
- Markdown 与 PG 之间没有跨介质原子事务；因此必须通过 outbox、重试和 parity 校验弥补，而不是假设两边可以同步提交。

---

#### B. 事件模型：一张物理表，三种逻辑事件

采用单一 `loopx_ledger.events` 表，使用 `event_class` 区分：

- `state`：接受的生命周期转移、baseline，以及必要的 state 审计事件；
- `rollout`：现有 22 类 rollout 事件，保留原有事件类型；
- `supervisor`：监督观察、调度决策或运行监督事件。

统一物理表的理由是复用 envelope、因果关联、hash、导入、查询和 retention 机制；统一物理表不意味着三类事件共享相同的聚合版本语义。

规则：

- 只有 `state` 中的 `baseline` 和 `transition` 事件更新 projection 并参与 replay。
- `rollout`、`supervisor` 的 `aggregate_version` 必须为空，即使它们带有 `aggregate_type/aggregate_id` 作为查询引用。
- supervisor 导致实际状态变化时，写一条 supervisor 事件，再由同一 command 产生一条独立的 state 事件，并以 `causation_id`/`correlation_id` 关联。
- 不把详细 tool transcript 或所有 runtime trace 强行转成生命周期事件。

---

#### C. Zleap 借鉴：实现最小真实机制，不照搬未实现的理想描述

Zleap 的 outbox、worker、SKIP LOCKED、insert-only 版本化和 fingerprint snapshot 不能作为“已验证实现”引用。LoopX 仍实现其中真正解决自身故障模式的子集：

**第一阶段必须实现：**

- `command_receipts`：统一命令幂等；
- transactional outbox：至少服务兼容导出和 scheduler dispatch；
- `FOR UPDATE SKIP LOCKED`：用于 outbox/schedule claim；
- claim `lock_token + locked_until`：防止过期 worker ack 覆盖新 worker；
- insert-only `goal_versions`；
- insert-only `quota_policies` 和 `quota_spends`；
- immutable `execution_snapshots`；
- canonical JSON + SHA-256 fingerprint。

**第一阶段明确不实现：**

- 通用消息总线、webhook 平台和外部 exactly-once；
- 完整 capability registry/bindings；
- `event_private_payloads`、详细 `run_steps/tool_calls/artifacts`；
- memory、pgvector、TimescaleDB、RLS、多租户和事件分区；
- TigerFS；
- 以 pg_cron 代替业务 scheduler。

单机 PG 仍需要 outbox 和 claim token，因为进程崩溃、daemon 重启、多个 CLI、未来多 worker 以及“外部动作成功但确认失败”都会产生可靠投递问题。

Outbox 状态闭集为：

```text
pending → processing → delivered
                    ↘ pending（退避重试）
                    ↘ dead_letter
```

领取与确认规则：

1. 短事务中用 `FOR UPDATE SKIP LOCKED` 领取到期行；
2. 写入 `lock_token`、`locked_until`、attempt 次数后提交；
3. 事务外执行导出或调度动作；
4. 只有 `id + lock_token` 仍匹配时才可确认 delivered；
5. 超时 processing 行可被重新领取；
6. `NOTIFY` 丢失不影响轮询发现；
7. required topic 的 dead-letter 阻止 promotion。

版本化范围只覆盖会改变历史解释的数据：

- `goal_versions`；
- `quota_policies`；
- `execution_snapshots`；
- `events`；
- `quota_spends`。

`goals.current_version` 是可变指针，不是版本内容；projection、schedule 的当前运行字段和 outbox claim 状态保持可变。

Execution snapshot 至少固定：

- goal/version；
- quota policy version；
- 当次解析出的有效 capability 集合及配置；
- authority、guard、validation、public-boundary policy；
- provider/model 的公开配置或 secret reference；
- `snapshot_schema_version`；
- `fingerprint_algorithm`；
- `fingerprint`。

secret 不存明文。fingerprint 用于完整性和可复现性，不宣称能抵御数据库 owner 的恶意篡改。

---

#### D. 调度：LoopX 自有 scheduler，pg_cron 不进入业务主路径

采用常驻 LoopX scheduler/outbox worker，`LISTEN/NOTIFY` 只做低延迟唤醒，定时轮询作为可靠兜底。

职责划分：

- `schedules`：唯一的计时权威，保存 `next_run_at`；
- `schedule_runs`：每个 occurrence 的去重、状态和恢复记录；
- `monitors`：监控目标、观察结果和 resume condition，并引用 `schedule_id`；
- `outbox`：将已生成的调度意图投递给 runtime；
- `events`：记录审计和生命周期结果，不承担 job claim/ack。

第一阶段只支持：

- `heartbeat`、`monitor`、`one_shot`；
- `interval`、`at`；
- `coalesce`、`skip` 两种 misfire policy；
- 默认 `max_concurrency = 1`；
- 用 `schedule_id + scheduled_for_utc` 生成 deterministic `trigger_key`；
- `UNIQUE(schedule_id, trigger_key)` 防止重复 occurrence。

Due schedule 处理顺序：

```text
数据库时间读取 due schedules
  → 短事务 FOR UPDATE SKIP LOCKED
  → 创建唯一 schedule_run
  → 依据原 scheduled_for 推进 next_run_at
  → 插入 scheduler outbox intent
  → commit / 发送 NOTIFY
  → worker 以 trigger_key 生成 CommandEnvelope
  → command_receipt 幂等执行
  → 更新 schedule_run
```

pg_cron 第一阶段不启用、不修改 preload。未来最多用于数据库 housekeeping 或分钟级 liveness nudge，不能承载 heartbeat/monitor 的业务语义，因为它的粒度、唤醒方式和权限/验证模型都不适合 LoopX。

---

#### E. 嵌入形态：每个栈由自己的常驻 daemon 持有自己的 PG；Alembic 负责各自 schema

PG 生命周期归**各自栈的唯一常驻 daemon**：

- LoopX daemon 调用并持有 LoopX 自己 `data_dir` 对应的 `get_server(data_dir)` handle；nooa/DBOS 由 nooa 侧持有自己的 handle，二者没有跨栈 PG owner；
- 普通 CLI 不在每次调用中启动或停止本栈 PG；
- CLI 连接本栈 daemon 发布的标准 PostgreSQL URI；
- CLI 可按需拉起本栈 daemon，但该动作是启动本栈常驻 owner，不是临时持有数据库；
- 同一**规范化** `data_dir` 对应一个本栈 embedded cluster；
- daemon 停止时才释放本栈 PG server。

默认拓扑与边界：

```text
LoopX command/runtime ──> LoopX daemon ──> LoopX pgembed PG ──> LoopX data root
nooa agent/DBOS runtime ──> nooa/DBOS owner ──> nooa pgembed PG ──> nooa data root

LoopX PG  X  nooa PG
```

两套栈之间禁止 cross-system SQL、直接读取对方私有表、共享 migration、跨系统事务或把一套数据库当作另一套的恢复后端。一个紧凑的可选 co-location profile 可以在同一主机上运行两个 pgembed 实例，但仍必须使用两个不同的规范化 `pgdata` 根、两个 `PostgresServer` handle、独立的端口或 socket URI、独立的角色/数据库、独立的 migration head，以及独立的清理与升级 gate。

启动与 lifetime ownership 协议：

1. 统一解析并规范化 `data_dir`，所有锁与 readiness metadata 都以该规范化根为命名空间；
2. CLI 尝试连接已发布且匹配当前 owner generation 的 endpoint；
3. 连接失败时取得短期 data-root bootstrap `fcntl` 锁，并检查**独立的 per-normalized-data-root owner lock**；
4. 如果 lifetime owner lock 仍由现有 daemon 持有，即使 endpoint 暂时不可达，也不得启动第二个 daemon；应等待/retry 或返回明确 unavailable，并保留现有 ownership；
5. 只有确认 lifetime owner lock 可取得时才能清理 stale readiness。候选 daemon 在 bootstrap lock 仍被父/启动方持有时取得 lifetime owner lock，启动方确认 ownership 已转移后才释放 bootstrap lock；
6. daemon 在整个存活期持有 lifetime owner lock，然后启动 PG、健康检查并迁移 schema；
7. 迁移完成后以 owner generation 原子发布 endpoint/readiness；CLI 只连接与当前 owner generation 一致的 ready endpoint；
8. daemon 正常停止时先撤销 readiness、停止/释放本栈 PG，再释放 lifetime owner lock。崩溃后的接管也必须先成功取得该锁，不能只凭 endpoint 失败或 metadata 超时推断 owner 已消失。

pgembed 的 DiskList 只用于本栈进程发现、清理和 crash reuse，不承担 singleton、schema readiness 或业务 fencing 正确性。pgembed 的**全局 init inter-process lock 只序列化库内部初始化，不是 daemon lifetime singleton**；LoopX 的 per-root lifetime owner lock 与它是两个不同机制。实际语义必须按库实现处理：`get_server` 按规范化 `pgdata` 复用 handle；不同 `pgdata` 的实例仍会共享 pgembed 的全局 init lock；Unix-socket 或平台 TCP 都是合法 endpoint，socket 路径过长时可能使用基于 `pgdata` 的哈希路径；PG major mismatch 是拒绝修改数据根的硬边界。`cleanup_mode` 必须显式配置并先以集成测试确认当前库版本的准确语义：正常持久化 data root 只能选择经验证的非破坏模式（`None` 或 `stop` 中符合 daemon lifecycle 的模式）；`delete` 只允许显式标记的 ephemeral/test root，或独立、二次确认且有备份/路径校验的 destructive reset 命令，绝不能用于正常 shutdown、upgrade 或 crash recovery。scheduler 和 outbox worker 各自使用独立数据库连接，禁止跨线程共享 psycopg connection。

Schema 采用：

- **Alembic**：管理 schema、索引、约束、触发器和后续演进；
- **session advisory lock**：防止多个 daemon/维护进程并发升级；
- **startup readiness check**：只有 Alembic revision 到达 binary 要求的 head 后才启动 worker 和接受写入。

不采用散落的 startup 幂等 DDL。迁移失败时不回退到文件写入；daemon 不 ready，CLI 返回 `schema_migration_failed` 或 `database_unavailable`。

运行时使用 psycopg 3 的显式短事务；Alembic 可依赖 SQLAlchemy 作为迁移工具，但不引入 ORM 或通用 repository 层。

---

#### F. MVP：第一阶段固定为 18 张业务表

原设计中的“17/18 张”歧义裁决为**18 张**。纳入 monitor、lease、outbox 和 scheduler，是因为它们分别对应现有 heartbeat/monitor 行为、无 fencing 的并发风险、跨介质可靠导出和第一阶段可运行性。

TigerFS 不进入 MVP：

- 会增加 companion 进程和挂载生命周期；
- 可写 mount 可能绕过 command envelope；
- 当前 Markdown/JSONL exporter 已足够提供兼容；
- `.build/` workspace 文件兼容不是控制面 ledger 迁移的前置条件。

---

#### G. 跨系统层 ownership 与稳定观察契约

**层 ownership 是分开的：**

| 层 | 唯一职责 | 不拥有的职责 |
|---|---|---|
| LoopX | control / authority / settlement：goal、todo、quota、lease、command receipt、迁移权威和最终结算 | nooa 的 agent 语义、DBOS workflow/step durability，或 nooa 私有证据 |
| nooa | agent semantics / evidence：agent 分支、工作流语义、证据指针和 nooa 侧观察 | LoopX 的 authority、quota/settlement 或 LoopX 私有表 |
| DBOS | workflow / step durability and recovery：workflow/step 接受、执行、恢复和 DBOS 自己的完成语义 | LoopX settlement；DBOS completion **不是** LoopX settlement |
| pgembed | 每个栈自己的本地 PostgreSQL substrate 与进程生命周期 | 跨栈 ownership、业务 authority、schema 共享或跨系统事务 |

稳定集成面不是 SQL，而是一个版本化、typed、public-safe 的 observation/envelope contract。建议首版命名为 `loopx.nooa.observation.v1`，至少包含：

```text
contract_version
producer:
  producer_id / producer_version / runtime_version
source:
  source_stream_id / source_cursor
identity:
  event_id / occurred_at / payload_hash
correlation:
  loopx_goal_id / loopx_todo_id / loopx_turn_id
  turn_instance / turn_key / effect_id
  nooa_workflow_id / nooa_branch_id / nooa_lineage_id / nooa_commit_seq
  business_idempotency_scope / business_idempotency_key  # nullable correlation only
observation_kind / status / authority_domain
public_payload / evidence_pointers
```

`producer_id` 是稳定、显式分配的生产者 namespace；`source_stream_id` 标识该 producer 内具有独立顺序/checkpoint 语义的稳定 stream，不能从文件路径、数据库表名或临时进程 ID 推导。`event_id` 全局唯一；`(producer_id, source_stream_id, source_cursor)` 也唯一。`business_idempotency_scope`/`business_idempotency_key` 只关联产生观察的 LoopX/nooa 业务 command，不参与 observation event 去重，不能替代 event/source identity。

字段语义相关但 authority 独立：LoopX 的 receipt、revision、lease fencing 和 settlement 只由 LoopX 判定；nooa/DBOS 的 workflow/step 状态只由 nooa/DBOS 判定。观察 envelope 不依赖 SQL schema，也不允许通过私有表形状推断协议。

**不可变 identity 与冲突规则：**首次摄入同时绑定 `event_id`、`(producer_id, source_stream_id, source_cursor)` 和 `payload_hash`。重投时只要 `event_id` 或 source tuple 任一已存在，两种 identity 都必须解析到**同一条不可变 observation**且 hash 相同，才可安全 no-op；若两种 identity 指向不同记录、另一 identity 不匹配，或 hash 不同，必须返回 typed `observation_payload_conflict`。冲突不得覆盖既有记录，也不得推进该 stream 的 checkpoint。

`payload_hash` 使用固定 canonicalization profile（随 `contract_version` 版本化），覆盖完整 serialized public envelope：contract/producer/source/identity（排除 `payload_hash` 字段自身）/correlation/observation kind/status/authority domain/public payload/typed evidence pointers；采用明确字符编码、字段顺序、数字与时间规范化后计算 SHA-256。它只用于 equality/corruption detection，不证明 producer authenticity、调用者权限或 evidence 访问授权。

**重投、恢复与 attempt 必须区分：**

- same-envelope redelivery：同一已序列化 envelope 因 ack 丢失等原因重投，必须保持 `event_id`、producer/source tuple、cursor、hash 以及所有 correlation identity 不变；
- transport reconnect：只重建连接，从已确认 checkpoint 后续传；不得重发为新 identity，也不得跳过未确认 gap/conflict；
- DBOS workflow recovery：保持原 `turn_instance`、`turn_key`、`effect_id` 和 `nooa_workflow_id`（即同一 business attempt 的已定义 correlation tuple）稳定，但每个新发生的 recovery/step 状态变化发布**新的 observation**，具有新的 `event_id` 和后续 source cursor；它不是旧 envelope redelivery；
- new business attempt：生成新的 `turn_instance`、`turn_key`、`effect_id` 和 nooa `workflow_id`，其 observations 也使用新的 event identity。

每个 source stream 必须采用一种冻结的 checkpoint 协议。首选单调连续 cursor：collector 仅在下一期望 cursor 已通过双 identity、hash 和 public-safety 校验并持久化后推进 high-water mark；未来 cursor 可暂存为 pending，但不得跨 gap/conflict 前移。若 producer 只能提供 opaque cursor，则 O1 必须同时冻结 producer-issued predecessor/commit token 与 compare-and-advance 规则，提供等价的 no-skip 保证。LoopX 可以因旧 lease、旧 receipt 或重复 envelope 而安全 no-op/reject；DBOS workflow recovery 只能恢复 DBOS 自己的步骤，不会自动完成 LoopX settlement。

**统一 timeline 只做相关，不做混淆：**

```text
LoopX: intent → dispatch → validation → settlement
                     │ correlation fields
nooa/DBOS: accepted → started → step → recovery → succeeded/failed
```

两条线可以由同一个 `effect_id`、turn identity 和 lineage 关联，但 `succeeded`/`completed` 不等于 LoopX `settled`；缺少 LoopX validation/authority/settlement receipt 的 nooa/DBOS 成功只能是观察结果。

public-safe boundary：observation 只携带紧凑 typed metadata 和 allowlisted typed evidence pointers。producer 必须在序列化或写入 staging **之前**执行 fail-closed schema/public-safety validation；collector 必须在 persistence 和 cursor/checkpoint 推进**之前**独立重验。任一侧失败都拒绝 envelope 且不推进 checkpoint。禁止 raw prompts、raw trajectories、raw logs、verifier tails、credentials、credential-bearing/query tokens、local absolute paths、private planning context，以及任何依赖内部组织语境才能解释的材料。evidence pointer 只能使用契约 allowlist 中的 type、稳定 public-safe identifier、必要 hash/classification 和非敏感 locator；禁止任意 URI/query string 或本地路径。复用 LoopX 既有 public/private boundary 校验思路。`payload_hash` 只用于 equality/corruption detection，不是 authenticity、authorization 或 evidence access grant。

#### H. DuckDB observation layer（设计选择，不是控制权威）

DuckDB 可作为本地 analytical read model / observation entry point，但**不是 control-plane authority、settlement store、权限边界或跨栈事务协调器**。受支持的 live topology 是：collector 是**唯一打开 live read/write DuckDB 文件的进程**，live 文件及其目录对其他进程不可读写。分析要么在 collector 进程内执行，要么通过受控的 owner-local query API 请求 collector 执行；需要外部 reader/analysis agent 时，它们只消费 collector 原子发布的 immutable DuckDB snapshot 或 Parquet dataset，绝不同时打开 live writer 文件。

collector 持久化每个 `(producer_id, source_stream_id)` 的 checkpoint，按双 identity 与 canonical `payload_hash` 做幂等 batch ingestion，并遵守 no-gap/no-conflict advancement。live DuckDB 文件必须可从已验证 envelope 与 Parquet/JSONL staging 重建；published snapshot/dataset 必须具有 generation/manifest/hash，发布后不可原地修改，而不是不可替代的事实源。

Parquet/JSONL staging 是推荐的解耦边界：上游 producer 先生成通过 producer-side validation 的 public-safe 批次，collector 重验后批量导入并 compare-and-advance checkpoint。DuckDB 官方文档明确支持嵌入式 client 连接、进程内并发以及一个进程读写或多个进程只读的文件访问模式、Parquet 读写和 JSON 数据读写；这些是可验证事实。本文选择更严格的 collector-private live file、in-process/controlled API analysis、immutable snapshot/dataset publication、strict permissions、rebuildable file 和 checkpoint ledger。参考：[connectivity overview](https://duckdb.org/docs/stable/connect/overview)、[architecture/internals overview](https://duckdb.org/docs/stable/internals/overview)、[concurrency](https://duckdb.org/docs/stable/connect/concurrency)、[PostgreSQL extension](https://duckdb.org/docs/stable/core_extensions/postgres)、[ATTACH](https://duckdb.org/docs/stable/sql/statements/attach)、[Parquet](https://duckdb.org/docs/stable/data/parquet/overview)、[JSON](https://duckdb.org/docs/stable/data/json/overview)。

不要把 PostgreSQL `ATTACH` 当作 primary ingestion path。DuckDB 的 PostgreSQL extension 在技术上支持访问运行中的 PostgreSQL；本架构支持的 `ATTACH`/federation 仅是 owner-authorized、**read-only** 的 ad-hoc/debug 选项，而且只能读取明确批准的 public-safe 数据。它不得写任一 PG 栈、读取对方私表或形成 cross-system SQL，不得向 collector live model 供数，也不得绕过 producer/collector validation 与 immutable publication boundary；使用时仍须显式处理 transaction scope、pushdown/性能差异、凭据暴露和 authority 边界。

DuckDB 是嵌入式数据库，而不是本设计中的 PostgreSQL 式共享 server auth/roles 边界；因此 live 文件必须保持 collector-private，query API 与 published snapshots/datasets 也只能面向 owner-local、受控主体，不能暴露为共享 multi-tenant service，也不能把 DuckDB 当成 permission boundary。访问控制属于宿主操作系统、collector API、发布目录和文件权限，而不是 DuckDB authority。官方安全说明见 [Securing DuckDB overview](https://duckdb.org/docs/stable/operations_manual/securing_duckdb/overview) 与 [Securing DuckDB when embedding](https://duckdb.org/docs/stable/operations_manual/securing_duckdb/embedding_duckdb)。

---

### 3.3 修正后的 18 表清单

技术表 `alembic_version` 不计入以下业务表数量。

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

第一阶段延后的 13 张表为：

```text
actors
goal_memberships
capability_definitions
goal_capability_bindings
event_private_payloads
run_steps
tool_calls
artifacts
todo_edges
handoffs
human_rewards
domain_records
memory_entries
```

第一阶段 actor 仍使用现有文本 ID，由既有 authority validator 校验；不引入数据库身份体系、RLS 或多租户隔离。

---

### 3.4 `events` 表的统一约束设计

#### 3.4.1 逻辑字段分组

```text
identity:
  sequence_id bigint identity
  event_id uuid

routing:
  project_id text
  goal_id text nullable
  stream_key text
  append_sequence bigint

semantic:
  event_class text
  event_type text
  projection_kind text
  aggregate_type text nullable
  aggregate_id text nullable
  aggregate_version bigint nullable

causality:
  command_id uuid nullable
  event_ordinal integer nullable
  correlation_id uuid nullable
  causation_id uuid nullable
  actor_id text
  run_id text nullable

dedupe:
  dedupe_scope text nullable
  dedupe_key text nullable

payload/integrity:
  public_payload jsonb
  payload_hash bytea
  occurred_at timestamptz
  recorded_at timestamptz

migration provenance:
  origin_kind text
  source_stream_key text nullable
  source_position bigint nullable
  source_hash bytea nullable
```

新生成的 command/event/outbox ID 使用 UUID；既有 goal、todo、run、actor 等业务 ID 保留为 text，避免迁移期间重映射。`dedupe_scope`/`dedupe_key` 仅用于 LoopX 账本内部 observation event 的命名空间去重，区别于跨系统 `loopx.nooa.observation.v1` 的 `event_id`/`source_cursor`/`payload_hash` 摄入冲突规则。

#### 3.4.2 必须存在的约束

| 约束对象 | 规则 |
|---|---|
| 事件身份 | `PRIMARY KEY(sequence_id)`；`UNIQUE(event_id)` |
| 事件类别 | `event_class ∈ {state, rollout, supervisor}` |
| 投影类别 | `projection_kind ∈ {none, baseline, transition}` |
| 投影事件条件 | `baseline/transition` 只能属于 `state`，且必须有 `aggregate_type`、`aggregate_id`、`aggregate_version >= 1` |
| 非投影事件条件 | `projection_kind = none` 时 `aggregate_version` 必须为空；可保留 aggregate 引用 |
| stream 顺序 | `UNIQUE(stream_key, append_sequence)` |
| aggregate 版本 | 对 `projection_kind IN (baseline, transition)` 建 `UNIQUE(project_id, aggregate_type, aggregate_id, aggregate_version)` |
| command 事件 | `command_id` 非空时 `event_ordinal` 必须非空且非负；`UNIQUE(command_id, event_ordinal)` |
| 观察事件去重 | 提供 `dedupe_scope`/`dedupe_key` 时，按命名空间建立唯一约束 |
| 历史导入去重 | 提供来源定位时，`UNIQUE(source_stream_key, source_position)`；相同位置不同 hash 是迁移冲突 |
| 内容完整性 | `payload_hash` 是规范化 `public_payload` 的 SHA-256；读取时可校验 |
| 不可变性 | runtime 角色只能 INSERT/SELECT；禁止 UPDATE/DELETE 事件行；维护操作只能由受控 migration 角色执行 |

事件表不建立以下约束：

```text
UNIQUE(goal_id, idempotency_key)
```

原因是一个 command 可以合法地产生多条事件。幂等归属 `command_receipts`：

```text
UNIQUE(scope_kind, scope_id, idempotency_key)
```

其中 `scope_kind` 至少支持 `project` 和 `goal`，以覆盖尚无 goal ID 的命令；相同 key 和相同 request hash 返回首次结果，相同 key 但 hash 不同返回 `idempotency_conflict`。

#### 3.4.3 三种序列的独立语义

1. **`sequence_id`**  
   PG 内部定位用的 identity。事务回滚可能产生空洞，并发提交顺序不一定等于分配顺序；不得作为唯一的可靠消费 cursor。

2. **`append_sequence`**  
   保留 JSONL 原有 stream 内序列。导入时原样复制，保留 gap，不重新编号。`stream_key` 必须准确表达原文件的实际序列作用域，不能简单用 `event_class` 代替。

   PG-native append 时，对 `stream_key` 获取 transaction advisory lock，再分配下一值；一个命令涉及多个 stream 时按稳定字典序获取锁。初期不增加 `event_stream_heads` 表，只有实测出现热点后再优化。

3. **`aggregate_version`**  
   只服务 projection 型 state event。写入流程必须是：

   ```text
   锁定 projection
     → 校验 expected_revision
     → 计算 current_revision + 1
     → append state event
     → 更新 projection revision/latest event
     → 同一事务提交
   ```

   唯一约束防止版本重复，连续性由行锁和事务流程保证。一个 command 修改多个 aggregate 时，为每个 aggregate 分配独立连续版本，并按稳定 aggregate 顺序加锁。

---

### 3.5 统一 command 与事务边界

新增的窄接口建议固定为：

```text
CommandEnvelope（不可变值对象）
  command_id
  command_type
  project_id / goal_id
  trusted actor context
  expected_revisions
  lease_fencing_token
  goal_version
  idempotency_key
  payload
  correlation_id / causation_id

CommandExecutor.execute(envelope) → CommandResult

ProjectionReader.read_goal_state(goal_id) → CanonicalGoalProjection
```

实例关系：

- CLI、scheduler、provider callback 创建 `CommandEnvelope`；
- `CommandRouter` 根据 goal 的 migration mode 选择 `LegacyCommandExecutor` 或 `PostgresCommandExecutor`；
- Kernel 拥有验证和事务编排；
- Agent 不创建数据库连接，也不能调用底层 store；
- `CommandResult` 至少返回 `committed/rejected`、receipt ID、事件 ID、更新后的 revision 和稳定错误码。

`TRANSACTION_PHASES` 保持名称不变，但边界改为：

```text
host_execute
typed_result
validation
  → 事务外

durable_writeback
quota_spend
scheduler_apply
  → 合并到一个短 PG 事务；
    scheduler_apply 只写 schedule/outbox intent

scheduler_ack
  → outbox handler 成功后的独立幂等确认
```

错误语义：

- 相同幂等 key/hash：返回第一次 receipt；
- 相同 key/不同 hash：`idempotency_conflict`；
- revision/fencing/authority/state-machine 失败：提交 rejected receipt，不写成功状态事件；
- quota 拒绝：不插入 spend、不完成 chargeable transition；
- 数据库或 schema 暂时不可用：不写 receipt，调用方可安全重试；
- export 冲突或 outbox 失败：PG 已提交的业务状态不回滚，保留 outbox 状态并暴露错误；
- host 被取消或 lease 过期：最终写回以 stale token 拒绝，外部已经发生的工具/文件副作用不承诺自动撤销。

---

## 4. File-by-file impact

提供的 file tree 是目录级视图，未列出所有直接写文件的具体模块；因此母计划必须先生成 writer inventory。以下是确定的修改点和新增路径。

| 文件/路径 | 变更 | 依赖与顺序 |
|---|---|---|
| `docs/plans/loopx-on-pgembed-design.md`（背景来源；本 worktree 当前未跟踪） | 若该原始设计文档重新纳入仓库，将“Zleap 已实现 outbox/cron/fingerprint”等不准确表述改为本纪要；固定四阶段迁移、18 表 MVP、自有 scheduler、daemon/Alembic 和 TigerFS 延后 | 不阻塞当前两份 canonical docs；重新纳入时以本纪要为准 |
| `loopx/control_plane/turn_driver/transaction.py` | 保留 `TRANSACTION_PHASES`；将最终 writeback、quota spend、scheduler intent 映射到一个短 PG 事务；ack 改为 outbox ack | 依赖 command kernel、quota store、outbox |
| `loopx/control_plane/runtime/event_store_migration_bridge.py` | 复用并扩展 `dual_read_shadow`、`bounded_canary`、`promotion_candidate`；增加 goal 级 authority、mirror lag、parity gate、fail-closed 终态 | 依赖 command router、import/parity |
| `loopx/control_plane/commands/model.py` | 新增不可变 `CommandEnvelope`、`CommandResult`、稳定 `CommandErrorCode` | 第 2 步 |
| `loopx/control_plane/commands/kernel.py` | 新增 PG command executor；复用现有 authority/transition/validation 逻辑；禁止通用 CRUD | 依赖数据库 stores 和 migrations |
| `loopx/control_plane/commands/router.py` | 按 goal migration mode 选择唯一 executor；canary/primary 禁止自动回落文件 | 依赖 bridge |
| `loopx/control_plane/database/config.py` | 统一 data root、PG URI、启动/轮询/claim timeout 等设置 | daemon、CLI、Alembic 共用 |
| `loopx/control_plane/database/runtime.py` | 封装 LoopX daemon 对本栈 `get_server(data_dir)` 的持有、短期 bootstrap lock、per-normalized-root lifetime owner lock、owner generation、endpoint/readiness、health/start/stop 与非破坏 cleanup policy；不得管理 nooa/DBOS PG | 第 3 步 |
| `loopx/control_plane/database/session.py` | psycopg 短事务、advisory lock、数据库时间和连接生命周期 | 所有数据库 store 共用 |
| `loopx/control_plane/database/alembic/env.py` 及 `versions/0001_*`～`0003_*` | 创建六 schema、18 表、索引、唯一约束和 immutable protections | 第 4 步；业务数据导入不得放入 Alembic |
| `loopx/control_plane/database/ledger.py` | receipts、事件 append、stream sequence、aggregate version、source import 去重、outbox intent | 第 5 步 |
| `loopx/control_plane/database/state.py` | goal/todo/gate/monitor/lease projection 的读写、revision、rebuild | 第 5～8 步 |
| `loopx/control_plane/database/runtime_store.py` | execution snapshot、fingerprint、run summary、evidence | 第 9 步 |
| `loopx/control_plane/database/quota_store.py` | 将现有 classification 映射为唯一 `quota_spends`，替换 JSONL Python 重扫 | 第 9 步 |
| `loopx/control_plane/database/legacy_import.py` | 导入三类 JSONL、Markdown baseline、runs/quota；支持 source hash 幂等和冲突检测 | 第 6 步 |
| `loopx/control_plane/database/legacy_export.py` | PG projection → `ACTIVE_GOAL_STATE.md`；PG events → 三类兼容 JSONL；整体渲染、幂等和人工编辑冲突检测 | 第 10 步 |
| `loopx/control_plane/database/parity.py` | canonical projection hash、事件高水位、quota parity、projection rebuild parity | 第 7、13 步 |
| `loopx/control_plane/todos/**`、`goals/**`、`quota/**` | 所有状态/config/quota 写入口改为构造 command；删除内部 Markdown 行级直写和独立事件追加 | 第 2 步先收敛，后接 PG |
| `loopx/control_plane/heartbeat/**`、`scheduler/**` | heartbeat/monitor 注册为 schedules；实现 schedule claim、schedule_runs、outbox dispatch | 第 11 步 |
| `loopx/control_plane/status/**` | 按 migration mode 读权威 projection；展示 mirror lag、projection mismatch、dead-letter、schema readiness | 第 7 步后 |
| `loopx/cli_commands/**` | 增加 `db start/status/stop/migrate`、storage shadow/canary/promote、outbox status/retry；写命令统一走 router | 第 3、12～14 步 |
| `pyproject.toml` 及实际 lockfile、根级 `alembic.ini` | 增加 pgembed、psycopg 3、Alembic；不增加 ORM、TigerFS 或 pg_cron 运行依赖 | 第 3～4 步 |
| `tests/architecture/**`、`tests/control_plane/runtime/**`、`tests/control_plane/**`、`tests/cli_commands/**` | 增加 direct-writer 禁止、迁移阶段、事件约束、并发、崩溃、outbox、scheduler、quota parity 测试 | 与对应步骤同步 |

**不纳入第一阶段的代码路径**：Dashboard、capability registry、memory/vector、TigerFS 相关实现不作为核心迁移依赖；如果现有 UI 直接写 Markdown，必须改成调用 CLI/command API，但不需要重做展示层。

---

## 5. Risks and migration

### 5.1 关键风险与控制措施

| 风险 | 具体后果 | 强制控制 |
|---|---|---|
| 双权威/分裂写入 | PG、Markdown、JSONL 对同一 goal 得出不同状态 | 按完整 goal 切换；任何时刻只有一个 authority；canary/primary PG 故障时 fail closed |
| 旧事件不可完整重放 | 错误地从不完整 JSONL 生成错误当前状态 | 旧事件标记 audit-only；以 Markdown 快照建立 baseline；baseline 后才承诺 replay |
| 文件与 PG 无跨介质原子事务 | 文件已提交但 PG 未镜像，或 PG 已提交但导出失败 | 异步 mirror/outbox、source hash、semantic parity、重试；不假装跨介质原子 |
| outbox 重复或确认过期 | 重复导出、重复调度、旧 worker 覆盖新状态 | `SKIP LOCKED`、`lock_token`、`locked_until`、handler dedupe key、at-least-once |
| stale turn 写回 | 过期 Agent 覆盖新状态或重复消费 quota | projection revision + lease fencing token；最终写回再次校验 |
| NOTIFY 丢失 | 事件发生但 worker 未被唤醒 | NOTIFY 只作唤醒；定期扫描 outbox/due schedules |
| quota 重算漂移 | 历史 run 规则改变或重复收费 | policy version、insert-only spend、`UNIQUE(run_id)`/receipt key，同一事务提交 |
| daemon/PG 竞态 | transient endpoint failure 时第二 daemon 启动，或 CLI 连到 stale owner | 短期 bootstrap lock + daemon 全生命周期 per-root owner lock + owner generation/readiness；owner lock 仍持有时禁止接管；pgembed init lock 与 DiskList 只作库初始化/辅助发现 |
| destructive cleanup 误用 | 正常 shutdown/upgrade/crash recovery 删除持久化 PG 根 | 持久根只用已验证的非破坏 `cleanup_mode`；`delete` 仅限显式 ephemeral/test root 或独立二次确认的 destructive reset |
| schema 未就绪 | CLI 在半迁移数据库上写入 | Alembic advisory lock；未到 required head 不发布 ready、不启动 worker |
| 旧版本回滚写文件 | 新 PG 状态被旧 binary 静默覆盖 | promotion 后文件只读导出；旧写入口硬拒绝；切换前做逻辑备份 |

### 5.2 迁移硬门槛

#### 进入 `dual_read_shadow`

必须完成：

- 所有直接写 `ACTIVE_GOAL_STATE.md`、三份 JSONL、`runs/index.jsonl` 的调用点已登记；
- 内部状态变更全部经过统一 command seam；
- Markdown parser/renderer、事件序列、run classification 已有 characterization tests；
- PG schema 已由 Alembic 创建并通过基本约束测试。

#### 进入 `bounded_canary`

必须同时满足：

- 目标 goal 已完成幂等 baseline；
- projection 可从 baseline + state transitions 全量 rebuild，结果与在线 projection 相同；
- 该 goal 的全部现有 command type 已有 PG handler；
- legacy/PG semantic projection、事件高水位、quota 结果一致；
- outbox exporter 和 scheduler handler 已具备重试、去重、过期 claim 恢复；
- 没有未解释的 source sequence/hash 冲突；
- 不允许 PG 失败后回落文件写。

#### 进入 `promotion_candidate`

必须同时满足：

- 所有活动 goal 均已完成 baseline/canary；
- 所有现有 run classification、状态命令和 schedule type 均通过 parity；
- required outbox 无 pending 或 dead-letter；
- 无 projection mismatch、mirror gap、人工编辑冲突；
- 七个 `TRANSACTION_PHASES` 边界均有崩溃注入测试；
- 事件账本重建、quota 重算和 status projection 全部通过；
- 已完成 PG 逻辑备份或等价安全备份。

历史上真实存在的 sequence gap 可以保留；硬门槛要求的是**没有未解释的新 gap、重复或 hash 冲突**。

#### 进入 `postgres_primary`

必须完成：

- 暂停切换期间的 goal 写入并 drain 必要 outbox；
- 原子更新 migration mode；
- 禁止旧 writer 和人工 Markdown 摄入路径；
- 所有读路径默认从 PG projection 读取；
- Markdown/JSONL exporter 仍可运行，但只作为兼容输出；
- 旧 binary 若没有只读兼容模式，不得直接回滚上线。

---

## 6. Implementation order

第一阶段范围为第 **1～12 步**，结束点是至少一个完整真实 goal 的 `bounded_canary`。第 13～14 步属于全局 promotion 的第二阶段。观察契约与 DuckDB collector 是**并行 track**：O1 在 LoopX command seam（步骤 2）稳定、且 nooa/DBOS 已确认 workflow/branch/lineage/commit identity 与 recovery 语义后，由双方共同冻结跨系统 envelope；它不以“nooa adapter contract 已先冻结”为前提。O2 使用冻结契约的 fixtures/test producers 建立本地 read model，可与步骤 3～11 的迁移工作并行，但绝不成为 LoopX `bounded_canary` 的前置条件，也不形成第二 authority。生产 nooa adapter、DBOS emission 与 collector 接入属于未来 `labs-OO-Agents` 工作，不在本分支伪装为已实现。

1. **建立 characterization 基线。**  
   固化 `ACTIVE_GOAL_STATE.md`、三类 JSONL、`runs/index.jsonl` 的当前输出；记录三类事件的 `append_sequence` 作用域、起始值、gap 和重复行为；枚举所有直接 writer、run classification 和现有 transaction phase。此步不改变生产行为。

2. **在 legacy backend 上建立统一 command seam。**  
   新增 `CommandEnvelope`、`CommandResult`、错误码和 `CommandRouter`，默认全部路由到 `LegacyCommandExecutor`。将 todos、goals、gates、monitors、leases、run finalization 的写入口统一改为 command；完成后内部直接 Markdown 行级写入必须为零。  
   **验收**：所有旧 command 行为和输出 parity 不变。

3. **落地 LoopX 栈的 pgembed 常驻 daemon。**
    实现 LoopX 自己的规范化 data-root、短期 bootstrap lock、daemon 全生命周期 per-root owner lock、owner generation、endpoint/readiness、health check、显式 start/stop 和多 CLI 并发启动协议。验证 transient endpoint failure 不会越过仍持有的 owner lock 启动第二 daemon，并覆盖 daemon 崩溃、stale readiness、端口变化、PG 子进程残留和 DiskList 行为；nooa/DBOS PG 不在本步骤的 ownership 范围内。为持久化 root 验证并固定非破坏 `cleanup_mode`；`delete` 仅用于显式 ephemeral/test root 或独立确认的 destructive reset。
    **验收**：同一规范化 LoopX data root 只有一个持有 lifetime owner lock 的 LoopX server owner；owner generation/readiness 与该锁一致；持久化 root 的正常 stop/upgrade/recovery 不删除数据；CLI 不再每次调用 `get_server()`。

4. **引入 Alembic 并建立 18 表 schema。**  
   创建六个业务 schema、18 张业务表、索引、唯一约束、事件不可变保护和必要的技术表。启动迁移持 session advisory lock；迁移失败不发布 ready。  
   **验收**：空库、并发启动、重复 upgrade、DB revision 新旧不匹配均有明确结果。

5. **实现 ledger、receipt 和 projection rebuild。** `[原子]`  
   同时落地统一 events、stream append、aggregate version、command receipts、source provenance 和 projection rebuild。任何 PG state command 必须让 `receipt + events + projection` 在一个事务中完成。  
   **验收**：并发 stale revision、相同/冲突幂等键、多 aggregate 锁顺序、事件重放测试通过。

6. **实现 legacy importer 和 baseline。**  
   按文件锁获取一致快照，导入三类 JSONL 和 runs；从 Markdown 当前状态生成 baseline projection/event；导入重复、截断、非法 JSON、sequence gap、source hash 冲突均不得静默跳过。  
   **验收**：同一 snapshot 重跑为 no-op，冲突可定位并阻止 promotion。

7. **启用 `dual_read_shadow`。**  
   文件仍是权威；每次 legacy command 之后异步镜像 PG，周期 tailer 用文件 hash/JSONL 高水位补偿崩溃窗口；比较 canonical projection、事件高水位和 quota decision。  
   **验收**：PG 不可用只增加 mirror lag，不改变 legacy 用户可见结果。

8. **实现 PG state vertical slice 与 fencing。**  
   先迁移一个完整 todo 生命周期（claim、lease、evidence、complete、defer/block），再覆盖 gate、monitor 和其他现有状态命令。使用 revision、lease expiry 和 fencing token 防止 stale write。  
   **验收**：旧 turn、过期 lease、重复 command、取消后的最终写回均 fail closed。

9. **实现 run、snapshot、quota 的原子事务。** `[原子]`  
   run 启动事务创建 `execution_snapshot + run + lease`；host 执行在事务外；最终 validated command 将 durable writeback、run result、唯一 quota spend 和 scheduler intent 一起提交。同步修改 `turn_driver/transaction.py` 的阶段映射。  
   **验收**：全部现有 run classification 与旧 quota 结果一致，重复 finalization 不重复收费。

10. **实现真实 transactional outbox 与兼容 exporter。** `[原子]`  
    实现 pending/processing/delivered/dead-letter、claim token、超时回收、退避、条件 ack、NOTIFY 加轮询；实现 PG projection 到 Markdown 和三类 JSONL 的幂等导出。  
    **验收**：commit 后崩溃、外部导出成功但 ack 失败、重复投递、NOTIFY 丢失均可恢复。

11. **实现 LoopX scheduler。**  
    落地 `schedules`、`schedule_runs`、due claim、deterministic trigger、interval/at、coalesce/skip；将 heartbeat/monitor 接入统一 command 和 run 流。  
    **验收**：重复 occurrence、worker 崩溃、misfire、多个 worker、调度通知丢失均不产生重复业务命令。

12. **进入完整 goal 的 `bounded_canary`。**  
    先使用合成 goal，再选择低风险真实 goal；该 goal 的所有读写、quota、lease、export 和 heartbeat/monitor 均走 PG，文件仅导出。任何 mismatch、required dead-letter、人工文件编辑或 schema/storage failure 都暂停 canary，不回落文件写。  
    **第一阶段到此结束。**

并行观察 track（不改变第 1～12 步编号）：

- **O1. 共同冻结观察 envelope。** 前置是步骤 2 的 LoopX command seam 已稳定，且 nooa/DBOS 项目已确认 workflow/branch/lineage/commit identity 与四类 retry/recovery 语义；随后双方共同冻结 `loopx.nooa.observation.v1`，不要求一个尚未实现的 nooa adapter contract 先行冻结。契约必须包含显式 `producer_id`、稳定 `source_stream_id`、`source_cursor`、全局唯一 `event_id`、双唯一/交叉解析冲突规则、canonical SHA-256 hash coverage、连续 no-skip 或等价 opaque checkpoint 协议、独立 authority，以及 producer/collector 双侧 fail-closed public-safety validation。业务 idempotency 字段只作 command correlation，不作 event dedupe。
- **O2. 用 fixtures 建立本地 collector/read model。** 在 O1 冻结后，以契约 fixtures/test producers 验证摄入，不等待也不实现生产 nooa adapter。collector 是唯一打开 collector-private live read/write DuckDB 文件的进程；分析只在 collector 进程内、经受控 owner-local query API，或针对原子发布的 immutable DuckDB snapshots/Parquet datasets 执行，外部 reader 不得打开 live 文件。collector 持久化每个 `(producer_id, source_stream_id)` checkpoint，按双 identity 与 canonical hash 幂等摄入；same-envelope redelivery 为 no-op，identity/hash conflict 返回 `observation_payload_conflict`，gap/conflict 不推进 checkpoint。该 track 的完成标志是可重建、可断点续传、可重复导入并能生成相关但不混淆的统一 timeline；它不写 LoopX authority、不参与 settlement、不阻塞 `bounded_canary`。
- **O3. 未来跨项目接入。** 在当前 `feat/loopx-on-pgembed` 文档分支只保留契约、fixtures 所需边界和验收条件；生产 nooa adapter、DBOS observation emission 与 collector 接入在 `labs-OO-Agents` 后续 Phase 6 完成，并实现已冻结 contract 后再由双方做 compatibility/readback 验证。不得在本分支添加 nooa-side code。

13. **执行 `promotion_candidate` 验收。**  
    对所有活动 goal 执行全量 rebuild/parity，确认无未解释 mirror gap、projection mismatch、quota 差异或 required outbox dead-letter；切换前暂停写入、drain outbox 并完成备份。

14. **切换 `postgres_primary` 并关闭旧权威路径。**  
    所有生产读写走 PG；Markdown/JSONL 标记为兼容导出；legacy importer 只保留为显式迁移/冲突处理工具；旧 direct writer 硬拒绝。稳定后再单独规划 actors、capability registry、详细 runtime trace、memory/vector 和 TigerFS，不能让这些扩展阻塞核心迁移。