# Xiaohongshu Launch Draft

## Positioning

Goal Harness 的发布重点不是“又做了一个 agent 框架”，而是一个更小但更实用的问题：

> 当 Codex / Claude 这类 coding agent 已经足够强，下一步缺的是让它们在多个项目里持续推进目标、记住状态、留下可复核记录，并且不把私有信息带进公开产物。

适合小红书首发的角度：

- 面向用 AI coding 工具做真实项目的人；
- 强调多项目管理、长期目标、状态文件、run history、公开/私有边界；
- 不夸大成自动化平台，先讲“我自己为什么需要它”。

## Title Options

1. 我给 Codex 做了一个 Goal Harness：让 AI 不只会聊天，也能持续推进项目
2. 用 AI coding 工具久了，我发现真正缺的是“目标管理层”
3. 开源一个小工具：把 Codex 的 goal mode 变成多项目控制面
4. AI agent 已经够聪明了，但长期工作需要一层 harness

## Draft

最近我在做一个小工具：`goal-harness`。

它不是新的 agent 框架，也不替代 Codex / Claude Code / Cursor。它解决的是我自己高频遇到的一个问题：当 AI coding 工具开始参与真实项目后，单次对话能力已经很强，但长期目标很容易漂。

典型问题包括：

- 今天说好的 next action，过两天换个 thread 就丢了；
- 多个项目同时推进，agent 容易混淆状态；
- goal mode 会努力工作，但不一定知道“当前最该推进什么”；
- 有些材料和日志是私有的，但总结、方法和工具又希望能开源沉淀；
- 做了很多操作，却缺少一份可回放的 run history。

所以我把它抽成一层很薄的 Goal Harness：

```text
项目里的 goal state
  + 项目 registry
  + 可选 adapter
        |
        v
共享 runtime / run history
        |
        v
Codex goal mode / heartbeat / future UI
```

它现在做的事情很朴素：

1. 一条命令把一个项目接入 goal harness；
2. 每个项目维护自己的 active goal state；
3. 多个项目共享同一个本地 runtime；
4. 每轮 goal tick 留下可检查的 run history；
5. 在公开发布前做一层 public/private boundary check。

快速接入大概是这样：

```bash
git clone https://github.com/huangruiteng/goal-harness ~/goal-harness
~/goal-harness/scripts/install-local.sh

cd /path/to/your-project
goal-harness bootstrap \
  --goal-id your-project-goal \
  --objective "Improve this project through bounded, verified goal segments." \
  --goal-doc GOAL.md
```

我现在的判断是：AI agent 的体验提升，不只来自更强模型，也来自更好的 harness。

Prompt engineering 解决“怎么说”，context engineering 解决“给模型看什么”，goal harness 更像解决“这个 agent 如何在受控边界里持续行动、被观察、被评估、被接手”。

这个项目还很早期，但我已经在用它管理几个本地项目的长期目标。后面会继续补：

- 更好的项目 adapter；
- 多项目状态面板；
- goal run 的可视化 history；
- 更强的 public/private boundary check；
- 面向 Codex / Claude Code / Cursor 的接入范式。

仓库：`https://github.com/huangruiteng/goal-harness`

如果你也在用 AI coding 工具做长期项目，我会很想知道：你遇到的最大问题是模型不够强，还是目标、状态、验证和交接不够稳？

## Image Ideas

- Image 1: simple architecture diagram with `project goal state -> shared runtime -> agent tick / UI`.
- Image 2: terminal screenshot of `goal-harness bootstrap`.
- Image 3: screenshot or diagram of multi-project goals: `project A / project B / project C`.
- Image 4: public/private boundary checklist.

## Follow-Up Post Ideas

- 为什么我不把它做成完整 agent framework。
- Goal mode 为什么需要状态文件，而不是只靠长上下文。
- 多项目 AI 协作里，public/private boundary 为什么是产品能力。
- 从 prompt engineering 到 context engineering，再到 harness engineering。
