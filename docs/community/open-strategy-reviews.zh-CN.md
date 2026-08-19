# 开放战略 Review

> [English](open-strategy-reviews.md)

LoopX Open Strategy Review 是面向用户、贡献者和 maintainer 的阶段性公开工作会议，
用于比较少量当前技术方向，把宽泛的 Discussion 与 RFC 反馈收敛为有界下一步、owner
和明确的证据要求。

它不是 roadmap 投票、交付承诺或第二套治理路径。真实已交付行为仍由 `main`、release
artifact 与稳定契约定义；
[当前技术方向](../project/technical-directions.zh-CN.md)仍是 canonical portfolio，
每份 RFC 的效力以其自身标注的状态为准。

## 何时召开

当两个以上公开方向存在难以异步解决的交叉问题，并且至少两个人可以展示证据、原型或
具体设计张力时，maintainer 可以发起一次 review。

周末可能更方便业余贡献者参加，但 LoopX 不把它固化为每周会议。Maintainer 根据贡献者
可用时间逐次决定日期，并至少提前 48 小时公布。前两期结束后，再根据本文的验收信号
决定保留、调整或停止 cadence。

## 会前准备

在 GitHub **General** 分类创建一个 Discussion，作为本期公开议程与记录。它必须链接
当前技术方向地图，以及所有必要的 RFC、tracker、issue 或 prototype pre-read。

最终议程最多保留四个方向。候选议题使用以下卡片：

```text
方向：
问题或目标结果：
当前公开证据或原型：
未解决问题：
希望本次 review 得到什么：
链接：
愿意承担的 owner（如有）：
```

主持人在会前冻结议程。没有公开问题陈述或具体问题的条目继续留在异步 Discussion，
不占用实时会议。

## 会议结构

第一期控制在 75 分钟：

| 时间 | 内容 |
| --- | --- |
| 5 分钟 | 重申已交付基线、治理边界和本次议程。 |
| 48 分钟 | 最多四个方向，每个不超过 12 分钟。 |
| 12 分钟 | 横向比较优先级、依赖与证据缺口。 |
| 10 分钟 | 确认 disposition、owner、下一产物与复核点。 |

主持人应优先让贡献者讲自己的工作。战略 review 不应变成 maintainer 单人演讲，也不
应该巡礼仓库中的所有想法。

## Review Disposition

每个议题只落入一个本期 disposition：

| Disposition | 含义 |
| --- | --- |
| `route_to_bounded_work` | 下一最小切片已经清楚；创建或更新可认领 issue / task-board 条目。 |
| `require_evidence` | 扩大实现前，先补指定用户案例、benchmark、parity、prototype 或其他证据。 |
| `keep_visible` | 方向仍有上下文价值，但当前没有 owner 或 promotion gate 支撑新增投入。 |
| `defer` | 在明确 trigger 改变前，停止继续消耗会议和实现时间。 |

Disposition 本身不会改变 RFC stage、晋级 integration branch、任命 maintainer 或授权
实现。Stage、scope、implementation lead、branch 或 promotion gate 的实质变化，继续
遵循仓库正常 PR 与治理路径。

## 必须留下的公开记录

会后 48 小时内，在本期 Discussion 追加总结评论：

| 方向 | 当前阶段 | 已复核证据 | Disposition | Owner | 下一产物或证据 | 下次复核 trigger |
| --- | --- | --- | --- | --- | --- | --- |

随后按结果路由：

- canonical portfolio 事实变化时，通过 PR 更新技术方向地图；
- 架构边界变化时，更新或创建 RFC；
- 任何实现被认领前，先创建有界 issue 或 task-board 条目；
- 未解决问题继续留在 Discussion，并写明证据要求，不能把沉默解释为同意。

Discussion 的文字总结是会议记录。录音录像可选且需要参与者同意，不能替代公开文本。

## 参与和公开边界

- 议题、示例和纪要必须公开安全。不得发布凭据、私有客户或雇主背景、原始逐字稿、
  私有链接或未公开评测数据。
- 聊天群、视频会议或直播只是 transport 与分发渠道，不是项目 authority。
- 参会、演讲或受欢迎程度不会授予 merge、release、subsystem 或 maintainer 权限。
- 无法达成共识时，由 lead maintainer 在相关公开 artifact 中记录未决选项，或记录最终
  决定与理由。
- 影响方向的实质结论应同时提供中英文摘要，避免实时会议语言静默排除贡献者。

## 前两期验收信号

不要只按参会人数判断成败。两期之后，根据以下结果决定是否继续或调整：

1. lead maintainer 之外的贡献者能独立解释或质疑一个 LoopX 方向；
2. 至少两个 review 条目形成 owner 与有界公开 artifact；
3. 这些 artifact 在下一次 review 前获得证据、实现结果或有记录的停止决定；
4. 跨方向的重复问题更容易被检索，不需要不断从聊天记录重新争论。

如果这些信号没有出现，就把工作退回异步 Discussion，不为维持会议而维持会议。
