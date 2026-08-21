# RFC：LoopX 控制面 TypeScript 渐进迁移方向 v0

- Status：Draft，首个 bounded cutover 等待维护者评审
- Proposed by：LoopX maintainers
- Date：2026-08-15
- Last revised：2026-08-21
- Scope：LoopX 控制面核心从 Python 到 TypeScript 的增量、replacement-first
  迁移；不长期维护两份语义实现
- Tracking issue：[#3225](https://github.com/huangruiteng/loopx/issues/3225)
- Language note：本中文版与
  [英文版](./typescript-control-plane-migration-v0.md) 为语义镜像；
  两者不一致视为缺陷。

---

## 0. 用一个例子说明决策

迁移期间，Python `loopx` CLI 向 LoopX 托管的 TypeScript runtime 发送一笔
粗粒度 typed transaction。已迁移的 TypeScript 模块拥有规则和已经迁移的
LoopX 内部 effect；Python 只保留 transport 与 legacy callback adapter。同一
PR 会删除被替代的 Python 规则和只验证旧实现的测试。

CLI 自身迁到 TypeScript 后，CLI-only 使用方式会在进程内直接 import 同一份
kernel，Python 到 TypeScript 的桥随之删除。当 App、CLI、scheduler 或多个
host 需要一个共享 writer 时，同一 kernel 可以运行在一个可选的 managed
daemon 内。这是一份 kernel 的两种部署形态，不是每个控制面状态族一个
server。

## 1. 问题

LoopX 已有 TypeScript host 与 dashboard 表面，但权威控制面规则在 Python。
一次性重写风险过高，长期保留双实现则更差：每次修 bug 都要改两份，parity
会从迁移工具变成永久产品能力。

因此，中间迁移节点必须同时满足：

- 每条已迁规则只有一个语义 owner；
- 用户看不到 CLI 分叉，也无需手动管理 daemon；
- 可以迁移真实副作用，而不只迁纯投影；
- 基于 pinned 迁移前基线和独立定义的不变量验证正确性；
- 每次 cutover 都测量 latency、packaging、upgrade、rollback 与 crash recovery；
- 每个 PR 都是完整、可评审的 replacement slice。

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

## 3. 为什么先迁 Effect Program

Effect Program 是已经连接 ordered step、identity、short-circuit failure、replay、
receipt 与 settlement 的底层合同。先迁它，后续 todo、quota、scheduler 和 gate
就能共用一套 typed execution language，而不是各自发明跨语言合同。

这不意味着把所有状态机塞进一个通用 protocol。Domain transition invariant
仍属于 domain owner。只有真实 caller 能切换、且 PR 能删除相应 Python 知识时，
才迁一个状态族。

## 4. 迁移顺序

### Stage 0 — 固定行为与 authority

对选中的 slice 记录：

- 权威 schema 和经过独立 review 的合法/非法 transition；
- pinned-base characterization fixtures；
- 生产 caller 与 side effects；
- latency 与 package/install 基线；
- rollback boundary 与 state compatibility。

### Stage 1 — Effect Program cutover

把 Effect algebra 与 normal-Turn settlement 语义迁到 TypeScript：ordered
program、settlement identity、bind/short-circuit、replay、receipt construction、
next-action selection 和 commit reduction。增加第一个 native internal effect——
atomic Turn-journal checkpoint——证明 runtime 不只拥有纯投影。

Python caller 使用 managed runtime，只保留 DTO conversion 和未迁外部 callback。
Parity 与 invariant coverage 成立后，删除 Python 语义实现及其 implementation-
specific tests。

### Stage 2 — Domain slices

一次迁一个 bounded owner，按重复知识与 runtime 价值选，不按文件大小选。候选
顺序是：

1. todo lifecycle 与 completion fence；
2. quota settlement/spend reducer 与 typed receipt；
3. scheduler/monitor state transition，host mutation 仍保持 delegated；
4. gate、capability resolution 与 status projection；
5. event-store writer 与 multi-client authority。

测试跟随规则一起迁。仓库不会先把整套 Python 测试改写成 TypeScript，因为
没有迁移 owner 的 TS 测试要么间接调用 Python，要么复制实现假设。

### Stage 3 — CLI 与 App 汇合

交付 native TS CLI，并在进程内 import kernel。只保留一个自动选择的 authority
路径：CLI-only 时进程内直接执行；App/scheduler 已拥有 workspace 时连接 managed
daemon。所有生产 caller 不再需要 Python bridge 后，删除 bridge 与协议。

### Stage 4 — 清理分发

通过 npm 与 LoopX release artifact 分发 kernel，删除 Python runtime 依赖，并
决定可选 daemon 使用普通 Node entry point 还是 LoopX 自建 single executable。
不要静默依赖非官方第三方 Node wheel。

## 5. 首个 bounded PR 合同

第一个 PR 是一个有意收敛的完整 vertical replacement：

- TypeScript 完整拥有现有生产 caller 使用的 Effect Program 与 settlement 语义；
- 一个 managed、idle-exiting loopback runtime，transport 与 typed handler
  registry 分离；
- 对已迁 authority input 使用集中式 runtime decoder；首个 slice 不允许
  `as unknown as T` 或 `as never` 断言跨过 RPC 边界；
- TS-owned Turn-journal interpretation 与 atomic checkpoint write；
- Python compatibility facade 切到 TS owner，并删除被替代的 Python rule code
  与 obsolete tests；
- Node readiness 与可行动的 doctor 输出；
- 自动恢复 stale PID 与 abandoned startup lock，提供稳定、public-safe 的启动
  diagnostic code，并让 CLI 与 App 消费同一个 lifecycle health projection，
  不另建第二套健康模型；
- wheel/sdist 包含、clean-environment probe、Windows coverage、crash restart、
  idempotent retry 与 upgrade fingerprint；
- pinned-base characterization、native TS invariant tests、Python caller regressions
  与 end-to-end latency evidence。

它**不**迁完整 CLI，不迁 todo/quota/scheduler domain，不发布 release，也不授权
第二个 PR。完成后停在 owner review gate。

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
invariant 冲突，PR 必须披露，并把行为变更单独批准。

### 性能

Cold startup 与 steady-state 分开测量。第一个 PR 必须报告：

- managed runtime cold-start p50/p95；
- warm typed request p50/p95；
- representative settlement transaction p50/p95；
- 相比 pinned Python baseline 的完整 CLI p50/p95；
- idle 后和 bounded request burst 下的 daemon 内存。

默认验收目标是 warm internal transition p95 低于 2 ms，完整 CLI 不出现物质
回退（p95 超过 5% 或出现无法解释的 25 ms 额外开销）。不达标是 owner review
gate，不能静默放宽 benchmark。

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
- 首个 PR 的正确性、性能、packaging 与 maintainability evidence 未通过 owner
  review 前，不开始下一 slice。

如果 bridge 需要用户手动管理、已迁规则仍有 Python 语义 owner、handler boundary
变得 chatty，或首个 slice 只能靠削弱既有行为才能通过 parity/recovery/performance
门禁，就停止或 replan。
