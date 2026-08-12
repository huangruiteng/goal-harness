# Control-Plane Developer Course

> 面向准备修改 LoopX Kernel、CLI、状态投影、调度或扩展能力的开发者。

## 与 Dev Book 的关系

Dev Book 给外部开发者一条“从机制模型到接入/贡献”的完整路径；Control-Plane
Developer Course 是独立章节，面向需要进入源码实现、判断规则优先级、定位 bounded
context 或新增一条控制面规则的开发者。

两者共享官方协议与源码事实，但不维护两份完整课程：

- Dev Book 讲清楚预测行为所需的机制；
- Course 提供 Showcase 推导、decision table、源码领读、实验与 review 问题。

## 课程地图

| 课程章节 | 主题 | 适合在读完 Dev Book 哪部分后进入 |
|---|---|---|
| [概念导读：先把 LoopX 放进一张图](/loopx/docs/development/control-plane-course/00-concept-primer/) | 有限上下文、外置状态与核心概念总图 | 第 1、2 章后 |
| [长程任务如何收敛](/loopx/docs/development/control-plane-course/topic-long-horizon-convergence/) | 方向、证据、Delta、活性与终局不变量 | 第 6 章后 |
| [第 1 讲：Harness 是 effectful program](/loopx/docs/development/control-plane-course/01-agent-loop-effectful-program/) | effect interpreter 心智模型，以及三类 adapter 如何复用 typed settlement algebra | 第 1 至 6 章后 |
| [第 2 讲：从三个 Showcase 理解 LoopX 架构](/loopx/docs/development/control-plane-course/02-goal-control-plane-architecture/) | Agent / Provider / Capability / Kernel 分工 | 第 2 章后 |
| [第 3 讲：从 Showcase 到第一次真实 Loop](/loopx/docs/development/control-plane-course/03-first-real-loop/) | guided start、todo、quota、refresh、spend | 第 1 至 6 章后 |
| [第 4 讲：状态底座与可重放事实](/loopx/docs/development/control-plane-course/04-state-substrate/) | registry、event、active state、run history、projection | 第 3 章后 |
| [第 5 讲：Todo 工作图与 Peer 协作](/loopx/docs/development/control-plane-course/05-work-graph-and-peers/) | claim、lease、handoff、equal peer | 第 4 章后 |
| [第 6 讲：Quota 决策内核与 Interaction Contract](/loopx/docs/development/control-plane-course/06-quota-decision-kernel/) | `should-run`、route、mode、interaction contract | 第 5 章后 |
| [第 7 讲：Host、Heartbeat 与 Stateful Backoff](/loopx/docs/development/control-plane-course/07-host-scheduler-and-heartbeat/) | execution context、RRULE、ACK、backoff | 第 5、6 章后 |
| [第 8 讲：证据、Refresh 与 Self-Repair](/loopx/docs/development/control-plane-course/08-evidence-refresh-and-self-repair/) | material progress、replan、repair delta | 第 6 章后 |
| [第 9 讲：如何给 Control Plane 增加一条规则](/loopx/docs/development/control-plane-course/09-engineering-a-control-plane-rule/) | invariant、ordered rules、schema、smoke | 第 10 至 13 章后 |
| [第 10 讲：Agent 自主写代码时的分层质量门禁](/loopx/docs/development/control-plane-course/10-autonomous-agent-quality-gates/) | 确定性测试、canary、模型行为、release gate | 第 13 章后 |
| [第 11 讲：扩展层、Explore 与领域产品](/loopx/docs/development/control-plane-course/11-extension-layer/) | 默认关闭的 Graph/Harness、领域产品 | 第 14 至 16 章后 |

## 与 Effect Interpreter RFC 的关系

课程第 1 讲与
[Agent Loop Effect Interpreter RFC](/loopx/docs/architecture/rfcs/agent-loop-effect-interpreter-v0/)
共用同一套语言：harness 是 agent loop 外面的 effectful program，状态机只是
interpretation table。进入 Kernel 实现前，建议先读第 1 讲，再按需要进入后续专题。
