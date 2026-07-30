from __future__ import annotations

import json

import pytest

from loopx.cli import build_parser, main, output_format, resolve_global_output_format
from loopx.cli_commands.quota import _validate_quota_command_request


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--goal-id", "example-goal", "--project", "."],
        ["quota", "should-run", "--goal-id", "example-goal", "--project", "."],
    ],
)
def test_unsupported_project_option_is_not_misparsed_as_projection_cache_ttl(
    argv: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "unrecognized arguments: --project ." in stderr
    assert "projection-cache-ttl-seconds" not in stderr
    assert "invalid int value" not in stderr


def test_quota_include_detail_rejects_unknown_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "quota",
                "should-run",
                "--goal-id",
                "example-goal",
                "--include-detail",
                "unknown",
            ]
        )

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "invalid choice: 'unknown'" in stderr
    assert "--include-detail" in stderr


def test_quota_include_detail_rejects_non_should_run_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--format",
            "json",
            "quota",
            "status",
            "--include-detail",
            "scheduler",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == (
        "--include-detail is only valid with `quota should-run`"
    )


def test_deprecated_scheduler_detail_alias_is_hidden_from_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["quota", "--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--include-detail" in help_text
    assert "--include-scheduler-detail" not in help_text


@pytest.mark.parametrize(
    (
        "command",
        "goal_id",
        "agent_id",
        "void_generated_at",
        "dry_run",
        "execute",
        "expected",
    ),
    [
        (
            "should-run",
            None,
            None,
            None,
            False,
            False,
            "`loopx quota should-run` requires --goal-id",
        ),
        (
            "scheduler-ack-current",
            "goal",
            None,
            None,
            False,
            False,
            "`loopx quota scheduler-ack-current` requires --agent-id",
        ),
        (
            "spend-slot",
            "goal",
            None,
            None,
            True,
            True,
            "`loopx quota spend-slot` accepts only one of --dry-run or --execute",
        ),
        (
            "void-slot",
            "goal",
            None,
            None,
            True,
            True,
            "`loopx quota void-slot` requires --void-generated-at",
        ),
    ],
)
def test_quota_command_request_validation_preserves_exact_diagnostics(
    command: str,
    goal_id: str | None,
    agent_id: str | None,
    void_generated_at: str | None,
    dry_run: bool,
    execute: bool,
    expected: str,
) -> None:
    args = build_parser().parse_args(["quota", command])
    args.goal_id = goal_id
    args.agent_id = agent_id
    args.void_generated_at = void_generated_at
    args.dry_run = dry_run
    args.execute = execute

    with pytest.raises(ValueError) as exc_info:
        _validate_quota_command_request(args)

    assert str(exc_info.value) == expected


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["quota", "should-run"], "json"),
        (["quota", "status"], "markdown"),
        (["status"], "markdown"),
        (["diagnose"], "markdown"),
        (["review-packet", "--goal-id", "example-goal"], "markdown"),
    ],
)
def test_only_quota_should_run_defaults_to_json(
    argv: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(argv)

    assert resolve_global_output_format(args) == expected


@pytest.mark.parametrize("explicit_format", ["markdown", "json"])
def test_explicit_global_format_overrides_quota_should_run_default(
    explicit_format: str,
) -> None:
    args = build_parser().parse_args(
        ["--format", explicit_format, "quota", "should-run"]
    )

    assert resolve_global_output_format(args) == explicit_format


def test_subcommand_format_keeps_precedence_over_resolved_global_default() -> None:
    args = build_parser().parse_args(["status", "--format", "json"])
    args.format = resolve_global_output_format(args)

    assert output_format(args) == "json"
