from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from loopx.attached_session import (
    bind_attached_agent_session,
    claim_attached_agent_turn,
    complete_attached_agent_turn,
)
from loopx.chat_runtime import ChatRuntimeController
from loopx.chat_server import ChatRequestHandler
from loopx.chat_store import CHAT_SESSION_MODE_ATTACHED, ChatSessionStore
from loopx.extensions.lark.goal_topic_runtime import answer_lark_goal_topic

GOAL_ID = "sample-goal"
AGENT_ID = "codex-sample-worker"
HOST_SURFACE = "codex-app-ssh"
HOST_SESSION_ID = "opaque-host-session"


def _registry() -> dict[str, object]:
    return {
        "goals": [
            {
                "id": GOAL_ID,
                "coordination": {
                    "registered_agents": [AGENT_ID],
                    "thread_agent_bindings": [
                        {
                            "host_surface": HOST_SURFACE,
                            "thread_id": HOST_SESSION_ID,
                            "agent_id": AGENT_ID,
                        }
                    ],
                },
            }
        ]
    }


def _bind(store: ChatSessionStore) -> dict[str, object]:
    packet = bind_attached_agent_session(
        store=store,
        registry=_registry(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        executor_endpoint_id="codex",
        execute=True,
    )
    assert packet["created"] is True
    return packet


def test_bind_requires_exact_registered_thread_and_is_idempotent(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    preview = bind_attached_agent_session(
        store=store,
        registry=_registry(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        executor_endpoint_id="codex",
        execute=False,
    )
    assert preview["changed"] is True
    assert not list(store.sessions_root.glob("*/session.json"))

    created = _bind(store)
    session = created["session"]
    assert session["agent_id"] == AGENT_ID
    assert session["executor_endpoint_id"] == "codex"
    assert session["session_mode"] == CHAT_SESSION_MODE_ATTACHED
    assert session["attached_capabilities"] == {
        "live_steering": False,
        "session_queue": True,
        "reply_readback": True,
    }

    duplicate = bind_attached_agent_session(
        store=store,
        registry=_registry(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        executor_endpoint_id="codex",
        execute=True,
    )
    assert duplicate["created"] is False
    assert duplicate["session"]["session_id"] == session["session_id"]

    with pytest.raises(ValueError, match="exact registered Agent"):
        bind_attached_agent_session(
            store=store,
            registry=_registry(),
            goal_id=GOAL_ID,
            agent_id=AGENT_ID,
            host_surface=HOST_SURFACE,
            host_session_id="different-host-session",
            executor_endpoint_id="codex",
            execute=True,
        )


def test_concurrent_bind_and_completion_are_duplicate_safe(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        packets = list(executor.map(lambda _index: _bind_or_reuse(store), range(2)))
    assert sorted(packet["created"] for packet in packets) == [False, True]
    session_id = str(packets[0]["session"]["session_id"])

    queued, created = store.create_queued_turn(
        session_id,
        client_turn_id="concurrent-completion",
        message="complete once",
        origin="web",
    )
    assert created
    claim_attached_agent_turn(
        store=store,
        session_id=session_id,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="shared-claim",
    )

    def complete(_index: int) -> dict[str, object]:
        return complete_attached_agent_turn(
            store=store,
            session_id=session_id,
            turn_id=str(queued["turn_id"]),
            host_surface=HOST_SURFACE,
            host_session_id=HOST_SESSION_ID,
            claim_id="shared-claim",
            completion_id="shared-completion",
            response={"message": "one durable response"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        completions = list(executor.map(complete, range(2)))
    assert sorted(packet["created"] for packet in completions) == [False, True]
    agent_messages = [item for item in store.messages(session_id) if item["role"] == "agent"]
    assert len(agent_messages) == 1


def test_loopback_attach_api_binds_without_exposing_host_session(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    responses: list[dict[str, object]] = []

    class Handler:
        server = SimpleNamespace(chat_store=store)

        def _read_json(self) -> dict[str, str]:
            return {
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "host_surface": HOST_SURFACE,
                "host_session_id": HOST_SESSION_ID,
                "executor_endpoint_id": "codex",
            }

        def _registry_and_goal(
            self,
            goal_id: str,
        ) -> tuple[dict[str, object], dict[str, object]]:
            assert goal_id == GOAL_ID
            return _registry(), {"id": GOAL_ID}

        def _send_json(self, payload: dict[str, object], *, status: int = 200) -> None:
            responses.append({**payload, "http_status": status})

        def _send_error(self, message: str, **_kwargs: object) -> None:
            responses.append({"ok": False, "error": message})

    ChatRequestHandler._attach_session(Handler())  # type: ignore[arg-type]

    assert responses[0]["http_status"] == 201
    session = responses[0]["session"]
    assert isinstance(session, dict)
    assert session["session_mode"] == CHAT_SESSION_MODE_ATTACHED
    assert "upstream_thread_id" not in session


def _bind_or_reuse(store: ChatSessionStore) -> dict[str, object]:
    return bind_attached_agent_session(
        store=store,
        registry=_registry(),
        goal_id=GOAL_ID,
        agent_id=AGENT_ID,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        executor_endpoint_id="codex",
        execute=True,
    )


def test_web_and_lark_share_ordered_attached_session_without_spawning(
    tmp_path: Path,
) -> None:
    store = ChatSessionStore(tmp_path)
    session = _bind(store)["session"]
    session_id = str(session["session_id"])
    runtime = ChatRuntimeController(store=store, codex_bin="missing-codex")

    web_turn, web_created = runtime.submit_turn(
        session_id=session_id,
        client_turn_id="web-1",
        message="web question",
        work_dir=tmp_path,
        objective="sample objective",
    )
    lark_turn, lark_created = runtime.enqueue_turn(
        session_id=session_id,
        client_turn_id="lark-1",
        message="lark question",
        work_dir=tmp_path,
        objective="sample objective",
        origin="lark",
    )
    assert web_created and lark_created
    assert not runtime.adapters

    first = claim_attached_agent_turn(
        store=store,
        session_id=session_id,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-web-1",
    )
    assert first["turn"]["turn_id"] == web_turn["turn_id"]
    assert first["turn"]["origin"] == "web"
    duplicate_claim = claim_attached_agent_turn(
        store=store,
        session_id=session_id,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-web-1",
    )
    assert duplicate_claim["turn"]["turn_id"] == web_turn["turn_id"]

    completed = complete_attached_agent_turn(
        store=store,
        session_id=session_id,
        turn_id=str(web_turn["turn_id"]),
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-web-1",
        completion_id="complete-web-1",
        response={"message": "web answer"},
    )
    assert completed["created"] is True
    duplicate_completion = complete_attached_agent_turn(
        store=store,
        session_id=session_id,
        turn_id=str(web_turn["turn_id"]),
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-web-1",
        completion_id="complete-web-1",
        response={"message": "different retry payload"},
    )
    assert duplicate_completion["created"] is False
    assert [
        item["text"] for item in store.messages(session_id) if item["role"] == "agent"
    ] == ["web answer"]

    second = claim_attached_agent_turn(
        store=store,
        session_id=session_id,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-lark-1",
    )
    assert second["turn"]["turn_id"] == lark_turn["turn_id"]
    assert second["turn"]["origin"] == "lark"
    messages = store.messages(session_id)
    assert [item.get("origin") for item in messages[:3]] == [
        "web",
        "lark",
        "attached_host",
    ]


def test_attached_live_steering_fails_closed_with_durable_receipt(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    session_id = str(_bind(store)["session"]["session_id"])
    runtime = ChatRuntimeController(store=store, codex_bin="missing-codex")

    with pytest.raises(RuntimeError, match="attached_session_live_steering_unavailable"):
        runtime.steer_active_turn(
            session_id=session_id,
            client_ingress_id="lark-steer-1",
            message="steer now",
        )
    receipt = store.create_ingress_receipt(
        session_id,
        client_ingress_id="lark-steer-1",
        mode="live_steering",
        message="steer now",
    )[0]
    assert receipt["status"] == "failed"
    assert receipt["error_code"] == "attached_session_live_steering_unavailable"


def test_lark_session_queue_waits_for_attached_host_reply_readback(tmp_path: Path) -> None:
    store = ChatSessionStore(tmp_path)
    session_id = str(_bind(store)["session"]["session_id"])
    runtime = ChatRuntimeController(store=store, codex_bin="missing-codex")
    result: dict[str, str] = {}

    def answer() -> None:
        result["reply"] = answer_lark_goal_topic(
            route={
                "goal_id": GOAL_ID,
                "agent_id": AGENT_ID,
                "session_id": session_id,
                "ingress_mode": "session_queue",
                "message_id": "om_synthetic_message",
                "topic_root_message_id": "om_synthetic_root",
            },
            text="question from lark",
            work_dir=tmp_path,
            objective="sample objective",
            runtime_controller=runtime,
        )

    waiter = threading.Thread(target=answer)
    waiter.start()
    deadline = time.monotonic() + 2
    while not store.queued_turns(session_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    claimed = claim_attached_agent_turn(
        store=store,
        session_id=session_id,
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-lark-reply",
    )
    assert claimed["turn"]["origin"] == "lark"
    complete_attached_agent_turn(
        store=store,
        session_id=session_id,
        turn_id=claimed["turn"]["turn_id"],
        host_surface=HOST_SURFACE,
        host_session_id=HOST_SESSION_ID,
        claim_id="claim-lark-reply",
        completion_id="complete-lark-reply",
        response={"message": "reply from attached host"},
    )
    waiter.join(timeout=2)
    assert not waiter.is_alive()
    assert result["reply"] == "reply from attached host"
