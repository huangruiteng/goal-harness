# codex × LoopX 在 SWE-Marathon 上的总结报告（探索性）

> **性质**：单次（每格 1 trial）、紧预算下的**探索性观察**，不是可下因果结论的对照实验。
> 数值为描述性统计；机制解释均为**假设**，需重复的匹配实验才能证实。
>
> **数据边界**：本报告只发布 **public-safe 聚合**（见同目录 `data.json`）。逐 trial 的
> 原始轨迹（reason / exec / 工具输出 / 消息 / goal 原文）按 LoopX benchmark 契约**保留在
> 私有存储，不公开**。

在 SWE-Marathon（Harbor 环境）15 个五模式齐全的任务上，对比裸 `codex`、codex 原生
`goal`、以及在其上叠加 LoopX 的三种模式。模型 `gpt-5.6`，agent 预算压到任务声明时限的
**~30%**（`agent_timeout_multiplier=0.3`）。共 **75 个 trial**（15 任务 × 5 模式，每格 1 trial）。

## 1. 实验设置：两条 baseline + 三个 LoopX 模式

| 模式 | 归属 | 含义 |
|---|---|---|
| **plain** | baseline① | 裸 codex，objective 固定 `"Finish the task."`，无 goal、无 LoopX |
| **goal** | baseline② | **codex 原生 goal**（codex 自带的 goal 功能），注入干净 goal，**非 LoopX** |
| **ssh-goal** | LoopX① | codex 原生 goal + LoopX 渲染的 goal body / skills，经 ssh（codex_app）驱动 |
| **codex-cli** | LoopX② | codex_cli 渲染 goal body（人值守 TUI 模式，无人跑靠传输替代） |
| **heartbeat** | LoopX③ | 心跳驱动的续跑 / 解锁 + LoopX goal body / skills（automation 驱动） |

`goal` 是 **codex 自己的** goal 机制，不是 LoopX。两条对照锚点：plain→goal 看 codex 原生
goal 的价值，goal→{ssh-goal, codex-cli, heartbeat} 看 LoopX 在其上的增量。

> 验证依据：`goal` 的 goal body 是干净任务描述（不含 `advance loopx / lease / peer /
> lhtb-goal / registry`），而三个 LoopX 模式 15/15 都带这套样板。

### 评分口径

- Harbor 的 `reward` 是**二值**的；紧预算下几乎全 0，区分度低。
- 主指标用任务自带的连续分 `partial_score`。
- **构建失败**（Rust 类任务，`partial_score` 被门禁归零）**作为观测结果计入**，不做单臂
  剔除；另用"构建失败"列单独标注。**所有模式共用同一 15 任务分母**（matched），避免不匹配
  分母冒充能力差异。

## 2. 总表（15 个五模式齐任务，matched 分母）

| 模式 | 归属 | reward | partial_score | 花费 | 自己收工 | 续跑 | 解锁 | 构建失败 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| plain | base① | 0.267 | 0.710 | $368 | 0/15 | 0 | 0 | 0/15 |
| goal | base② | 0.267 | 0.767 | $533 | 12/15 | 7 | 0 | 0/15 |
| ssh-goal | LoopX | 0.267 | 0.773 | $696 | 14/15 | 40 | 0 | 0/15 |
| codex-cli | LoopX | 0.200 | 0.655 | $419 | 12/15 | 37 | 19 | **1/15** |
| heartbeat | LoopX | 0.333 | 0.778 | $830 | 13/15 | 42 | 8 | 0/15 |

> codex-cli 的 `1/15` 构建失败（kubernetes-rust-rewrite）已计入其 reward/partial，未剔除。

## 3. 观察（描述性；机制为假设）

单 trial/格、无不确定度、多机制同变（prompt + driver + continuation + unlock）且存在已知
prompt confound，因此以下均为**描述性观察与待验证假设**，非因果结论。

1. **plain→goal 的提升与 codex 原生 goal 同现**：partial 0.710→0.767、自收工 0/15→12/15。
   在本次数据里，紧预算下"主动收尾"这个行为差异，codex 原生 goal 已呈现绝大部分。（假设：
   多数收益来自原生 goal，需重复匹配实验验证。）

2. **LoopX 三模式相对 goal 的增量较小、且更贵**：以 goal（0.767 / 自收工 12/15 / $533）为锚，
   ssh-goal partial +0.006、heartbeat +0.011（最高 0.778）、codex-cli −0.112（0.655）；花费
   ssh-goal $696、heartbeat $830、codex-cli $419。binary reward 仅 heartbeat 上移（0.333）。

3. **codex-cli 最弱、且是唯一构建失败**（0.200 / 0.655）。**一个可能的解释**：其 goal body 由
   `codex_cli` profile 渲染，带 LoopX 多智能体 git 协作样板（claim/lease/peer/PR），对单机
   SWE-Marathon 任务错配；它的解锁 19 次为各模式最多，与"在错配样板上空转"一致。这是**假设**，
   非定论（见配套机制分析：codex-cli 与 ssh-goal 的 goal body 逐字节几乎相同，唯一差 guard 的
   `--runtime-profile` 与是否带 `--begin-turn`）。

## 4. 逐任务矩阵（15 × 5，matched）

| 任务 | plain | goal | ssh-goal | codex-cli | heartbeat |
|---|---|---|---|---|---|
| find-network-alignments | 0/0.00 | 0/0.88 | 0/0.79 | 0/0.87 | 0/0.86 |
| zstd-decoder | 0/0.72 | 0/0.86 | 1/1.00 | 0/0.60 | 1/1.00 |
| kubernetes-rust-rewrite | 0/1.00 | 1/1.00 | 0/1.00 | 0/0.00✗ | 1/1.00 |
| ruby-rust-port | 1/1.00 | 0/0.98 | 0/0.99 | 0/0.98 | 0/0.98 |
| stripe-clone | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 |
| vliw-kernel-optimization | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 |
| wasm-simd | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 | 1/1.00 |
| biofabric-rust-rewrite | 0/0.98 | 0/0.96 | 0/0.97 | 0/0.97 | 0/0.97 |
| nextjs-vite-rewrite | 0/0.99 | 0/0.99 | 0/0.99 | 0/0.94 | 0/0.99 |
| rust-c-compiler | 0/0.98 | 0/0.97 | 0/0.97 | 0/0.98 | 0/0.98 |
| excel-clone | 0/0.49 | 0/0.50 | 0/0.49 | 0/0.49 | 0/0.50 |
| s3-clone | 0/0.50 | 0/0.46 | 0/0.46 | 0/0.50 | 0/0.46 |
| slack-clone | 0/0.50 | 0/0.50 | 0/0.48 | 0/0.50 | 0/0.50 |
| mastodon-clone | 0/0.50 | 0/0.41 | 0/0.46 | 0/0.00 | 0/0.44 |
| rust-java-lsp | 0/0.00 | 0/0.00 | 0/0.00 | 0/0.00 | 0/0.00 |

*每格 = `reward | partial_score`；✗ = 构建失败，partial 被门禁归零（仍计入均值）。*

## 5. LoopX 使用真实性（harness 层 vs agent 层）

- **harness 层（goal body 注入 + 续跑再唤醒）**：三个 LoopX 模式 15/15 都注入了带 LoopX
  样板的 goal body、每个 trial 都被续跑循环再唤醒——这层真实、统一存在。
- **agent 自己敲 `loopx` CLI**：稀疏——ssh-goal 2/15、codex-cli 1/15、heartbeat 4/15；轨迹里
  多数"loopx"字样是读 `SKILL.md`，非执行。

> 以上计数为聚合口径。更强的证据（typed countability / treatment-fidelity receipt）尚未提供，
> 结论按此保留为观察而非认证。

## 6. 复现与血缘

**公开可复现的部分**：从本目录 pinned 的 public-safe 聚合 `data.json` 重算所有表格：

```bash
# data.json 为 public-safe 聚合产物（无 raw 轨迹）；表格可直接由它重算
python3 - <<'PY'
import json; d=json.load(open("data.json"))
for a in d["arms"]:
    s=d["arm_summary"][a]; print(a, "partial=%.3f reward=%.3f cost=$%.0f self=%d/%d"
        % (s["partial"], s["reward"], s["cost"], s["self_complete"], s["n"]))
PY
```

**从原始结果树重算 `data.json`**（需私有数据 + 评测 harness，见 companion PR **#3842**）：

```bash
# 脚本随 #3842 落在 benchmark/swe-marathon/scoring/
python3 benchmark/swe-marathon/scoring/_aggregate.py <private_results_dir> data.json
python3 benchmark/swe-marathon/scoring/_compare.py   <private_results_dir>
```

**血缘 / 已知项**：模型 `gpt-5.6`；bench=swe-marathon；`agent_timeout_multiplier=0.3`；
75 trial（15×5，每格 1）；聚合口径见 `scoring/_common.py`。原始 75-trial 结果树按 LoopX
契约**私有**，不随本 PR 公开。本 PR 依赖 / 应与 **#3842**（harness + scoring）合并评审。

---
*探索性观察，生成于 2026-09-02。public-safe 聚合见 `data.json`；原始轨迹私有。*
