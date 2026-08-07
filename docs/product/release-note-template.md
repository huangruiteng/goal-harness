<!--
Copy this file into the draft GitHub release body. Replace every angle-bracket
placeholder, remove instructional comments, and omit empty detailed groups.
Keep the Release Decision section compact enough to scan before the fold.
-->

# LoopX vX.Y.Z

<Summarize the release in one outcome-led paragraph. Name the most important
improvement and its authority or compatibility boundary without repeating the
section list.>

## Release Decision

**Who should upgrade:** <Name the affected users or operators and say who can
remain on the current version. Do not write "everyone" without a reason.>

**What this release solves:** <State the concrete failure, missing workflow, or
reliability gap addressed by this release.>

**Breaking changes:** <Start with "No." or "Yes." If yes, give the migration
path. If no, still name any changed default, deprecated path, or experimental
surface that existing users should notice.>

**How to verify:** <State the expected post-upgrade result, then provide the
smallest commands that prove package identity and the affected behavior.>

**Contributors:** <Name the release maintainer and every community contributor
from the tag range, or explicitly state that there were no community
contributions in this release. Link the detailed section when present.>

```bash
loopx --version
loopx doctor
<focused-command-that-proves-the-affected-behavior>
```

<!-- Omit an empty product group. Every material claim needs direct PR links. -->

## State Kernel & Control Plane

- <User-visible state, todo, quota, scheduler, gate, peer-routing, or authority
  change with direct PR links.>

## Capabilities & Workflows

- <Shipped user outcome, shipped layer, and any last-mile boundary with direct
  PR links.>

## Quality & Testing

- <Durable regression coverage, canary, qualification, or release-gate change
  with direct PR links.>

## Benchmarks & Integrations

- <Host, provider, benchmark, or external-boundary change with direct PR links.
  State explicitly when no benchmark or long-horizon outcome claim is made.>

## Documentation & Compatibility

- <Documentation, migration, default, deprecation, or compatibility detail with
  direct PR links. Repeat the persisted-state migration decision explicitly.>

<!--
Include this section only when the tag range contains eligible contributors
other than @huangruiteng. Keep founder stewardship out of this community-only
section; it is already named in Release Decision when relevant.
-->

## Community Contributors

- <Link each eligible GitHub handle and PR, and name the concrete contribution.
  Call out external or first-time contributors when applicable.>

## Optional Capability Activation & Use

No new optional capability activation is introduced in this release.

<!--
If the release adds or materially changes an experimental, default-off, or
opt-in surface, replace the no-change declaration with one entry per surface:

### <Surface Name>

**Activation:** <Exact install, enable, command, or profile opt-in.>

**Validation:** <Minimum runnable readback or verification command.>

**Disable / rollback:** <Exact disable, uninstall, envelope removal, or rollback.>

**Authority boundary:** <Writes, merges, providers, privacy, or host powers not granted.>

**Docs:** https://github.com/huangruiteng/loopx/blob/vX.Y.Z/<canonical-doc>

```bash
<activation-command>
<validation-command>
<disable-or-rollback-command>
```
-->

## Install / Update

New users should install from the named stable ref. Existing users should
preview the update, then execute it explicitly:

```bash
loopx update --check --ref stable
loopx update --execute --ref stable
loopx doctor
```

## 中文摘要

### 升级决策

**谁需要升级：**<写明受影响的用户或 operator，以及谁可以暂不升级。>

**解决了什么：**<用结果语言说明本版本解决的故障、缺口或可靠性问题。>

**是否有破坏性变更：**<以“无。”或“有。”开头；若有则给出迁移路径，
若无也要说明默认值、废弃路径或实验能力的变化。>

**如何验证：**<指向上方最小验证命令，并写明升级后的预期结果。>

**贡献者：**<用 GitHub handle 列出 release maintainer 与 tag range 内的
社区贡献者；若没有社区贡献者则明确说明。>

<!-- 保留与英文相同的非空产品分组、PR 归因和边界，可以更短但不能弱化。 -->

### 状态内核与控制面

- <中文摘要与 PR 链接。>

### 能力与工作流

- <中文摘要与 PR 链接。>

### 质量与测试

- <中文摘要与 PR 链接。>

### 基准与集成

- <中文摘要与 PR 链接。>

### 文档与兼容性

- <中文摘要与 PR 链接。>

<!-- 英文存在 Community Contributors 时，保留同一人员、PR 和贡献范围。 -->

### 社区贡献者

- <社区贡献者中文归因。>

### 可选能力启用与使用

本版本未新增可选能力启用入口。

<!--
若英文存在 optional capability 条目，以 #### <Surface Name> 逐项镜像，并使用：
**启用：**、**验证：**、**停用 / 回退：**、**权限边界：**、**文档：**，
同时保留可运行的 bash 命令块。
-->

### 发布验证

- Package version and public tag: `X.Y.Z` / `vX.Y.Z`.
- Tag target: `<full-commit-sha>`.
- <Exact-commit checks that passed, including failures or skips without
  overclaiming hosted, live-model, benchmark, or long-horizon evidence.>

Compare: https://github.com/huangruiteng/loopx/compare/vPREVIOUS...vX.Y.Z
