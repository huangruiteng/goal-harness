# DSH × LoopX Replan Demo

This public-safe demo shows LoopX running inside a real DeepSeek Harness (DSH)
session. The agent starts with an ordinary library decision, receives a new
serverless constraint, and records an explicit Replan instead of silently
rewriting the earlier decision.

[![DSH × LoopX: one skill, durable work, real Replan](../../docs/assets/showcases/dsh-loopx/dsh-loopx-cover.png)](../../docs/assets/showcases/dsh-loopx/dsh-loopx-quickstart-replan.mp4)

**[Watch the 60-second recording](../../docs/assets/showcases/dsh-loopx/dsh-loopx-quickstart-replan.mp4).**

## What the recording proves

1. /loopx is selected explicitly from DSH's skill picker.
2. An ordinary research-and-implementation request creates durable Goal/Todo
   state.
3. A new serverless constraint changes the decision from Pino to Roarr through
   a recorded Replan.
4. The final implementation preserves CLI behavior, passes 3/3 tests, and
   closes the GoalBar at 2/2.

The dependency tree shown in the run changes from 12 packages to 4; the
machine-local installed footprint changes from roughly 2.2 MB to 548 KB. Those
measurements explain this example's decision, not a universal logger ranking.

## Install the DSH plugin

Requirements: Node.js 22.19+, npm, Python 3.11+, pip, pnpm, DSH, and a model
provider already configured in DSH.

    dsh plugin --profile web add \
      "https://github.com/huangruiteng/loopx/releases/download/dsh-loopx-plugin-v0.1.1-beta.4/dsh-loopx-plugin-0.1.1-beta.4.tgz"
    dsh --profile web --port 0

Invoke the loopx skill in the DSH composer. /loopx-init is the explicit repair
command; normal installation does not require it.

## Verify the completed fixture

    cd examples/dsh-loopx-demo
    npm ci --ignore-scripts
    npm test

This deterministic check verifies JSON stdout for success, JSON stderr for
failure, and their exit codes. It does not claim to replay the model's exact
wording.

## Reproduce the agent loop

    examples/dsh-loopx-demo/reproduce-demo.sh /tmp/dsh-loopx-replan-demo
    cd /tmp/dsh-loopx-replan-demo
    dsh --profile web --port 0

In DSH, select loopx and submit:

> Research Pino, Consola, and Roarr for this CLI. Record the evidence and
> decision, then complete a minimal integration and tests.

After the first decision, select loopx again and submit:

> New constraint: this CLI will run in serverless, so cold start and dependency
> footprint are now high priority. Re-evaluate the decision; if the plan
> changes, record a LoopX Replan and update implementation, docs, and tests.

Model wording and timing can vary. The acceptance boundary is the durable
decision change, preserved CLI behavior, passing tests, and closed Todo state.

## 中文说明

这段真实录屏展示了最短接入路径：安装 Plugin，在 DSH 技能选择器中显式选择
loopx，然后直接描述任务。Agent 最初选择 Pino；收到 serverless 冷启动和
依赖体积优先的新约束后，LoopX 保留原决策并记录 Replan，最终切换到 Roarr。

完整案例、证据边界和中英文分享文案见
[DSH × LoopX showcase](../../docs/showcases/cases/dsh-loopx-replan-demo.md)。
