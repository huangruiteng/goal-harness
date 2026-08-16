#!/usr/bin/env python3
"""Opt-in live E2E for Codex app-server restart and thread resume."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.chat_runtime import ChatRuntimeController  # noqa: E402
from loopx.chat_store import ChatSessionStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real Codex app-server restart/resume Chat conversation.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required because this test sends two real model turns.",
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--turn-timeout-seconds", type=float, default=300.0)
    return parser.parse_args()


def wait_completed(
    controller: ChatRuntimeController,
    *,
    session_id: str,
    turn_id: str,
    timeout_sec: float,
) -> dict[str, object]:
    turn = controller.wait_for_turn(
        session_id=session_id,
        turn_id=turn_id,
        timeout_sec=timeout_sec,
    )
    if turn.get("status") != "completed":
        raise RuntimeError(f"Codex live turn ended with status={turn.get('status')}")
    return turn


def wait_running(
    controller: ChatRuntimeController,
    *,
    session_id: str,
    turn_id: str,
    timeout_sec: float = 30.0,
) -> dict[str, object]:
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        turn = controller.store.load_turn(session_id, turn_id)
        if (
            isinstance(turn, dict)
            and turn.get("status") == "running"
            and turn.get("upstream_turn_id")
        ):
            return turn
        time.sleep(0.02)
    raise TimeoutError("Codex live turn did not start in time")


def main() -> None:
    args = parse_args()
    if not args.execute:
        raise SystemExit("Pass --execute to run the two-turn live Codex resume test.")
    codex_bin = shutil.which(args.codex_bin)
    if not codex_bin:
        raise SystemExit("Codex executable was not found.")
    marker = f"LOOPX-{uuid.uuid4().hex[:12]}"
    with tempfile.TemporaryDirectory(prefix="loopx-chat-codex-resume-") as raw_tmp:
        root = Path(raw_tmp)
        work_dir = root / "workspace"
        work_dir.mkdir()
        store = ChatSessionStore(root / "runtime")
        first = ChatRuntimeController(
            store=store,
            codex_bin=codex_bin,
            idle_timeout_sec=max(30.0, args.turn_timeout_seconds),
            hard_timeout_sec=max(60.0, args.turn_timeout_seconds),
        )
        session, resumed = first.open_session(
            goal_id="codex-resume-e2e",
            agent_id="codex",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
            mode="new",
        )
        if resumed:
            raise RuntimeError("Fresh live session unexpectedly resumed")
        session_id = str(session["session_id"])
        upstream_thread_id = str(session["upstream_thread_id"])
        first_turn, created = first.submit_turn(
            session_id=session_id,
            client_turn_id="remember-marker",
            message=f"请记住会话标记 {marker}，并确认已经记住。",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
        )
        if not created:
            raise RuntimeError("Fresh live turn was deduplicated")
        wait_completed(
            first,
            session_id=session_id,
            turn_id=str(first_turn["turn_id"]),
            timeout_sec=args.turn_timeout_seconds,
        )
        first.close()

        second = ChatRuntimeController(
            store=store,
            codex_bin=codex_bin,
            idle_timeout_sec=max(30.0, args.turn_timeout_seconds),
            hard_timeout_sec=max(60.0, args.turn_timeout_seconds),
        )
        restored, resumed = second.open_session(
            goal_id="codex-resume-e2e",
            agent_id="codex",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
            mode="resume_latest",
        )
        if not resumed or str(restored["session_id"]) != session_id:
            raise RuntimeError("LoopX did not restore the original local Chat session")
        if str(restored["upstream_thread_id"]) != upstream_thread_id:
            raise RuntimeError("LoopX changed the upstream Codex thread during resume")
        second_turn, created = second.submit_turn(
            session_id=session_id,
            client_turn_id="recall-marker",
            message="请仅复述上一轮要求你记住的会话标记。",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
        )
        if not created:
            raise RuntimeError("Recall turn was deduplicated")
        completed = wait_completed(
            second,
            session_id=session_id,
            turn_id=str(second_turn["turn_id"]),
            timeout_sec=args.turn_timeout_seconds,
        )
        response = completed.get("response")
        answer = str(response.get("message") or "") if isinstance(response, dict) else ""
        if marker not in answer:
            raise RuntimeError("Resumed Codex thread did not recall the prior-turn marker")

        interrupt_turn, created = second.submit_turn(
            session_id=session_id,
            client_turn_id="interrupt-live-turn",
            message="请深入检查当前空工作区，并在得出结论前持续分析一段时间。",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
        )
        if not created:
            raise RuntimeError("Interrupt live turn was deduplicated")
        interrupt_turn_id = str(interrupt_turn["turn_id"])
        wait_running(
            second,
            session_id=session_id,
            turn_id=interrupt_turn_id,
        )
        interrupted = second.interrupt_turn(
            session_id=session_id,
            turn_id=interrupt_turn_id,
        )
        if interrupted.get("status") != "interrupted":
            raise RuntimeError("Codex live turn did not reach interrupted state")
        final_turn, created = second.submit_turn(
            session_id=session_id,
            client_turn_id="continue-after-interrupt",
            message="请仅回复：中断后同一会话可以继续。",
            work_dir=work_dir,
            objective="Validate durable Chat context across an app-server restart.",
        )
        if not created:
            raise RuntimeError("Post-interrupt live turn was deduplicated")
        final_completed = wait_completed(
            second,
            session_id=session_id,
            turn_id=str(final_turn["turn_id"]),
            timeout_sec=args.turn_timeout_seconds,
        )
        final_response = final_completed.get("response")
        final_answer = str(final_response.get("message") or "") if isinstance(final_response, dict) else ""
        if "中断后同一会话可以继续" not in final_answer:
            raise RuntimeError("Codex did not continue after interrupt in the original Session")
        second.close()
    print(
        json.dumps(
            {
                "ok": True,
                "schema_version": "loopx_chat_codex_resume_e2e_v1",
                "same_local_session": True,
                "same_upstream_thread": True,
                "context_recalled": True,
                "interrupt_verified": True,
                "continued_after_interrupt": True,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
