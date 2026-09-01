# RFC：LoopX 控制面 TypeScript 渐进迁移方向 v0

- Status：Accepted，transaction-payoff 阶段进行中
- Proposed by：LoopX maintainers
- Date：2026-08-15
- Last revised：2026-08-23
- Scope：LoopX 控制面核心从 Python 到 TypeScript 的增量、replacement-first
  迁移；不长期维护两份语义实现
- Tracking issue：[#3225](https://github.com/huangruiteng/loopx/issues/3225)
- Language note：本中文版与
  [英文版](./typescript-control-plane-migration-v0.md) 为语义镜像；
  两者不一致视为缺陷。

---

## 0. 用一个例子说明决策

迁移期间，Python `loopx` CLI 向 LoopX 托管的 TypeScript runtime 发送一笔
粗粒度 typed transaction。例如，Turn settlement 先由 TypeScript 验证 journal，
并授权仍由 Python 承载的 provider；Python checkpoint 这些外部结果后，再由
TypeScript 完成最终 reduction 并返回 typed result。没有待执行 provider 的 replay
只需一次 reduction。Python 只把结果投影为旧 CLI shape，不再串行调用一组
TypeScript leaf helper，也不保留平行的 enum 和 reducer。

同一 PR 必须删除被它替代的 Python 语义路径。仅新增 TypeScript module 不等于取得
迁移进展；真正的兑现是语义 owner 更少、跨 runtime round trip 更少，并且 facade
有可信的删除条件。

CLI 自身迁到 TypeScript 后，CLI-only 使用方式会在进程内直接 import 同一份
kernel，Python 到 TypeScript 的桥随之删除。当 App、CLI、scheduler 或多个
host 需要一个共享 writer 时，同一 kernel 可以运行在一个可选的 managed
daemon 内。这是一份 kernel 的两种部署形态，不是每个控制面状态族一个
server。

## 1. 问题

LoopX 已有 TypeScript host 与 dashboard 表面。Effect Program、Turn-journal effect、
若干 Todo/quota decision 和 scheduler state 已有 TypeScript owner，但大量 CLI
composition 与兼容表面仍在 Python。一次性重写风险过高；然而继续逐个翻译 leaf
helper 会留下 chatty bridge 和重复 DTO 知识：代码位置变了，产品并没有简化。

因此，中间迁移节点必须同时满足：

- 每条已迁规则只有一个语义 owner；
- 用户看不到 CLI 分叉，也无需手动管理 daemon；
- 可以迁移真实副作用，而不只迁纯投影；
- 基于 pinned 迁移前基线和独立定义的不变量验证正确性；
- 每次 cutover 都测量 latency、packaging、upgrade、rollback 与 crash recovery；
- 每个 PR 都是完整、可评审的 replacement slice；
- 迁移经济性必须改善：旧语义代码和临时 scaffolding 的退出速度要快于 bridge
  代码的累积速度。

## 2. 架构决策

### 2.1 一份 TypeScript kernel

`@loopx/control-plane` 是目标语义 kernel。Domain module 拥有 typed state、
解释、transition rule 和属于这些规则的内部 effect。Transport shell 不能成为
第二个业务 owner。

```text
迁移期 Python CLI ─────────┐
LoopX App / scheduler ─────┼─> 一个 typed runtime boundary ─> TS kernel
未来 TS CLI ───────────────┘
```

边界传递“结算这个 Turn”“提交这个 journal”这类粗粒度、版本化请求，而不是
频繁的属性 getter。Runtime 只有一个静态 typed handler registry；新增 domain
handler 不会新增 server。

### 2.2 两种部署形态，一份实现

| 产品拓扑 | 执行形态 |
| --- | --- |
| TS CLI cutover 后的 CLI-only | CLI 进程内 import 并执行 TS kernel；没有 daemon |
| 仅 App | App runtime 内嵌同一 kernel |
| App + CLI + scheduler，或多个并发 client | 一个 managed local authority daemon；client 连接当前 writer |
| Python 仍是 CLI 的迁移期 | 一个 idle-exiting loopback runtime 把 Python 桥接到已迁 TS kernel |

如果 authority daemon 已拥有某个 registry/workspace，CLI 必须连接它，而不能
绕过它再打开第二个直接 writer。Runtime discovery 与启动全自动；用户无需配置
端口或守护进程。

### 2.3 TypeScript 拥有已迁 effect

目标不是“TypeScript 决策、Python 永远执行”。TypeScript 可以拥有 atomic
state checkpoint、event append、receipt commit、幂等 reducer write 等 LoopX
内部 effect。每个 effect 都有 typed request、稳定 idempotency identity、typed
receipt 与 retry policy。

异步执行不会削弱 settlement ordering：只有被 `await` 的 durability boundary
成功后，才能发出 effect receipt。但异步允许请求并发，因此拥有已迁写入 authority
的一方也必须拥有按 key 串行化或 compare-and-swap 合同。Caller-side lock 只能作为
明确的迁移期 guard；native TypeScript caller 在 cutover 后不得绕过这个 invariant。
Retry identity 必须绑定具体 operation：当一个 Turn effect 连续 checkpoint 多个
journal 状态时，仅凭宽粒度 Turn effect id 不能证明两次写入 payload 是同一 operation。

外部 authority 仍是显式 adapter：model call、human gate、host scheduler、
credential 和第三方 mutation 不会藏到一个万能 executor 后面。它们的 receipt
回到 Effect Program 完成 settlement。

### 2.4 替换，而不是生产双跑

Characterization 可以离线让新旧实现运行同一份 pinned corpus。生产环境不保留
两个 rule engine，也不 dual-write semantic state。一个 slice 通过门禁后，caller
翻到 TypeScript，并删除被替代的 Python 规则。只有真实 public import、持久化
schema 或未迁 callback 需要时，才保留窄 compatibility facade。

### 2.5 在每个信任边界只验证一次

TypeScript 类型在运行时会被擦除。因此 network/RPC payload、解析后的 JSON、
持久化状态、extension 输入与 adapter response 都必须以 `unknown` 进入系统；
静态类型标注或 `as T` 断言不能证明这些字节满足合同。每个已迁 domain 都必须先
通过 typed decoder 或显式的版本化 schema parser 解码，再交给 domain handler
或 Effect interpreter 消费。

解码成功后，TypeScript kernel 拥有这个 typed value，domain 内部可以依赖编译器，
而不必在每层重复临时字段检查。Framing、authentication、size limit 等 transport
检查与 schema validation、semantic invariant 分层负责。未经检查的
`JSON.parse(...) as T` 不能建立控制面 authority。

`as unknown as T` 只允许作为具名迁移缝：cutover PR 必须明确其调用点、上游
validator、负向边界覆盖和移除 owner。只要 public、持久化、RPC 或 extension
输入仍通过未经验证的断言进入已迁 domain 的 semantic core，该 domain 就不能
通过 promotion gate。TypeScript 补充运行时验证，而不是替代它。

## 3. 当前基线与阶段转换

Effect Program 先迁，是因为它连接 ordered step、identity、short-circuit failure、
replay、receipt 与 settlement。这个架构选择已经落地，不再是假设。

### 3.1 已交付基线

| 切片 | 已交付的 TypeScript 权威能力 | 剩余迁移债务 |
| --- | --- | --- |
| Effect runtime 与 Turn journal（[#3416](https://github.com/huangruiteng/loopx/pull/3416)） | Effect algebra、settlement rule、runtime lifecycle、typed Turn-journal interpretation 与 durable checkpoint effect | Python settlement facade 仍暴露细粒度调用，并重复 DTO/enum shape |
| Todo、quota 与 scheduler 证明切片（[#3431](https://github.com/huangruiteng/loopx/pull/3431)–[#3434](https://github.com/huangruiteng/loopx/pull/3434)） | Completion fence/state、workspace causality 与 scheduler transition 各有一个 TS rule owner | 切口大多仍是 leaf-shaped；Python 继续组合多个产品 transaction |
| Scheduler durable state（[#3440](https://github.com/huangruiteng/loopx/pull/3440)） | State normalization、persistence、replay 与一笔粗粒度 transition 由 TS 拥有 | Python compatibility path 仍承担跨 runtime transport 税 |
| Scheduler heartbeat/state transaction | TypeScript 拥有 ACK 与 host-failure validation、state construction、failure-cache transition、replay/CAS fencing 与 atomic write | Python 只保留 native command transport 与 legacy event projection；external host mutation 仍在 Python |
| Quota spend commit transaction | TypeScript 拥有最终 spend transition 校验、typed event 构造、effect replay/CAS fencing、crash repair，以及 JSON/Markdown/index write set | Python 仍投影 `should-run` 与 settlement readback facts，并在 CLI/index writer 进程内迁移前持有 legacy cross-writer index lock |
| Runtime decoder（[#3443](https://github.com/huangruiteng/loopx/pull/3443)） | 稳定 primitive decoding 进入一个很小的共享模块；domain decoder 仍留在本地 | 没有理由建设更大的 schema framework |
| Transaction 兑现（[#3464](https://github.com/huangruiteng/loopx/pull/3464)、[#3481](https://github.com/huangruiteng/loopx/pull/3481) 与 Todo completion） | Turn settlement、quota delivery routing 与 Todo completion 均只跨一个粗粒度 TS boundary；Todo transaction 拥有 identity、replay fence、validation planning/result reduction、continuation/recovery 与 completion metadata | Python 仍执行显式 external provider，并物化 legacy Markdown/event result；其他 domain 仍需各自的 bounded cutover |

Scheduler facade exit 现已成为一个具体迁移阶段。原生
`heartbeat_commit_cli.ts` 接收 compact scheduler/host facts，并在同一进程内拥有
scoped state read、CAS digest、semantic effect identity、validation、replay 与锁内
写入。managed `scheduler.heartbeat.commit` handler 与 Python semantic bridge 均被删除。
Python quota 代码只保留直接 subprocess transport 与兼容 event projection；host
automation adapter 及其 TOML/SQLite 写入仍有意留在 Python。剩余代码的最终删除条件是
host adapter 与 scheduler CLI/projection 迁移到同一 native transaction boundary。

这些切片已经证明 correctness、packaging、Windows lifecycle、crash recovery、真实
TS-owned write 和可接受的 warm primitive-call latency。它们也暴露了迁移边界：
逐 leaf 翻译会先增加 TypeScript、facade、parity fixture 与 bridge traffic，尚未删除
足够多的 Python composition。

### 3.2 兑现阶段决策

迁移因此进入 **transaction-payoff 阶段**。后续 leaf migration 默认拒绝；只有它
能在同一 PR 或明确的紧邻 bounded follow-up 中直接解锁完整 transaction cutover
与删除时才例外。进展单位改为 operator 可感知的 transaction，而不是 helper、
enum、dataclass 或源文件。

一笔 transaction cutover 必须：

1. 把 validation、state transition、已迁 internal effect 和 result construction
   放到一个 domain-owned TS request/response boundary 后；
2. 删除被替代的 Python rule composition、细粒度 API、重复 enum/dataclass 和
   implementation-specific test；
3. 让 Python 只保留 transport、legacy response projection，以及仍属于外部
   authority 的显式 adapter；
4. 不允许 leaf-level bridge chatter。Effect provider 已迁入 TypeScript，或没有待执行
   provider 的 replay，只使用一次 request/response。真实 provider 仍在 Python 时，
   最多使用两次：一次 fail-closed preflight 授权具名 effect，一次基于已 checkpoint
   outcome 的最终 reduction。Model call、human gate 或第三方 mutation 会开启一笔
   新的、带 receipt 的 transaction，而不是隐式 callback tunnel；
5. 写明 Python facade 与 bridge operation 的精确删除条件。

Domain invariant 仍归各自 bounded owner。“更粗粒度”不等于建立一个万能控制面
command 或 mega-reducer。

## 4. 迁移顺序

### Stage 0 — 固定行为与 authority（已完成；每笔 transaction 重复执行）

每个选中的 transaction 都要记录权威 schema、经独立 review 的合法/非法
transition、生产 caller 与 side effect、matched latency/install baseline，以及
rollback/state-compatibility boundary。Characterization fixture 是临时迁移证据，
不是永久 specification。

### Stage 1 — Effect Program 与 managed runtime 基础（已交付）

TypeScript Effect algebra、settlement 语义、Turn-journal interpretation、durable
checkpoint effect、runtime lifecycle、packaging、upgrade fingerprint 与 boundary
decoder 基础都已进入 `main`。Stage 1 的 settlement facade 清理已完成：Python
细粒度 settlement reader 已移除，coarse readback/projection 留作有界的 Stage 2B 工作。

### Stage 2A — Bounded rule-owner 证明（已交付；不再复制该模式）

Todo completion、quota workspace causality、scheduler transition 与 scheduler
durable state 已证明 Python caller 可以安全切换到唯一 TS semantic owner。它们的
characterization 与 facade layer 是合适的迁移证据，但继续在更多 domain 平铺相同
leaf pattern 会增加总复杂度。

### Stage 2B — 完整 transaction cutover（进行中）

按删除杠杆与 runtime traffic 选切口，而不是按翻译难度选。已经交付的 Turn
settlement、quota delivery routing、Todo completion、scheduler heartbeat、quota
spend commit 与 task-lease acquire cutover 建立了这一模式。后续候选必须明确剩余
transaction 及其删除杠杆；剩余 quota settlement readback 只有在能退出或显著收窄
facade，而不是再增加 leaf handler 时才适合迁移。

每完成一笔 transaction，就用 native TS semantic/invariant test 加一个持久的
end-to-end adapter contract，替换 migration-only characterization worker 与 Python
implementation fixture。只有旧 authority 仍可执行，或 versioned compatibility
window 仍需 differential proof 时才保留 characterization corpus；引入时必须记录
删除触发条件。

当前实现状态：Stage 1、bounded Stage 2A proof 与已交付的 Stage 2B cutover 已就位：

- Turn settlement/commit：TypeScript 拥有 preflight authorization、ordered-prefix
  与 replay validation、provider failure classification、receipt construction、
  terminal closeout joining 和 canonical result。真实 Python provider 使用两次
  coarse reduction；完成态 replay 使用一次。
- Quota delivery routing：TypeScript 拥有 continuity 与 fallback 的选择，以及
  selected Todo 的 settlement boundary。In-flight 路径从两次跨 runtime 调用降到
  一次；空 candidate 的 short circuit 仍为零次。
- Todo completion：TypeScript 在一笔 transaction 中拥有 completion identity、
  terminal replay fence、validation declaration/effect planning、validation receipt
  reduction、continuation/recovery 与 completion metadata。没有声明 validation 的
  Todo（包括 replay）使用一次 reduction；真实 caller-approved validation command
  作为显式 Python provider，位于两次 reduction 之间。取得 mutation lock 后会比较
  source snapshot，确保一份 declaration 的 receipt 不能授权已经变化的 Todo。
  Materialized 与 event-projected 写入消费同一 typed result。
- Scheduler heartbeat/state：TypeScript 拥有 ACK 与 host-failure validation、带
  identity 的 progression、failure-cache retention/counting、replay 与 CAS
  fencing、preview reduction，以及锁内 atomic write。Python 提供 host outcome 与
  compact scheduler facts，再把 typed state 投影成 legacy event shape。剩余 facade
  会在 scheduler CLI 与 host adapter 原生调用这笔 transaction 后退出；在此之前，
  它的 state preflight 仅限于 external-provider boundary。
- Quota spend commit：TypeScript 重新校验 compact before/after transition，构造
  canonical public-safe spend event，以带锁 index CAS fence effect，并把 JSON、
  Markdown、index 与 transaction receipt 作为一笔可修复操作提交。同一 effect retry
  幂等，跨 effect 漂移冲突，prepared transaction 可修复 partial artifact set。
  receipt 绑定 append 前的 index digest 与字节偏移，因此 retry 只会修复属于本事务的
  截断 JSONL 尾行，其他损坏仍然 fail closed。
  Python 只保留 `should-run`/settlement fact projection、一次 coarse transport call 与
  legacy kernel index lock；它不再构造或写入 spend event。
- Task-lease acquire：一笔 native TypeScript transaction 拥有 boundary decode、
  handoff 与 owner/Todo eligibility、同 Todo 与重叠 write scope conflict、
  compare-and-swap、generation 与 idempotency rule、per-goal mutation lock、atomic
  lease persistence，以及 canonical result/receipt。Python 只投影带有前后 source
  digest 的 compact registry、active-state、event-log 与 rollout-log facts，然后执行
  一次 native transaction call。TypeScript 在 lease lock 内、decision 前和 write 紧前各
  重验一次 source。尚未迁移的 Python renew、transfer、release 与 fence writer 会先
  取得同一个 exclusive-create lock，再取得 legacy kernel lock，因此 cutover 期间只有
  一个跨 runtime 串行化点。
  NoKV/shared-goal coordination executor 通过 typed Python adapter 到达同一份纯 acquire
  decision，因此 provider seam 后不会残留第二份 Python acquire rule engine。

Quota-spend cutover 删除了 Python spend-event builder 与三文件 writer。它的 bounded
facade 会在 quota CLI 和剩余 run-index writer 进程内执行 transaction 后退出；在此
之前，它只提供 compact projection facts，并与未迁 writer 共享 legacy Python index
lock。Todo cutover 删除了 Python state-evaluation dataclass、local identity projection、
replay helper，以及这些 implementation leaf 的 public runtime handler。剩余 Python
Todo facade 只拥有 transport、external command execution、source compare-and-swap、
legacy response projection 与实际 Markdown/event write；当 writer 与 CLI 进入 native
TS transaction 后即可退出。剩余细粒度 Turn facade 则在 quota 与 host-adapter
caller 进入各自 coarse transaction 后退出。Task-lease acquire 的 semantic facade、
Python atomic provider、settlement bridge operation 与 legacy CLI result projection
已经删除。Python 只保留 compact source projection、一次 process transport，以及供
仍调用 `acquire_task_lease()` 的 caller 使用的 compatibility import。顶层 LoopX CLI
与 authority-source adapter 进入 Node 后，这层 compatibility surface 即可退出；
renew、transfer、release 与 lease fence 迁到同一 TypeScript owner 后，dual-runtime
lock 也随之退出。Vision checkpointing 属于不同的 refresh/writeback 生命周期阶段，
因此继续作为独立 transaction。

#### Task-lease acquire 迁移经济账

| 字段 | 回执 |
| --- | --- |
| Canonical owner | 迁移前由 Python 拥有 atomic acquire provider，TypeScript 在外层做 settlement reduction。迁移后由 `task_lease_acquire.ts` 拥有完整带锁 transaction 与 canonical result。 |
| 删除的旧语义代码 | 973 行产品代码，包括 Python provider/acquire 组合与 conflict 路径、Python↔TS settlement bridge/reducer 及 handler，以及 legacy CLI settlement projection。 |
| 新增的 bridge 代码 | 约 641 行 gross、有界的 compatibility 产品代码，包括 compact Python authority projection 加一次 managed-runtime request、compatibility import、Python/TypeScript 共享锁协议，以及 typed NoKV/coordination decision adapter。顶层 CLI 进入 Node 后删除本地 projection 与 import；其余 lease writer 与 fence 迁移后删除 dual lock；coordination executor 进入 native runtime 后删除该 adapter。 |
| 跨 runtime 调用 | 公开 acquire 与 replay 路径从两次 request/response reduction 降为一次 native transaction request/response。 |
| 产品代码净增减 | 产品代码 +2,130/−1,122 行，净增 1,008 行。Test 与 fixture 单独计为 +898/−1,081，build configuration 为 +4。 |
| 迁移 scaffolding | 删除 task-lease settlement characterization、fault-matrix、incident-replay 及其 fixture 切片。以 native invariant、crash/retry、direct-CLI、adapter 与 cross-runtime lock 测试取代；不再保留 migration-only worker。 |
| Facade 退出 | 本次删除 semantic facade、atomic provider、settlement operation 与 legacy CLI projection。仅保留 source/transport compatibility 与 cross-runtime serialization，删除条件如上。 |
| 正确性与性能 | 公开 CLI 在 5 个 acquire/replay/failure 场景与旧实现精确匹配；20 个 focused native test、207 个 Node test、4,615 个 Python test（12 个 skip）、crash/retry 与 packaged-wheel smoke 通过。在匹配的 16 样本 full-CLI 测试中，happy-path p95 从 1,593.7 ms 变为 1,167.8 ms，replay p95 从 513.3 ms 变为 445.4 ms；中位数分别为 364.6→425.6 ms 与 343.3→351.9 ms。 |

### Stage 3 — CLI 与 App 汇合

交付 native TS CLI，并在进程内 import kernel。只保留一个自动选择的 authority
路径：CLI-only 时进程内直接执行；App/scheduler 已拥有 workspace 时连接 managed
daemon。所有生产 caller 不再需要 Python bridge 后，删除 bridge 与协议。

### Stage 4 — 清理分发

通过 npm 与 LoopX release artifact 分发 kernel，删除 Python runtime 依赖，并
决定可选 daemon 使用普通 Node entry point 还是 LoopX 自建 single executable。
不要静默依赖非官方第三方 Node wheel。

## 5. 兑现阶段 PR 合同

后续每个迁移 PR 都要在描述与 validation comment 中附一份 **migration economics
receipt**：

| 字段 | 必需证据 |
| --- | --- |
| Canonical owner | Cutover 前后分别由谁拥有；不得存在模糊双 authority |
| 删除的旧语义代码 | 删除的 Python rule、细粒度 API、enum/dataclass 与 implementation-only adapter 的产品 LOC |
| 新增的 bridge 代码 | 仅为 Python↔TS transport 或 compatibility 新增的产品 LOC |
| 跨 runtime 调用 | Happy path 与 recovery path 在变更前后的 request/response 次数；effect 已由 TS 拥有或没有待执行 provider 时目标为一次，否则真实 Python provider 尚存期间最多一次 preflight 加一次最终 reduction |
| 产品代码净增减 | 产品 LOC 的新增减去删除；与 test、fixture、generated file 和 docs 分开报告 |
| 迁移 scaffolding | 新增、保留或删除的 characterization/parity helper，以及具体删除触发条件 |
| Facade 退出 | 本次已删除，或列出精确剩余 caller/compatibility contract 和删除条件 |
| 正确性与性能 | 与变更 transaction 相关的 invariant、负例、matched end-to-end baseline、packaging、crash/retry 与 host coverage |

LOC 以最终 merge-base diff 为准，并把 production code 与 test、fixture、generated
file、docs 分开分类。搬移代码按删除加新增计算；bridge LOC 必须列出那些唯一职责是
跨 runtime transport 或 compatibility 的函数。Round trip 要在一条具名 public
happy path 及其 retry/recovery path 上实测，不能由 handler 数量推断。

只搬动代码、只新增 handler，或扩大 bridge 却不删除 authority 的 PR 不能通过这一
阶段。一笔 cohesive transaction 可以暂时净增代码，但 receipt 必须说明 bridge
为何有界，以及下一次哪项删除会兑现收益；这个例外不能被串成无限 leaf migration。

稳定 primitive decoder 可以复用现有的小型 runtime decoder module。Domain decoder
仍留在各自 bounded context；本 RFC 不授权 generic schema framework。

## 6. 正确性与性能门禁

### 正确性

- 独立定义 algebra properties：identity、适用场景下的 associativity、ordering、
  short-circuit、replay 与 effect-id isolation。
- pinned characterization corpus 输出精确一致。
- malformed state、cross-effect overwrite、partial commit、cancellation、
  permission denial 与 budget rejection 的负例。
- 边界 decoder 必须在 domain dispatch 前拒绝缺失字段、错误类型、不支持的 schema
  版本，以及 oversized 或 malformed payload。Cutover inventory 必须列出仍存在的
  `as unknown as T` 迁移缝并证明其已受保护；promotion 要求移除已迁 domain
  authority 输入上的未经验证断言。
- 被 `await` 的写入只有在其声明的 durability point 成功后才能发出 receipt；同 key
  并发 mutation 必须串行化或使用经过测试的 CAS 合同，retry identity 必须区分同一
  Turn 内连续发生的 checkpoint。
- 进程 crash 与 retry 不得重复已经提交的内部 effect。
- wheel 与 sdist 安装到全新环境后，从打包文件执行 deep semantic probe。

Characterization output 是证据，不是 specification。Pinned 行为若与独立 review 的
invariant 冲突，PR 必须披露，并把行为变更单独批准。旧 authority 删除后，promotion
还要求删除只服务这次实现对比的 characterization machinery；当 fixture 表达 public
或 persisted compatibility contract 时，可以保留为持久 regression test。

### 性能

Cold startup 与 steady-state 分开测量。每笔 transaction cutover 必须报告：

- managed runtime cold-start p50/p95；
- warm typed request p50/p95；
- representative complete transaction p50/p95 与跨 runtime round trip 次数；
- 相比 pinned Python baseline 的完整 CLI p50/p95；
- idle 后和 bounded request burst 下的 daemon 内存。

默认验收目标仍是 warm、non-durable internal transition p95 低于 2 ms，完整 CLI
不出现物质回退（p95 超过 5% 或出现无法解释的 25 ms 额外开销）。Durable
transaction 要和 matched durability baseline 比较，而不是套用 2 ms kernel budget。
不达标，或用更快的 microbenchmark 隐藏 tail regression，都是 owner review gate，
不能静默放宽。

## 7. 安装、升级与回滚

迁移不能要求用户管理服务。Python 过渡版本可以要求 Node.js 22.6 或更新版本，
但 installer 与 `loopx doctor` 必须在正常控制面工作前检测，并给出精确修复方式。
Wheel 与 sdist 携带 TS source 和版本化 schema。

Runtime 因 idle 退出时仍是健康状态：`stopped` 表示下一次控制面请求会自动拉起，
不表示用户需要手工执行 daemon 命令。CLI 与 App 消费同一个 lifecycle projection
（`running`、`stopped` 或 `unavailable`）和稳定 diagnostic code；raw stderr、token、
本地路径和私有 runtime metadata 不进入投影。

Runtime fingerprint 包含每个实际执行的 TS module 与 contract。升级会启动新
fingerprint 的 runtime；旧进程可完成 in-flight work，并在 idle 后退出。Request
携带稳定 effect identity；只有显式幂等的 handler 才允许 transport retry。

Rollback 恢复上一版本 artifact 与 fingerprint。在单独通过 state-schema cutover
前，不把持久化状态改写为 TS-only 格式。

## 8. 非目标与停止条件

- 不永久维护 Python/TS 语义双胞胎。
- 不为每个 domain 建 server，也不建 arbitrary-command 通用 executor。
- 不 big-bang 重写 CLI。
- 不以 dual-write production semantic state 作为迁移策略。
- 不只凭 microbenchmark 声称性能。
- 不因 bridge 已存在就继续平铺迁更多 leaf helper。
- 除非存在具名 public import、persisted wire contract 或未迁 caller，不保留重复的
  Python enum/dataclass。
- 不为已经不存在的实现永久保留 characterization harness。

如果 bridge 需要用户手动管理、已迁规则仍有 Python 语义 owner、handler boundary
变得 chatty、连续两个 PR 增加 bridge/scaffolding 却没有退出 facade，或一笔
transaction 只能靠削弱既有行为才能通过 invariant/recovery/performance 门禁，
就停止或 replan。
