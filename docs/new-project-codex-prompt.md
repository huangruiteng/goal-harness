# New Project Codex Prompt

Use this prompt when you already have:

- a local project folder;
- a project goal document;
- a Codex session with access to that folder.

Replace the placeholders before sending it to Codex.

## CLI Generator

Generate the same handoff prompt locally:

```bash
goal-harness new-project-prompt \
  --project <PROJECT_ROOT> \
  --goal-doc <GOAL_DOC_PATH>
```

If the project needs a controller that can split scoped sub-agent probes:

```bash
goal-harness new-project-prompt \
  --project <PROJECT_ROOT> \
  --goal-doc <GOAL_DOC_PATH> \
  --spawn-allowed \
  --allowed-domain docs-map \
  --allowed-domain validation-map \
  --write-scope "docs/**"
```

## Copy-Paste Prompt

````text
我有一个新项目要接入 Goal Harness。

项目文件夹：
<PROJECT_ROOT>

项目目标文档：
<GOAL_DOC_PATH>

请你按下面步骤推进，不要停在方案讨论：

0. 先确认当前 shell 能调用 Goal Harness CLI；如果提示 `goal-harness`
   不在 PATH，运行本机安装脚本再继续：

   ```bash
   install_script="$HOME/goal-harness/scripts/install-local.sh"
   if ! command -v goal-harness >/dev/null 2>&1; then
     if [ -x "$install_script" ]; then
       "$install_script"
       export PATH="$HOME/.local/bin:$PATH"
     else
       echo "goal-harness is not on PATH; clone the Goal Harness repo and run scripts/install-local.sh" >&2
       exit 1
     fi
   fi
   goal-harness doctor >/dev/null
   ```

1. 再只读检查项目文件夹和目标文档，抽取：
   - stable goal id；
   - 一句话 objective；
   - domain；
   - authority sources；
   - work clusters；
   - validation surfaces；
   - private/public boundary；
   - 第一个 recommended_action。
2. 运行 Goal Harness 接入命令。优先使用：

   cd <PROJECT_ROOT>
   goal-harness connect \
     --goal-id <STABLE_GOAL_ID> \
     --objective "<OBJECTIVE_FROM_GOAL_DOC>" \
     --domain <DOMAIN> \
     --goal-doc <GOAL_DOC_PATH> \
     --adapter-kind read_only_project_map_v0 \
     --adapter-status connected-read-only

   如果已有安全的只读 pre-tick 命令，再追加：

   --next-probe "<READ_ONLY_PRE_TICK_COMMAND>"

   如果项目需要主控拆 sub-agent，再加：

   --spawn-allowed \
   --allowed-domain docs-map \
   --allowed-domain validation-map \
   --write-scope "<SAFE_WRITE_SCOPE>"

3. 确认 `.goal-harness/registry.json` 和
   `.codex/goals/<STABLE_GOAL_ID>/ACTIVE_GOAL_STATE.md` 已创建或更新。
   如果目标状态包含私有证据，把 `.goal-harness/` 和 `.codex/goals/`
   加入该项目 `.gitignore`。
   `goal-harness connect` 默认会同步到共享全局 registry；不要手动编辑其他
   项目的 registry。
4. 在任何 heartbeat、scheduled tick、long-running adapter 或自主 delivery 前，
   先问 compute guard：

   ```bash
   goal-harness --format json quota should-run --goal-id <STABLE_GOAL_ID>
   ```

   如果返回 `should_run=false`，本轮不要做实现或 adapter 工作，只记录
   public-safe reason；不要执行任何 `agent_command`，即使 status 或 review
   packet 里提到过命令。只有当返回 `should_run=true` 且 payload 里包含
   `agent_command` 时，才执行该命令。如果 `should_run=true` 但没有
   `agent_command`，只按 `recommended_action` 选择下一个安全只读动作。
   如果命令非零，fail closed，先修
   `goal-harness doctor` / `goal-harness status`。这个 guard 不等于写权限、
   不绕过 operator gate、也不替代 human reward。
5. 生成一个 read-only project map 或 first pre-tick run。不要启动线上任务、
   不同步外部系统、不要写生产状态，除非目标文档明确授权。通用接入优先跑：

   ```bash
   goal-harness read-only-map --goal-id <STABLE_GOAL_ID>
   ```
6. 如果本轮只更新了 active state、ledger 或外部规划文档，没有产生新的
   adapter run，或者 dashboard 仍显示旧 run，追加一个 state-only refresh
   run：

   ```bash
   goal-harness refresh-state --goal-id <STABLE_GOAL_ID>
   ```

   这个命令也会自动同步全局 registry。

7. 跑验证：
   - `goal-harness registry`
   - `goal-harness status`（在没有项目局部 registry 的目录里也应自动读共享全局 registry）
   - `goal-harness check --scan-path <PUBLIC_SAFE_FILE_OR_DIR>`
8. 如果本轮实际花了 automatic delivery compute（例如 read-only map、adapter tick、
   实现推进或验证推进），在 validation 和必要的 `refresh-state` 完成后，只
   append 一次 quota spend：

   ```bash
   goal-harness quota spend-slot --goal-id <STABLE_GOAL_ID> --slots 1 --source adapter --execute
   ```

   不要为 `should_run=false` 的 skip、preflight 失败、或纯 dry-run preview 记账；
   不要重复执行。
9. 最后用中文汇报：
   - changed files；
   - validation output；
   - 当前 goal 在 dashboard/attention queue 里会怎么显示；
   - next safe action；
   - 如果还不能接入 decision-advisor，明确缺哪些 gates。
````

## Minimal Command

If the goal is simple and does not need a project-specific adapter yet:

```bash
cd <PROJECT_ROOT>
goal-harness connect \
  --goal-id <STABLE_GOAL_ID> \
  --objective "<OBJECTIVE_FROM_GOAL_DOC>" \
  --domain <DOMAIN> \
  --goal-doc <GOAL_DOC_PATH>
```

Then inspect:

```bash
goal-harness registry
goal-harness status
goal-harness check --scan-root .
```

## What Good Looks Like

The first connection is successful when:

- the project has a stable `ACTIVE_GOAL_STATE.md`;
- the registry points to that state file;
- the goal appears in `goal-harness status`;
- the attention queue says exactly who should act next;
- private evidence is kept in the project or local runtime, not in public docs;
- the next Codex tick can continue from saved state instead of re-reading the
  whole conversation.

For larger projects, the first useful adapter is usually read-only. It should
map documents, TODOs, validation surfaces, risks, and handoff packets before it
edits files.
