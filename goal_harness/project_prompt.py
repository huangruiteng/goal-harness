from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from .bootstrap import default_goal_id


DEFAULT_HANDOFF_OBJECTIVE = "<OBJECTIVE_FROM_GOAL_DOC>"
DEFAULT_HANDOFF_DOMAIN = "<DOMAIN>"
DEFAULT_HANDOFF_ADAPTER_KIND = "read_only_project_map_v0"
DEFAULT_HANDOFF_ADAPTER_STATUS = "connected-read-only"
DEFAULT_HANDOFF_NEXT_PROBE = "(omit --next-probe until a read-only pre-tick command exists)"


def shell_arg(value: str) -> str:
    return shlex.quote(value)


def render_cli_preflight() -> str:
    return """install_script="$HOME/goal-harness/scripts/install-local.sh"
if ! command -v goal-harness >/dev/null 2>&1; then
  if [ -x "$install_script" ]; then
    "$install_script"
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "goal-harness is not on PATH; clone the Goal Harness repo and run scripts/install-local.sh" >&2
    exit 1
  fi
fi
goal-harness doctor >/dev/null"""


def render_quota_guard_command(goal_id: str) -> str:
    return f"goal-harness --format json quota should-run --goal-id {shell_arg(goal_id)}"


def render_quota_spend_command(goal_id: str, *, source: str = "adapter") -> str:
    return (
        "goal-harness quota spend-slot "
        f"--goal-id {shell_arg(goal_id)} "
        f"--slots 1 --source {shell_arg(source)} --execute"
    )


def render_connect_command(
    *,
    project: str,
    goal_doc: str,
    goal_id: str,
    objective: str,
    domain: str,
    adapter_kind: str,
    adapter_status: str,
    next_probe: str | None,
    spawn_allowed: bool,
    allowed_domains: list[str],
    write_scope: list[str],
) -> str:
    lines = [
        f"cd {shell_arg(project)}",
        "goal-harness connect \\",
        f"  --goal-id {shell_arg(goal_id)} \\",
        f"  --objective {shell_arg(objective)} \\",
        f"  --domain {shell_arg(domain)} \\",
        f"  --goal-doc {shell_arg(goal_doc)} \\",
        f"  --adapter-kind {shell_arg(adapter_kind)} \\",
        f"  --adapter-status {shell_arg(adapter_status)}",
    ]
    if next_probe:
        lines[-1] += " \\"
        lines.append(f"  --next-probe {shell_arg(next_probe)}")
    if spawn_allowed:
        lines[-1] += " \\"
        lines.append("  --spawn-allowed")
        for allowed_domain in allowed_domains:
            lines[-1] += " \\"
            lines.append(f"  --allowed-domain {shell_arg(allowed_domain)}")
        for scope in write_scope:
            lines[-1] += " \\"
            lines.append(f"  --write-scope {shell_arg(scope)}")
    return "\n".join(lines)


def build_new_project_prompt(
    *,
    project: Path,
    goal_doc: Path,
    goal_id: str | None,
    objective: str | None,
    domain: str | None,
    adapter_kind: str,
    adapter_status: str,
    next_probe: str | None,
    spawn_allowed: bool,
    allowed_domains: list[str] | None,
    write_scope: list[str] | None,
) -> dict[str, Any]:
    project_text = str(project.expanduser())
    goal_doc_text = str(goal_doc.expanduser())
    resolved_goal_id = goal_id or default_goal_id(project)
    resolved_objective = objective or DEFAULT_HANDOFF_OBJECTIVE
    resolved_domain = domain or DEFAULT_HANDOFF_DOMAIN
    resolved_next_probe = next_probe or DEFAULT_HANDOFF_NEXT_PROBE
    allowed_domains = allowed_domains or []
    write_scope = write_scope or []
    connect_command = render_connect_command(
        project=project_text,
        goal_doc=goal_doc_text,
        goal_id=resolved_goal_id,
        objective=resolved_objective,
        domain=resolved_domain,
        adapter_kind=adapter_kind,
        adapter_status=adapter_status,
        next_probe=next_probe,
        spawn_allowed=spawn_allowed,
        allowed_domains=allowed_domains,
        write_scope=write_scope,
    )
    quota_guard_command = render_quota_guard_command(resolved_goal_id)
    quota_spend_command = render_quota_spend_command(resolved_goal_id)
    prompt = render_prompt_text(
        project=project_text,
        goal_doc=goal_doc_text,
        goal_id=resolved_goal_id,
        objective=resolved_objective,
        domain=resolved_domain,
        adapter_kind=adapter_kind,
        adapter_status=adapter_status,
        next_probe=resolved_next_probe,
        cli_preflight=render_cli_preflight(),
        connect_command=connect_command,
        quota_guard_command=quota_guard_command,
        quota_spend_command=quota_spend_command,
        spawn_allowed=spawn_allowed,
        allowed_domains=allowed_domains,
        write_scope=write_scope,
    )
    return {
        "ok": True,
        "project": project_text,
        "goal_doc": goal_doc_text,
        "goal_id": resolved_goal_id,
        "objective": resolved_objective,
        "domain": resolved_domain,
        "adapter_kind": adapter_kind,
        "adapter_status": adapter_status,
        "next_probe": resolved_next_probe,
        "spawn_allowed": spawn_allowed,
        "allowed_domains": allowed_domains,
        "write_scope": write_scope,
        "connect_command": connect_command,
        "quota_guard_command": quota_guard_command,
        "quota_spend_command": quota_spend_command,
        "cli_preflight": render_cli_preflight(),
        "prompt": prompt,
    }


def render_prompt_text(
    *,
    project: str,
    goal_doc: str,
    goal_id: str,
    objective: str,
    domain: str,
    adapter_kind: str,
    adapter_status: str,
    next_probe: str,
    cli_preflight: str,
    connect_command: str,
    quota_guard_command: str,
    quota_spend_command: str,
    spawn_allowed: bool,
    allowed_domains: list[str],
    write_scope: list[str],
) -> str:
    spawn_note = "本项目初始不需要主控拆 sub-agent；除非目标文档另有授权，先保持单 controller read-only 接入。"
    if spawn_allowed:
        spawn_note = (
            "本项目允许主控拆 sub-agent；子 agent 只能进入已声明 allowed-domain，"
            "写入范围只能落在已声明 write-scope。"
        )
    allowed_domains_text = ", ".join(allowed_domains) if allowed_domains else "(none)"
    write_scope_text = ", ".join(write_scope) if write_scope else "(none)"
    return f"""我有一个新项目要接入 Goal Harness。

项目文件夹：
{project}

项目目标文档：
{goal_doc}

请你按下面步骤推进，不要停在方案讨论；如果信息缺失，先从目标文档和项目结构中做保守抽取，并在最后说明假设。

0. 先确认当前 shell 能调用 Goal Harness CLI；如果提示 `goal-harness` 不在 PATH，运行本机安装脚本再继续：

```bash
{cli_preflight}
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
2. 用这些初始参数作为默认值；如果目标文档给出更好的命名或边界，可以修正：
   - stable goal id: `{goal_id}`
   - objective: `{objective}`
   - domain: `{domain}`
   - adapter_kind: `{adapter_kind}`
   - adapter_status: `{adapter_status}`
   - goal_doc: `{goal_doc}`
   - next_probe: `{next_probe}`
   - spawn_allowed: `{spawn_allowed}`
   - allowed_domains: `{allowed_domains_text}`
   - write_scope: `{write_scope_text}`
3. 运行 Goal Harness 接入命令：

```bash
{connect_command}
```

4. 确认 `.goal-harness/registry.json` 和 `.codex/goals/{goal_id}/ACTIVE_GOAL_STATE.md` 已创建或更新。
   如果目标状态包含私有证据，把 `.goal-harness/` 和 `.codex/goals/` 加入该项目 `.gitignore`。
   `goal-harness connect` 默认会同步到共享全局 registry；不要手动编辑其他项目的 registry。
5. 在任何 heartbeat、scheduled tick、long-running adapter 或自主 delivery 前，先问 compute guard：

```bash
{quota_guard_command}
```

   如果返回 `should_run=false`，本轮不要做实现或 adapter 工作，只记录 public-safe reason；
   不要执行任何 `agent_command`，即使 status 或 review packet 里提到过命令。
   只有当返回 `should_run=true` 且 payload 里包含 `agent_command` 时，才执行该命令。
   如果 `should_run=true` 但没有 `agent_command`，只按 `recommended_action` 选择下一个安全只读动作。
   如果命令非零，fail closed，先修 `goal-harness doctor` / `goal-harness status`。
   这个 guard 不等于写权限、不绕过 operator gate、也不替代 human reward。
6. 生成一个 read-only project map 或 first pre-tick run。不要启动线上任务、不同步外部系统、不要写生产状态，除非目标文档明确授权。通用接入优先跑：

```bash
goal-harness read-only-map --goal-id {goal_id}
```

7. 如果本轮只更新了 active state、ledger 或外部规划文档，没有产生新的 adapter run，或者 dashboard 仍显示旧 run，追加一个 state-only refresh run：

```bash
goal-harness refresh-state --goal-id {goal_id}
```

这个命令也会自动同步全局 registry。

8. 跑验证：
   - `goal-harness registry`
   - `goal-harness status`（在没有项目局部 registry 的目录里也应自动读共享全局 registry）
   - `goal-harness check --scan-path <PUBLIC_SAFE_FILE_OR_DIR>`
9. 如果本轮实际花了 automatic delivery compute（例如 read-only map、adapter tick、实现推进或验证推进），在 validation 和必要的 `refresh-state` 完成后，只 append 一次 quota spend：

```bash
{quota_spend_command}
```

   不要为 `should_run=false` 的 skip、preflight 失败、或纯 dry-run preview 记账；不要重复执行。
10. 最后用中文汇报：
   - changed files；
   - validation output；
   - 当前 goal 在 dashboard / attention queue 里会怎么显示；
   - next safe action；
   - 如果还不能接入 decision-advisor，明确缺哪些 gates。

并行/权限边界：
{spawn_note}
"""


def render_new_project_prompt_markdown(payload: dict[str, Any]) -> str:
    return f"""# New Project Codex Handoff Prompt

Copy the block below into the Codex session that can access the target project.

````text
{payload.get("prompt", "")}
````

## Generator Inputs

- project: `{payload.get("project")}`
- goal_doc: `{payload.get("goal_doc")}`
- goal_id: `{payload.get("goal_id")}`
- domain: `{payload.get("domain")}`
- adapter: `{payload.get("adapter_kind")}:{payload.get("adapter_status")}`
"""
