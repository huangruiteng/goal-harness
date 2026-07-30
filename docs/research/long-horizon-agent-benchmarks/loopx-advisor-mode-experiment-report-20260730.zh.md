# 我们从 LoopX Advisor 模式实验中学到了什么

LoopX Advisor 模式最初来自一个很直接的假设：让更强的模型先给出有限建议，
再让更便宜的模型执行修改。如果建议足够准确、足够紧凑，执行模型就可以少
做探索，在保持质量的同时降低总 Token 使用量。

这个假设值得验证。PR #2406 实现了一个 opt-in 的 Advisor 路径，并在一个
provider-backed qualification 中得到过正向结果：两个质量 arm 都通过，总
Token 从 263,472 降到 130,782，下降 50.36%。这说明产品链路可以跑通，也
说明单个 case 上确实可能省 Token。

但后续更大范围实验没有支持这个假设。Token 降低只出现在孤立样本中，没有
在更大样本里稳定复现。Advisor 阶段本身经常很贵，有时超时，有时没有真正
影响最终结果，也没有带来稳定质量提升。在 Agent 编程任务里，Advisor 会形成
一次额外的 Agent 运行。按当前协议，这次额外运行没有为自己赚回成本。

## 我们想验证什么

Advisor 模式吸引人的地方，是把“思考”和“执行”拆开：强模型用有限预算找
root cause、关键文件、不变量和风险；便宜模型基于这些信息做实际修改，减少
重复探索。

如果这个模式成立，应该看到三个信号：

- Advisor plus executor 的总 Token 低于高质量基线；
- 它至少不低于便宜 executor 单独执行的通过率；
- 它能产生 rescue，也就是便宜 executor 单独失败，但加 Advisor 后成功。

这三个信号在当前实验里都没有成立。

## 我们怎么测

实验分三层。

第一层是 PR #2406 的单 case qualification。它测试的是 LoopX 产品路径，
结果有价值，但只能说明链路可运行，不能说明普遍收益。

第二层是 20 case 实验：Pro Advisor 先给执行前建议，Flash 再执行。这个实
验走的是 TraeX wrapper，与 LoopX 产品路径并不完全相同。因此它用于判断
当前协议思想，不作为直接的产品 benchmark。

第三层是 5 case 消融和 3 case 调优探针，用来判断效果到底来自真实 Advisor
洞察、通用提示，还是 fail-open fallback。

## 主实验：没有稳定质量收益

20 case 结果没有证明 Advisor 能带动弱执行模型。

| Arm | 通过数 | 结果 |
| --- | ---: | --- |
| DeepSeek-V4-Flash direct | 11 / 20 | 本批次最高通过率 |
| DeepSeek-V4-Pro direct | 8 / 20 | 在该 harness 下未形成稳定强基线 |
| Pro Advisor plus Flash | 10 / 20 | 无 rescue，且出现 1 个 harm |

最关键的数字是 rescue：0。没有一个 case 是 Flash direct 失败，而 Advisor
plus Flash 成功。反过来还出现了 1 个 harm：Flash direct 通过，但 Advisor
组合失败。

Advisor 还有 6 / 20 个 case 没有产出可用 patch，主要原因是超时或缺少有效
回执。这类运行仍然消耗时间和 Token，但没有改善 executor。

## Token 结果：额外 Agent 运行太贵

可归因 Token 的 13 case 子集给出了最清楚的成本信号。

| Arm | 通过数 | 成本代理 |
| --- | ---: | ---: |
| Flash direct | 10 / 13 | 约 $2.31 |
| Pro direct | 8 / 13 | 约 $7.35 |
| Pro Advisor plus Flash | 10 / 13 | 约 $5.13 |

在这 13 个可比 case 上，Advisor plus Flash 和 Flash direct 一样都是
10 / 13，但成本约高 122%。它比 Pro direct 便宜约 30%，但 Pro direct 在这
个 harness 里的通过数也更低，所以这个比较不能支持产品收益结论。

结论很直接：当前 Advisor 路径不能稳定降低总 Token。PR 单 case 说明“有时
可以省”，但更大范围实验说明“不能稳定省”。把 Advisor 自身作为一次 Agent
运行计入成本后，当前协议没有形成 Token 效率优势。

## 消融：Advisor 没有超过通用提醒

5 case 消融把真实 Advisor 替换成一段固定通用提醒：先找 root cause、相关
文件和 symbol，形成紧凑 patch plan，考虑边界情况，实现最小生产代码修复，
并用仓库事实验证假设。

| Arm | 通过数 |
| --- | ---: |
| Flash direct | 3 / 5 |
| 固定通用建议 plus Flash | 2 / 5 |
| 现有 Pro Advisor plus Flash | 2 / 5 |

现有 Advisor 没有超过通用提醒。在这个切片上，实验没有证明 Advisor 提供了
超出普通执行前提示的有效信息。

## 调优探针：更安全，但仍无 rescue

后来我们把协议调得更安全：Advisor 输出更结构化；当 Advisor 超时或输出不
可用时 fail-open，让 Flash 继续执行。

| Case | Advisor 处理 | Token | 结果 |
| --- | --- | ---: | --- |
| `astropy__astropy-8707` | 高置信度证据包 applied | 总计 2,987,804 | 失败 |
| `pydata__xarray-6992` | 300 秒超时，fallback 到 Flash | executor 4,437,735 | 失败 |
| `sympy__sympy-19040` | 300 秒超时，fallback 到 Flash | executor 3,358,021 | 通过 |

聚合结果是 1 / 3 通过，rescue 为 0，harm 为 0。唯一通过来自 fallback，不
是来自真正 applied 的 Advisor packet。fail-open 是必要安全属性，但它没有
证明 Advisor 能提质或省 Token。

## 为什么这个协议没有起作用

当前结果只说明这套协议没有产生预期收益。它采用一次执行前建议，缺少闭环
控制。

在一个 Sphinx 失败样本里，Advisor 识别到了关键方向：当前 class namespace
必须优先。但 executor 最终写出的 patch 仍然让 base `attr2` 先进入 map，
导致 child `attr2` 因 duplicate 被跳过。target test 可以通过，但旧
regression test 仍然失败。GPT-5.5 和 Gemini 3.1 Pro 的旧 checkpoint 都
出现过类似模式：Advisor 指出了方向，但最终 patch 仍违反关键不变量。

这就是当前协议的核心缺口。executor 写完代码后，Advisor 没有检查实际 diff。
它没有验证 patch 是否遵守建议、保持不变量、避免回归。缺少这个闭环时，
Advisor 经常只会增加一次昂贵分析，无法带来质量或 Token 优势。

## 对下一版设计的启发

实验指向了一个更具体的失败机制。实验版 Advisor 可以访问较宽的仓库范围，
自由探索后再输出自由文本。它在 executor 开始前重复了大量高成本的定位和
分析工作。组合链路因此支付了两次重叠的 Agent 探索成本。

更有成本效率的多模型设计，会把额外调用收缩为一个可度量的窄任务，例如
issue localization、上下文压缩、patch review 或 verifier feedback 分流。
这类调用可以使用受限输入、结构化输出和明确的调用或 Token 预算。executor
随后消费一个能替代重复探索的产物。

这是下一轮实验需要验证的方向，还不是 benchmark 结论。下一版协议应只在
明确目的下触发一次受限 Advisor 调用：

- 实现前生成紧凑 evidence packet，给出相关文件、symbol 和不变量；
- 实现后只审查受限 diff 和测试摘要；
- review 识别出具体违反项时，才触发一次 repair。

评测需要分别记录 Advisor 成本、executor 成本、重复探索、rescue、harm 和
总 Token。只有受限调用节省的 executor 工作超过它自身成本时，额外复杂度才
有价值。

## 结论

PR #2406 中当前的 Advisor runtime 代码不应该合并。

当前证据说明：

- 单个 case 上可以出现 Token 降低；
- 更大范围实验没有证明稳定降 Token；
- Advisor plus Flash 没有超过 Flash direct 的通过率；
- 20 case 主实验 rescue 为 0；
- 消融实验没有证明 Advisor 超过通用提醒；
- fail-open 让协议更安全，但没有产生功能 rescue；
- 在 Agent 编程任务里，Advisor 自身太耗 Token，当前协议无法提升总 Token
  效率。
- 下一轮应验证受限 Advisor 调用，避免再次运行一个自由探索型 Agent。

正确处理方式是：把 PR #2406 改成实验文章，移除 Advisor runtime 代码。

如果未来继续做 Advisor，不应该再做一次性执行前建议，而应该做闭环协议：
紧凑 Advisor contract、executor 实现、Advisor 检查实际 diff、最多一次定向
repair。只有这个协议证明至少一个稳定 rescue、harm 为 0，并且有可信的总
Token 收益后，Advisor mode 才适合作为产品优化继续推进。

证据边界：本文只使用公开 PR 元数据、紧凑实验摘要、聚合 case 结果和协议层
观察。不包含原始任务文本、原始轨迹、原始 verifier 输出、原始模型输出、私
有运行路径、凭据、本地机器路径或内部运行上下文。
