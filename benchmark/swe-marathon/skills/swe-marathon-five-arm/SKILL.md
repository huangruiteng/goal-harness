---
name: swe-marathon-five-arm
description: 在 SWE-Marathon 上做 codex harness 五臂对照（裸 codex / 原生 /goal / LoopX 三模式）。包含 agent 适配、跑法、监控，以及一整天踩出来的坑——这些坑的共同特征是**退出码 0、日志干净、结果看着正常**，不看这份文档几乎必然重踩。
---

# SWE-Marathon 五臂对照

对照维度是 **harness**，不是模型。五条臂的模型、effort、工具面、沙箱、容器完全一致，唯一变量是"怎么驱动 codex"。

## 五条臂

| 臂 | agent 类 | 是什么 | runtime profile |
|---|---|---|---|
| `plain` | `codex_plain_appserver:CodexPlainAppServer` | 裸 codex，不挂 Goal、不装 LoopX | — |
| `goal` | `codex_goal_agent:CodexGoalAgent` | codex 原生 `/goal`，不装 LoopX | — |
| `ssh-goal` | `codex_loopx_agent:CodexLoopxAgent` | LoopX 模式二：Codex App over SSH | `codex_app_ssh_goal --begin-turn` |
| `codex-cli` | 同上，`WEN_MODE=codex-cli` | LoopX 模式三：Codex CLI 可见 `/goal` | `codex_cli` |
| `heartbeat` | 同上，`WEN_MODE=heartbeat` | LoopX 模式一：心跳自动化 | `generic_cli --turn-instance-id` |

三个 LoopX 臂共用一个 agent 类，靠 `WEN_MODE` 选 `modes/profiles.py` 里的 Mode。**模式差异是数据不是分支**——body 文本、runtime profile、是否需要 turn instance 都写在 Mode 里。

`ssh-goal` 与 `codex-cli` 的 goal body 逐字只差一行（runtime profile 那行），这符合上游设计：分流发生在 LoopX CLI 的闸门里，不在 body 文本里。

## 必须披露的两处偏离

1. **`plain` 走 app-server，不是论文的 `codex exec`。** 原因见下面「只杀对照组」那节。
2. **`heartbeat` 用 `generic_cli` 代替 `codex_app`。** 上游 `host_surface=codex_app` 是留给真 Codex App 的：它回一套 `stateful_backoff`，期待宿主调 App 的 `automation_update` 改 RRULE 再 ACK；没有真 App 就永远悬着。上游给自建定时器指定的对口就是 `generic_cli`（参考实现 `scripts/external_scheduler_worker.py` 的默认值）。这个替换写在 `profiles.py` 的 `substitution` 字段里，**但不会自动进产物，报表时要手工带上**。

## 跑法

```bash
# 环境验收（install-only，不烧 token）
./scripts/verify_envs.sh

# 超时路径冒烟（~10 分钟跑完五臂，验证预算耗尽后能正常收尾评分）
./scripts/canary_timeout.sh

# 全量
MARATHON_CONCURRENCY=12 GOAL_TIMEOUT_SEC=21600 MARATHON_AGENT_TIMEOUT_MULT=1.0 \
  setsid nohup ./scripts/marathon_all.sh >> marathon-full.log 2>&1 < /dev/null &

# 监控（进度 + 逐臂 reward + receipt 的续跑/解锁/错误事件 + 连续分）
./scripts/progress.sh
./scripts/health_check.sh [--fix]
```

常用旋钮（都可放进 `marathon-full/.driver_env`，`health_check --fix` 重新拉起时会读）：

| 变量 | 作用 |
|---|---|
| `GOAL_TIMEOUT_SEC` | **我们自己的死线**，默认 5340（89 分钟）。多数任务是它先到，不是 harbor |
| `MARATHON_AGENT_TIMEOUT_MULT` | harbor 侧 = 任务声明预算 × 它 |
| `MARATHON_VERIFIER_MULT` | verifier 超时倍率，默认 4 |
| `MARATHON_CONCURRENCY` | 跨 (任务,臂) 的并发 |
| `MARATHON_ARM_MAJOR` | 1=按臂分组，0=按任务分组 |
| `MARATHON_TASKS` / `MARATHON_ARMS` | 覆盖任务集/臂集与顺序 |
| `MARATHON_NET_CAP` / `NET_MARGIN` | docker 网段池闸门 |
| `MARATHON_MAX_PASSES` | 多趟扫描次数，捡漏延迟失败 |

## 环境准备（跑之前必须做完的三步）

### 1. `stage_codex_offline.sh` —— 搬 codex 运行时

`@openai/codex-linux-x64` 这个 npm 包里 vendor 的是 **static-pie musl 静态可执行文件**，不需要 Node 运行时，断网空白容器里直接能跑。

**必须整棵拷,不能只抠 `codex` 和 `rg`**：0.151 的 `unified_exec` 需要 `codex-code-mode-host` 这个 sidecar。缺了它容器里**每次工具调用都失败,而且不报错**——表现是 47 轮什么都没干成、零错误上报。

### 2. `stage_local.sh` —— 把重资产搬到本地 NVMe

`wen/` 在 NFS 上（`<nfs-host>:/<vol>`，nfs v3）。docker 数据根在本地 NVMe，所以**镜像层不慢**，慢的是每个 trial 往容器里搬的东西：

```
codex 二进制    331M   NFS 读
LoopX 源码      178M   NFS 读（整个 git checkout）
node（整个 nvm）721M   本地，但含 npm/lib/include，其实只要 bin/node
可移植 python   109M   本地
                ─────
LoopX 臂每次   ~1.3G，其中 ~509M 走 NFS —— 12 路并发时这是主要瓶颈
```

预装到 `$HOME/wen-cache` 后全部本地，node 裁到只剩二进制（721M→119M），每 trial 降到约 400M。

**只搬 agent 自己的依赖，`swe-marathon/tasks` 一个字节不动**——那是 benchmark 数据，`dataset.toml` 里有 sha256 digest，改了就不是这个 benchmark。

### 3. `prebuild_images.sh` —— 预构建任务镜像

任务 Dockerfile 里有 `apt-get update && install`，构建要出网。本机出网必须过 `<host-proxy>`，而 **dockerd 自己钉的代理 `<dead-dockerd-proxy>` 是死的**，症状：

```
W: Failed to fetch http://deb.debian.org/... connection timed out
failed to solve: process "/bin/sh -c apt-get update ..." did not complete
```

**不能用 `~/.docker/config.json` 的 proxies 段**：它会把 `HTTP_PROXY` **同时注入运行时容器**，等于给 `no-network` 任务开了出口，公平性直接没了。

正确做法是只在**构建**时经 `--build-arg` 给代理 + `--network host`。BuildKit 层缓存按内容寻址，预构建产生的层 harbor 之后照样命中，而 harbor 自己那次构建不带代理、运行时容器干净。

`wen/.venv` 里改过 harbor 两个文件（自己的副本，允许改）：

- `harbor/environments/docker/docker-compose-build.yaml` —— 加 `network: host` + proxy build-args。**两边 build-arg 必须一致**，不一致会导致缓存不命中、白构建一遍
- `.../harbor-docker-egress-control-sidecar/Dockerfile` —— 去掉 digest pin

## LoopX profile 怎么装进容器

布局**照抄 `benchmark_toolkit` 的 `_profile_paths()`**，这样 LoopX 自己的 `inspect` / `doctor` 逻辑才对得上：

```
/opt/loopx-src      LoopX 源码（docker cp 进去）
/opt/loopx-py       可移植 python
/opt/loopx-node     可移植 node
/opt/lxprofile/     profile 根
    bin/loopx       install-local.sh 生成的 wrapper
    codex-home/     CODEX_HOME（config.toml、skills/）
    registry.json
    runtime/
```

LoopX `dependencies = []`，零第三方依赖，`install-local.sh` 只拷文件 + 生成 wrapper，所以断网容器里装得起来。

**node 必须在 PATH 上**：`doctor` 用 `shutil.which("node")` 找它，TS control plane 要 node ≥ 22.6。装配和后续所有 CLI 调用都用这套环境：

```
PATH=/opt/loopx-node/bin:/opt/lxprofile/bin:/usr/local/bin:/usr/bin:/bin
HOME=/opt/lxprofile/home   CODEX_HOME=/opt/lxprofile/codex-home
LOOPX_PYTHON=/opt/loopx-py/bin/python3
```

（**查容器内状态时也要用这套**，否则 `loopx status` 会报 `status_collection_failed`，看着像 LoopX 坏了，其实是你没给 PATH。）

### 三道门禁，任何一道不过就硬失败

1. **技能齐全**：`_REQUIRED_SKILLS` 从上游常量 `NATIVE_CODEX_PROFILE_REQUIRED_SKILL_IDS` 读，**不要硬编码**——0.5.3 是 7 个，历史值是 6 个，硬编码会漏掉 `loopx-benchmark`
2. **`doctor` 通过**：`loopx --format json doctor --agent-type codex-app-ssh`
3. **`skills/list` 发现**：`native_codex_goal` 在 `thread/start` **之前**发 `skills/list`，codex 没真的发现那些 skill 就直接失败，**一个 token 都不花**——这是最省钱的门禁

装配成功的日志长这样：`LoopX profile 就绪（7 skills + CLI + doctor ok）`

### goal body 渲染

`render_native_codex_goal_prompt` 产出的 body 里带 `$HOME/.codex/loopx/registry.global.json` 占位符，**必须替换成真实 registry 路径，替换后还要验证占位符确实消失**。

日志：`LoopX goal body 已渲染（2953 字符，goal_id=lhtb-goal，ungated=True）`。字符数按模式不同（heartbeat 1682 / codex-cli 2931 / ssh-goal 2953），这是模式确实分开渲染的证据。

### 运行期状态写在仓库里

`/app/.codex/goals/<goal-id>/ACTIVE_GOAL_STATE.md`，Agent Todo 带完整元数据：

```markdown
- [x] [P1] Identify the fastest validation command from Cargo.toml ...
  <!-- loopx:todo todo_id=todo_d657c9f294e2 status=done
       successor_todo_ids=todo_909ae1136cbc completion_continuation=successor
       evidence=cargo check -p rusternetes-common exited 0 in 48.88s; ...
       completed_at=2026-09-01T05:46:28 -->
```

这是 LoopX "跨 turn 不丢上下文"的落地形式：自举出候选待办 → 带证据完成 → 派生后继。实测 LoopX CLI 调用占工具调用的 12–37%。

**注意**：`agent/` 目录保存了 sessions / goals sqlite / trajectory，但**没有保存 `registry.json`**，所以已完成 trial 的最终 todo 状态查不到，只能对在跑的容器采样。要在报表里给这个，得把 registry 加进 `_save_sessions` 的拷贝清单。

### 一个装配期的坑

`pip install -e` 会在源码树里留下 `loopx.egg-info`，`docker cp` 时被一起带进容器，污染 profile。改用非编辑安装 + 容器侧清理。

## 坑（按危险程度排）

### 一、"只杀对照组"的偏向性 —— 会得出**反向结论**

同一个故障如果只打某一条臂，最终会显示"另一条臂更强"，而那是基础设施差异。已发现四次：

1. **TPM 限流**只杀 `plain`（裸 codex 上下文线性膨胀，单请求 116k token）→ 降并发 + 压预算
2. **HTTP 400 `internal_chat_message_metadata_passthrough`** 只打 `plain`（只在 `codex exec` 路径出现）→ `scripts/param_strip_proxy.py` 剥字段
3. **传输通道不同**：`plain` 走 SSE，其余四臂走 app-server，SSE 在 routify 上 2/2 全错 → 新增 `codex_plain_appserver.py`，plain 也走 app-server
4. **异常类分裂**（下条单列）

**判据**：任何时候看到某条臂的失败率显著高于其他臂，先假设是基础设施，不要先假设是能力。

### 二、同名异常类分裂 —— 整晚三条臂颗粒无收

`NativeGoalProtocolError` 存在两份：

```
agents/native_codex_goal.py                            ← 符号链接到 wen/loopx 源码树
loopx.capabilities.benchmark_toolkit.native_codex_goal ← 装在 .venv
```

互不为子类。`run()` 里按**类**捕获 `goal_timeout_before_terminal` 的后果：只有 `goal` 臂的超时被吞掉并正常评分，LoopX 三臂的超时逃到 harbor 被当基础设施故障 → 重试 → 记 errored，几小时的真实进度全丢。

**修法**：按**消息**判定（两个类都继承 `RuntimeError`）。

```python
except RuntimeError as exc:
    if str(exc) != "goal_timeout_before_terminal":
        raise
```

超时是长程任务的**正常预算耗尽**，五臂必须一视同仁按部分进度评分。

### 三、二值 reward 在紧预算下没有区分度

SWE-Marathon 的 `reward` 是二值的（全部测试通过才给 1）。实测：**撞死线的 23 条 trial 无一得分，自己收尾的 14 条中 11 条得分**——决定分数的是"任务能不能在预算内做完"，不是哪条臂。

连续分在 `metrics.json` 的 `partial_score`（任务官方定义，[0,1]）。用 `scripts/_partial.py` 提取。两个坑：

- **字段名不统一**：有的任务只写 `pass_rate`
- **不是所有任务都真连续**：`s3-clone` 有 correctness+ux 两阶段，后一阶段按 `0.5×unit + 0.5×cua` 改写 `partial_score`，而两个子分各自二值 → 22 个 gate 过 16 个、pytest 87.7%，`partial_score` 仍是 0.0
- **Rust 任务有构建门禁**：`BUILD FAILED` → `partial_score` 直接归零。同一条臂早一分钟或晚一分钟被切断，分数可能在 0 和 0.98 之间跳变

所以报表要**两个口径并排**（partial_score + 测试通过率），且把 `build_failed` 单独标注。

### 四、`BUILD FAILED` 不是环境故障

它发生在 **verifier 阶段**（agent 早跑完了），是 `cargo` 编译 **agent 写的代码**。典型报错是"缺东西"而不是"写错了"：

```
can't find lib `xxx` at path `src/lib.rs`        Cargo.toml 声明了但没建文件
error[E0432]: unresolved imports ...              import 了还没定义的类型
couldn't read `src/client.rs`: No such file       测试引用的源文件不存在
```

排除环境嫌疑的三个交叉验证：同环境下别的臂构建成功；四条臂报错在四个不同 crate；网络类关键词（`failed to download` / `registry` / `no matching package`）命中 0 次。

harbor 记 `n_errored_trials=0`，**不作废**。对比真正的环境故障：

```
Docker compose command failed ... all predefined address pools have been fully subnetted
```
那种记 `n_errored_trials=1`，**要作废重跑**。

### 五、docker 网段池 —— 一次废掉 12 条

默认地址池只支持约 32 个 bridge 网络（一个 RFC 1918 私网池切成 16 个子网，另一个私网池再切成 16 个子网）。**机器是共用的**，别人常年占约 15 个，每个 trial 一个 compose 网络。撑爆后新 trial 直接死在环境启动。

泄漏源常常是自己：**`docker rm -f` 只删容器，不删 compose 网络**。清理容器时必须连网络一起清。

`marathon_all.sh` 有起跑前闸门（`MARATHON_NET_CAP/NET_MARGIN`），等待时顺手回收空网络。扩池要改 `daemon.json` + 重启 dockerd，**会杀掉别人所有容器**，需要本人操作并先打招呼。

### 六、清理进程：绝不用模糊匹配（已犯五次）

`pkill -f` / `pgrep -f` / `case` 匹配 `/proc/cmdline` 都会命中**调用者自己的 shell**——因为命令文本里就含那些字样。第五次的表现是 TERM 发给自己、shell 在清容器之前就死（退出码 144）。

正确写法：模式用字符串拼接构造，让命令行里不出现完整字面量，再显式排除 `$$` 和 `$PPID`：

```bash
PAT=$'marathon''_all.sh'; ME=$$; PA=$PPID
for p in /proc/[0-9]*; do pid=${p#/proc/}
  [ "$pid" = "$ME" ] && continue; [ "$pid" = "$PA" ] && continue
  cl=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null) || continue
  case "$cl" in *"$PAT"*) echo "$pid" >> /tmp/kill.txt;; esac
done
xargs -r kill -TERM < /tmp/kill.txt
```

另：`ps -eo` 里的 `-e` 会**覆盖** `-p`，`ps -eo pid= -p 123` 会列出全机进程。

### 七、监控工具本身出错比 trial 失败更危险

一天里监控工具错了七次，每次都表现为"看起来一切正常"：

| 错误 | 后果 |
|---|---|
| `health_check.sh` 扫 `marathon-jobs*` 而产物在 `marathon-full` | 整晚报 OK，实际三条臂全挂 |
| `find -mindepth 4` 而 job 级 `result.json` 在深度 5 | 永远查不到错误跑次 |
| `_summarize.py` 用 `glob("*/*")` 太浅 + 目录 mtime 排序 | 「0 完成 0 错误」而实际已有失败 |
| `_partial.py` 用 `m.parts[1]`，绝对路径下是 `mnt` | 异常被 `2>/dev/null` 吞掉，整段连续分静默消失 |
| `grep -c` 计数为 0 时退出码 1，`\|\| echo 0` 追加第二个 0 | 变量含换行，监控输出被拆成三行 |
| 计数不按「本次跑次」切分 | 跨重启累加，显示 37/90 而当次只排了 10 |
| `_receipts.py` 读 `unblock_count`（真名 `_unblock_count`，带下划线） | 五臂全返回 None，会永远报"解锁 0 次" |

**教训**：监控工具要和被测对象一样对待——先验证它真能看见东西。路径写错的监控比没有监控更坏，因为它每轮都报"正常"。

### 八、别拿环境不同的数据下结论

- **臂均值不可比**：各臂跑过的任务集不同。`ssh-goal` 均值低是因为它多跑了几个难任务。只用**双方都跑过的格**做配对比较
- **遗留目录要排除**：root 属主的旧跑次目录（`marathon_run.sh` 写不进去会另起 `<arm>-<pid>`），里面的 receipt 是上一轮的。`_receipts.py` 按臂目录属主排除
- **半成品 metrics 要排除**：正在重跑的 trial 也留 `metrics.json`，内容是 `phase: initialized`、partial 0.0，采信会**凭空造出一个 0 分**
- **查容器内状态要复现 agent 的环境**：`docker exec` 裸奔没有 PATH，`loopx doctor` 找不到 node 会报 `status_collection_failed`，看着像 LoopX 坏了。正确环境是
  `PATH=/opt/loopx-node/bin:/opt/lxprofile/bin:...  HOME=/opt/lxprofile/home  CODEX_HOME=/opt/lxprofile/codex-home`

### 九、其他单点

- **codex 缺 `codex-code-mode-host` sidecar**：容器里每次工具调用都失败，不报错、只是零产出。`stage_codex_offline.sh` 要镜像整个 vendor 树
- **app-server 需要 `sandbox_mode = "danger-full-access"` + `projects."/app" = { trust_level = "trusted" }"`**，否则 bwrap 缺用户命名空间，`initialize` 握手就失败
- **`config.toml` 必须一次性写完**：TOML 里 table 头之后的裸键都归该 table，分两次 `cat >>` 会让 `web_search` 变成 `model_providers.harbor.web_search`
- **LoopX 自锁**：goal body 规定连续三轮相同阻塞就 `update_goal status=blocked`，只有 user `/goal resume` 能复活——benchmark 里没有 user。`LOOPX_UNGATED=1` 让 harness 扮演 operator，解锁次数记进 receipt 的 `_unblock_count`
- **NAS 输出盘的 mtime 比宿主机慢约 2 分钟**，别用宿主机时间 `find -newermt` 筛产物
- **`$$` 在 bash 子 shell 里是父进程 PID**，认领文件要用 `$BASHPID`

## 产物与判据

```
marathon-full/<task>/<arm>/<stamp>/<arm>/result.json          job 级，含 stats
                                       /<trial>/verifier/     reward.txt / metrics.json / test-stdout.txt
                                                /agent/       trajectory.json / goal_receipt.json / sessions/
marathon-full/.claims/<task>__<arm>.claim                     在跑认领（内容是 BASHPID）
marathon-full/.driver_env                                     驱动参数，health_check --fix 会读
marathon-voided/                                              作废的 trial，带 README 说明原因
```

"成功"的统一判据（`scripts/_is_done.py`，断点续跑和监控共用，避免两处判据打架）：

```
n_completed_trials >= 1 且 n_errored_trials == 0
```

`errors > 0` **不算跑过**，必须重跑——那多半是基础设施故障。
