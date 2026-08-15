# 生态采用与衍生清单

> [English](ecosystem-adoption.md)

LoopX 正在被其他开源项目采样、集成和再实现。本页是这份观察的事实化、
公开安全清单。

> **边界**：收录是事实记录，不代表背书。仅收录公开 GitHub 证据；状态变化
> （合并、关闭、改名、停滞）由每周扫描刷新，见[维护方式](#维护方式)。

## 1. 真实集成

在真实流程中调用 LoopX CLI/契约、或把 LoopX 作为 provider 接入的项目。

- **Adaptive-Agent-Orchestration-Protocol**（YuemingHub）——把 LoopX 作为
  可选的长程执行 provider 采纳（[PR #41，已合并](https://github.com/YuemingHub/Adaptive-Agent-Orchestration-Protocol/pull/41)），
  并在 [issue #57](https://github.com/YuemingHub/Adaptive-Agent-Orchestration-Protocol/issues/57)
  跟踪 host pilot。状态：已采纳（协议层）。
- **LoopX Console / BitFun**（xielixing、GCWing）——把 LoopX 控制面打包成
  BitFun MiniApp：宿主心跳调用 `quota should-run`、按 `scheduler_hint` 调整
  轮询、用 `heartbeat-prompt --compact` 生成任务体
  （[loopx-console](https://github.com/xielixing/loopx-console)、
  [BitFun PR #1808](https://github.com/GCWing/BitFun/pull/1808)、
  [PR #2006](https://github.com/GCWing/BitFun/pull/2006)）。
  状态：进行中（新仓库 + 开放 PR）。
- **Meta-RLR**（hk20013106）——已合并维护边界
  （[PR #17](https://github.com/hk20013106/RLR/pull/17)）：LoopX 只持有维护
  目标/todo/evidence/monitor/replan 状态，`research_loop` 保持权威。
  状态：已合并 / 运行中。
- **codexia**（milisp、connorodea）——为自动化调度器提出 LoopX
  `should-run` 预检（上游 [PR #71，已关闭未合并](https://github.com/milisp/codexia/pull/71)，
  fork 上重新开启 [PR #1](https://github.com/connorodea/codexia-task-management/pull/1)）。
  状态：尝试中；契约尚未对着 live 安装验证。
- **spoon-core**（XSpoonAi）——计划增加可选的只读控制上下文中间件
  （[issue #285](https://github.com/XSpoonAi/spoon-core/issues/285)）。
  状态：计划中。
- **OpenViking / NoKV**——已确认合作伙伴；见
  [README 合作伙伴项目](../../README.zh-CN.md#合作伙伴项目)。

## 2. 采样与借鉴

明确把 LoopX 作为灵感或待吸收能力的 issue、PR、书籍或文档。

- **《深入理解 AI Agent》/ ai-agent-book**（bojieli，约 37k stars）——合并了
  一章内容，在 13 个维护版本中把 LoopX 锚定为具体的 Loop Engineering
  framework，并给出 verifier 视角案例与 pin 定的 stable commit
  （[PR #614](https://github.com/bojieli/ai-agent-book/pull/614)、
  [chapter 10](https://github.com/bojieli/ai-agent-book/blob/01e54bf2acc28c7ebb9c325b6d93aef79e1b5069/book/chapter10.md)）。
  状态：已合并 / 教材级。
- **Mindthus**（rv198-star）——明确的“对比吸收改进总纲（兼容借鉴，不硬融
  理念）”，带字段级吸收候选：
  [issue #132](https://github.com/rv198-star/Mindthus/issues/132)（总纲）、
  [issue #133](https://github.com/rv198-star/Mindthus/issues/133)（范围化
  human gate + 诚实 fallback 字段）、
  [issue #138](https://github.com/rv198-star/Mindthus/issues/138)（handoff
  恢复五问）。状态：开放，等待主项目方审批。
- **GovernLoop**（liangzhipengdamon-maker）——Phase 0 评估报告
  （[PR #23](https://github.com/liangzhipengdamon-maker/GovernLoop/pull/23)）
  把真实问题映射到 LoopX 能力；关键结论：LoopX 是**被动 state kernel**——
  强于状态持久化、机器可读状态与可恢复性，不适合主动执行路径。
- **hartevo-desktop**（tangpingqingwa）——借鉴 Prime Agent + LoopX patterns
  的 durable Mission Control kernel spec
  （[issue #55](https://github.com/tangpingqingwa/hartevo-desktop/issues/55)）。
  状态：早期 spec。
- **stablyai/orca**——引用 LoopX 提出目标设定与自动迭代的 feature request
  （[issue #12628](https://github.com/stablyai/orca/issues/12628)）。
  状态：一句话诉求，开放。
- **polyphemus**（Diekgbbtt）——研究如何集成 LoopX primitives
  （[issue #89](https://github.com/Diekgbbtt/polyphemus/issues/89)）。
  状态：一句话诉求，开放。
- **mingos-foundation**（YuemingHub）——刻意只做实验的 consumer PR，验证
  LoopX 作为 AAOP execution-continuity provider
  （[PR #18](https://github.com/YuemingHub/mingos-foundation/pull/18)）。
  状态：按设计关闭（实验）。

## 3. 衍生与周边

围绕 LoopX 构建或受其启发的 fork、kit、书籍与同名项目。

- **loopx-book / loopx-book-labs**（cocolord）——中英双语、协议优先的
  LoopX 开发者书（[loopx-book](https://github.com/cocolord/loopx-book)、
  [labs](https://github.com/cocolord/loopx-book-labs)），带可运行 labs：
  项目接入、issue-to-PR、standalone extension。
- **foreman**（needware）——把 LoopX 内核迁移为原生 TypeScript 的提案，
  pin 定上游 authority commit（[PR #1](https://github.com/needware/foreman/pull/1)）。
  已邀请上游协作；见该 PR 评论串。
- **Fork 贡献**：内网离线 bundle + OpenCode 协作 kit
  （[Allenskoo856](https://github.com/Allenskoo856/loopx/pull/1)）、
  dashboard 英文本地化（[manoelcalixto，已合并](https://github.com/manoelcalixto/loopx/pull/1)）、
  fork CI fail-safe（[Kankandesuyo](https://github.com/Kankandesuyo/loopx/pull/1)）、
  原生 Windows 资格验证（[hk20013106，已关闭](https://github.com/hk20013106/loopx/pull/1)）。
- **同名独立项目**（非上游代码）：rye567/loopx（质量门禁 kit）、
  lcmax/Loopx（agent loop 设计 skill）、hugh-zhan9/loopx（docs-first 工程
  纪律）。列出仅为品牌澄清，不代表关联关系。

## 不在此清单内

- Trending/digest 机器人与一句话提及（github-trending、BuilderPulse、
  agents-radar 等）属于认知信号，不作为采用证据列出。
- 无关的同名匹配（如 x86 `LOOPx` 指令、音频 loop 工具）不收录。

## 维护方式

- 每周扫描（7d）由 LoopX value-explorer monitor
  （`github-loopx-mention-scan`）执行：`gh search code "huangruiteng/loopx"`、
  `gh search issues loopx`、`gh search prs loopx`、`gh search repos loopx`。
- 每次扫描后，通过 pull request 更新本文件；material transition 另行创建
  具体跟进 todo。
- 最近核对：2026-08-15。
