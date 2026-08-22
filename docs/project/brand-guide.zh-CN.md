# LoopX 对外品牌使用指南

这份指南面向希望提及 LoopX、描述集成、展示 LoopX 名称或图形的开源项目、商业公司、
用户、作者和活动组织者。它是项目层面的实务指引，不是法律意见；名称和标识的当前
项目立场仍见[名称与标识使用说明](trademarks.md)。

最短规则是：准确介绍 LoopX，清楚介绍自己的产品，并且不要让读者在没有依据时误以为
存在赞助、认证、合作、背书或官方发行关系。

## 1. LoopX 是什么

对外介绍可以从这段事实性描述开始：

> LoopX 是一个开放、provider-neutral、local-first 的长程 Agent 动态目标控制面。
> 它让 goal、todo、decision scope、gate、evidence、quota、handoff 和 recovery
> 在有界 turn 之间保持可见。

LoopX 运行在 agent harness 之上。harness 或应用继续执行工作；LoopX 负责让控制状态
可审阅、可恢复。

不要把 LoopX 描述成模型、agent runtime、完整 agent platform 或自治生产控制器。LoopX
不授予 credential，不批准 destructive 或 production action，也不会把未经验证的运行
变成成功证明。

## 2. 先选择关系表述

根据公开实现和证据，选择最窄的关系词：

| 你的项目或产品… | 可以说… | 不要暗示… |
| --- | --- | --- |
| 链接或讨论 LoopX | “提到 LoopX”或“记录 LoopX” | 已经集成或获得背书 |
| 调用公开的 LoopX 命令或契约 | “使用 LoopX” | LoopX 在运营你的服务 |
| 通过维护中的 adapter 交换状态 | “集成 LoopX” | adapter 是 LoopX 官方产品 |
| 在 LoopX 周围增加 provider 或 extension | “扩展 LoopX” | extension 由 LoopX 维护 |
| 是修改版发行 | “LoopX 的 fork”或“基于 LoopX” | 是官方 LoopX 发行版 |
| 仍在探索想法 | “proposed”或“experimental” | 已交付兼容能力 |

只有维护者针对具体表面和版本明确授权时，才使用“LoopX 官方”“LoopX 认证”“LoopX
合作伙伴”等表述。

## 3. 名称、包名和产品身份

- 项目名称写作 **LoopX**。不要写成 `Loop X`、`loop-x`，也不要用没有边界的“自治
  Agent 平台”替代项目名。
- 不由 LoopX 运营的项目、公司、托管服务、package、domain 或社交账号，不应把
  `LoopX` 作为主要身份使用到看起来像官方表面的程度。
- `acme-loopx-adapter` 这类描述真实集成关系的名称可以解释用途，但周边页面必须清楚
  写明 Acme 是运营者，并且不能使用“官方”等同义表述。
- fork 或实质修改后的发行版应有自己的主要名称，把与 LoopX 的关系放在次要描述中。
- 在标题、package 描述、目录条目和社交简介中直接写清项目名称和关系，不要只藏在 badge
  或页脚里。

## 4. Logo 与图形素材

仓库当前的公开素材在 [`docs/assets/`](../assets/)，包括
[`loopx-logo.png`](../assets/loopx-logo.png)、social preview 和 control-plane 图表。

展示标识或截图时：

- 保留原图、比例和可读对比度；
- 留出足够周边空间，避免读者把标识误认成你自己的产品标识；
- 在周边引用中链接官方 LoopX 仓库或文档；
- 在集成页、托管服务页或商业产品页上展示标识时，明确写出你的产品和运营者。

不要重绘、拉伸、改色、裁切成新 logo、动画化，也不要以让产品看起来像 LoopX 官方表面的
方式组合标识。未经维护者许可，不要把 LoopX 标识用作无关产品的 favicon、app icon 或
主要头像。

如果现有素材不适合布局，使用纯文本 **LoopX** 并链接项目，不要自行发明替代 logo。

## 5. 常见对外表面

### 开源 README 或文档

可以这样写：

> Acme Relay 集成 LoopX 以持久化有界 goal state。Acme Relay 是独立项目；详见集成
> 指南和 LoopX 项目。

如果能力依赖版本、adapter 或命令，写出具体边界。`works with LoopX` badge 应链接到
解释实际测试内容的页面；badge 不是认证证明。

### 商业产品或托管服务

把公司和服务作为主要产品来命名，说明服务如何使用 LoopX 以及谁负责运营。“Acme Cloud
集成 LoopX”比“LoopX Cloud”更清楚，后者会让人误以为服务由 LoopX 运营。

不要在定价层级、domain、账号名称或销售标题中使用 LoopX 到让人误以为服务由 LoopX 托管、
销售或支持的程度。仅有 API 或 adapter 并不等于合作伙伴关系。

### Fork、plugin、extension 或发行版

给发行版一个独立的主要名称并写清关系，例如“Acme Flow，LoopX 的 fork”或“Acme Flow，
LoopX 的 extension”。保留适用软件许可证要求的 notices，说明修改、支持边界以及没有
LoopX 背书这一事实。

### 博客、演讲、benchmark 或比较文章

准确使用 LoopX 作为被讨论对象。把测量结果归因到具体的公开 setup、版本和证据。不要
把一次 demo、star 数、benchmark 行或用户报告写成 LoopX 普遍都会得到的结果。

## 6. 联合品牌、活动和看起来官方的使用

如果使用涉及以下情况，请在发布前向维护者询问：

- 联合 logo、“官方”集成 badge、认证或 partner 标识；
- 托管服务、付费产品、会议板块或活动，其名称显著包含 LoopX；
- 可能被误认成 LoopX 运营表面的 package、domain、社交账号或 app icon；
- 以 LoopX 公告形式发布的 press quote、launch 文案或兼容性声明；
- 视觉身份高度接近 LoopX 项目的修改版发行。

请开一个聚焦的 GitHub issue，写明拟用文案、使用表面和相关版本。不要在 issue 中放
credential、私有证据、未公开的安全细节或私下商业安排。

## 7. ADOPTERS 与公开归因

项目和用户可以自愿在 [`ADOPTERS.md`](../../ADOPTERS.md) 添加公开、自报的条目。该目录
记录提交者声称使用了什么，不代表 LoopX 认证或背书。选择 adoption mode，说明 active
还是 experimental，链接公开证据，并避免私有或无法核验的声明。

维护者观察到的[生态采用清单](../community/ecosystem-adoption.zh-CN.md)是另一份记录。没有
项目或用户自愿提交，不要把观察内容复制进 `ADOPTERS.md`。

## 8. 归因与声明卫生

每次对外引用都应：

1. 把 **LoopX** 链接到规范仓库或对应版本文档；
2. 写出外部项目的运营者和支持边界；
3. 说明使用了哪个 command、adapter、release 或公开行为；
4. 在有必要时标记 shipped、observed、reported 或 proposed；
5. 说明证据没有证明什么，尤其不要暗示背书或普遍能力。

Apache 和历史 MIT license 按各自条款覆盖代码和文档。它们不会把第三方产品变成官方
LoopX 产品，也不授予误述项目身份的许可。

## 9. 快速检查清单

发布提及 LoopX 的页面、package、launch 或视觉素材前，检查：

- **LoopX** 是否拼写正确并正确链接？
- 外部运营者或作者是否一眼可见？
- 关系词是否由实现和证据支持？
- 相关时是否写明版本、adapter 或测试表面？
- 页面、package、logo 或服务是否可能被误认为 LoopX 官方提供？
- 未经明确授权，是否避免了认证、赞助、合作、背书等表述？
- 截图、用户数据、私有路径和 raw run 是否 public-safe？
- 如果使用有歧义，是否已在发布前开聚焦的维护者询问？
