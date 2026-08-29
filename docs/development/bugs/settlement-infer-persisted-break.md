# Settlement readback 身份恢复边界不变量

**状态**：已锁定（PR #3360，fail-closed 边界显式化 + 语义测试）；当前由
`read_heartbeat_settlement(..., infer_turn_instance_id=True)` 的聚合读取路径持有。

## 不变量

结算身份恢复缝只跳过**显式 typed、quota-neutral** 的 run（`quota_slot_voided` /
`quota_scheduler_ack` / 无 `material_change` 的 `quota_monitor_poll` / 非 accountable
的 `state_refreshed`），并取最近一次同 agent 的 `quota_slot_spent` 或 accountable
delivery outcome 作为候选。

任何**未知或不完整**的同 agent 非中性记录都不是可穿透的「中性」记录：它构成恢复边界，
读取在该处 fail-closed（返回 `None`，回退到 frontier 规则），绝不跨越它去恢复更旧的
settlement identity。这与 `slot_accounting._latest_unspent_accountable_delivery_run`
及 `test_custom_non_neutral_event_still_fails_closed` 的语义一致。

## 说明

原实现用循环体级的无条件 `break` 隐式表达这条 fail-closed 边界，容易被误读为
「未知记录应当穿透」。本次改动把 `break` 收进 candidate 分支，并在其后显式
`return None`；行为保持不变，仅把边界显式化。

## 验证

- `test_typed_material_poll_is_recovered_not_shadowed`：生产端忠实（`material_change=true`
  且 `delivery_outcome=outcome_progress`）的 material poll 被正确恢复，不被更旧的 spend 遮蔽。
- `test_unknown_non_neutral_record_fails_closed`：旧 spend 之后追加缺 `delivery_outcome`
  的不完整 poll，断言恢复 fail-closed（返回 `None`），不穿透到旧身份。
