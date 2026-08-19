"""Thin DeepSeek Harness host adapter for the LoopX governed Turn contract.

This module is the canonical home of the dsh goal-mode adapter; the historical
``scripts/dsh_turn_host_adapter.py`` launcher still works and re-exports this
module for backward compatibility.

LoopX runs this adapter with one ``loopx_turn_host_request_v0`` JSON object on
stdin. The adapter:

1. extracts the bounded action text from the signed Turn envelope,
2. starts a DeepSeek Harness SDK runtime (or a compatible runner for tests),
3. asks dsh to execute one bounded work segment and return a schema-constrained
   result in its final assistant message,
4. emits exactly one ``loopx_turn_result_v0`` JSON object on stdout.

It does not read goal/todo state, build prompts from todo ids, write LoopX
state, spend quota, or validate its own work. Task body delivery and authority
stay in ``loopx turn run-once``; this is a dumb translation layer.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..control_plane.quota.turn_envelope import (
    turn_envelope_action_signature_document,
)

LOOPX_TURN_HOST_REQUEST_SCHEMA = "loopx_turn_host_request_v0"
LOOPX_TURN_RESULT_SCHEMA = "loopx_turn_result_v0"
COMPLETED_PHASES = ["host_execute", "typed_result"]

ACCEPTED_RESULT_KINDS = {
    "validated_progress",
    "repair_required",
    "replan_required",
    "user_action_required",
    "wait",
}
MATERIAL_KINDS = {"validated_progress", "repair_required", "replan_required"}

TEXT_LIMITS = {
    "classification": 120,
    "recommended_action": 1_200,
    "next_action": 1_200,
    "vision_unchanged_reason": 240,
    "summary": 400,
}

DEFAULT_MODEL = os.environ.get("DSH_MODEL", "deepseek-v4-flash")
DEFAULT_PROVIDER = os.environ.get("DSH_PROVIDER", "deepseek-official")
DEFAULT_SESSION_ROOT_NAME = ".dsh-sessions"


def _bounded(value: Any, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 3].rstrip() + "..."
    return text


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def extract_turn_authority(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the signed action and safety boundary exactly as projected."""

    envelope = _mapping(request.get("turn_envelope"))
    signature = _mapping(envelope.get("action_signature"))
    source_hash = str(signature.get("source_hash") or "")
    envelope_hash = str(signature.get("envelope_hash") or "")
    computed_envelope_hash = _canonical_hash(
        turn_envelope_action_signature_document(envelope)
    )
    if (
        signature.get("matches") is not True
        or not source_hash
        or source_hash != envelope_hash
        or envelope_hash != computed_envelope_hash
    ):
        raise ValueError("TurnEnvelope action signature is missing or does not match")

    action = _mapping(envelope.get("action"))
    primary_action = _bounded(
        action.get("primary_action"),
        limit=TEXT_LIMITS["recommended_action"],
    )
    if not primary_action:
        raise ValueError("signed TurnEnvelope has no primary_action")

    boundary = _mapping(envelope.get("boundary"))
    required_reads = envelope.get("required_reads")
    write_scope = boundary.get("write_scope")
    return {
        "primary_action": primary_action,
        "required_reads": list(required_reads) if isinstance(required_reads, list) else [],
        "write_scope": list(write_scope) if isinstance(write_scope, list) else [],
        "workspace_guard": _mapping(boundary.get("workspace_guard")),
    }


def extract_action_text(request: Mapping[str, Any]) -> str:
    """Return the bounded, control-plane-authored task body for the host."""

    return str(extract_turn_authority(request)["primary_action"])


def render_prompt(authority: Mapping[str, Any]) -> str:
    """Wrap one signed Turn authority packet in a typed JSON result request.

    dsh owns execution. The final assistant message is the only channel this
    adapter reads back as a typed candidate; it stays public-safe and bounded.
    """

    authority_json = json.dumps(
        dict(authority),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "You are executing one bounded LoopX-governed work segment.\n"
        "The JSON below is the complete host authority for this Turn. Execute "
        "primary_action only after required_reads, write only inside write_scope, "
        "and obey workspace_guard. Do not infer authority from other prose.\n\n"
        f"Turn authority JSON:\n{authority_json}\n\n"
        "When finished, return only one JSON object (no Markdown fence) with "
        "these public-safe fields:\n"
        "- result_kind: one of validated_progress | repair_required | "
        "replan_required | user_action_required | wait\n"
        "- classification: short label (<=120 chars)\n"
        "- summary: what changed or why stopped (<=400 chars)\n"
        "- recommended_action: the bounded follow-up recommendation (<=1200 chars)\n"
        "- next_action: the concrete next step (<=1200 chars)\n"
        "- vision_unchanged_reason: why the goal path is unchanged (<=240 chars)\n"
        "Use repair_required when the task is sound but a recoverable defect "
        "blocks it, replan_required when this route is exhausted, and "
        "wait/user_action_required when no material write is safe. "
        "Do not include raw transcripts, credentials, or absolute local paths."
    )


def parse_model_json(text: str) -> dict[str, Any] | None:
    """Parse the dsh final assistant message as one JSON object.

    Prefer exact JSON; fall back to the outermost object so a model that wraps
    the result in prose or a code fence still produces a typed candidate.
    """

    value = text.strip()
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Strip a Markdown code fence if present.
    lines = value.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    value = "\n".join(lines).strip()

    start = value.find("{")
    end = value.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(value[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def build_result(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
    *,
    fallback_reason: str = "",
) -> dict[str, Any]:
    """Shape a dsh model result block into a valid loopx_turn_result_v0."""

    turn_key = str(request.get("turn_key") or "")
    if candidate is None:
        # Fail closed: no typed material claim means a stop, never fabricated
        # progress. This spends no quota.
        return {
            "schema_version": LOOPX_TURN_RESULT_SCHEMA,
            "turn_key": turn_key,
            "result_kind": "wait",
            "completed_phases": list(COMPLETED_PHASES),
            "classification": "no_typed_host_result",
            "next_action": _bounded(
                fallback_reason
                or "DeepSeek Harness returned no typed JSON result; rerun or inspect the dsh session.",
                limit=TEXT_LIMITS["next_action"],
            ),
            "vision_unchanged_reason": _bounded(
                "host adapter could not confirm a material change",
                limit=TEXT_LIMITS["vision_unchanged_reason"],
            ),
        }

    kind = str(candidate.get("result_kind") or "").strip()
    if kind not in ACCEPTED_RESULT_KINDS:
        return {
            "schema_version": LOOPX_TURN_RESULT_SCHEMA,
            "turn_key": turn_key,
            "result_kind": "wait",
            "completed_phases": list(COMPLETED_PHASES),
            "classification": "unsupported_host_result_kind",
            "next_action": _bounded(
                fallback_reason
                or "DeepSeek Harness returned unsupported result_kind "
                + repr(kind) + ".",
                limit=TEXT_LIMITS["next_action"],
            ),
            "vision_unchanged_reason": _bounded(
                "host adapter could not accept the returned result kind",
                limit=TEXT_LIMITS["vision_unchanged_reason"],
            ),
        }
    result: dict[str, Any] = {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA,
        "turn_key": turn_key,
        "result_kind": kind,
        "completed_phases": list(COMPLETED_PHASES),
    }
    for field, limit in TEXT_LIMITS.items():
        if field == "vision_unchanged_reason":
            continue
        value = candidate.get(field)
        text = _bounded(value, limit=limit) if value else ""
        if text:
            result[field] = text

    if kind in MATERIAL_KINDS:
        result["delivery_batch_scale"] = "single_surface"
        result["delivery_outcome"] = "outcome_progress"
        # Material results require these bounded text fields; fill them from
        # adjacent fields if the model returned a sparse block.
        if not result.get("recommended_action"):
            result["recommended_action"] = _bounded(
                result.get("next_action") or result.get("classification") or kind,
                limit=TEXT_LIMITS["recommended_action"],
            )
        if not result.get("next_action"):
            result["next_action"] = _bounded(
                result.get("recommended_action"),
                limit=TEXT_LIMITS["next_action"],
            )
        if not result.get("classification"):
            result["classification"] = _bounded(
                kind, limit=TEXT_LIMITS["classification"]
            )
    # This adapter has no goal-vision packet, so the executor treats the path
    # delta as unchanged and requires a bounded reason for material results.
    result["vision_unchanged_reason"] = _bounded(
        candidate.get("vision_unchanged_reason")
        or (
            "host reported material work without a goal vision replan packet"
            if kind in MATERIAL_KINDS
            else "host reported no material change"
        ),
        limit=TEXT_LIMITS["vision_unchanged_reason"],
    )
    return result


def run_dsh_turn(
    *,
    prompt: str,
    session_id: str,
    workspace: Path,
    session_root: Path,
    provider: str,
    model: str,
    max_tokens: int | None,
    cordis: Path | None,
    runtime_bin: str | None,
    request_timeout_seconds: float | None,
) -> str:
    """Run one bounded DeepSeek Harness session through the Python SDK."""

    try:
        from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig
    except ImportError as exc:
        raise RuntimeError(
            "deepseek-harness-sdk is required; install it with "
            "`python -m pip install 'loopx[deepseek-harness]'`"
        ) from exc

    config: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "cwd": str(workspace),
        "session_root": str(session_root),
    }
    if max_tokens is not None:
        config["max_tokens"] = max_tokens
    if cordis is not None:
        config["cordis"] = str(cordis)
    if runtime_bin is not None:
        config["runtime_bin"] = runtime_bin
    if request_timeout_seconds is not None:
        config["request_timeout_seconds"] = request_timeout_seconds

    with DeepSeekHarness(DeepSeekHarnessConfig(**config)) as harness:
        return harness.run(prompt, session_id=session_id).final_response


def load_dsh_runner(path: Path):
    """Load a test/production runner module exposing ``run_dsh_turn``.

    The runner module must expose the same keyword signature as
    :func:`run_dsh_turn`. This is primarily used by hermetic smokes so the
    repository does not need a real DeepSeek Harness SDK/runtime installed.
    """

    spec = importlib.util.spec_from_file_location("dsh_turn_runner", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load dsh runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    runner = getattr(module, "run_dsh_turn", None)
    if runner is None:
        raise AttributeError(f"{path} must define run_dsh_turn(...)")
    return runner


def _default_session_root(workspace: Path) -> Path:
    return workspace / ".local" / DEFAULT_SESSION_ROOT_NAME


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--workspace", default=os.getcwd())
    parser.add_argument("--session-root", default=None)
    parser.add_argument("--cordis", default=None)
    parser.add_argument("--runtime-bin", default=None)
    parser.add_argument("--request-timeout-seconds", type=float, default=None)
    parser.add_argument(
        "--dsh-runner",
        default=None,
        help="Path to a Python module exposing run_dsh_turn(...); used by tests.",
    )
    args = parser.parse_args(argv)

    try:
        request = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"adapter: invalid request JSON on stdin: {exc}", file=sys.stderr)
        return 2
    if not isinstance(request, dict) or request.get("schema_version") != LOOPX_TURN_HOST_REQUEST_SCHEMA:
        print("adapter: stdin is not a loopx_turn_host_request_v0 object", file=sys.stderr)
        return 2

    try:
        authority = extract_turn_authority(request)
    except ValueError as exc:
        print(f"adapter: invalid TurnEnvelope authority: {exc}", file=sys.stderr)
        return 2

    workspace = Path(args.workspace).expanduser().resolve()
    session_root = (
        Path(args.session_root).expanduser().resolve()
        if args.session_root
        else _default_session_root(workspace)
    )
    session_root.mkdir(parents=True, exist_ok=True)

    turn_key = str(request.get("turn_key") or "")
    # Keep the opaque dsh session keyed by the same (goal, agent, todo) lineage
    # LoopX already uses for the Turn transaction. The exact value is a local
    # adapter concern and must not enter public LoopX state.
    envelope = _mapping(request.get("turn_envelope"))
    action = _mapping(envelope.get("action"))
    selected_todo = _mapping(action.get("selected_todo"))
    session_id = "-".join(
        str(value)
        for value in (
            envelope.get("goal_id"),
            envelope.get("agent_id"),
            selected_todo.get("todo_id"),
        )
        if value
    ) or f"dsh-{turn_key.removeprefix('sha256:')[:24]}"

    try:
        prompt = render_prompt(authority)
        if args.dsh_runner:
            runner = load_dsh_runner(Path(args.dsh_runner).expanduser().resolve())
            final_response = runner(
                prompt=prompt,
                session_id=session_id,
                workspace=workspace,
                session_root=session_root,
                provider=args.provider,
                model=args.model,
                max_tokens=args.max_tokens,
                cordis=Path(args.cordis).expanduser().resolve() if args.cordis else None,
                runtime_bin=args.runtime_bin,
                request_timeout_seconds=args.request_timeout_seconds,
            )
        else:
            final_response = run_dsh_turn(
                prompt=prompt,
                session_id=session_id,
                workspace=workspace,
                session_root=session_root,
                provider=args.provider,
                model=args.model,
                max_tokens=args.max_tokens,
                cordis=Path(args.cordis).expanduser().resolve() if args.cordis else None,
                runtime_bin=args.runtime_bin,
                request_timeout_seconds=args.request_timeout_seconds,
            )
    except Exception as exc:  # noqa: BLE001 - adapter fails closed at boundary
        print(f"adapter: dsh execution failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    candidate = parse_model_json(final_response)
    if candidate is None:
        print(
            "adapter: dsh final response did not contain a JSON result object",
            file=sys.stderr,
        )
    result = build_result(
        request,
        candidate,
        fallback_reason="dsh returned no typed JSON result; inspect the local dsh session",
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
