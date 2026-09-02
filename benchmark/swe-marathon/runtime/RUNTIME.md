# runtime：模式框架 + automation 驱动

codex×LoopX 对照所用的运行时。`heartbeat` 模式的续跑由**外部 driver**（`turn/loopx_turn_runner.py`）
拥有：每轮发 `--turn-instance-id` + 过 `quota should-run` 闸门，回合边界由 driver 保证，因此
无人自动化下最稳——不依赖人值守（codex-cli TUI）或 Codex 自身的 visible-Goal 循环（ssh-goal）。

## 结构

```
runtime/
  modes/
    profiles.py          # 声明式 Mode 表：ssh-goal / codex-cli / heartbeat
    run_mode.py          # CLI 入口：选模式、装 profile、跑 session
    session.py           # session 生命周期
    codex_host.py        # host 接线
    profile_install.py   # 把 loopx runtime profile / skills 装进 CODEX_HOME
  turn/
    loopx_turn_runner.py # automation 驱动：每轮 turn-instance + quota 闸门 + turn 超时 + HEAD-moved 进度检查
    loopx_native_codex.py# 原生 codex turn 驱动
    goal_codex.py        # visible-Goal turn 驱动（ssh-goal / codex-cli）
    codex_nosandbox_wrapper.py
```

## 三模式（见 modes/profiles.py）

| 模式 | runtime_profile | 续跑归属 | 备注 |
|---|---|---|---|
| ssh-goal | codex_app_ssh_goal | Codex（visible Goal） | guard 带 `--begin-turn`，原生无人值守路径 |
| codex-cli | codex_cli | Codex（visible Goal） | guard **不带** `--begin-turn`（人值守 TUI 设计） |
| heartbeat | generic_cli | **driver**（本运行时） | driver 拥有唤醒，无人自动化下最鲁棒 |

## 依赖

- `loopx.capabilities.benchmark_toolkit`（native_codex_goal / native_codex_profile）。
- 试验/agent 框架（harbor）提供环境与已安装的 Codex agent。
- 环境变量旋钮，如 `MR_LOOPX_TURN_TIMEOUT`（每轮超时秒，默认 1200）。

未内嵌任何内部网络拓扑或凭证；环境相关接线（网关、代理）由环境变量在外部提供。
