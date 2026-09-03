"""三种 Codex × LoopX 运行模式的声明式定义。

模式取自 LoopX README 的 Codex 三行 host 表（upstream README.md:289-291）。
三者的差别不是"接法不同"，而是 LoopX 渲染出的 body、闸门命令、结算来源不同——
这里把差别集中成数据，驱动逻辑（session.py / codex_host.py）对三者一视同仁。

实测三个 profile 在同一个 goal 上渲染出的差别（loopx 0.5.3）：

    codex_app_ssh_goal   body 2720 字符  guard 带 --begin-turn      spend --source visible-goal
    codex_cli            body 2698 字符  guard 不带 --begin-turn    spend --source visible-goal
    codex_app_heartbeat  body 1557 字符  guard --codex-app + LOOPX_TURN  spend --source heartbeat

前两者是 visible-Goal 渲染器（body 开头"in this visible Codex `/goal`"），
Codex 自己拥有续跑；第三个是精简派发器 body，每次唤醒是全新 turn，续跑由外部
调度器拥有。
"""

from __future__ import annotations

from dataclasses import dataclass


class ModeError(RuntimeError):
    """模式定义或使用方式不成立。"""


@dataclass(frozen=True)
class Mode:
    """一种运行模式。"""

    name: str
    """命令行上的短名。"""

    runtime_profile: str
    """传给 loopx 的 --runtime-profile。"""

    host_surface: str
    scheduler_owner: str
    execution_mode: str
    """profile 展开后的三元组，仅用于自检与记录，不重复传给 CLI。"""

    continuation_owner: str
    """'codex' = Codex 自己续跑（visible Goal）；'driver' = 本驱动按节拍再唤醒。"""

    needs_turn_instance: bool = False
    """是否每 tick 需要一个 LOOPX_TURN turn-instance-id。"""

    spend_source: str = "visible-goal"

    notes: str = ""
    """这个模式在无人值守环境下的真实边界，写进产物收据里。"""

    substitution: str = ""
    """若本适配器用了替代传输/替代 host_surface，在这里写清楚。空 = 无替代。"""


#: `Codex App over SSH` —— LoopX 自己的 benchmark 方法唯一认可的 treatment 臂。
#: benchmark/deepswe/README.md 要求三项产品路径证据：本 profile 渲染的 Goal body、
#: 装进 app-server 所用 CODEX_HOME 的 skills、以及 body 里点名的 release CLI。
SSH_GOAL = Mode(
    name="ssh-goal",
    runtime_profile="codex_app_ssh_goal",
    host_surface="codex_app_ssh",
    scheduler_owner="agent_cli_loop",
    execution_mode="interactive",
    continuation_owner="codex",
    spend_source="visible-goal",
    notes=(
        "LoopX benchmark/deepswe 的官方 treatment 臂。app-server 承载 visible Goal，"
        "Codex 拥有自动续跑；驱动只起首轮 turn 并观察终态。"
    ),
)

#: `Codex CLI` —— 可见 `/goal`。文档（docs/product/runtimes/codex-cli/
#: codex-cli-tui-loop.md 的 "Headless Disabled Boundary"）明确：这条路默认不提供
#: headless 回退，连 opt-in 都没有；`codex-cli-exec-handoff` 已从"输出可运行脚本"
#: 改成"报告禁用边界"。真正的 TUI 注入（Session-Attached Automation）在上游是
#: 一串 dry-run 诊断，没有任何代码真的往活 TUI 里写。
#:
#: 所以本适配器对这个模式做的是**传输替代**：body 仍由 `--runtime-profile codex_cli`
#: 渲染（渲染器、闸门命令、结算来源都是真的），但承载它的是 app-server 的 Goal
#: 事务而不是人值守的 TUI。这样模式语义可测，且不假装有人在场。
CODEX_CLI = Mode(
    name="codex-cli",
    runtime_profile="codex_cli",
    host_surface="codex_cli",
    scheduler_owner="agent_cli_loop",
    execution_mode="interactive",
    continuation_owner="codex",
    spend_source="visible-goal",
    notes=(
        "上游把有人值守的 TUI 当作本模式的定义特征，headless 回退被显式禁用。"
        "无人值守跑分时 body/闸门/结算是真的，承载传输是替代的。"
    ),
    substitution=(
        "transport: 用 codex app-server 的 Goal 事务承载 codex_cli 渲染的 visible "
        "body，替代人值守 TUI 里的 `/goal` 粘贴。渲染 profile 未被替换。"
    ),
)

#: `Codex App` 心跳 —— host_automation + hosted_automation。
#:
#: host_surface=codex_app 在上游是留给真 Codex App 产品的：它会回一套
#: scheduler_hint.codex_app.stateful_backoff（apply_needed / recommended_rrule /
#: reset_token / identity_signature），期待宿主去调 App 自己的 automation_update
#: 改 RRULE 再 ACK。没有真 App 就兑现不了，只会永远悬着或者伪造 ACK。
#:
#: 上游为自建定时器指定的对口是 `--runtime-profile generic_cli`：shell_worker
#: 参考实现 `scripts/external_scheduler_worker.py` 默认就是它，其 help 明写
#: "Quota runtime profile that emits the local_scheduler hint"。
#:
#: 不要直接传 -H local_scheduler：`--turn-instance-id` 只接受 generic_cli 或
#: codex_app_heartbeat（否则报 "requires runtime-profile generic_cli or
#: codex_app_heartbeat so quota guard creates a heartbeat receipt"），而没有
#: turn instance 就拿不到心跳收据。
HEARTBEAT = Mode(
    name="heartbeat",
    runtime_profile="generic_cli",
    host_surface="generic_cli",
    scheduler_owner="agent_cli_loop",
    execution_mode="interactive",
    continuation_owner="driver",
    needs_turn_instance=True,
    spend_source="heartbeat",
    notes=(
        "自建定时器拥有唤醒，对应上游 shell_worker 连接器。闸门发 local_scheduler "
        "提示（初始间隔 + 递进阶梯 + 未变轮询上限），驱动照 external_scheduler_"
        "worker.py 的做法推进阶梯。"
    ),
    substitution=(
        "host_surface: generic_cli 代替 codex_app —— 这是上游为自建定时器指定的"
        "对口 profile，不是权宜之计。用 --claim-codex-app 可切到硬声明 codex_app。"
    ),
)

#: `--claim-codex-app` 时用的变体：硬声明 codex_app。会拿到 App 形状的
#: stateful_backoff，但本驱动没有真 App 去 automation_update，apply_needed /
#: ack_needed 会一直悬着。仅用于观察这套义务在无 App 环境下如何卡住。
HEARTBEAT_CLAIM_APP = Mode(
    name="heartbeat-codex-app",
    runtime_profile="codex_app_heartbeat",
    host_surface="codex_app",
    scheduler_owner="host_automation",
    execution_mode="hosted_automation",
    continuation_owner="driver",
    needs_turn_instance=True,
    spend_source="heartbeat",
    notes=(
        "硬声明 codex_app。校验只查枚举组合、不验身份，所以能过；但没有真 App，"
        "scheduler_hint 的 apply_needed/ack_needed 无法诚实兑现。"
    ),
    substitution=(
        "host_surface: 声明为 codex_app 但没有真 Codex App 支撑。"
        "属上游文档意义上的误用，只用于观察义务如何悬空。"
    ),
)


MODES: dict[str, Mode] = {m.name: m for m in (SSH_GOAL, CODEX_CLI, HEARTBEAT)}
MODES[HEARTBEAT_CLAIM_APP.name] = HEARTBEAT_CLAIM_APP


def resolve(name: str, *, claim_codex_app: bool = False) -> Mode:
    """按短名取模式；heartbeat 可切成硬声明 codex_app 的变体。"""

    if name == HEARTBEAT.name and claim_codex_app:
        return HEARTBEAT_CLAIM_APP
    try:
        return MODES[name]
    except KeyError:
        raise ModeError(
            f"未知模式 {name!r}；可用：{', '.join(sorted(MODES))}"
        ) from None


def profile_args(mode: Mode) -> list[str]:
    """渲染成 loopx CLI 的 profile 参数。

    有具名 profile 就用 --runtime-profile（上游 round-trip 测试保证它与三元组
    等价）；没有的（local_scheduler）就显式传 -H/-O/-M。
    """

    if mode.runtime_profile:
        return ["--runtime-profile", mode.runtime_profile]
    return [
        "-H", mode.host_surface,
        "-O", mode.scheduler_owner,
        "-M", mode.execution_mode,
    ]
