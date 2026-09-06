"""Structured guidance survives summary/chunk noise without changing other clients."""

import json
import subprocess

from loopx.capabilities.context_providers.openviking import OpenVikingContextProvider


def test_reward_retrieval_uses_bodies_and_refills_after_unusable_hits():
    root = "viking://resources/example"
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[1] == "--version":
            output = "OpenViking 0.4.9"
        elif command[1] == "status":
            output = "{}"
        elif command[1] == "search":
            assert "-L" in command and command[command.index("-L") + 1] == "2"
            assert command[command.index("-n") + 1] == "8"
            output = json.dumps(
                {
                    "resources": [
                        {"uri": root + "/.overview.md", "level": 1},
                        {"uri": root + "/bad", "level": 2},
                        {"uri": root + "/one#chunk_0001", "level": 2},
                        {"uri": root + "/one#chunk_0002", "level": 2},
                        {"uri": root + "/two", "level": 2},
                    ]
                }
            )
        else:
            assert command[1] == "read"
            assert "#" not in command[2] and "overview" not in command[2]
            output = json.dumps(
                {
                    "content": "not a record"
                    if command[2].endswith("bad")
                    else json.dumps(
                        {"schema_version": "reward_memory_active_record_v0"}
                    )
                }
            )
        return subprocess.CompletedProcess(command, 0, output)

    provider = OpenVikingContextProvider(runner=runner)
    result = provider.retrieve(
        namespace="reward_memory",
        scope_ref=root,
        query="example destination guidance",
        query_summary="guidance",
        max_results=2,
        timeout_seconds=30,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert [item.resource_ref for item in result.items] == [
        root + "/one",
        root + "/two",
    ]
    assert sum(c[1:3] == ["read", root + "/one"] for c in calls) == 1


def test_other_namespaces_keep_original_search_contract():
    def runner(command, **kwargs):
        if command[1] == "--version":
            output = "OpenViking 0.4.9"
        elif command[1] == "search":
            assert "-L" not in command
            assert command[command.index("-n") + 1] == "2"
            output = '{"resources": []}'
        else:
            output = "{}"
        return subprocess.CompletedProcess(command, 0, output)

    result = OpenVikingContextProvider(runner=runner).retrieve(
        namespace="ordinary_context",
        scope_ref="viking://resources/example",
        query="context",
        query_summary="context",
        max_results=2,
        timeout_seconds=30,
        observed_at="2026-01-01T00:00:00Z",
    )
    assert result.status == "completed" and not result.items
