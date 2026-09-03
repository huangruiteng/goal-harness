---
name: tb4-five-arm
description: 在 Terminal-Bench 4.0 上做 codex harness 五臂对照（裸 codex / 原生 /goal / LoopX 三模式）。复用 SWE-Marathon 那套驱动，靠 WEN_BENCH 切换。重点是 TB4 相对 SWE-Marathon 的四处结构性差异——每一处踩错都**退出码 0、有轨迹、有分数**，只是分数不对。
---

# Terminal-Bench 4.0 五臂对照

五臂定义、LoopX profile 装配、agent 类、监控工具全部与
[[swe-marathon-five-arm]] 相同，**先读那一份**。这里只写 TB4 特有的部分。

对照维度仍是 **harness 不是模型**：五臂的模型、effort、工具面、沙箱、容器一致。

## 切换方式

```bash
export WEN_BENCH=tb4      # 必须 export，见下面「最毒的一个坑」
source env.sh

./scripts/prebuild_images.sh music-harmony   # 应建 2 个镜像，不是 1 个
./scripts/verify_envs.sh music-harmony       # install-only，不烧 token
./scripts/canary_timeout.sh                  # 五臂 × 短死线
./scripts/marathon_all.sh --dry              # 63 任务 × 5 臂 = 315 trial
```

benchmark 相关的量全在 `scripts/bench/tb4.sh`，驱动脚本里没有任何 TB4 常量。
`WEN_BENCH` 不设时默认 `swe-marathon`，行为与引入 bench 层之前逐字一致
（已用 `bash -x` 逐参数 diff 验证过）。

## 数据来源

`terminal-bench/` 是 `harbor-framework/terminal-bench` 的 **tag v4.0.0**
（commit `452bf305c6`），66 个任务，见 `terminal-bench/VERSION`。

- **不能用 `harbor run -d terminal-bench@4.0`**：harbor 的注册表（Supabase
  `dataset` 表）里只有 `terminal-bench@2.0`，实测查 4.0 返回 `null`。
- **不要跟 main**：上游 README 明说 "will be continuously updated"，
  跟 main 跑出来的结果不可复现。
- `tasks/dataset.toml` 里每个任务有 sha256 digest，`task.toml` 与 `tests/`
  一个字节都不能改。要注入环境变量走 harbor 的 `--ve` / `--ae`。

## TB4 vs SWE-Marathon：四处结构性差异

| 项 | SWE-Marathon | TB4.0 |
|---|---|---|
| `agent.timeout_sec` | 3600–36000 各异 | **全部 28800（统一 8h）** |
| `verifier.environment_mode` | 无（shared） | **全部 `separate`** |
| `network_mode` | 三态，逐任务 | **一个都没声明** → harbor 默认 public |
| 每任务镜像数 | 1（`environment/`） | **2（`environment/` + `tests/`）** |
| 连续分 | `metrics.json` 有 | **没有**，只有二值 reward |

排除 3 个要 H100 的任务（`fp8-rmsnorm-gemm` / `jax-speedrun-gpu` /
`math-eval-grader`），本机是 4090D。剩 63 个，其中 11 个是多容器
（`environment/docker-compose.yaml`），1 个（`medical-claims-processing`）
还要 MCP server（playwright，sse `http://playwright-mcp:3080/sse`）。

## 坑（都会静默通过）

### 一、最毒的一个：`WEN_BENCH` 用前缀赋值

```bash
WEN_BENCH=tb4 source env.sh      # ✗ 错
export WEN_BENCH=tb4; source env.sh   # ✓ 对
```

bash 在 `source` 返回后会把前缀赋值的变量**还原成未设置**，但 `WEN_TASKS_DIR`
是 export 的、留了下来。于是后续任何脚本自己 source env.sh 时：`WEN_BENCH` 空 →
回退 swe-marathon profile，却继承着 TB4 的任务目录 —— 拿 **TB4 的任务**、套
**marathon 的网络策略**（`from-task` 找不到 `network_mode` 就断网）、
开着判官注入、写进 `marathon-full/`。退出码 0，全程无警告。

`env.sh` 里有个一致性闸门专门拦这个（`WEN_TASKS_DIR_BENCH` 与当前 bench 不符
就丢弃继承值），但闸门只保证**状态自洽**，不保证是你想要的那个 bench。
开跑前看一眼各脚本打印的 `bench:` 那一行。

### 二、网络策略反了 → 66 个任务全跑成断网

TB4 的 66 个 `task.toml` **一个都没有声明 `network_mode` / `allow_internet`**，
而 harbor 0.20.0 的 `NetworkPolicy.network_mode` 默认是 `PUBLIC` ——
上游的标定条件是联网。

而 `marathon_run.sh` 原本的做法是 grep `task.toml` 的 `network_mode`、
**找不到就回退 `no-network`**。直接套用会把 66 个任务全跑成断网：
退出码 0、有轨迹、有分数，只是分数偏低，看着像"模型不行"。

`bench/tb4.sh` 里 `BENCH_NET_POLICY=public` 显式钉死，不走那条 grep。

**另注：`--allow-agent-host` 在 public 下是空操作。** 实测 harbor 会打印

```
UserWarning: Run-specific allowlist host(s) ['<model-gateway>', '<container-gateway>'] are
ignored because the effective network policy is public.
```

模型端点的可达性靠代理环境变量和宿主机路由，不靠这个参数，别以为加了就生效。

**再注：本机实测容器不穿代理也能出网**（`docker run` 里直连 pypi.org 得 200）。
代理注入是沿用 marathon 对 public 任务的既有做法、属冗余保险；
`no_proxy` 已包含模型网关，不会劫持 codex 的调用。

### 三、`environment_mode = "separate"`：两个镜像、两个环境

全部 66 个任务都是 separate。harbor 0.20.0 的实际时序
（`harbor/trial/single_step.py:38-55`、`trial/trial.py:610-680`）：

```
跑 agent → 上传 agent 日志 → 收 artifacts → **停掉 agent 环境**
        → 起一个从 tests/ 构建的独立 verifier 环境 → 验证 → 停
```

三个后果：

1. **每个任务两个镜像**（66 × 2 = 132）。`prebuild_images.sh` 原来只扫
   `environment/`，漏掉 `tests/`。漏了的话 verifier 镜像会在**运行期**首次构建，
   而运行期没有代理（那是刻意的，代理进运行时容器会破坏隔离），dockerd 自己钉的
   `<dead-dockerd-proxy>` 又是死的 → `apt-get` 超时 → verifier 起不来记 errored。
   **症状极像"任务没做出来"**：agent 阶段完全正常、有轨迹、有 token 消耗。
   现在由 `BENCH_IMAGE_DIRS=(environment tests)` 覆盖，且跳过会计数。

2. **只有声明在 `artifacts` 里的文件能跨到 verifier**（66 个全声明了）。
   agent 把活干在别处、没写到声明路径 → verifier 看到空目录 → reward 0，
   而 agent 轨迹完全正常。这是 shared 模式下不存在的失败模式。

3. 串行，所以每 trial 的容器/网段**峰值**不翻倍，但多一次构建、
   多一个 compose project。

### 四、二值 reward 在紧预算下没有区分度，而 TB4 没有连续分

SWE-Marathon 靠任务自写的 `metrics.json`（`partial_score` / `pass_rate` /
`pytest` / `gates_*`）补救；**TB4 不写这个文件**，只有 harbor 的二值 reward。

`bench/tb4.sh` 设 `BENCH_HAS_PARTIAL=0`，于是：
- `_partial.py` 整体跳过并打印原因，不静默兜底
- `_compare.py` **整列不渲染** partial，而不是渲染成一列 0.0
  （一列 0.0 会被读成"全都没得分"，比不显示更坏）
- `_compare.py` 的跨跑次对照自动改用 `reward` 做差，表头跟着变

marathon 那轮实测：撞死线的 23 条 trial 无一得分，自己收尾的 14 条中 11 条得分
——决定分数的是"能不能在预算内做完"。TB4 统一 8h 预算而我们的死线远短于此，
这个问题只会更严重。**唯一还能分辨的信号是终止原因**（自己收工 vs 撞死线），
`_receipts.py` 有这个数据，报表必须并排给出。

### 五、超时倍率不要照抄 marathon

marathon 用的是 build 6× / setup 3× / verifier 4×，那是为**未做资源标定**的
Dockerfile 定的。TB 4.0 的卖点恰恰是"重新标定了 time/CPU/memory"
（`build_timeout_sec` 中位数 900、`verifier.timeout_sec` 中位数 600），
照抄 6× 等于把上游的标定压掉。`bench/tb4.sh` 用 4 / 3 / 2。

### 六、canary 的预算比例要重算

`canary_timeout.sh` 的 `CANARY_TIMEOUT_MULT=0.05` 是按 8h 声明预算定的
（8h × 0.05 = 24 分钟 > `GOAL_TIMEOUT_SEC` 5 分钟，保证**我们先到**）。
TB4 恰好也统一 8h，所以同一个值仍成立。换到声明预算短的 benchmark 上，
harbor 侧可能反而先到，冒烟就白做了 —— 而那是**静默**的：
五臂照样出 result.json，只是走的是另一条超时路径。

### 七、全量的量级要先量再定

63 任务 × 5 臂 = **315 trial**，外加 126 个镜像构建。
`MARATHON_AGENT_TIMEOUT_MULT` 沿用 marathon 的 0.3 得 8640s（2.4h）/trial。
**先拿冒烟的真实单 trial 墙钟再算总时长**，别直接开全量。

网段池是硬约束：默认约 32 个 bridge 网络，机器共用。起跑前确认池子有余量
（`marathon_all.sh` 有 `MARATHON_NET_CAP` 闸门），清理容器时**连 compose 网络
一起清**（`docker rm -f` 不删网络）。

### 八、11 个多容器 + 1 个 MCP 任务未验证

冒烟只覆盖单容器路径。`ctr-optimization` `cumulative-layout-shift`
`freight-dispatch-shift` `heat-pump-warranty` `intrastat-meldung`
`kv-live-surgery` `legacy-utility-triage` `live-database-cutover`
`medical-claims-processing` `nextjs-performance` `payments-pipeline-fix`
容器数与内存压力显著更高；`medical-claims-processing` 还要
MCP server 起得来。全量前单独验这 11 个。

## 产物

```
tb4-full/<task>/<arm>/<stamp>/<arm>/result.json          job 级，含 stats
                                   /<trial>/verifier/    reward.txt
                                            /agent/      trajectory.json / goal_receipt.json
tb4-full/.claims/<task>__<arm>.claim
tb4-jobs/                                                marathon_run.sh 单独跑的落脚点
verify-envs-tb4/  canary-timeout-tb4/
```

成功判据与 marathon 相同（`scripts/_is_done.py`，驱动与监控共用）：

```
n_completed_trials >= 1 且 n_errored_trials == 0
```
