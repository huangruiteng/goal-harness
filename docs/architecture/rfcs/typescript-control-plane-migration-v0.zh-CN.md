# RFC：LoopX 控制面 TypeScript 渐进迁移方向 v0

- Status: Draft，维护者评审中
- Proposed by: LoopX maintainers
- Date: 2026-08-15
- Scope: LoopX 控制面核心从 Python 到 TypeScript 的增量迁移策略；
  契约优先、parity 门禁、逐块替换
- Source baseline: `d1fe05932`
- Tracking issue: [#3225](https://github.com/huangruiteng/loopx/issues/3225)
- Language note: 本中文版与
  [英文版](./typescript-control-plane-migration-v0.md) 为语义镜像；
  两者不一致视为缺陷。

---

## 0. 示例

某个宿主希望在不需要 Python 运行时的情况下内嵌 LoopX 的决策能力。现在
Pi 扩展（`loopx/pi_goal_mode/loopx-goal.ts`）已经通过子进程调用 Python CLI
（`loopx quota should-run --runtime-profile generic_cli`）来完成 quota
决策。扩展本身的 goal loop 用 TypeScript 实现，只有决策内核是 Python。

迁移问题是：这个切分能否不经过一次性重写，逐步长成完整的 TypeScript
控制面核心——Python 和 TypeScript 相互调用、一次迁移一块、用户体验不变。

本 RFC 的结论是：可以，但不是靠进程内互调，而是基于三个已有接缝做
契约优先的 strangler 迁移：事件存储、parity fixture 层、CLI 边界。

## 1. 问题

- 外部项目已经在把 LoopX 内核移植到 TypeScript，最完整的草图是
  [Foreman PR #1](https://github.com/needware/foreman/pull/1)。
- frontstage/dashboard 表面已经是 TypeScript。
- 共享运行时能简化 CLI 分发与宿主集成，包括 npm 包。
- 控制面核心约 34.3 万行 Python，`tests/` 与 `examples/` 下超过 1,200
  个文件。一次性重写风险高、几乎不可评审，并且会把生产行为押在一次
  切换上。
- "Python 和 TypeScript 互相调"如果指进程内直接 import，不现实：
  在 Node 里嵌入 CPython、在 Python 里嵌入 V8 都有 GIL/ABI/打包成本；
  Pyodide/WASM 有启动、单线程、文件系统与进程能力的限制。

因此真正的问题变成：哪条边界能承载"双语言渐进切换 + parity 保证 +
可回滚"？

## 2. 决策

采用契约优先、parity 门禁、逐块迁移：

1. 互调走进程边界 + JSON 契约（stdio JSON-RPC/NDJSON），不做进程内
   import。调用粒度是粗粒度的——一条 CLI 命令、一次投影渲染、一个决策
   请求——所以单次调用延迟可接受。
2. 事件存储是双语言的共同事实面：append-only 事件带版本化 schema
   （`loopx_state_event_v0`），两种语言都从同一事件流构建投影。
3. 读路径与投影先迁（纯函数、无副作用），然后是确定性决策内核
   （quota `should-run`、todo 生命周期迁移、scheduler 状态迁移），用
   parity fixture 与决策回放校验；事件存储与写路径最后迁，走
   dual-read → dual-write → flip 序列，带有限 canary 与已记录的
   rollback 计划。
4. 过渡期内 Python 仍是权威实现。一个块只有在 parity 门禁通过且
   rollback 计划已记录之后才能翻转。

### 2.1 互调方案对比

| 方案 | 结论 | 说明 |
| --- | --- | --- |
| TS 子进程调 Python | ✅ 已在生产 | `pi_goal_mode` 用 `execFile("loopx", ...)`，30s 超时；粗粒度调用最简单、已被验证 |
| Python 子进程调 TS | ✅ 可行 | `node dist/...` + stdin JSON；已迁移的内核被 Python 调用时同构 |
| 长驻 sidecar（Unix socket 上 JSON-RPC） | ⚠️ 后续优化 | 摊薄启动开销，适合热路径；需要生命周期、版本与锁纪律 |
| Pyodide / WASM | ❌ 不适合生产 CLI | 启动秒级、单线程、文件系统/进程受限 |
| Rust 核心 + PyO3/napi-rs 双绑定 | ⚠️ 另一个项目 | 真正的共享核心 + Python/TS 薄绑定（类似 huggingface/tokenizers），但那是 Rust 重写，不是 TS 迁移 |

## 3. 让该方案可行的现有接缝

迁移不是从零赌一个方案，仓库里已有三个接缝：

- `loopx/pi_goal_mode/loopx-goal.ts` 与 `pi-goal-loop-runtime.mjs`：
  生产级 TypeScript 表面，通过进程边界把 quota 决策委托给 Python CLI。
- `loopx/control_plane/testing/quota_should_run_parity.py`：用于新旧 quota
  构建器对比的 compact 稳定表面；是未来所有 parity fixture 的模板。
- `loopx/control_plane/testing/decision_replay.py`：用历史真实输入回放决策
  构建器——即双实现对比的 harness。
- `loopx/control_plane/testing/cli_output_differential.py`：约束 CLI 输出
  契约与增长预算。
- `loopx/event_sourced_state.py`：append-only、schema 版本化的事件状态
  （`loopx_state_event_v0`）。
- `loopx/control_plane/runtime/event_store_migration_bridge.py`：已建模
  dual-read parity、有限 canary 与事件投影晋升的 rollback 记录。

## 4. 迁移阶段

### Phase 0 — 契约冻结

把 #3225 的候选范围固化为类型化 schema 与 parity fixture 清单：
append-only 事件状态与幂等写入；todo 生命周期（claim、lease、status、
revision、完成校验）；gates 与决策范围；quota（`should-run`/spend）与
scheduler/monitor 契约；Turn envelope 与事务语义；handoff 与 review-packet
投影；CLI 与 status/quota JSON parity。本阶段不迁移任何代码。

### Phase 1 — 读路径与投影

迁移 status JSON、todo list projection、handoff review-packet projection 与
frontstage 渲染。这些是纯函数、无副作用。TypeScript 实现每个表面，Python
生成 golden fixture；dual-read 门禁要求 TS 投影与 Python 头一致后才能对外
服务。

### Phase 2 — 确定性决策内核

迁移 `quota should-run`、todo 状态迁移与 scheduler 状态迁移规则。这些是
无 IO 的纯决策，天然适合 parity 验证。`decision_replay` 把历史输入回放给
两个实现；只有逐字段一致才允许翻转。此阶段完成后，Pi 扩展可以去掉对
Python quota 的依赖。

### Phase 3 — 事件存储与写路径

TypeScript 先作为投影读取者（dual-read），再双写并做幂等校验，最后翻转
写路径。每一步都套用 `event_store_migration_bridge` 的 canary 与 rollback
门禁。

### Phase 4 — 分发

发布 npm 包与 pip shim（或二者之一）。TypeScript CLI shim 把未迁移命令
转发给 Python，`loopx` 的用户体验全程不变。

## 5. 互调契约

- 每个表面带版本化 JSON schema（`..._v0`）。
- 请求/响应以 NDJSON 走 stdio；长驻 sidecar 可加 content-length 帧。
- 错误用机器可读信封（code + message），不传原始 traceback。
- 调用方设置超时，沿用现有 `LOOPX_CLI_TIMEOUT_MS` 模式。
- 写入幂等：事件带稳定 id，重复应用是 no-op。
- 边界上不出现凭据、原始日志或私有路径。

## 6. 验证

- 每个表面的 parity fixture：同一输入语料在两个实现上产生完全相同的
  compact JSON 输出。
- 决策回放：历史输入回放两个实现。
- Dual-read 门禁：TS 投影服务流量前必须与 Python 头一致。
- 有限 canary：翻转前在一小组 canary goal 上运行新路径。
- Rollback 记录：翻转由 flag 控制，翻转前记录回滚计划。
- CLI 输出预算继续由 `cli_output_differential` 强制。

## 7. 非目标

- 不做行为变更；过渡期内 Python 仍是权威实现。
- 不做进程内嵌入（Node 内嵌 CPython，或 Python 内嵌 V8）。
- 不以 Pyodide/WASM 作为生产运行时。
- 不做 fork-first 迁移；上游主导、欢迎贡献。
- 不做控制面核心的一次性全量重写。

## 8. 开放问题

- 运行时选择：Node.js、Bun 还是 Deno？
- 打包/分发：npm 包、pip shim，还是两者都要？
- TypeScript 轨道的贡献者归属与评审通道？
- 热路径预算：哪些表面值得引入长驻 sidecar？
- 最终共享核心是否应改为 Rust + Python/TS 薄绑定（单独 RFC）？

## 9. 最小可用实现切片

用 TypeScript 实现 `quota should-run` 的 compact parity 表面，与
`quota_should_run_parity.py` 使用同一 fixture 语料，输出完全一致的 JSON。
可选配一个读路径探针：TypeScript 的 todo list/status 投影渲染与 Python
投影相同的事件 fixtures。这能以接近零的生产风险验证整条管线——契约、
parity fixtures、双实现与进程边界。

## 10. 上线与回滚

每个块都走同一序列：双实现 → parity 门禁 → dual-read（读路径）→ 有限
canary → flag 控制翻转 → 记录回滚计划。任何 parity 不一致都会阻止翻转。
回滚即翻回并保留双实现，直到该块重新通过验证；用户状态不会二次迁移，
也不会留下半迁移状态。
