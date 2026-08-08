# 第 1 讲：Harness 是 effectful program

> 建议时长：30 分钟。先建立心智模型，不进入具体状态枚举。

## 这一讲要建立的判断

Harness 不是“一堆状态机”，而是 agent loop 的 effectful program 和 effect
interpreter。agent loop 是被解释的循环，harness 才是解释外部 effect 的程序；
状态机只是 harness 内部的决策表。

全文参考：
[Agent Loop Effect Interpreter RFC](../../architecture/rfcs/agent-loop-effect-interpreter-v0.md)。
公开来源：
[主线一：Agent Loop 是 effectful program(1)](https://www.xiaohongshu.com/discovery/item/6a01d501000000003700c5de?source=webshare&xhsshare=pc_web&xsec_token=ABqpNuladcxhev099wLKw8M3ilhKBua0BQXNpxnBZEGkc=&xsec_source=pc_share)、
[主线一：Tool Calling 是 Kleisli arrow(2)](https://www.xiaohongshu.com/discovery/item/6a02f388000000003502b2d6?source=webshare&xhsshare=pc_web&xsec_token=ABHcIpzpd2RlhAaRr9sZZ-q1OIfRgt7rvG2jn7GUO3tNo=&xsec_source=pc_share)、
[主线一：Agent Loop 里的小魔法：函数的组合(3)](https://www.xiaohongshu.com/discovery/item/6a057524000000003701f6aa?source=webshare&xhsshare=pc_web&xsec_token=AB43lNCJ5ULmfTrGfeTLWd2-jQ6q8nFMGyNAd-tlXJ1uw=&xsec_source=pc_share)。

## 一个最朴素的 Agent Loop

```text
while true:
  response = llm_api.invoke(messages)
  if not response.tool_calls:
    return response.final_answer
  observations = [tools[call.name].invoke(call.args) for call in response.tool_calls]
  messages += [response.message] + observations
```

把 tool call 推广到所有外部动作，就得到控制面真正在解释的形状：

```text
model -> effect request -> harness interprets effect -> observation -> model
```

模型输出的是动作请求，不是动作本身。真正的执行、权限、预算、调度、失败恢复、
证据沉淀都发生在 harness 这一侧。

## 为什么 harness 是这个解释器

普通 Agent 只在当前上下文里推理。LoopX 把一个长程任务的有限上下文之外的
目标、todo、authority、quota、evidence、cadence 和 recovery 状态外置，再把
当前状态编译成一轮可执行的 CLI packet。

用纯函数和 effect 的差别表达：

```text
A => B        // 普通计算：给定状态，算出结果
A => F[B]     // effectful：结果活在外部世界
```

LoopX harness 是那个 `F`：

```text
GoalState => F[QuotaDecision]
```

## Effect Request 到 Observation 的映射

| Agent loop 环节 | LoopX 对应物 |
|---|---|
| Agent loop | 每轮 automation、heartbeat、PR monitor、持续重构 |
| Effect request | `todo add`、`quota spend`、`refresh-state`、`notify`、`monitor poll`、`bind-agent-thread` |
| Harness interprets effect | `quota should-run` + `interaction_contract` + `capability_gate` + `work_lane_contract` + `scheduler_hint` |
| Observation | quota packet、run history、evidence log、状态 writeback |
| Middleware 挂载点 | user gate、capability bridge、scheduler ACK、cooldown、外部 evidence poll |

## State Machine 是 Interpretation Table

每个状态机都回答同一组问题：

```text
输入 effect | 解释器 | 决策 | observation | 下一 effect
```

例子：monitor scheduler。

```text
Monitor cadence / due horizon
  -> scheduler interpreter
  -> host RRULE / initial interval
  -> scheduler_hint packet
  -> next heartbeat or monitor poll
```

例子：quota runtime。

```text
Agent proposes next bounded turn
  -> quota interpreter
  -> run / gate / wait / repair / quiet
  -> quota packet + interaction contract
  -> execute, ask owner, observe, repair, or no-op
```

## 组合：Around 是数据，不是回调

公开课程把组合分成三层：

| 组合 | 形状 | LoopX 对应物 |
|---|---|---|
| 函数组合 | `A => B`、`B => C` | read model -> projection -> decision |
| Kleisli 组合 | `A => F[B]`、`B => F[C]` | 一轮 bounded turn、host effect、validated writeback |
| Middleware 组合 | `(A => F[B]) => (A => F[B])` | `capability_gate`、`interaction_contract`、`work_lane_contract`、`scheduler_hint` |

很多 runtime 的 around 逻辑会拿到 `handler`：一个可继续执行主流程的回调，
然后决定是否调用、调用几次、失败后怎样 fallback。LoopX 不能跨上下文和 session
传递一个可调用对象。它的 `handler` 是数据：packet 里的 `next_effect` 编码下一组
CLI 动作、scheduler ACK 和 failure hint，由 host 或下一轮 automation 执行。

这个差异不是缺一个 middleware 层，而是控制面的合理形状：

- 可以 short-circuit：`decision` / `effective_action` 直接表达
  `skip`、`wait`、`monitor_quiet_skip`、`repair_bridge`、`ask_owner`，不会假装原
  effect 已经执行；
- 可以 rewrite：`capability_gate` 把下一步改写成先补能力，`work_lane_contract`
  可以用 due monitor 或 Lark inbox 抢占普通 advancement；
- 可以 settle：`scheduler_hint` 的 ACK / failure hint 告诉 host 如何提交成功或
  失败，`unchanged_poll` 限制重复轮询。

失败、取消、权限和预算必须保持结构化，不能被一个通用 catch 吞掉。看一个
around 决策时，问七件事：

1. 它在解释哪个 effect request？
2. 哪个 around layer 拥有决策，输出什么 observation？
3. 它能否 short-circuit，而且不假装原 effect 已执行？
4. `next_effect` 在哪里被编码？
5. 失败、取消、权限、预算是否仍然结构化可见？
6. around layer 的先后顺序是否明确并有测试？
7. host effect 之后，evidence、trace、budget 是否通过 writeback / ACK / spend
   继续成立？

## CLI 是更高密度的 effect

单个 tool call 是 `ToolInput => F[ToolOutput]`。LoopX 的 CLI packet 是一条更高
密度的 effect：一条命令可以把权限、预算、参数校验、外部执行、失败语义、scheduler
ACK 和 writeback 都编码进同一个 request。模型仍然只提出 effect request，harness
负责解释并决定下一步执行什么。

如果未来厂商 API 原生支持 serial tool calls 或 interleaved reasoning，对 LoopX
来说只是解释器内部的一种 execution mode：

- 串行、并行、交错是 execution strategy，不是新的状态机；
- `effect_request -> interpretation -> observation -> next_effect` 仍然稳定；
- `next_effect` 从一条 CLI 命令变成一段有序 effect program。

## 读代码前先问五个问题

1. 这个 effect request 是谁提出的？
2. 哪个 interpreter 决定它能否执行？
3. 决策输出了什么 observation？
4. observation 如何回灌到下一轮模型上下文？
5. 失败、取消、权限、预算和证据在哪里被解释？

## 实验

运行一次真实 CLI：

```bash
loopx --format json quota should-run \
  --goal-id loopx-meta \
  --agent-id codex-quality-qualification \
  --available-capability network \
  --available-capability external_evidence_poll \
  --codex-app
```

在输出里找到：

- `interaction_contract`：解释后的本轮协议；
- `capability_gate`：权限解释；
- `scheduler_hint`：时间解释；
- `work_lane_contract`：路由解释；
- `recommended_action`：observation 指向的下一 effect。

## Review 问题

- 如果把状态机文档写成 interpretation table，哪个状态维度最容易被讲清楚？
- 为什么 `quota should-run` 是解释器而不是另一个状态机？
- 一个新的 capability 应该解释哪一类 effect request，输出什么 observation？
