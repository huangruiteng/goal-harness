# SWE-Marathon: codex × LoopX 评测总结

> 📊 **交互式可视化 + 逐 trial 轨迹浏览**：https://bouwenzhou.github.io/loopx/
>
> 下面是静态总结报告；网页版含五模式对比总表、逐任务热力、以及每个 trial 的完整执行轨迹。


> 在 SWE-Marathon（Harbor 环境）15 个五模式齐全的长程软件工程任务上，对比裸
> `codex`、codex **原生 goal**、以及在其之上叠加 LoopX 的三种模式。模型 `gpt-5.6`，
> agent 预算被压到任务声明时限的 **~30%**（`agent_timeout_multiplier=0.3`），刻意
> 制造"做不完"的紧预算，以放大不同接入方式在**续跑 / 自我收尾**上的差别。
>
> 共 **75 个 trial**（15 任务 × 5 模式），每格 1 trial。每个 trial 的完整执行轨迹
> 可在配套网页的"轨迹浏览"里逐步查看。

## 1. 实验设置：两条 baseline + 三个 LoopX 模式

| 模式 | 归属 | 含义 |
|---|---|---|
| **plain** | baseline① | 裸 codex，objective 固定 `"Finish the task."`，无 goal、无 LoopX |
| **goal** | baseline② | **codex 原生 goal**（codex 自带的 goal 功能），注入干净的 goal，**非 LoopX** |
| **ssh-goal** | LoopX① | codex 原生 goal + LoopX 渲染的 goal body / skills，经 ssh 驱动 |
| **codex-cli** | LoopX② | 容器内跑 `loopx` CLI 现渲 goal body（带 claim/lease/peer 样板） |
| **heartbeat** | LoopX③ | 心跳驱动的续跑 / 解锁 + LoopX goal body / skills |

关键：`goal` 是 **codex 自己的** goal 机制，不是 LoopX。真正的 LoopX 只有后三个模式。
所以本报告有**两个对照锚点**：plain→goal 衡量 codex 原生 goal 的价值，
goal→{ssh-goal, codex-cli, heartbeat} 才衡量 **LoopX 在 codex 原生 goal 之上的增量**。

> 验证依据：`goal` 模式注入的 goal body 是干净的任务描述（不含 LoopX 的
> `advance loopx / lease / peer / lhtb-goal / registry` 等词），而三个 LoopX 模式
> 15/15 的 goal body 都带这套样板。见第 5 节的使用真实性核查。

### 评分口径（重要）

- Harbor 的 `reward` 是**二值**的（多数任务要求全部测试通过才给 1）。在 ~30% 的紧
  预算下它几乎全 0，单看它区分度很低。
- 因此以任务自带的**连续分**为主：`partial_score`（写在 `/logs/verifier/metrics.json`）。
- 构建失败（Rust 类任务）会让 `partial_score` 被门禁**直接归零**，单独标注（✗），
  并**从 reward / partial 的均值中剔除**——那是环境/门禁问题、不是能力信号。
- 模式均值只在**五模式都跑过的 15 个任务**上算，避免任务集差异冒充能力差异。

## 2. 总表（仅 15 个五模式齐任务）

| 模式 | 归属 | reward | partial_score | 花费 | **自己收工** | 续跑 | 解锁 | 构建失败 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| plain | base① | 0.267 | 0.710 | $368 | **0/15** | 0 | 0 | 0/15 |
| goal | base② | 0.267 | 0.767 | $533 | **12/15** | 7 | 0 | 0/15 |
| ssh-goal | LoopX | 0.267 | 0.773 | $696 | 14/15 | 40 | 0 | 0/15 |
| codex-cli | LoopX | 0.214 | 0.702 | $419 | 12/15 | 37 | 19 | 1/15 |
| heartbeat | LoopX | **0.333** | **0.778** | $830 | 13/15 | 42 | 8 | 0/15 |

> codex-cli 的 reward / partial 按 **14 个非构建失败任务**计（kubernetes-rust-rewrite
> 已剔除）；其余四模式为 15 个。花费 / 自收工 / 续跑 / 解锁按全量 15 个。

## 3. 结论

1. **对裸 codex 的提升，绝大部分来自 codex 自己的 goal 功能，不是 LoopX。**
   plain→goal（codex 原生）：partial 0.710→0.767（+0.057），**自己收工 0/15→12/15**。
   紧预算下"会不会主动收尾交付而不是撞死线被砍"这个最显著的行为差异，**codex 原生
   goal 已经拿到了绝大部分**。

2. **LoopX 三模式在 codex 原生 goal 之上的增量很小，且更贵。**
   以 goal（0.767 / 自收工 12/15 / $533）为锚：
   - ssh-goal：partial +0.006、自收工 +2（14/15），但花费 +$163（$696）；
   - heartbeat：partial +0.011（最高 0.778）、reward 唯一上移（0.333，多解 kubernetes、zstd
     两题），但最贵 $830（1.56× goal、2.25× plain）；
   - codex-cli：partial −0.065（0.702，剔除构建失败后仍低于 goal），更便宜（$419）。

   即：**LoopX 的续跑/心跳把连续分再抬 1 个百分点级别的量，代价是 30–56% 的额外花费**；
   binary reward 只有 heartbeat 能撬动。

3. **代价随续跑机制上升**：续跑合计 ssh-goal 40 / codex-cli 37 / heartbeat 42，
   对应花费也最高。heartbeat 是"分数换钱"最激进的一档。

4. **codex-cli 是最弱的 LoopX 模式，也是唯一撞到构建失败的模式。** 剔除那次构建失败
   后 partial 0.702、reward 0.214，仍低于 goal 与另两个 LoopX 模式。它的 goal body
   由容器内 `loopx heartbeat-prompt --thin` **现场渲染**，带出了 LoopX 老家（多智能体
   在 git 仓库上协作跑 PR）的通用样板——claim/lease、peer lane、independent repo、
   PR program。而 SWE-Marathon 任务**没有 repo / peer / PR / 租约**可对应，这套词对
   单机任务是**错配的**，也解释了它 19 次"解锁"（在自造阻塞上空转）为何最多。这是
   一个已定位的 confound，不是 LoopX 机制本身的上限。

## 4. 逐任务要点

| 任务 | plain | goal | ssh-goal | codex-cli | heartbeat | 备注 |
|---|---|---|---|---|---|---|
| find-network-alignments | 0/**0.00** | 0/0.88 | 0/0.79 | 0/0.87 | 0/0.86 | plain 归零，有 goal 的四模式全线 0.8+ |
| zstd-decoder | 0/0.72 | 0/0.86 | **1/1.00** | 0/0.60 | **1/1.00** | 续跑把 ssh-goal / heartbeat 送到满分 |
| kubernetes-rust-rewrite | 0/1.00 | **1**/1.00 | 0/1.00 | **0/0.00✗** | **1**/1.00 | codex-cli 构建失败归零 |
| ruby-rust-port | **1**/1.00 | 0/0.98 | 0/0.99 | 0/0.98 | 0/0.98 | 少见地 plain 二值 reward 反超 |
| stripe-clone | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 五模式全解 |
| vliw-kernel-optimization | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 五模式全解 |
| wasm-simd | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 五模式全解 |
| biofabric-rust-rewrite | 0/0.98 | 0/0.96 | 0/0.97 | 0/0.97 | 0/0.97 | 408 个测试，差在最后几个 |
| nextjs-vite-rewrite | 0/0.99 | 0/0.99 | 0/0.99 | 0/0.94 | 0/0.99 | 普遍接近满分 |
| rust-c-compiler | 0/0.98 | 0/0.97 | 0/0.97 | 0/0.98 | 0/0.98 | 五模式接近 |
| excel-clone | 0/0.49 | 0/0.50 | 0/0.49 | 0/0.49 | 0/0.50 | 半程停在 ~0.5 |
| s3-clone | 0/0.50 | 0/0.46 | 0/0.46 | 0/0.50 | 0/0.46 | 多阶段+CUA 评审，卡在 0.5 |
| slack-clone | 0/0.50 | 0/0.50 | 0/0.48 | 0/0.50 | 0/0.50 | 卡在 0.5 |
| mastodon-clone | 0/0.50 | 0/0.41 | 0/0.46 | 0/0.00 | 0/0.44 | codex-cli 归零 |
| rust-java-lsp | 0/0.00 | 0/0.00 | 0/0.00 | 0/0.00 | 0/0.00 | 五模式全灭，紧预算下无人破题 |

*每格 = `reward | partial_score`；✗ = 构建失败，partial 被门禁归零。*

## 5. LoopX 使用真实性核查（两层介入）

为回答"LoopX 三模式的轨迹里到底有没有真的 LoopX 调用"，把轨迹里的 LoopX 介入分两层数：

**第 1 层——harness 施加的 LoopX 机制（goal body 注入 + 续跑再唤醒）：真实、统一存在。**

| 模式 | 每 trial 被再唤醒(goal_updated) | goal body 带 LoopX 样板 | 续跑合计 | 解锁合计 |
|---|---:|---:|---:|---:|
| plain | 0/15 | — | 0 | 0 |
| goal（codex 原生） | 15/15 | 0/15（干净 goal） | 7 | 0 |
| ssh-goal | 15/15 | 15/15 | 40 | 0 |
| codex-cli | 15/15 | 15/15 | 37 | 19 |
| heartbeat | 15/15 | 15/15 | 42 | 8 |

三个 LoopX 模式 15/15 都注入了带 claim/lease/peer 的 LoopX goal body，且每个 trial 都被
续跑循环再唤醒——**这层是真的**，不是空壳；`goal` 模式虽也被再唤醒，但注入的是干净 goal。

**第 2 层——agent 自己敲 `loopx` CLI：很稀疏。**

| 模式 | 真 CLI 调用的 trial | 说明 |
|---|---|---|
| goal | 0/15 | codex 原生，容器里本就没有 loopx |
| ssh-goal | 2/15 | 偶尔 `loopx status/todo/read-only-map`；轨迹里几百次"loopx"几乎全是**读 `skills/loopx/SKILL.md`**，非执行 |
| codex-cli | 1/15 | goal body 由 harness 现渲，agent 自己基本不调 |
| heartbeat | 4/15 | 有货真价实的 `loopx status / todo complete / quota should-run / refresh-state`，集中在 biofabric、kubernetes 等少数任务 |

**含义**：本轮测到的"LoopX 效果"主要来自 **harness 的续跑循环**（把 agent 反复唤醒去
收尾），而**不是** agent 主动用 LoopX 工具做自我编排。而续跑带来的"自我收尾"能力，
**codex 原生 goal 已经提供了绝大部分**，LoopX 在其上的增量有限。

## 6. 复现

```bash
cd wen
.venv/bin/python scripts/_aggregate.py    marathon-full viz/data.json          # 聚合为单一 JSON
.venv/bin/python scripts/_extract_traj.py marathon-full viz/trajectories       # 抽逐 trial 轨迹
.venv/bin/python scripts/_build_viz.py    viz/data.json viz/SUMMARY.md viz/index.html
.venv/bin/python scripts/_compare.py      marathon-full                        # 终端对照表
```

聚合口径（模式名归一化、只认 job 级 result.json、属主校验、半成品 metrics 排除、
cost 取 `cost_usd`）与 `scripts/_compare.py`、`scripts/_partial.py` 一致。

---
*生成于 2026-09-02。数据：`wen/marathon-full`（75 trial）。配套网页含逐 trial 轨迹浏览。*
