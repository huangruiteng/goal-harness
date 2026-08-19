"""Benchmark-source compatibility import for the shipped native Goal runtime.

Real adapters should import from
``loopx.capabilities.benchmark_toolkit.native_codex_goal``.  This facade keeps
the research tree's original import path thin so it cannot become a second
Goal state-machine implementation.
"""

from loopx.capabilities.benchmark_toolkit.native_codex_goal import (
    NativeGoalConfig,
    NativeGoalEventTransport,
    NativeGoalProtocolError,
    NativeGoalTransport,
    NativeGoalTurn,
    StdioNativeGoalTransport,
    attach_native_goal,
    compact_native_goal_receipt,
    observe_native_goal_event,
    probe_native_goal_process,
    refresh_native_goal_status,
    run_native_goal_process,
    run_native_goal_process_until_terminal,
    run_native_goal_turn,
    run_native_goal_until_terminal,
    start_native_goal_turn,
    wait_native_goal_turn,
)
from loopx.capabilities.benchmark_toolkit.native_codex_profile import (
    NATIVE_CODEX_GOAL_PROMPT_SCHEMA_VERSION,
    NATIVE_CODEX_PROFILE_REQUIRED_SKILL_IDS,
    NativeCodexGoalPrompt,
    NativeCodexProfile,
    NativeCodexProfileError,
    compact_native_codex_goal_prompt_receipt,
    compact_native_codex_profile_receipt,
    inspect_native_codex_profile,
    install_native_codex_profile,
    native_codex_app_server_environment,
    native_codex_profile_environment,
    render_native_codex_goal_prompt,
)

__all__ = [
    "NATIVE_CODEX_GOAL_PROMPT_SCHEMA_VERSION",
    "NATIVE_CODEX_PROFILE_REQUIRED_SKILL_IDS",
    "NativeCodexGoalPrompt",
    "NativeCodexProfile",
    "NativeCodexProfileError",
    "NativeGoalConfig",
    "NativeGoalEventTransport",
    "NativeGoalProtocolError",
    "NativeGoalTransport",
    "NativeGoalTurn",
    "StdioNativeGoalTransport",
    "attach_native_goal",
    "compact_native_codex_goal_prompt_receipt",
    "compact_native_codex_profile_receipt",
    "compact_native_goal_receipt",
    "inspect_native_codex_profile",
    "install_native_codex_profile",
    "native_codex_app_server_environment",
    "native_codex_profile_environment",
    "observe_native_goal_event",
    "probe_native_goal_process",
    "refresh_native_goal_status",
    "render_native_codex_goal_prompt",
    "run_native_goal_process",
    "run_native_goal_process_until_terminal",
    "run_native_goal_turn",
    "run_native_goal_until_terminal",
    "start_native_goal_turn",
    "wait_native_goal_turn",
]
