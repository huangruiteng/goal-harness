# Resolved: `_todo_from_added_event` 丢弃 `updated_at`

**状态**：已修复（PR #3359，回归测试已转绿）。

## 问题

`_todo_from_added_event` 的构造字典漏拷贝 `updated_at`。生产端 `event_writeback.py` 在
`TODO_ADDED` payload 中始终写入该字段，读取端 `render_todo_markdown` 与
`management_projection` 又消费它；reducer 漏拷贝使新增 todo 投影丢失最后活动时间，
破坏「生产者写入 → 投影 → 消费者读取」的保真不变量。

## 修复

构造字典补入 `"updated_at": compact_text(payload.get("updated_at"))`，归一化与完成事件
reducer 一致。缺省时 `compact_text(None)` 为空串，读取端
`todo.get("updated_at") or todo.get("latest_event_at")` 的 fallback 不变。

## 回归测试

`test_updated_at_survives_todo_add_projection`
（`tests/control_plane/test_todo_mutation_authority.py`）—— 走真实 `TODO_ADDED` 事件 +
`build_state_projection`，断言投影保留时间戳。
