# SWE-Marathon：codex × LoopX 评测

裸 `codex`、codex 原生 `goal`、以及三种 LoopX 接入模式在 SWE-Marathon（Harbor）15 个任务上的对照。
模型 `gpt-5.6`；agent 预算压至任务时限的 ~30%（`agent_timeout_multiplier=0.3`）；共 75 trial（15×5，每格 1）。
目标是在长程领域产出可复算的一手对照，为"无人自动化默认姿势"提供评测证据。

> **性质**：单次、每格 1 trial、多机制同变的**探索性观察**。数值为描述性统计，机制陈述为假设，需重复的匹配实验方能证实。
>
> **数据边界**：仅发布 public-safe 聚合（`data.json`）。逐 trial 原始轨迹按 LoopX benchmark 契约保留私有。

## 1. 模式

| 模式 | 归属 | 说明 |
|---|---|---|
| `plain` | baseline① | 裸 codex，objective 固定 `"Finish the task."` |
| `goal` | baseline② | codex 原生 goal（非 LoopX），注入干净 goal |
| `ssh-goal` | LoopX | codex 原生 goal + LoopX goal body/skills，codex_app over ssh |
| `codex-cli` | LoopX | codex_cli 渲染 goal body（人值守 TUI 模式，无人跑靠传输替代） |
| `heartbeat` | LoopX | 外部调度器驱动的续跑/解锁（automation） |

两条对照锚点：`plain→goal` 衡量 codex 原生 goal 的价值；`goal→{ssh-goal, codex-cli, heartbeat}` 衡量 LoopX 的增量。

## 2. 评分口径

- `reward` 为二值，紧预算下几乎全 0；主指标用任务连续分 `partial_score`。
- 构建失败（partial 被门禁归零）作为观测结果计入，所有模式共用同一 15 任务 matched 分母（无单臂剔除），另列标注。

## 3. 结果（15 个 matched 任务）

| 模式 | reward | partial | 花费 | 自收工 | 续跑 | 解锁 | 构建失败 |
|---|---:|---:|---:|---:|---:|---:|---:|
| plain | 0.267 | 0.710 | $368 | 0/15 | 0 | 0 | 0/15 |
| goal | 0.267 | 0.767 | $533 | 12/15 | 7 | 0 | 0/15 |
| ssh-goal | 0.267 | 0.773 | $696 | 14/15 | 40 | 0 | 0/15 |
| codex-cli | 0.200 | 0.655 | $419 | 12/15 | 37 | 19 | 1/15 |
| heartbeat | 0.333 | 0.778 | $830 | 13/15 | 42 | 8 | 0/15 |

## 4. 观察（描述性；机制为假设）

1. `plain→goal`：partial 0.710→0.767、自收工 0/15→12/15。紧预算下"主动收尾"这一行为差异，本次数据中主要与 codex 原生 goal 同现。
2. LoopX 三模式相对 `goal` 的连续分增量较小（ssh-goal +0.006、heartbeat +0.011、codex-cli −0.112），成本更高；binary reward 仅 heartbeat 上移。
3. codex-cli 最弱且唯一构建失败。其解锁 19 次为各模式最多，与"在错配的 LoopX 多智能体样板（claim/lease/peer）上空转"一致（假设）。

## 5. 逐任务矩阵（reward | partial；✗=构建失败）

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

## 6. LoopX 使用真实性

- harness 层（goal body 注入 + 续跑再唤醒）：三个 LoopX 模式 15/15。
- agent 自调 `loopx` CLI：稀疏（ssh-goal 2/15、codex-cli 1/15、heartbeat 4/15）；轨迹中多数 "loopx" 为读 `SKILL.md`。

## 7. 机制观察（假设）

- **codex-cli ≈ ssh-goal，差异可能主要来自 harness 与 continuation 方式**：两者 goal body 逐字节几乎相同，唯一差异是 guard 行的 `--runtime-profile` 与是否带 `--begin-turn`。无人自动化下 codex-cli 缺 `--begin-turn`，多轮续跑退化为空转（如 kubernetes：11 轮仅 13 次工具调用、终态 blocked），而 ssh-goal 每轮均有效工作。这与"能力相当、差异主要在 harness 与 continuation 方式"的假设一致，仍需更多重复匹配实验验证。
- **本轮未观察到明显的 H1（prompt 漂移）**：跨轮注入除 `Tokens used` 计数器外无变化，automation 与 goal 的注入内容本轮均未见漂移。
- **goal 内部续跑 prompt 干扰（H2，当前较有解释力的假设）**：`goal` 携带大量 LoopX 生命周期记账引导（claims/leases/successor/refresh-state/classification），且卡壳处理是"第三次相同 blocked 轮即 cancel"；`heartbeat` 派发器用"配额节拍 + 卡两次即 **replan** + 干净 writeback"替代了这些，续跑由外部 driver 拥有、每轮以当前 worktree 重新锚定。长程反复卡壳时，replan 比 cancel 更能续命。此类 goal 内部续跑 prompt 的干扰在交互体验中不易察觉，主要由评测暴露。

> **方向（趋势，非定论）**：本次数据中，无人值守长程下由外部 driver 拥有续跑的 automation（heartbeat）最鲁棒，与"将 automation 作为无人自动化默认姿势"的方向一致；作为最佳实践仍需重复的匹配实验确认。

## 8. 代码结构

```
agents/    Harbor 适配器（LoopX treatment + codex 原生 goal baseline）
scoring/   评分/聚合/可视化（口径见 _common.py）
skills/    两个五模式 benchmark skill
runtime/   模式框架 + turn 驱动，含 automation 唤醒循环 loopx_turn_runner.py（见 runtime/RUNTIME.md）
data.json  pinned public-safe 聚合产物
```

依赖 `loopx.capabilities.benchmark_toolkit` 与 harbor；内部网络拓扑与凭证未内嵌。

## 9. 复现与血缘

```bash
# 从 pinned 聚合直接重算表格（public-safe，无需 raw）
python3 - <<'PY'
import json; d=json.load(open("data.json"))
for a in d["arms"]:
    s=d["arm_summary"][a]; print(a,"partial=%.3f reward=%.3f cost=$%.0f self=%d/%d"%(
        s["partial"],s["reward"],s["cost"],s["self_complete"],s["n"]))
PY

# 从原始结果树重算 data.json（需私有数据 + harness）
python3 scoring/_aggregate.py <private_results_dir> data.json
python3 scoring/_compare.py   <private_results_dir>
```

**血缘 / 版本**：

| 组件 | 版本 |
|---|---|
| model | `gpt-5.6` |
| Codex | `0.151.0` |
| LoopX | `0.5.3`（repo `bd52b28a`） |
| harness (harbor) | `0.20.0` |
| benchmark / verifier | SWE-Marathon（Harbor 任务集，`partial_score` 由任务 verifier 写入 `/logs/verifier/metrics.json`） |
| 预算 | `agent_timeout_multiplier=0.3`（~30%） |
| 规模 | 75 trial（15 任务 × 5 模式，每格 1） |

原始 75-trial 结果树按 LoopX 契约**私有**，不随本 PR 公开。本 PR 为 exploratory research contribution；portable harness、统一 benchmark evidence、missing-score policy、重复 adapter 与 benchmark-toolkit 的收敛按维护者约定作为后续 follow-up。
