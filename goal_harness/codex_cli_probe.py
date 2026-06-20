from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping


DEFAULT_CODEX_BIN = "codex"
DEFAULT_TIMEOUT_SECONDS = 2.0


HELP_COMMANDS = {
    "root": ("--help",),
    "exec": ("exec", "--help"),
    "resume": ("resume", "--help"),
}


def _normalize(text: str | None) -> str:
    return " ".join((text or "").lower().replace("_", "-").split())


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _visible_session_injection_detected(text: str) -> bool:
    has_session = _has_any(
        text,
        (
            "session",
            "conversation",
            "thread",
            "--session",
            "--conversation",
            "session-id",
            "session id",
        ),
    )
    has_attach = _has_any(
        text,
        (
            "attach to existing tui",
            "attach to active tui",
            "attach to an idle tui",
            "attach to existing session",
            "attach to active session",
            "inject into session",
            "inject into active session",
            "inject prompt into session",
            "send prompt to session",
            "send message to session",
            "send-message",
            "send message",
        ),
    )
    has_visible_turn = _has_any(text, ("prompt", "message", "stdin", "turn", "tui", "visible"))
    return has_session and has_attach and has_visible_turn


def _remote_control_surface_detected(text: str) -> bool:
    return _has_any(text, ("remote-control", "remote control")) and _has_any(
        text,
        ("--remote", "app server", "app-server"),
    )


def _visible_resume_supported(resume_help: str) -> bool:
    return "usage: codex resume" in resume_help and "[prompt]" in resume_help


def classify_codex_cli_session_surface(
    *,
    command_outputs: Mapping[str, str],
    command_errors: Mapping[str, str] | None = None,
    codex_cli_available: bool = True,
) -> dict[str, Any]:
    """Classify public Codex CLI help text without reading local sessions."""

    command_errors = command_errors or {}
    normalized_outputs = {name: _normalize(text) for name, text in command_outputs.items()}
    all_help = " ".join(normalized_outputs.values())
    root_help = normalized_outputs.get("root", "")
    exec_help = normalized_outputs.get("exec", "")
    resume_help = normalized_outputs.get("resume", "")

    exec_supported = " exec" in f" {root_help} " or bool(exec_help.strip())
    resume_supported = " resume" in f" {root_help} " or bool(resume_help.strip())
    session_handle_detected = resume_supported or _has_any(
        all_help,
        (
            "--session",
            "--conversation",
            "session-id",
            "session id",
            "conversation id",
            "resume",
        ),
    )
    same_tui_injection_detected = _visible_session_injection_detected(all_help)
    remote_control_surface_detected = _remote_control_surface_detected(all_help)
    visible_resume_supported = _visible_resume_supported(resume_help)
    safe_injection_supported = same_tui_injection_detected

    if safe_injection_supported:
        recommended_mode = "session_attached_visible_turn"
        automation_action = "try_visible_session_attach_with_idle_guard"
    elif remote_control_surface_detected or visible_resume_supported:
        recommended_mode = "visible_resume_or_remote_control_spike"
        automation_action = "prototype_visible_resume_or_remote_control_with_idle_guard"
    elif exec_supported:
        recommended_mode = "tui_bootstrap_then_explicit_headless_fallback"
        automation_action = "keep_tui_bootstrap_primary_and_require_explicit_fallback"
    else:
        recommended_mode = "tui_bootstrap_only"
        automation_action = "ask_user_to_start_inside_codex_cli_tui"

    warnings: list[str] = []
    if session_handle_detected and not same_tui_injection_detected:
        warnings.append(
            "Resume/session help is not enough to claim same-open-TUI injection; require an explicit visible attach/inject primitive."
        )
    if (remote_control_surface_detected or visible_resume_supported) and not same_tui_injection_detected:
        warnings.append(
            "A visible resume or remote-control surface exists; prototype it behind an idle guard before calling it session-attached automation."
        )
    if not codex_cli_available:
        warnings.append("Codex CLI was not available on PATH; classification used missing-command evidence.")
    if command_errors:
        warnings.append("Some probe commands returned errors; inspect command_errors before enabling automation.")

    return {
        "ok": True,
        "schema_version": "codex_cli_session_probe_v0",
        "codex_cli_available": codex_cli_available,
        "capabilities": {
            "exec_supported": exec_supported,
            "resume_supported": resume_supported,
            "session_handle_detected": session_handle_detected,
            "visible_resume_supported": visible_resume_supported,
            "remote_control_surface_detected": remote_control_surface_detected,
            "same_tui_injection_detected": same_tui_injection_detected,
            "safe_injection_supported": safe_injection_supported,
        },
        "recommended_mode": recommended_mode,
        "automation_action": automation_action,
        "boundary": {
            "help_only_probe": True,
            "reads_raw_transcripts": False,
            "reads_credentials": False,
            "reads_session_files": False,
            "mutates_codex_session": False,
            "spends_goal_harness_quota": False,
        },
        "command_errors": dict(command_errors),
        "warnings": warnings,
    }


def load_codex_cli_probe_fixture(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text())
    if "command_outputs" in data:
        outputs = data["command_outputs"]
    else:
        outputs = data
    if not isinstance(outputs, dict):
        raise ValueError("Codex CLI probe fixture must be a JSON object")
    return {str(key): str(value) for key, value in outputs.items()}


def run_codex_cli_session_probe(
    *,
    codex_bin: str = DEFAULT_CODEX_BIN,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    fixture: Path | None = None,
) -> dict[str, Any]:
    if fixture:
        outputs = load_codex_cli_probe_fixture(fixture)
        payload = classify_codex_cli_session_surface(
            command_outputs=outputs,
            codex_cli_available=True,
        )
        payload["source"] = "fixture"
        return payload

    outputs: dict[str, str] = {}
    errors: dict[str, str] = {}
    available = True
    for name, extra_args in HELP_COMMANDS.items():
        try:
            result = subprocess.run(
                [codex_bin, *extra_args],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            available = False
            errors[name] = "codex_cli_not_found"
            break
        except subprocess.TimeoutExpired:
            errors[name] = "timeout"
            continue
        text = "\n".join(part for part in (result.stdout, result.stderr) if part)
        if result.returncode != 0:
            errors[name] = f"exit_{result.returncode}"
        outputs[name] = text

    payload = classify_codex_cli_session_surface(
        command_outputs=outputs,
        command_errors=errors,
        codex_cli_available=available,
    )
    payload["source"] = "real_help"
    payload["codex_bin"] = codex_bin
    payload["timeout_seconds"] = timeout_seconds
    return payload


def render_codex_cli_session_probe_markdown(payload: dict[str, Any]) -> str:
    capabilities = payload.get("capabilities") or {}
    boundary = payload.get("boundary") or {}
    warnings = payload.get("warnings") or []
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- none"
    return f"""# Codex CLI Session Probe

- source: `{payload.get("source")}`
- recommended_mode: `{payload.get("recommended_mode")}`
- automation_action: `{payload.get("automation_action")}`

## Capabilities

- exec_supported: `{capabilities.get("exec_supported")}`
- resume_supported: `{capabilities.get("resume_supported")}`
- session_handle_detected: `{capabilities.get("session_handle_detected")}`
- visible_resume_supported: `{capabilities.get("visible_resume_supported")}`
- remote_control_surface_detected: `{capabilities.get("remote_control_surface_detected")}`
- same_tui_injection_detected: `{capabilities.get("same_tui_injection_detected")}`
- safe_injection_supported: `{capabilities.get("safe_injection_supported")}`

## Boundary

- help_only_probe: `{boundary.get("help_only_probe")}`
- reads_raw_transcripts: `{boundary.get("reads_raw_transcripts")}`
- reads_credentials: `{boundary.get("reads_credentials")}`
- reads_session_files: `{boundary.get("reads_session_files")}`
- mutates_codex_session: `{boundary.get("mutates_codex_session")}`
- spends_goal_harness_quota: `{boundary.get("spends_goal_harness_quota")}`

## Warnings

{warning_lines}
"""
