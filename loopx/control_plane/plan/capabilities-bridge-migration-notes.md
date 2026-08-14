# Capability-Pack Bridge — Migration Notes

> 状态：P1/P2/P3 已实现并测试通过（`tests/control_plane/test_capabilities_bridge.py`）。
> 本文件记录桥接引入的**行为变更**与**边界**，供迁移与运维参考。

## 背景

老框架（`loopx/capabilities`）通过三条独立路径挂载能力包：

1. `cli.py` 静态 import 各包的 `register_*_commands`（能力包 = CLI 子命令）；
2. `catalog.py` 的 `BUILTIN_CAPABILITIES` 元数据 + `CapabilityRegistry`（只读发现）；
3. 能力包函数被硬编码 import 进 `quota.py` / `configure_goal.py` / `heartbeat_prequota.py` / `lark_inbox.py` 等 90+ 处钩子。

新框架的 capability 标签（`required_capabilities` / `target_capabilities`）与老框架能力包目录原本完全解耦。
`capabilities_bridge.py` 将两者桥接起来，分三阶段：

- **P1**：token 归一化（`capability_token`），任务 `capability_binding_ref` 参与 `eligible` 判定；
- **P2**：`discover_cli_registrars` 反射式注册替代 12 处静态 import；
- **P3**：`CapabilityEventHub` 事件订阅底座 + `CapabilityHookRegistry` 钩子注册表（heartbeat pre-quota 已接入）。

## 行为变更（重要）

1. **带 binding 的任务要求 worker 声明 pack token**。
   旧行为：任务只要带 `capability_binding_ref` 且无显式 `required_capabilities`，任何 worker 都可 claim。
   新行为：`eligible()` 在任务带 binding 时走 `eligible_bridged`，把绑定包 token 并入 required 集合，
   worker 必须声明该 pack token 才能 claim。

2. **pack 未 ready 时 fail-closed**。
   `event_driven_dispatch.claim_next_task` 现已向 `claim_next_eligible_task` 补传
   `build_capability_registry()`，因此「任务绑定一个 registry 中未知/未 ready 的 pack」时不可 claim。
   内置包（`loopx-core` provider）默认全部 `ready: True`，不受影响；
   只有未安装/未启用的扩展能力包会触发 fail-closed——这正是期望行为。

3. **CLI 注册顺序由 registry 决定**。
   `build_parser()` 的命令注册改为 `register_all_capability_commands` 驱动，
   顺序来自 `CapabilityRegistry.records()`，而非源文件 import 顺序。命令名与 handler 分发未变。

## P3 边界

- 已完成：`CapabilityEventHub` 事件订阅/发布底座（错误与正常结果分离返回）；`CapabilityHookRegistry`
  进程级钩子注册；`heartbeat_prequota` 已改为通过 hook registry 收集钩子（保留
  `acknowledged_pr_reviews` 兼容键 + 新增 `hooks` 键）。
- 未完成：`quota.py` / `configure_goal.py` / `lark_inbox.py` 等其余 90+ 处硬编码钩子
  **仍是静态 import**，尚未迁移到事件订阅。这是刻意的阶段边界，不是已完成状态。

## Hook 契约

`register_pre_quota_hook(hook, *, source="")` 的 hook 签名：
`hook(*, registry_path, runtime_root_arg, goal_id, agent_id, fetch_timeout_seconds=10) -> dict`。
签名不符 / 抛异常 / 返回非 dict 均视为失败（`degraded`），不影响其他 hook。
结果以 hook `__name__` 为 key 并入 `checks.hooks`。

## 迁移注意事项

- 存量队列中带 `capability_binding_ref` 的 pending 任务，在 worker 未声明对应 pack token 前不可 claim；
  上线前需核对在途 binding 的 pack token 是否已被 worker 声明。
- 扩展能力包若未在本机 `ready`，其绑定任务会被 fail-closed；确认扩展包的安装/启用状态。
