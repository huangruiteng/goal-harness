#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loopx.capabilities.change_quality.shadow import (
    CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS,
    build_change_quality_shadow_prompt,
    build_change_quality_shadow_receipt,
    change_quality_shadow_output_schema,
    grade_change_quality_shadow_result,
    load_change_quality_shadow_matrix,
    normalize_change_quality_shadow_result,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the public simplify-first v0/v1 model-behavior shadow matrix "
            "and print only a bounded receipt."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("tests/fixtures/change_quality/model_shadow_matrix.json"),
    )
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh"),
        default="low",
    )
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument(
        "--contract-version",
        action="append",
        choices=CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS,
        default=[],
    )
    parser.add_argument("--output", type=Path)
    return parser


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: float = 60.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _copy_overlay(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _materialize_case(
    *,
    repo_root: Path,
    case: dict[str, Any],
    destination: Path,
) -> dict[str, Any]:
    if case["kind"] == "real_pr_clean":
        _run(
            [
                "git",
                "clone",
                "--shared",
                "--quiet",
                "--no-checkout",
                str(repo_root),
                str(destination),
            ],
            cwd=repo_root,
            timeout=120.0,
        )
        _run(
            ["git", "checkout", "--quiet", "--detach", case["source"]["head_ref"]],
            cwd=destination,
        )
        return {"validator_status": "not_run"}

    fixture_root = repo_root / case["source"]["fixture_root"]
    shutil.copytree(fixture_root / "base", destination)
    _run(["git", "init", "--quiet"], cwd=destination)
    _run(["git", "config", "user.name", "LoopX Shadow"], cwd=destination)
    _run(
        ["git", "config", "user.email", "loopx-shadow@example.invalid"],
        cwd=destination,
    )
    _run(["git", "add", "--all"], cwd=destination)
    _run(["git", "commit", "--quiet", "-m", "fixture base"], cwd=destination)
    _copy_overlay(fixture_root / "candidate", destination)
    _run(["git", "add", "--all"], cwd=destination)
    _run(["git", "commit", "--quiet", "-m", "fixture candidate"], cwd=destination)
    validator = _run(
        shlex.split(case["source"]["validator"]),
        cwd=destination,
        timeout=120.0,
        check=False,
    )
    return {"validator_status": "passed" if validator.returncode == 0 else "failed"}


def _parse_codex_events(stdout: str) -> tuple[dict[str, Any], dict[str, int]]:
    final_message: str | None = None
    usage: dict[str, int] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                final_message = str(item.get("text") or "")
        if event.get("type") == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    "input_tokens": int(raw_usage.get("input_tokens") or 0),
                    "cached_input_tokens": int(
                        raw_usage.get("cached_input_tokens") or 0
                    ),
                    "output_tokens": int(raw_usage.get("output_tokens") or 0),
                    "reasoning_output_tokens": int(
                        raw_usage.get("reasoning_output_tokens") or 0
                    ),
                }
    if final_message is None:
        raise ValueError("missing_final_message")
    parsed = json.loads(final_message)
    if not isinstance(parsed, dict):
        raise ValueError("final_message_not_object")
    return parsed, usage


def _compact_error_code(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return "actor_timeout"
    if isinstance(exc, subprocess.CalledProcessError):
        return "actor_process_failed"
    if isinstance(exc, json.JSONDecodeError):
        return "actor_json_invalid"
    if isinstance(exc, ValueError):
        message = str(exc)
        if message in {"missing_final_message", "final_message_not_object"}:
            return message
        if any(
            field in message
            for field in ("schema_version", "case_id", "contract_version")
        ):
            return "actor_result_identity_invalid"
        if "findings[" in message or "finding codes" in message:
            return "actor_result_finding_invalid"
        if "reviewed_lenses" in message:
            return "actor_result_lenses_invalid"
        if "simplification" in message:
            return "actor_result_simplification_invalid"
        if "safe_fix" in message:
            return "actor_result_safe_fix_invalid"
        if "validation_commands" in message:
            return "actor_result_validation_invalid"
        return "actor_result_invalid"
    return "actor_execution_failed"


def _run_arm(
    *,
    repo_root: Path,
    case: dict[str, Any],
    contract_version: str,
    model: str,
    reasoning_effort: str,
    timeout_seconds: float,
    schema_path: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    usage: dict[str, int] = {}
    tracked_files_modified = False
    validator_status = "not_run"
    try:
        with TemporaryDirectory(
            prefix=f"loopx-cq-shadow-{case['case_id']}-{contract_version}-"
        ) as temporary:
            workspace = Path(temporary) / "repo"
            materialized = _materialize_case(
                repo_root=repo_root,
                case=case,
                destination=workspace,
            )
            validator_status = materialized["validator_status"]
            prompt = build_change_quality_shadow_prompt(
                case,
                contract_version=contract_version,
            )
            completed = _run(
                [
                    "codex",
                    "exec",
                    "--json",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--disable",
                    "apps",
                    "--disable",
                    "plugins",
                    "--disable",
                    "remote_plugin",
                    "--disable",
                    "browser_use",
                    "--disable",
                    "computer_use",
                    "--disable",
                    "image_generation",
                    "--disable",
                    "multi_agent",
                    "--disable",
                    "goals",
                    "--disable",
                    "tool_suggest",
                    "--disable",
                    "workspace_dependencies",
                    "--disable",
                    "hooks",
                    "-m",
                    model,
                    "-c",
                    f'model_reasoning_effort="{reasoning_effort}"',
                    "-s",
                    "workspace-write",
                    "-C",
                    str(workspace),
                    "--output-schema",
                    str(schema_path),
                    prompt,
                ],
                cwd=workspace,
                timeout=timeout_seconds,
            )
            raw_result, usage = _parse_codex_events(completed.stdout)
            tracked_files_modified = (
                _run(
                    ["git", "diff", "--quiet", "HEAD", "--"],
                    cwd=workspace,
                    check=False,
                ).returncode
                != 0
            )
            result = normalize_change_quality_shadow_result(
                raw_result,
                case=case,
                contract_version=contract_version,
            )
            grade = grade_change_quality_shadow_result(
                result,
                case=case,
                tracked_files_modified=tracked_files_modified,
            )
            return {
                **grade,
                "valid": True,
                "error_code": None,
                "validator_status": validator_status,
                **usage,
                "latency_ms": int((time.monotonic() - started) * 1000),
            }
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "contract_version": contract_version,
            "valid": False,
            "error_code": _compact_error_code(exc),
            "validator_status": validator_status,
            "tracked_files_modified": tracked_files_modified,
            **usage,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def main() -> int:
    args = _parser().parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    matrix_path = args.matrix if args.matrix.is_absolute() else repo_root / args.matrix
    matrix = load_change_quality_shadow_matrix(matrix_path)
    selected_ids = set(args.case_id)
    cases = [
        case
        for case in matrix["cases"]
        if not selected_ids or case["case_id"] in selected_ids
    ]
    unknown_ids = selected_ids - {case["case_id"] for case in cases}
    if unknown_ids:
        raise ValueError(f"unknown shadow case ids: {sorted(unknown_ids)}")
    selected_matrix = {**matrix, "cases": cases}
    versions = list(
        dict.fromkeys(args.contract_version or CHANGE_QUALITY_SHADOW_CONTRACT_VERSIONS)
    )
    source_commit = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
    ).stdout.strip()
    workers = max(1, min(args.workers, 4))
    with TemporaryDirectory(prefix="loopx-cq-shadow-schema-") as temporary:
        schema_path = Path(temporary) / "result-schema.json"
        schema_path.write_text(
            json.dumps(
                change_quality_shadow_output_schema(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        futures = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for case in cases:
                for version in versions:
                    futures.append(
                        executor.submit(
                            _run_arm,
                            repo_root=repo_root,
                            case=case,
                            contract_version=version,
                            model=args.model,
                            reasoning_effort=args.reasoning_effort,
                            timeout_seconds=args.timeout_seconds,
                            schema_path=schema_path,
                        )
                    )
            runs = [future.result() for future in as_completed(futures)]
    runs.sort(key=lambda item: (item["case_id"], item["contract_version"]))
    receipt = build_change_quality_shadow_receipt(
        matrix=selected_matrix,
        declared_matrix=matrix,
        runs=runs,
        model_ref=f"{args.model}:{args.reasoning_effort}",
        source_commit=source_commit,
    )
    rendered = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.expanduser().write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["strict_receipt_promotion_recommended"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
