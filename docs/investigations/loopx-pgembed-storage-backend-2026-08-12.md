# Investigation: LoopX 可选 pgembed 存储后端

## Summary
可行，但不能先做一个笼统的 `storage_backend=file|pgembed`。真正需要拆开的有两条迁移轴：先把普通 todo 的 canonical write 从 Markdown 提升为稳定的 event contract，再把 event store 的物理实现从文件 JSONL 切换到 pgembed。第一阶段应交付 provider-neutral event-store seam、文件默认实现、pgembed read-only shadow/parity 和运维工具；不应立即宣称用户可以把整个 LoopX 后端切到 PostgreSQL。

## Symptoms
- LoopX 当前持久化/状态路径可能直接绑定文件系统语义，尚不清楚是否已有稳定的后端接口。
- pgembed 是嵌入式 PostgreSQL 运行时，不只是一个 Python 存储驱动；它引入进程、端口、数据目录、扩展和生命周期管理。
- 需要区分“替换哪些文件状态”与“把所有 LoopX 状态搬入 PostgreSQL”，避免形成过宽、不可逆的后端抽象。

## Background / Prior Research

### pgembed public/runtime model
- `pgembed.get_server(pgdata, cleanup_mode=..., shared_preload_libraries=...)` returns a process-local singleton handle per resolved PGDATA. The handle starts a real PostgreSQL postmaster and exposes `get_uri()`, `psql()`, `create_extension()`, context-manager cleanup, and explicit cleanup (`pgembed/src/pgembed/postgres_server.py`).
- The wheel contains PostgreSQL binaries and extensions under its package tree; there is no runtime binary download. Bundle metadata is attested against `postgres --version` and `pg_config --version` before startup (`pgembed/src/pgembed/_bundle_metadata.py`, `pgembed/MANIFEST.in`).
- Current release constraints found on 2026-08-12: Python >=3.12; macOS arm64 and Linux x86_64/aarch64 wheels; no supported Windows release path, no Intel macOS, and a relatively new manylinux baseline (`pgembed/pyproject.toml`, `pgembed/.github/workflows/build-and-test.yml`, `pgembed/README.md`).
- pgembed supplies no SQL driver or pool. LoopX would still need psycopg/asyncpg/SQLAlchemy-side connection and transaction management. The returned URI uses a Unix socket on supported Unix platforms; fresh clusters use trust authentication (`pgembed/src/pgembed/utils.py`, `pgembed/src/pgembed/postgres_server.py`).

### Lifecycle, concurrency, and migration constraints
- Server initialization is blocking and includes PGDATA inspection, optional `initdb`, preload configuration, `pg_ctl start`, and readiness waits. Default cleanup stops the postmaster when the final tracked handle exits; persistent always-on use therefore needs an explicit ownership model rather than blindly wrapping every short CLI command in a context manager.
- Thread/process coordination uses a process-local singleton, a host inter-process lock, `.handle_pids.json`, and `atexit`. This supports multiple local clients in normal operation but introduces crash recovery, stale ownership, and daemon/CLI semantics that LoopX must test explicitly.
- PGDATA is tied to the bundled PostgreSQL major. A mismatched major fails before mutation; pgembed does not automatically run `pg_upgrade` or dump/restore. LoopX must own schema migrations and must separately define PostgreSQL major upgrade/rollback procedures (`pgembed/docs/migrations/postgresql-17-to-18.md`).
- pgvector is bundled/attested and can be activated with `CREATE EXTENSION`; VectorChord and other preload extensions add restart/configuration semantics. Vector capability is available but is not required for a first transactional storage backend.

### Packaging, security, and product-boundary implications
- pgembed is Apache-2.0, but its all-in-one distribution includes extensions with heterogeneous licenses; bundled TimescaleDB merits a distribution/legal review if LoopX depends on the full wheel rather than a minimal bundle.
- Default trust authentication is appropriate only for a local/trusted boundary. LoopX must not imply network-service hardening, TLS, or multi-user isolation merely by selecting this backend.
- Running as root can create/use a dedicated system user and adjust permissions. Container/root workflows therefore need explicit tests and operator documentation.
- Preliminary external conclusion: SQL CRUD is not the hard part. The hard parts are defining the correct LoopX persistence seam, preserving file-backend behavior and observability, process ownership across short-lived CLIs and long-lived runtimes, packaging/platform eligibility, schema and PostgreSQL-major migration, and safe fallback/rollback.

Sources inspected: local `pgembed` repository public API, lifecycle, errors, bundle metadata, build workflow, tests, examples, and PostgreSQL 17→18 migration guide; upstream project: https://github.com/Ladybug-Memory/pgembed .

## Investigator Findings
### 1. 结论：首阶段应抽象 state-event store，而不是建立“全局 storage backend”

Context Builder 的方向基本正确，但名称和迁移含义需要收窄：首个 provider-neutral seam 应围绕现有 `AppendOnlyStateEventStore` 的事件追加/回放语义建立，而不应把 LoopX 的全部文件状态归入一个全局 `storage` 接口。

- 当前 `AppendOnlyStateEventStore` 是具体文件实现，不是 Protocol、factory 或依赖注入点。`load()` 读取并规范化/去重整个 JSONL；`append()` 在独占文件锁内重读日志、分配单调递增的 `append_sequence`、检查同一 `event_id` 的幂等或冲突，然后追加一行；`append_many()` 只是逐项调用 `append()`，并非一个原子事务（`loopx/event_sourced_state.py:542-585`）。文件追加路径也没有显式的数据文件 `flush/fsync`，因此不能把现状描述成已具备数据库级 durability。
- 生产代码直接构造该具体类的调用点包括 todo event-only writeback（`loopx/control_plane/todos/event_writeback.py:336`）、active-state 事件投影（`loopx/control_plane/goals/active_state_event_projection.py:68`）、supervisor injection（`loopx/control_plane/agents/supervisor_inject.py:72`）以及 supervisor event paths（`loopx/control_plane/agents/supervisor_events.py:273,312,433`）。这些直接构造点说明需要 resolver/factory，但没有证明存在全局存储抽象。
- 未发现生产配置中的全局 storage backend selector。事件日志位置仅从 goal row 的 `state_event_log`、`state_events_file`、`event_log` 等键或 state file 同目录的 `events.jsonl` 推导（`loopx/control_plane/goals/active_state_event_projection.py:22-44`）。

因此，推荐的 capability owner 是现有 state-event/control-plane outcome，而不是新增一个按交付机制命名的通用 `storage` capability。pgembed 应作为可选的 state-event store provider 交付；其他文件协议只有在各自语义被独立刻画后，才可能拥有各自的 SQL seam。

### 2. 当前 todo / active-state / event 的真实 canonical read/write 链

| 操作 | 真实调用链与 canonical 行为 | 事件日志角色 |
| --- | --- | --- |
| list/read | `list_todos()` 先解析 registry/state file，再尝试加载事件投影，同时读取 active-state Markdown；两者都有 todo 时以 Markdown overlay 合并，来源标记为 `event_projection_with_markdown_overlay`，只有无 Markdown todo 时才使用纯 `event_projection`（`loopx/todos.py:412-479`）。事件投影由候选 JSONL 经具体 store 加载、reduce、渲染为 active-state Markdown 后再走同一 parser（`loopx/control_plane/goals/active_state_event_projection.py:47-103`）。 | 可参与读投影，但 Markdown 仍是优先 overlay/fallback。 |
| add | `add_todo()` 锁定 active-state 文件、读取 Markdown、调用 `add_todo_to_lines()`，最后直接 `Path.write_text()`（`loopx/todos.py:852-1068`）。 | 不追加事件。 |
| claim/update | `update_todo()` 的 claim-only 与普通 update 都锁定并读取 Markdown，要求 todo 存在于 Markdown，执行 authority 检查，调用 `apply_todo_update_to_lines()`，再写回 Markdown（`loopx/todos.py:1137-1477`）。 | 正常 claim 不追加 `TODO_CLAIMED`。 |
| complete | `complete_todo()` 同时进入 active-state 文件锁和 task-lease fence，优先在 Markdown 查找 todo；只有 Markdown 中不存在时才查事件投影上下文（`loopx/todos.py:1507-1643`）。正常分支更新并写回 Markdown（`loopx/todos.py:1734-1843`）；仅 event-projected/Markdown-missing 分支调用 event completion（`loopx/todos.py:1698-1733`）。 | event-only completion 构造并追加 `TODO_COMPLETED`；successor 事件也是逐项追加（`loopx/control_plane/todos/event_writeback.py:250-275,301-455`）。 |

由此排除三个容易误导设计的假设：事件日志不是当前 todo canonical write backend；正常 add/claim/complete 并非全部写事件；“为 `AppendOnlyStateEventStore` 增加 pgembed 实现”也不会自动把现有 todo lifecycle 切换到 PostgreSQL。第一阶段若只替换 event store，必须明确其目标是事件读影子、event-only writeback 和 supervisor event users，而不是宣称 todo Markdown 已完成迁移。

### 3. promotion/write gates：确实阻止直接 promotion，但不是现成的 backend dispatch

#### `event_store_migration_bridge`

- bridge 定义了 `wait_for_event_read_path`、`dual_read_shadow`、`bounded_canary`、`promotion_candidate` 等阶段和必需检查（`loopx/control_plane/runtime/event_store_migration_bridge.py:45-95`）。
- 它明确把 `markdown_active_state` 保持为 source of truth，把事件投影视为 candidate，并始终返回 `promotion_allowed = False`；最终 promotion 要求一次显式、经审阅的 write-path change（`loopx/control_plane/runtime/event_store_migration_bridge.py:93-103`）。fallback 也优先回到 Markdown（`loopx/control_plane/runtime/event_store_migration_bridge.py:110-139`）。
- canary 输出仍是 `write_path: "disabled"`，读偏好仍为 Markdown；失败结论是继续保持 Markdown canonical（`loopx/control_plane/runtime/event_store_migration_bridge.py:152-196`）。
- 全仓生产调用搜索没有发现 `build_event_store_migration_bridge` 的运行时消费者；调用仅存在于定义、tests/examples/docs。它目前是 fail-closed 的评估/rollout contract，不是已经接入 todo/status 命令的 backend switch。

#### `local_state_write_correctness`

- todo 只在 `dry_run` 时附加 write-correctness packet；真实写入立即绕过该 packet（`loopx/todos.py:134-162`）。
- packet builder 明示调用方仍负责真正的 lock/write/rollout，结果状态为 `preview_only`，且 public boundary 不授权 production action（`loopx/control_plane/runtime/local_state_write_correctness.py:29-100`）。shadow validation 只比较 revision 和可选 lease references，不改变写行为（`loopx/control_plane/runtime/local_state_write_correctness.py:103-159`）。
- 协议当前模式为 `dry_run_preview`、目标为 `shadow_validate`，并明确 `allowed_to_change_write_behavior: false`；它允许建立脚手架和证据，但不允许据此拒绝或改写之前可接受的真实写入（`docs/reference/protocols/local-state-write-correctness-v0.md:151-188`）。

所以，两个 gate 的准确结论是：migration bridge 阻止把 shadow/read parity 自动提升为 canonical write；write-correctness 协议阻止把 preview evidence 当作修改真实写路径的授权。它们确实排除了“直接切换”，但都不是全局 provider selector，也不会拦截当前真实 Markdown 写入。pgembed promotion 仍需新增、显式审阅的 write-path rollout。

### 4. 为什么 run history、task leases、domain state、registry/authority 不能一起迁移

这些表面上都是 JSON/JSONL 文件，实际却是不同的一致性、原子性和可观察性协议；用一个 SQL table 或全局 storage API 一次替换会隐藏而非保留这些契约。

#### Run history：三类 artifact 加路径分配/修复语义

- run path 通过 `O_CREAT|O_EXCL` 原子保留 JSON sentinel，并把 Markdown 同名碰撞也视为不可用（`loopx/control_plane/runtime/run_artifacts.py:46-78`）。
- 写入随后生成完整 JSON、渲染后的 Markdown，并追加 compact `index.jsonl`，不是单一 ledger transaction（`loopx/history.py:84-103`）。
- 读取会结合 registry 与 runtime 目录发现 goals；index reader 容忍坏行、按 generated/path tuple 去重并检查 artifact 是否仍存在（`loopx/history.py:117-192`）。`collect_history()` 还读取每个 goal 的 run index、补充 registry/quota 信息并兼容 legacy runtime goals（`loopx/history.py:697-782`）。

这套协议承担用户可见证据文件、路径引用、修复/发现和 legacy compatibility。把它与 event log 同迁会改变 export/observability contract；`loopx/control_plane/runtime/run_history.py` 是 reducer/read model，不是可直接替换这些 artifact 的持久化 seam。

#### Task leases：CAS、TTL、冲突扫描和 commit fence

- lease 是每 todo 一个 JSON，并有 per-goal lock target（`loopx/control_plane/work_items/task_lease.py:93-102`）。mutation fence 在 lifecycle write 期间持有 goal lease lock，验证 owner、execution-instance idempotency key 和 expected version；真实 lifecycle write commit 后才 release，release 失败也不能回滚已经提交的 lifecycle write（`loopx/control_plane/work_items/task_lease.py:115-256`）。
- lease 文件使用严格 JSON 读取和 temp+replace 写入（`loopx/control_plane/work_items/task_lease.py:423-447`），active 判定依赖 schema/status/expiry（`loopx/control_plane/work_items/task_lease.py:461-467`），冲突检测会扫描 `todo_*.json` 并比较 write-scope overlap（`loopx/control_plane/work_items/task_lease.py:539-581`）。
- acquire/renew/transfer/release 都有 owner/key/version 的 CAS-like 规则和 authority validation（`loopx/control_plane/work_items/task_lease.py:584-909`）。

lease seam 需要表达 TTL、versioned CAS、冲突范围和 fence ordering，而不是 append/replay。若 event log 在 SQL、lease 仍在文件，跨资源提交顺序本身已需单独设计；把 lease 同时迁移只会扩大事务边界和失败矩阵。

#### Domain state：带领域 merge policy 的 keyed upsert

- domain state 位于项目局部的 `.loopx/domain-state/<goal>/<pack>/...`（`loopx/domain_state.py:30-49`）。
- 它按稳定 key 对 JSONL 做 upsert，使用 sidecar `fcntl` lock，锁内重读全文件，执行 domain-specific merge/unchanged callbacks，最后 temp+replace 重写整个 ledger（`loopx/domain_state.py:52-137`）。

这不是不可变 event append，而是 mutable keyed merge；redaction、promotion 和 merge policy 仍属于 domain owner。未来如需 SQL，应另建 JSONB/upsert contract，而不是搭便车进入 state-event provider。

#### Registry/authority：bootstrap routing 与公开/私有边界

- registry 严格读取根 JSON object，解析 repo-relative state file，并以 temp file、`flush/fsync`、replace 原子写回（`loopx/registry.py:21-68`）。它还扫描 private/local source/path 并决定 boundary classification 和 publish policy（`loopx/registry.py:172-307`）。
- global registry 的 route identity 是 `source_registry`、`repo`、`state_file`；更新在锁内执行 authoritative read-modify-write，可写 backup，并拒绝静默替换 route identity 的碰撞（`loopx/global_registry.py:28,56-91,150-165,201-229`）。

registry 负责先定位 repo、state file、runtime root 和 authority route。若 provider 的选择或连接信息也依赖被迁移后的 registry，就形成“先打开 provider 才能读到如何打开 provider”的 bootstrap circularity。它的隐私分类、备份与路由碰撞语义也不是通用 event storage。

### 5. extension/provider 生命周期的适配度

现有 extension 机制适合交付和选择一个可选 pgembed provider，但不足以单独拥有 PostgreSQL 服务生命周期。

- LoopX core 支持 Python `>=3.11`、核心 dependencies 为空，只有 test extra，并暴露主 CLI 与少量 bundled provider scripts（`pyproject.toml:5-30`）。pgembed 当前要求 Python `>=3.12` 且 wheel 平台有限，因此把它和 SQL driver 变成 core unconditional dependency 会改变 LoopX 的 Python/平台产品边界。
- extension manifest 要求 `entrypoint` 或 `python_module` 二选一，声明协议、参数、doctor 参数、权限，并把 timeout 限定在 1–120 秒（`loopx/extensions/manifest.py:178-244`）。这是 bounded invocation 声明，不是 daemon/service 声明。
- install 只验证 manifest/doctor 并登记一个已经安装的 provider；enable 重跑 doctor 并绑定 active revision/runtime identity；disable、rollback、catalog 和 capability resolution 管理 enabled/readiness/revision 状态，且多个 enabled-ready provider 会 fail closed（`loopx/extensions/runtime.py:132-360,477-582`）。
- doctor 解析 executable 或 Python module，启动有界 subprocess 并把 readiness 绑定到 executable/module identity（`loopx/extensions/readiness.py:64-168`）。实际 provider invocation 也是一次请求一个 subprocess，带 process group、timeout、输出上限并在结束时终止（`loopx/extensions/process_runtime.py:85-204`）。
- 公共 extension contract 明确：install 不下载包；`run` 是有界 JSON stdin/stdout；enable 重跑 doctor；独立版本的可选 provider 应放在 `packages/<package-id>/` 或独立分发；runtime 不负责下载/安装 package，也不启动 service 或配置 credentials（`docs/reference/extensions.md:74-105,181-217,237-253,387-415,571-580`）。

推荐 placement：

- **Capability owner:** 现有 state-event/control-plane contract，而不是新建 generic storage capability。
- **Provider id:** 一个明确表达结果边界的可选 pgembed event-store provider。
- **Delivery:** co-located `packages/<package-id>/` 或独立 distribution；只有随 LoopX wheel 捆绑时才把 provider 实现放进 `loopx/extensions/`。
- **Core addition:** 在 `event_sourced_state`/control-plane 最近 owner 附近定义窄 contract 和 resolver。
- **Additional lifecycle:** 另建明确的 server/session manager，负责 PGDATA、postmaster owner、start/readiness/stop、crash recovery、schema migration、PostgreSQL major upgrade、export/rollback。不能把这些职责伪装成一次 `loopx extension run`。

### 6. CLI、entrypoint、config 与 package surfaces

- `loopx/entrypoint.py` 只委托到 `loopx.cli`（`loopx/entrypoint.py:8-16`）。主 parser 当前只有 registry/runtime-root/format 等全局参数，并注册 extension commands，没有 storage backend selector（`loopx/cli.py:197-229`）。
- extension CLI 已提供 init/list/install/upgrade/enable/disable/rollback/doctor/run/publish 的解析和 dispatch（`loopx/cli_commands/extension.py:89-166,190-271`）。这些命令可复用为 provider package 的登记、启停、doctor 和 revision 管理，但普通 todo/status/quota/supervisor 命令仍需一个 in-process event-store resolver；仅靠 `extension run` 无法替换它们内部的直接 constructor。
- backend selection 必须在启动 pgembed 前即可读取，且不应依赖已经迁移的 registry。需要决定 dedicated local config、runtime profile 或 goal-level key 中哪一个是 bootstrap source。迁移期间还要显式处理多个 provider、file fallback 和 provider revision，而不能依靠“启用了某 extension”进行隐式选择。
- 用户可见的最小运维 surface 至少包括：provider install/enable/disable/doctor；backend scope/selection；PGDATA 与 process owner；start/readiness/stop/recovery；SQL schema migrate/readback/rollback/export；PostgreSQL major migration；Python/平台 eligibility；不可用时的可执行 file fallback。
- pgembed 和 SQL driver 应独立可选打包。若 extension commands 足以管理生命周期，不一定需要新的 top-level console script；但 normal LoopX command 的 store resolution 仍需要核心内 contract/registration surface。

### 7. 已排除的假设

1. **“LoopX 已有全局 storage interface。”** 未发现；现状是多个拥有不同协议的具体文件实现。
2. **“事件日志已经是 todo canonical backend。”** 错；Markdown 仍是正常 add/claim/update/complete 的写入真相，并在读时 overlay/fallback。
3. **“正常 todo lifecycle 全部追加事件。”** 错；只有 event-projected/Markdown-missing completion 走 event writeback。
4. **“migration bridge 已经直接切换生产 reads。”** 错；未发现生产 caller，且 contract 固定 fail closed。
5. **“write-correctness packet 会阻止当前真实 writes。”** 错；它只在 dry-run/shadow 路径出现。
6. **“一个 SQL table 可以统一替换 JSON/JSONL state。”** 错；history、lease、domain state、registry 分别拥有 artifact、CAS/TTL、merge/upsert、bootstrap/privacy 协议。
7. **“extension enablement 足以拥有 pgembed postmaster。”** 错；现有 runtime 只管理 bounded subprocess invocation/readiness。
8. **“phase one 需要 pgvector。”** 错；state-event transaction seam 不依赖 vector search。
9. **“pgembed 可无条件加入 LoopX core dependency。”** 错；这会抬高 Python 和平台基线并引入 SQL driver/二进制分发边界。

### 8. 推荐第一阶段范围与验收门槛

第一阶段应是可回退、以 parity 为目标的 event-store seam/canary，而不是“把 LoopX 搬进 PostgreSQL”：

1. 定义窄的 provider-neutral state-event store contract，至少保留：`load`、按 `event_id` 幂等 append、同 ID 不同 payload 冲突、单调 `append_sequence`、确定性排序/回放、schema/privacy validation。
2. 对 `append_many()` 作显式兼容决策：保留现有可能部分成功的逐项追加，或升级为事务性批量写；不能在 provider 间默默采用不同语义。
3. file store 保持默认和 rollback source；建立 resolver/factory，消除 production direct constructors，但不要改动 todo Markdown canonical writes。
4. 以 optional package/extension-delivered provider 实现 pgembed event store，并补充独立的 postmaster/PGDATA/session owner 与 SQL schema lifecycle。
5. 先做 shadow/dual-read，或在明确单写者规则下做 mirrored-write canary；保留 Markdown parser/write path、文件可观察性和逆向 export。
6. phase one 明确排除 run history、task leases、domain state、registry/authority；也不引入 pgvector。
7. promotion 前至少验证：file/pgembed replay parity、event-head/sequence 对齐、幂等与冲突语义、坏行/partial append 兼容决策、公开/私有边界、bounded canary、故障注入、file rollback/reverse export，以及一次显式审阅的 canonical write-path change。

一个重要的范围选择仍需在实施前固定：该 seam 的自然调用者还包括 supervisor event logs，而不只 todo state events。可以让 contract 覆盖所有 state-event users，但 canary/resolver 应按 event-log namespace 或用途分阶段启用，避免一次扩大所有 supervisor 路径的故障域。

### 9. 未决问题

- 谁拥有 pgembed process：每次 CLI、常驻 daemon、长生命周期 runtime manager，还是受监督的共享本地服务？
- backend selection 的 scope 是 global、runtime profile、registry goal 还是 dedicated local config；其 bootstrap 信息放在哪里？
- file 与 pgembed client 是否允许同时访问同一 goal；single-writer、dual-writer、leader/fencing 规则是什么？
- `append_many()` 是保留 partial-append compatibility，还是定义真正事务；`append_sequence` 在并发 SQL clients 下如何分配？
- 正向 migration、reverse export、rollback point、事件文件可观察性和用户手工检查能力如何保留？
- SQL schema migration 与 PostgreSQL major upgrade 分别由谁执行、如何失败回退？
- provider package 名称、SQL driver/pool、Python 3.11 和不受支持平台的 fallback policy 是什么？
- phase-one canary 是否包含 supervisor event logs，还是只包含 todo state-event namespace？
- PGDATA 权限、trust authentication 和本机多用户边界如何文档化和测试？
- 第一阶段只作为内部 shadow，还是立即暴露用户可选择的 backend？
- backup、dump/restore、provider disable/rollback 后的 readback 与数据保留承诺是什么？

## Investigation Log

### Initial Assessment - Scope and hypotheses
**Hypothesis:** 最大风险不在 SQL CRUD，而在现有文件协议、原子写/锁/可观察性、CLI 生命周期和兼容迁移能否被一个窄接口表达。
**Findings:** 假设成立，但需加一个关键修正：`AppendOnlyStateEventStore` 是最适合先抽象的物理存储 seam，却尚未拥有普通 todo 的 canonical write；正常 add/claim/update/complete 仍以 Markdown 为写入真相。
**Evidence:** `loopx/event_sourced_state.py:542-585`；`loopx/todos.py:412-479,852-1068,1137-1477,1698-1843`；`loopx/control_plane/runtime/event_store_migration_bridge.py:90-105`。
**Conclusion:** Confirmed with scope correction.

### Oracle Synthesis - Migration axes and product promise
**Hypothesis:** 可以通过一次后端开关同时完成 todo 真相迁移和数据库迁移。
**Findings:** 被排除。必须分成 Markdown canonical → event canonical 的语义迁移，以及 file event store → pgembed event store 的物理迁移；前者尚未完成，后者只能先做 shadow/parity。
**Evidence:** Investigator Findings §§2-3；现有 bridge 固定 `source_of_truth=markdown_active_state` 且 `promotion_allowed=false`。
**Conclusion:** Eliminated.

## Root Cause
问题表面上是“增加第二种存储实现”，实际根因是 LoopX 当前没有一个覆盖全部状态的统一后端合同，而且也不应该有一个通用 KV/blob 合同。Registry/authority、Markdown active state、event ledger、run artifact bundle、task lease、domain state 分别拥有不同的 canonical owner、原子单位、锁/CAS、路径可观察性、隐私和恢复语义。

最接近可替换后端的现有 seam 是 `AppendOnlyStateEventStore`：它定义了 event normalization、幂等 `event_id`、冲突检测、per-stream append sequence 和 replay/checksum。但它仍是具体文件类，生产调用者直接构造它，`append_many()` 也只是逐项追加。更关键的是，普通 todo 生命周期仍直接写 Markdown，事件投影只参与 overlay/fallback，故“把 event store 换成 pgembed”不会自动把 LoopX todo 的 canonical truth 迁入 PostgreSQL。

因此主要难点按优先级是：

1. **Canonical ownership：** 先决定 Markdown 与 event ledger 谁是写入真相，并完成显式 promotion，而不是让两个介质都像 canonical。
2. **领域合同：** 固定 event store 的 expected-head、幂等 receipt、冲突、原子 batch、namespace ordering、privacy 和 projection checkpoint 语义。
3. **Single writer / fencing：** 后端切换时旧进程和旧 provider 必须因 generation 过期而拒绝写；禁止 file 与 pgembed 双 active writer，也禁止 pgembed 故障后静默写回 file。
4. **跨介质可恢复迁移：** registry 文件、PostgreSQL commit 和 Markdown projection 不可能共享一个事务，需要 journaled cutover、canonical export/import、head/checksum parity、reverse migration 和显式 rollback gate。
5. **长期进程所有权：** pgembed 启动真实 PostgreSQL；每个短 CLI 启停一次会有延迟和故障噪音，`cleanup_mode=None` 又会留下无 owner 的隐式 daemon，因此需要明确的 local storage supervisor/runtime manager。
6. **版本与分发：** LoopX SQL schema、event schema、provider revision、PostgreSQL major 是四套独立版本；pgembed 的 Python/平台/二进制边界不适合成为 LoopX core unconditional dependency。
7. **安全与运维：** 默认 trust auth 只能限定为本地受控边界；必须提供 init/start/status/stop/doctor/export/import/migrate/backup-readiness，并把 PGDATA、socket、URI 和原始日志留在私有诊断面。

## Recommendations
1. **Phase 0 — contract first:** 在 `loopx/event_sourced_state.py` 最近 owner 中定义 core-owned、provider-neutral 的 event-state-store port 与 resolver。保留 file JSONL 为默认实现；冻结 event type/version、normalized JSON、幂等/冲突 receipt、per-namespace head、writer generation、expected-head 和原子 `append_batch` 语义。
2. **Phase 1 — internal pgembed shadow:** 作为独立可选包（建议 `packages/loopx-pgembed-event-store/` 或独立 distribution）实现 pgembed provider；通过 extension manifest 完成安装、enable、doctor 和 revision identity，但由单独的 storage runtime manager 管理 PGDATA/postmaster、schema、health、export/import 和 fencing。此阶段只做 import/replay/read parity，不暴露含糊的全局 backend selector。
3. **Phase 2 — semantic promotion on file first:** 让普通 todo add/claim/update/complete 经过 canonical event append，再由 event 生成 Markdown projection；先在文件 provider 上通过现有 migration bridge、write correctness、projection head 和 bounded canary gate。
4. **Phase 3 — physical provider cutover:** 以 goal/event namespace 为范围，而非全局 storage；registry 继续作为数据库外 bootstrap，保存 provider binding、logical namespace 和 writer generation。执行 `stable(file) → cutover_pending → fence → final export/import → parity → activate pgembed generation → stable(pgembed)` 的可恢复状态机。
5. **Rollback 规则:** promotion 后若 pgembed 已有新写，回 file 必须先 fence、从 pgembed 导出、幂等导入新的 file store、校验 head/checksum/projection、提升 generation，再恢复 file 写入；不能只改配置，也不能使用旧文件快照静默继续。
6. **第一阶段明确排除:** registry/authority、run history、task leases、domain state、capability-local stores、pgvector/TigerFS、远程 PostgreSQL、HA/多机协调和 PostgreSQL major 自动升级。
7. **测试矩阵:** 同一 backend contract suite 同时跑 file/pgembed，覆盖并发 append、同 event id 重试/冲突、batch 原子性、commit outcome unknown、projection failure、mirror lag、cutover crash、reverse migration、schema/PG major mismatch、unsupported Python/platform 和 public/private boundary。

### Decision matrix

| 范围 | 判断 |
| --- | --- |
| 提取 provider-neutral event-store port；保留 file 默认实现 | 现在可做 |
| pgembed event table、import/replay/checksum、read-only shadow | 现在可做，但仅 internal/experimental |
| extension 安装/enable/doctor/provider revision | 现有机制可复用 |
| 普通 todo event-first、原子 batch、expected-head、fencing | 需要先完成合同与 rollout 工作 |
| goal/event-namespace 级用户选择与 journaled cutover | 完成上述合同后再开放 |
| 一个全局开关迁移所有 LoopX 文件状态 | 不应做 |
| file 与 pgembed 双 active writer或故障时静默 fallback | 禁止 |
| task leases、run history、domain state、registry、pgvector 同期迁移 | Phase 1 不应捆绑 |

## Preventive Measures
- 为每个持久化 bounded context 维护 `canonical owner / read model / write API / atomic unit / lock or CAS / idempotency / repair / privacy` inventory，新增后端前先证明真实 seam。
- 所有 provider 必须通过同一语义 contract suite；测试预期来自协议，而不是从任一实现的当前输出反推。
- 把 truth-model migration 与 physical-provider migration 分成独立 PR、独立 canary 和独立 rollback gate。
- 在 status/doctor 中显示实际 backend coverage，而不是一个误导性的全局标签；例如 event ledger 可为 pgembed，而 registry、Markdown projection、history、leases 仍为 file。
- 将 silent fallback、双 active writer、stale generation write、未知 schema 继续启动定义为 fail-closed regression cases。
- 保持 canonical logical export 为跨 provider、跨 PostgreSQL major 的恢复格式；不要把复制运行中的 PGDATA 当作唯一备份策略。
- 任何 PostgreSQL major 或 provider revision 升级都必须先验证 SQL schema compatibility、logical export 和 reverse-readback；代码 rollback 不等于数据 rollback。
