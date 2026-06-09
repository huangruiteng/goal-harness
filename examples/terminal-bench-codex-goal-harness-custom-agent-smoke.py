#!/usr/bin/env python3
"""Smoke-test codex_goal_harness custom-agent prompt and counters."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
TOPIC_DIR = REPO_ROOT / "docs" / "research" / "long-horizon-agent-benchmarks"
DOC = TOPIC_DIR / "terminal-bench-codex-goal-harness-custom-agent-v0.md"
README = TOPIC_DIR / "README.md"
MANAGED_AGENT_SMOKE = REPO_ROOT / "examples" / "terminal-bench-managed-codex-custom-agent-smoke.py"

FORBIDDEN_TEXT = [
    "/" + "Users/",
    "/" + "tmp/",
    ".local/benchmark-runs",
    "OPENAI" + "_API_KEY=",
    "ARK" + "_API_KEY=",
    "ARK" + "_BASE_URL=",
    "DOUBAO" + "_MODEL=",
    "CODEX" + "_AUTH_JSON_PATH=",
    "auth.json" + "\":",
    "raw" + "_thread",
    "session" + "_history",
    "lark" + "office",
    "fei" + "shu.cn",
    "sk-" + "example",
    "tok" + "en=",
    "-----BEGIN",
]

REQUIRED_DOC_SNIPPETS = [
    "Terminal-Bench Codex Goal Harness Custom Agent V0",
    "goal_harness_mode=codex_goal_harness",
    "Goal Harness Access Packet V0",
    "goal_harness_interface_surface: prompt_packet_only_no_cli_bridge",
    "goal_harness_cli_bridge_available: false",
    "goal_harness_cli_bridge_contract: terminal_bench_goal_harness_cli_bridge_contract_v0",
    "declared_goal_harness_interface_commands",
    "extract_goal_harness_interaction_counters_from_trace",
    "counter_trust_level=compact_trace_audited",
    "runtime_metadata_prompt_only_no_cli_bridge",
    "--agent-kwarg goal_harness_mode=codex_goal_harness",
    "python3 examples/terminal-bench-codex-goal-harness-custom-agent-smoke.py",
]


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_public_safe(payload: object) -> None:
    text = json.dumps(payload, sort_keys=True) if not isinstance(payload, str) else payload
    leaked = [marker for marker in FORBIDDEN_TEXT if marker in text]
    assert not leaked, leaked
    assert len(text) < 22000, len(text)


def assert_doc_contract() -> None:
    text = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")
    missing = [snippet for snippet in REQUIRED_DOC_SNIPPETS if snippet not in text]
    assert not missing, missing
    assert "terminal-bench-codex-goal-harness-custom-agent-v0.md" in readme, readme
    assert_public_safe(text)


def helper_module() -> Any:
    return load_module(MANAGED_AGENT_SMOKE, "terminal_bench_managed_codex_custom_agent_smoke_helper")


def counter_trace() -> list[dict[str, str]]:
    return [
        {"kind": "goal_harness_cli_call", "command": "status"},
        {"kind": "goal_harness_cli_call", "command": "quota_should_run"},
        {"kind": "goal_harness_cli_call", "command": "todo_list"},
        {"kind": "goal_harness_cli_call", "command": "history"},
        {"kind": "goal_harness_cli_call", "command": "check"},
        {"kind": "goal_harness_cli_call", "command": "append_benchmark_run"},
        {"kind": "goal_harness_state_read", "surface": "status"},
        {"kind": "goal_harness_state_read", "surface": "quota"},
        {"kind": "goal_harness_state_read", "surface": "todo"},
        {"kind": "goal_harness_state_read", "surface": "history"},
        {"kind": "goal_harness_state_write", "action": "append_benchmark_run"},
        {"kind": "codex_runtime_goal_tool_call", "name": "create_goal"},
        {"kind": "case_result_writeback", "target": "worker_goal_harness_writeback"},
    ]


def assert_counters(counters: dict[str, Any]) -> None:
    assert counters["schema_version"] == "terminal_bench_goal_harness_interaction_counters_v0", counters
    assert counters["prompt_policy_injected"] is True, counters
    assert counters["harness_skill_or_packet_injected"] is True, counters
    assert counters["codex_runtime_goal_tool_calls"]["create_goal"] == 1, counters
    assert counters["codex_runtime_goal_tool_calls"]["update_goal"] == 0, counters
    assert counters["codex_runtime_goal_tool_calls"]["total"] == 1, counters
    assert counters["goal_harness_cli_calls"]["total"] == 6, counters
    assert counters["goal_harness_cli_calls"]["status"] == 1, counters
    assert counters["goal_harness_cli_calls"]["append_benchmark_run"] == 1, counters
    assert counters["goal_harness_state_reads"] == 4, counters
    assert counters["goal_harness_state_writes"] == 1, counters
    assert counters["case_result_writeback"] == "worker_goal_harness_writeback", counters
    assert counters["counter_trust_level"] == "compact_trace_audited", counters
    assert counters["raw_trace_recorded"] is False, counters
    assert counters["raw_task_prompt_recorded"] is False, counters
    assert_public_safe(counters)


def assert_command_preview() -> None:
    from goal_harness.benchmark import (
        build_terminal_bench_benchmark_run,
        build_terminal_bench_managed_harbor_command,
    )

    command = build_terminal_bench_managed_harbor_command(
        goal_harness_mode="codex_goal_harness",
        job_name="terminal_bench_sample_build_cython_ext_codex_goal_harness_pilot",
    )
    assert "goal_harness_mode=codex_goal_harness" in command, command
    assert "goal_harness_goal_id=<goal-id>" in command, command
    assert "--upload" not in command, command
    assert "--share-org" not in command, command

    event = build_terminal_bench_benchmark_run(mode="codex-goal-harness")
    preview = event["managed_runner_command_preview"]
    assert "goal_harness_mode=codex_goal_harness" in preview, preview
    assert event["real_run"] is False, event
    assert event["submit_eligible"] is False, event
    assert_public_safe({"command": command, "event": event})


def assert_prompt_and_metadata() -> None:
    helper = helper_module()
    module = helper.load_agent_module()
    task = "Build the extension and make the test pass."
    instruction = module.build_managed_terminal_bench_instruction(
        task,
        goal_harness_mode="codex_goal_harness",
        goal_id="terminal-bench-fixture",
    )
    assert "Goal Harness Access Packet V0" in instruction, instruction
    assert "mode: codex_goal_harness" in instruction, instruction
    assert "available_goal_harness_interfaces" not in instruction, instruction
    assert "goal_harness_interface_surface: prompt_packet_only_no_cli_bridge" in instruction, instruction
    assert "goal_harness_cli_bridge_available: false" in instruction, instruction
    assert "goal_harness_cli_bridge_contract: terminal_bench_goal_harness_cli_bridge_contract_v0" in instruction, instruction
    assert "declared_goal_harness_interface_commands" in instruction, instruction
    assert "create_goal" not in instruction, instruction
    assert task in instruction, instruction

    agent = module.GoalHarnessManagedCodex(
        logs_dir=Path("logs"),
        model_name="gpt-5.5",
        goal_harness_mode="codex_goal_harness",
        goal_harness_goal_id="terminal-bench-fixture",
        goal_harness_counter_trace=counter_trace(),
    )
    context = helper.FakeAgentContext()
    asyncio.run(agent.run(task, object(), context))
    assert agent.received_instruction is not None
    assert "Goal Harness Access Packet V0" in agent.received_instruction
    assert context.is_empty(), context.metadata

    agent.populate_context_post_run(context)
    goal_harness = context.metadata["goal_harness"]
    assert goal_harness["mode"] == "codex_goal_harness", goal_harness
    assert goal_harness["goal_harness_access_packet_injected"] is True, goal_harness
    assert goal_harness["goal_harness_access_packet_schema_version"] == "terminal_bench_goal_harness_access_packet_v0", goal_harness
    assert goal_harness["goal_harness_interface_surface"] == "prompt_packet_only_no_cli_bridge", goal_harness
    assert goal_harness["goal_harness_cli_bridge_available"] is False, goal_harness
    assert goal_harness["goal_harness_cli_bridge_contract"] == "terminal_bench_goal_harness_cli_bridge_contract_v0", goal_harness
    assert goal_harness["goal_harness_prompt_only_until_cli_bridge"] is True, goal_harness
    assert goal_harness["available_goal_harness_interface_commands"] == [], goal_harness
    assert set(goal_harness["declared_goal_harness_interface_commands"]) == {
        "status",
        "quota_should_run",
        "todo_list",
        "history",
        "check",
        "append_benchmark_run",
    }, goal_harness
    assert goal_harness["raw_interaction_trace_recorded"] is False, goal_harness
    assert goal_harness["raw_managed_prompt_recorded"] is False, goal_harness
    assert goal_harness["context_post_run_ingested"] is True, goal_harness
    assert goal_harness["goal_harness_counter_trace_schema_version"] == "terminal_bench_goal_harness_counter_trace_v0", goal_harness
    assert_counters(goal_harness["goal_harness_interaction_counters"])
    assert_public_safe(goal_harness)

    prompt_only_agent = module.GoalHarnessManagedCodex(
        logs_dir=Path("logs"),
        model_name="gpt-5.5",
        goal_harness_mode="codex_goal_harness",
        goal_harness_goal_id="terminal-bench-fixture",
    )
    prompt_only_context = helper.FakeAgentContext()
    asyncio.run(prompt_only_agent.run(task, object(), prompt_only_context))
    prompt_only_agent.populate_context_post_run(prompt_only_context)
    prompt_only_counters = prompt_only_context.metadata["goal_harness"][
        "goal_harness_interaction_counters"
    ]
    assert prompt_only_counters["goal_harness_cli_calls"]["total"] == 0, prompt_only_counters
    assert prompt_only_counters["case_result_writeback"] == "not_observed_prompt_only_no_cli_bridge", prompt_only_counters
    assert prompt_only_counters["counter_trust_level"] == "runtime_metadata_prompt_only_no_cli_bridge", prompt_only_counters
    assert_public_safe(prompt_only_context.metadata["goal_harness"])


def main() -> None:
    assert_doc_contract()
    assert_command_preview()
    assert_prompt_and_metadata()
    print("terminal-bench-codex-goal-harness-custom-agent-smoke ok cli_calls=6 runtime_goal_calls=1")


if __name__ == "__main__":
    main()
