"""用 codex app-server 承载一轮 Goal。

三种模式共用这一个 host：LoopX 渲染出的 task_body 作为 Goal objective 送进
app-server 的 Goal 事务，Codex 执行。模式差别在于**谁拥有续跑**：

  continuation_owner="codex"   —— visible Goal，起首轮后 Codex 自己续跑到终态，
                                  驱动只观察（run_until_terminal）。
  continuation_owner="driver"  —— 心跳，每次唤醒是全新一轮，驱动起完这轮就收，
                                  下次 tick 用新的 body 再起（run_single_turn）。

Goal 状态机本身不在这里实现：直接用 benchmark_toolkit 里那份安装态运行时，
上游 benchmark/deepswe/README.md 明确要求适配器 import 它而不是抄第二份。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

from loopx.capabilities.benchmark_toolkit.native_codex_goal import (
    NativeGoalConfig,
    NativeGoalDeadlineExceeded,
    NativeGoalProtocolError,
    StdioNativeGoalTransport,
    compact_native_goal_receipt,
    probe_native_goal_process,
    refresh_native_goal_status,
    start_native_goal_turn,
    wait_native_goal_turn,
)

from .profiles import Mode


class HostError(RuntimeError):
    """app-server 那一侧没能按契约走完。"""


def app_server_command(codex_bin: str) -> list[str]:
    """起 app-server 的 argv。

    两个 feature 都要开：goals 是 Goal 事务本身，unified_exec 是工具面。基线臂
    也开 unified_exec，两臂工具面必须一致，否则比的是工具不是 harness。
    """

    return [
        codex_bin,
        "app-server",
        "--listen", "stdio://",
        "--enable", "goals",
        "--enable", "unified_exec",
    ]


@dataclass
class CodexHost:
    """把一个 task_body 交给 codex 跑。"""

    codex_bin: str
    mode: Mode
    model: str | None = None
    effort: str | None = None
    """推理档位，进 turn/start 的 turn_params.effort（native_codex_goal.py:277）。"""
    sandbox: str = "danger-full-access"
    required_skill_ids: tuple[str, ...] = ()
    response_timeout_sec: float = 60.0
    goal_timeout_sec: float = 1800.0
    process_env: dict[str, str] | None = None

    def _config(self, *, cwd: str, objective: str, task_instruction: str) -> NativeGoalConfig:
        return NativeGoalConfig(
            cwd=cwd,
            objective=objective,
            task_instruction=task_instruction,
            model=self.model,
            effort=self.effort,
            sandbox=self.sandbox,
            required_skill_ids=self.required_skill_ids,
        )

    def _env(self) -> dict[str, str]:
        """app-server 的环境。

        process_env 里带着 profile 的 CODEX_HOME —— 少了它，codex 的 skills/list
        找不到装好的技能，required_skill_ids 门禁会以
        required_skills_missing 失败。preflight 和 run 必须用同一份，否则
        preflight 过了 run 才炸（或者反过来），白跑。
        """

        return {**os.environ, **(self.process_env or {})}

    def preflight(self, *, cwd: str, objective: str, task_instruction: str,
                  process_cwd: str | None = None) -> dict[str, Any]:
        """只证 initialize / thread / Goal 挂载，不起模型 turn。不烧 token。"""

        turn = probe_native_goal_process(
            self._config(cwd=cwd, objective=objective, task_instruction=task_instruction),
            process_command=app_server_command(self.codex_bin),
            process_env=self._env(),
            process_cwd=process_cwd,
            response_timeout_sec=self.response_timeout_sec,
        )
        receipt = compact_native_goal_receipt(turn)
        receipt["execution_mode"] = "goal_attachment_preflight"
        return receipt

    def run(self, *, cwd: str, objective: str, task_instruction: str,
            process_cwd: str | None = None) -> dict[str, Any]:
        """跑一轮，跑到 Goal 离开 active 或预算耗尽为止。

        **不用上游的 run_native_goal_process_until_terminal**：那个函数在预算耗尽时
        抛 NativeGoalDeadlineExceeded，而异常不携带 turn 对象，于是整份收据全丢。
        实测后果是——模型已经把任务做完（文件改了、测试建了、跑通了），只因为 Goal
        还没离开 active 就被记成"彻底失败、零信息"。

        长程任务里预算耗尽是**正常终止**而不是异常：SWE-Marathon 的任务超时上到
        10 小时，本来就指望跑满预算再交给验证器判分。所以这里照抄上游的循环
        （native_codex_goal.py:412-449 同样的 start/wait/refresh 三步），只把终止
        原因作为数据返回，收据一律保留。
        """

        config = self._config(cwd=cwd, objective=objective,
                              task_instruction=task_instruction)
        config.validate()
        deadline = time.monotonic() + self.goal_timeout_sec
        stop_reason = "goal_terminal"

        with StdioNativeGoalTransport.spawn(
            app_server_command(self.codex_bin),
            env=self._env(),
            cwd=process_cwd or cwd,   # spawn 的 cwd 是必填
        ) as transport:
            turn = start_native_goal_turn(transport, config)
            completed_before = turn.turn_completed_count
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stop_reason = "budget_exhausted"
                    break
                try:
                    wait_native_goal_turn(
                        transport, turn,
                        timeout_sec=remaining,
                        completed_before=completed_before,
                    )
                except NativeGoalDeadlineExceeded:
                    stop_reason = "budget_exhausted"
                    break
                except NativeGoalProtocolError as exc:
                    if str(exc) == "goal_turn_timeout":
                        stop_reason = "budget_exhausted"
                        break
                    raise
                completed_before = turn.turn_completed_count
                if refresh_native_goal_status(transport, turn) != "active":
                    break
                # 心跳模式一次唤醒只做一段：Codex 的续跑归外部调度器管，
                # 这一轮到此为止，下一 tick 由 LoopX 重新渲染 body 再起。
                if self.mode.continuation_owner == "driver":
                    stop_reason = "single_wake_complete"
                    break

        receipt = compact_native_goal_receipt(turn)
        receipt["execution_mode"] = (
            "goal_until_terminal" if self.mode.continuation_owner == "codex"
            else "goal_single_wake"
        )
        receipt["continuation_owner"] = self.mode.continuation_owner
        receipt["stop_reason"] = stop_reason
        return receipt


def classify(receipt: dict[str, Any]) -> str:
    """把 Goal 收据折成一个 refresh-state 能吃的分类标签。

    只看运行时自己的 typed 计数，不去解析模型说了什么——模型自称完成不是完成。
    """

    status = str(receipt.get("post_goal_status") or "")
    turns = int(receipt.get("turn_completed_count") or 0)
    if receipt.get("terminal_event_observed") and status and status != "active":
        return "validated_progress" if turns else "replan_required"
    # 预算耗尽但确实推进过：算进展，不算需要修复——判分交给 benchmark 的验证器。
    if turns:
        return "validated_progress"
    return "repair_required"
