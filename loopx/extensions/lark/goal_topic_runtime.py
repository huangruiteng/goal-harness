"""Runtime bridge from bound Lark Goal Topics into the existing Inbox path."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .event_inbox import (
    acknowledge_lark_event_inbox,
    ingest_lark_event_inbox,
    inspect_lark_event_inbox,
)
from .event_collector_runtime import enrich_lark_event_reply_context
from .goal_channel_contracts import binding_for_goal
from .goal_channel_targets import goal_channel_target_for_name
from .goal_topic_connections import route_lark_topic_event
from .inbox_reply import CommandRunner, reply_lark_event_inbox


Answer = Callable[[Mapping[str, Any], str], str]
SnapshotProvider = Callable[[], Mapping[str, Any]]
ProfilePoller = Callable[[str, threading.Event], None]
SimpleRunner = Callable[[list[str]], Mapping[str, Any]]
ProcessFactory = Callable[[list[str]], Any]


_EVENT_PROJECTION = (
    '{schema_version:"lark_event_inbox_event_v0",'
    "event_id:(.event_id // .message_id),message_id:.message_id,"
    "create_time:.create_time,content:.content,sender_id:.sender_id,"
    "chat_id:.chat_id,root_id:.root_id,parent_id:.parent_id,"
    "mentions:(.mentions // [])}"
)


def _opaque_digest(*values: Any) -> str:
    joined = "\0".join(str(value or "") for value in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


def _active_profile_configs(snapshot: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    target_payload = snapshot.get("target_payload")
    target_payload = target_payload if isinstance(target_payload, Mapping) else {}
    binding_payloads = snapshot.get("binding_payloads")
    binding_payloads = binding_payloads if isinstance(binding_payloads, Mapping) else {}
    profiles: dict[str, dict[str, str]] = {}
    for goal_id, payload in binding_payloads.items():
        if not isinstance(payload, Mapping):
            continue
        binding = binding_for_goal(payload, str(goal_id))
        if not binding or binding.get("enabled") is not True:
            continue
        target = goal_channel_target_for_name(
            target_payload,
            str(binding.get("target_ref") or ""),
        )
        if target is None or target.get("enabled") is not True:
            continue
        identity = target.get("identity")
        identity = identity if isinstance(identity, Mapping) else {}
        profile = str(identity.get("sender_profile") or "").strip()
        if not profile:
            continue
        profiles.setdefault(
            profile,
            {"cli_bin": str(identity.get("cli_bin") or "lark-cli")},
        )
    return profiles


def _default_simple_runner(args: list[str]) -> Mapping[str, Any]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return {"returncode": 1, "stdout": "", "stderr": ""}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _default_process_factory(args: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _target_for_profile_chat(
    target_payload: Mapping[str, Any], *, profile: str, chat_id: str
) -> Mapping[str, Any] | None:
    targets = target_payload.get("targets")
    targets = targets if isinstance(targets, Mapping) else {}
    for target in targets.values():
        if not isinstance(target, Mapping) or target.get("enabled") is not True:
            continue
        channel = target.get("channel")
        channel = channel if isinstance(channel, Mapping) else {}
        identity = target.get("identity")
        identity = identity if isinstance(identity, Mapping) else {}
        if (
            str(channel.get("chat_id") or "") == chat_id
            and str(identity.get("sender_profile") or "") == profile
        ):
            return target
    return None


def _event_payloads(stdout: Any) -> list[Mapping[str, Any]]:
    events: list[Mapping[str, Any]] = []
    for line in str(stdout or "").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            events.append(payload)
        elif isinstance(payload, list):
            events.extend(item for item in payload if isinstance(item, Mapping))
    return events


def poll_lark_goal_topic_profile_once(
    *,
    profile: str,
    snapshot: Mapping[str, Any],
    runtime_root: str | Path,
    answer: Answer,
    consume_runner: SimpleRunner = _default_simple_runner,
    provider_runner: Any = subprocess.run,
    reply_runner: CommandRunner = _default_simple_runner,
) -> dict[str, Any]:
    """Consume one bounded event batch for an App and reuse Inbox reply/ACK."""

    profile_configs = _active_profile_configs(snapshot)
    profile_config = profile_configs.get(profile)
    if profile_config is None:
        return {"ok": True, "status": "inactive", "event_count": 0, "replied_count": 0}
    cli_bin = str(profile_config["cli_bin"])
    result = consume_runner(
        [
            cli_bin,
            "--profile",
            profile,
            "event",
            "consume",
            "im.message.receive_v1",
            "--as",
            "bot",
            "--timeout",
            "5s",
            "--max-events",
            "50",
            "--jq",
            _EVENT_PROJECTION,
            "--quiet",
        ]
    )
    if int(result.get("returncode") or 0) != 0:
        return {"ok": False, "status": "consume_failed", "event_count": 0, "replied_count": 0}

    target_payload = snapshot.get("target_payload")
    target_payload = target_payload if isinstance(target_payload, Mapping) else {}
    binding_payloads = snapshot.get("binding_payloads")
    binding_payloads = binding_payloads if isinstance(binding_payloads, Mapping) else {}
    events = _event_payloads(result.get("stdout"))
    replied_count = 0
    event_statuses: list[str] = []
    for event in events:
        chat_id = str(event.get("chat_id") or "")
        target = _target_for_profile_chat(
            target_payload,
            profile=profile,
            chat_id=chat_id,
        )
        if target is None:
            event_statuses.append("target_unmatched")
            continue
        identity = target.get("identity")
        identity = identity if isinstance(identity, Mapping) else {}
        bot_app_id = str(identity.get("bot_app_id") or "")
        enriched = enrich_lark_event_reply_context(
            event,
            runner=provider_runner,
            command_prefix=[cli_bin],
            profile=profile,
            profile_app_id=bot_app_id,
            configured_chat_id=chat_id,
        )
        try:
            event_result = process_lark_goal_topic_event(
                target_payload=target_payload,
                binding_payloads={
                    str(goal_id): payload
                    for goal_id, payload in binding_payloads.items()
                    if isinstance(payload, Mapping)
                },
                event=enriched,
                runtime_root=runtime_root,
                answer=answer,
                reply_runner=reply_runner,
            )
        except Exception:
            event_statuses.append("processing_failed")
            continue
        event_statuses.append(str(event_result.get("status") or "unknown"))
        replied_count += int(event_result.get("status") == "replied_and_acknowledged")
    return {
        "ok": True,
        "status": "polled",
        "event_count": len(events),
        "replied_count": replied_count,
        "event_statuses": event_statuses,
    }


def stream_lark_goal_topic_profile(
    *,
    profile: str,
    snapshot_provider: SnapshotProvider,
    stop: threading.Event,
    runtime_root: str | Path,
    answer: Answer,
    process_factory: ProcessFactory = _default_process_factory,
    provider_runner: Any = subprocess.run,
    reply_runner: CommandRunner = _default_simple_runner,
) -> dict[str, Any]:
    """Keep one bounded long-lived CLI consumer attached between messages."""

    snapshot = snapshot_provider()
    profile_config = _active_profile_configs(snapshot).get(profile)
    if profile_config is None:
        return {
            "ok": True,
            "status": "inactive",
            "event_count": 0,
            "replied_count": 0,
        }
    cli_bin = str(profile_config["cli_bin"])
    process = process_factory(
        [
            cli_bin,
            "--profile",
            profile,
            "event",
            "consume",
            "im.message.receive_v1",
            "--as",
            "bot",
            "--timeout",
            "30m",
            "--max-events",
            "0",
            "--jq",
            _EVENT_PROJECTION,
            "--quiet",
        ]
    )
    watcher_done = threading.Event()

    def stop_consumer() -> None:
        while not watcher_done.wait(0.1):
            if stop.is_set():
                if process.poll() is None:
                    process.terminate()
                return

    watcher = threading.Thread(
        target=stop_consumer,
        name=f"loopx-lark-stop-{profile}",
        daemon=True,
    )
    watcher.start()
    event_count = 0
    replied_count = 0
    try:
        stdout = process.stdout
        if stdout is None:
            return {
                "ok": False,
                "status": "stream_failed",
                "event_count": 0,
                "replied_count": 0,
            }
        for line in stdout:
            if stop.is_set():
                break
            result = poll_lark_goal_topic_profile_once(
                profile=profile,
                snapshot=snapshot_provider(),
                runtime_root=runtime_root,
                answer=answer,
                consume_runner=lambda _args, payload=line: {
                    "returncode": 0,
                    "stdout": payload,
                    "stderr": "",
                },
                provider_runner=provider_runner,
                reply_runner=reply_runner,
            )
            event_count += int(result.get("event_count") or 0)
            replied_count += int(result.get("replied_count") or 0)
            if int(result.get("event_count") or 0):
                print(
                    json.dumps(
                        {
                            "schema_version": "loopx_lark_goal_topic_runtime_event_v0",
                            "event_count": int(result.get("event_count") or 0),
                            "replied_count": int(result.get("replied_count") or 0),
                            "event_statuses": list(result.get("event_statuses") or []),
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
    finally:
        watcher_done.set()
        if process.poll() is None:
            process.terminate()
        try:
            returncode = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            returncode = process.wait(timeout=3)
        watcher.join(timeout=1)
    return {
        "ok": returncode == 0 or stop.is_set(),
        "status": "stopped" if stop.is_set() else "stream_ended",
        "event_count": event_count,
        "replied_count": replied_count,
    }


class LarkGoalTopicRuntimeService:
    """Own one event-consumer worker per reusable Lark App profile."""

    def __init__(
        self,
        *,
        snapshot_provider: SnapshotProvider,
        runtime_root: str | Path,
        runtime_controller: Any,
        profile_poller: ProfilePoller | None = None,
    ) -> None:
        self.snapshot_provider = snapshot_provider
        self.runtime_root = Path(runtime_root).expanduser().resolve()
        self.runtime_controller = runtime_controller
        self._profile_poller = profile_poller or self._poll_profile
        self._lock = threading.Lock()
        self._workers: dict[str, tuple[threading.Event, threading.Thread]] = {}

    def _poll_profile(self, profile: str, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                def answer(route: Mapping[str, Any], text: str) -> str:
                    snapshot = self.snapshot_provider()
                    contexts = snapshot.get("goal_contexts")
                    contexts = contexts if isinstance(contexts, Mapping) else {}
                    context = contexts.get(str(route.get("goal_id") or ""))
                    context = context if isinstance(context, Mapping) else {}
                    return answer_lark_goal_topic(
                        route=route,
                        text=text,
                        work_dir=str(context.get("work_dir") or self.runtime_root),
                        objective=str(context.get("objective") or route.get("goal_id") or ""),
                        runtime_controller=self.runtime_controller,
                    )

                stream_lark_goal_topic_profile(
                    profile=profile,
                    snapshot_provider=self.snapshot_provider,
                    stop=stop,
                    runtime_root=self.runtime_root,
                    answer=answer,
                )
            except Exception:
                pass
            stop.wait(0.25)

    def refresh(self) -> None:
        desired = set(_active_profile_configs(self.snapshot_provider()))
        with self._lock:
            stale = set(self._workers) - desired
            missing = desired - set(self._workers)
            for profile in stale:
                stop, _thread = self._workers.pop(profile)
                stop.set()
            for profile in sorted(missing):
                stop = threading.Event()
                thread = threading.Thread(
                    target=self._profile_poller,
                    args=(profile, stop),
                    name=f"loopx-lark-{profile}",
                    daemon=True,
                )
                self._workers[profile] = (stop, thread)
                thread.start()

    def active_profiles(self) -> list[str]:
        with self._lock:
            return sorted(self._workers)

    def close(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for stop, _thread in workers:
            stop.set()
        for _stop, thread in workers:
            thread.join(timeout=3)


def answer_lark_goal_topic(
    *,
    route: Mapping[str, Any],
    text: str,
    work_dir: str | Path,
    objective: str,
    runtime_controller: Any,
) -> str:
    """Run one addressed Topic message through the durable Goal Chat session."""

    goal_id = str(route.get("goal_id") or "")
    channel_id = "lark." + _opaque_digest(
        route.get("app_ref"),
        route.get("target_ref"),
        route.get("topic_root_message_id"),
    )
    session, _resumed = runtime_controller.open_session(
        goal_id=goal_id,
        agent_id="codex",
        work_dir=Path(work_dir).expanduser().resolve(),
        objective=str(objective or goal_id),
        mode="resume_latest",
        channel_id=channel_id,
        agent_goal_id=goal_id,
    )
    message = (
        "这是来自已绑定 Lark Goal Topic 的用户消息。请直接回答当前问题；"
        "任何 Goal、Todo 或其他持久状态修改只生成预览，等待用户在 LoopX 明确确认后应用。\n\n"
        f"用户消息：{str(text or '').strip()}"
    )
    turn, _created = runtime_controller.submit_turn(
        session_id=str(session["session_id"]),
        client_turn_id="lark."
        + _opaque_digest(route.get("message_id"), route.get("topic_root_message_id")),
        message=message,
        work_dir=Path(work_dir).expanduser().resolve(),
        objective=str(objective or goal_id),
    )
    completed = runtime_controller.wait_for_turn(
        session_id=str(session["session_id"]),
        turn_id=str(turn["turn_id"]),
    )
    if completed.get("status") != "completed":
        raise RuntimeError(str(completed.get("error") or "Lark Goal Topic turn failed"))
    response = completed.get("response")
    reply_text = str(response.get("message") or "") if isinstance(response, Mapping) else ""
    if not reply_text.strip():
        raise RuntimeError("Lark Goal Topic turn returned no message")
    return reply_text


def _inbox_config(
    *,
    runtime_root: Path,
    route: Mapping[str, Any],
    target_payload: Mapping[str, Any],
) -> tuple[Path, str]:
    target_ref = str(route.get("target_ref") or "")
    target = goal_channel_target_for_name(target_payload, target_ref)
    if target is None:
        raise ValueError("the routed Lark target is unavailable")
    channel = target.get("channel") if isinstance(target.get("channel"), Mapping) else {}
    identity = target.get("identity") if isinstance(target.get("identity"), Mapping) else {}
    chat_id = str(channel.get("chat_id") or "")
    profile = str(route.get("app_ref") or "")
    bot_display_name = str(identity.get("bot_display_name") or profile)
    digest = hashlib.sha256(
        f"{profile}\0{chat_id}\0{route.get('topic_root_message_id')}".encode("utf-8")
    ).hexdigest()[:20]
    config_ref = f".loopx/config/lark-goal-topics/{digest}.json"
    config_path = runtime_root / config_ref
    payload = {
        "schema_version": "lark_event_inbox_config_v0",
        "enabled": True,
        "inbox_dir": f".loopx/inbox/lark-goal-topics/{digest}",
        "capture_scope": "configured_chat_all",
        "reply": {
            "enabled": True,
            "sender_profile": profile,
            "sender_identity": "bot",
            "bot_display_name": bot_display_name,
            "chat_id": chat_id,
        },
    }
    config_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = config_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(config_path)
    return config_path, config_ref


def process_lark_goal_topic_event(
    *,
    target_payload: Mapping[str, Any],
    binding_payloads: Mapping[str, Mapping[str, Any]],
    event: Mapping[str, Any],
    runtime_root: str | Path,
    answer: Answer,
    reply_runner: CommandRunner,
) -> dict[str, Any]:
    """Route, persist, answer, reply, and ACK one bound Topic event."""

    route = route_lark_topic_event(
        target_payload=target_payload,
        binding_payloads=binding_payloads,
        event=event,
    )
    if route is None:
        return {"ok": True, "status": "ignored"}
    root = Path(runtime_root).expanduser().resolve()
    config_path, config_ref = _inbox_config(
        runtime_root=root,
        route=route,
        target_payload=target_payload,
    )
    canonical = {
        "schema_version": "lark_event_inbox_event_v0",
        "event_id": str(event.get("event_id") or event.get("message_id") or ""),
        "message_id": str(event.get("message_id") or ""),
        "create_time": str(event.get("create_time") or ""),
        "content": str(event.get("content") or ""),
        "root_id": str(event.get("root_id") or ""),
        "parent_id": str(event.get("parent_id") or ""),
        "reply_context_verified": event.get("reply_context_verified") is True,
        "reply_to_bot": event.get("reply_to_bot") is True,
    }
    ingest_lark_event_inbox(
        project=root,
        config_path=config_path,
        events=[canonical],
        execute=True,
    )
    message_id = str(route["message_id"])
    projection = inspect_lark_event_inbox(project=root, config_path=config_path)
    pending_ids = {
        str(item.get("message_id") or "")
        for item in projection.get("items", [])
        if isinstance(item, Mapping)
    }
    if message_id not in pending_ids:
        return {
            "ok": True,
            "status": "already_acknowledged",
            "goal_id": route["goal_id"],
            "inbox_config_ref": config_ref,
        }
    reply_text = " ".join(str(answer(route, canonical["content"]) or "").split())[:1200]
    if not reply_text:
        return {
            "ok": False,
            "status": "answer_empty",
            "goal_id": route["goal_id"],
            "inbox_config_ref": config_ref,
        }
    reply = reply_lark_event_inbox(
        project=root,
        config_path=config_path,
        message_id=message_id,
        text=reply_text,
        execute=True,
        runner=reply_runner,
    )
    if not reply.get("ok"):
        return {
            "ok": False,
            "status": str(reply.get("status") or "reply_failed"),
            "goal_id": route["goal_id"],
            "blocker": reply.get("blocker"),
            "inbox_config_ref": config_ref,
        }
    acknowledge_lark_event_inbox(
        project=root,
        config_path=config_path,
        message_ids=[message_id],
        execute=True,
    )

    return {
        "ok": True,
        "status": "replied_and_acknowledged",
        "goal_id": route["goal_id"],
        "inbox_config_ref": config_ref,
    }
