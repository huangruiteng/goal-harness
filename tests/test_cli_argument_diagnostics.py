from __future__ import annotations

import json

import pytest

from loopx.cli import build_parser, main, output_format, resolve_global_output_format
from loopx.cli_commands.quota import _validate_quota_command_request
from loopx.cli_commands.todo_argument_validation import (
    validate_todo_archive_completed_options,
    validate_todo_capture_followups_options,
    validate_todo_claim_options,
    validate_todo_complete_options,
    validate_todo_suggest_options,
    validate_todo_supersede_options,
    validate_todo_update_options,
)


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
    ("extra_args", "expected"),
    [
        ([], "todo claim requires --todo-id"),
        (
            ["--todo-id", "todo_example"],
            "todo claim requires --claimed-by",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--claimed-by",
                "codex-example",
                "--clear-claim",
            ],
            "todo claim requires --claimed-by and does not support --clear-claim",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--claimed-by",
                "codex-example",
                "--decision-outcome",
                "approve",
                "--next-agent-todo",
                "Continue the work.",
            ],
            "todo claim only accepts --todo-id, --claimed-by, --agent-id, optional --role, "
            "--project, --state-file, and --dry-run; unsupported: "
            "--decision-outcome, --next-agent-todo",
        ),
    ],
)
def test_todo_claim_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "claim", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_claim_options(args)

    assert str(exc_info.value) == expected


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ([], "todo update requires --todo-id"),
        (
            [
                "--todo-id",
                "todo_example",
                "--claimed-by",
                "codex-example",
                "--clear-claim",
            ],
            "todo update accepts either --claimed-by or --clear-claim, not both",
        ),
        (
            ["--todo-id", "todo_example"],
            "todo update requires at least one mutable todo field",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--no-follow-up",
            ],
            "--no-follow-up requires --note, --reason, or --evidence",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--note",
                "validated",
                "--decision-outcome",
                "approve",
            ],
            "todo update does not accept --decision-outcome; use todo complete",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--next-required-capability",
                "network",
            ],
            "todo update requires at least one mutable todo field",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--note",
                "validated",
                "--next-required-capability",
                "network",
            ],
            "todo update does not support --next-required-capability",
        ),
    ],
)
def test_todo_update_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "update", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_update_options(args)

    assert str(exc_info.value) == expected


def test_todo_update_validation_accepts_a_mutable_field() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "update",
            "--goal-id",
            "example-goal",
            "--todo-id",
            "todo_example",
            "--note",
            "validated",
        ]
    )

    validate_todo_update_options(args)


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ([], "todo complete requires --todo-id"),
        (
            ["--todo-id", "todo_example", "--explore-result-node-ref", "result_1"],
            "todo complete does not update --explore-result-node-ref; "
            "use todo update first",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--claimed-by",
                "codex-example",
                "--clear-claim",
            ],
            "todo complete accepts either --claimed-by or --clear-claim, not both",
        ),
        (
            ["--todo-id", "todo_example", "--task-repository", "git:example/repo"],
            "todo complete does not update current todo routing metadata; "
            "use todo update first",
        ),
        (
            ["--todo-id", "todo_example", "--cadence", "1h"],
            "todo complete does not update target or monitor schedule metadata; "
            "use todo update before completion",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--no-follow-up",
                "--next-agent-todo",
                "Continue.",
            ],
            "--no-follow-up cannot be combined with successor todos",
        ),
        (
            [
                "--todo-id",
                "todo_example",
                "--successor-todo-id",
                "todo_successor",
                "--next-agent-todo",
                "Continue.",
            ],
            "--successor-todo-id links existing work and cannot be combined with "
            "--next-agent-todo or --next-user-todo",
        ),
        (
            ["--todo-id", "todo_example", "--no-follow-up"],
            "--no-follow-up requires --note or --evidence",
        ),
        (
            ["--todo-id", "todo_example", "--continuation-policy", "same_agent_non_delivery"],
            "todo complete does not update --continuation-policy; use todo update first",
        ),
        (
            ["--todo-id", "todo_example", "--next-user-todo", "Approve."],
            "--next-user-todo requires explicit --next-user-task-class "
            "user_action|user_gate",
        ),
    ],
)
def test_todo_complete_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "complete", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_complete_options(args)

    assert str(exc_info.value) == expected


def test_todo_complete_validation_accepts_no_follow_up_with_evidence() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "complete",
            "--goal-id",
            "example-goal",
            "--todo-id",
            "todo_example",
            "--no-follow-up",
            "--evidence",
            "validated",
        ]
    )

    validate_todo_complete_options(args)


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ([], "todo supersede requires --todo-id"),
        (
            ["--todo-id", "todo_example", "--explore-result-node-ref", "result_1"],
            "todo supersede does not update --explore-result-node-ref; "
            "use todo update first",
        ),
        (
            ["--todo-id", "todo_example", "--decision-outcome", "approve"],
            "todo supersede does not accept --decision-outcome; use todo complete",
        ),
        (
            ["--todo-id", "todo_example", "--claimed-by", "codex-example"],
            "todo supersede does not support --claimed-by; use --next-claimed-by "
            "to assign the successor, or omit it to inherit the superseded todo "
            "owner when present",
        ),
        (
            ["--todo-id", "todo_example", "--self-merged"],
            "todo supersede does not support --self-merged",
        ),
        (
            ["--todo-id", "todo_example", "--no-follow-up"],
            "todo supersede does not support --no-follow-up",
        ),
        (
            ["--todo-id", "todo_example", "--continuation-policy", "same_agent_non_delivery"],
            "todo supersede does not update --continuation-policy; use todo update first",
        ),
        (
            ["--todo-id", "todo_example", "--next-user-todo", "Approve."],
            "--next-user-todo requires explicit --next-user-task-class "
            "user_action|user_gate",
        ),
        (
            ["--todo-id", "todo_example", "--blocks-agent", "codex-example"],
            "todo supersede does not update current todo routing metadata; "
            "use todo update first",
        ),
        (
            ["--todo-id", "todo_example", "--successor-todo-id", "todo_successor"],
            "todo supersede does not support --successor-todo-id; "
            "use --next-agent-todo or update the source todo before supersede",
        ),
        (
            ["--todo-id", "todo_example", "--target-key", "monitor"],
            "todo supersede does not update target or monitor schedule metadata; "
            "use todo update before supersede",
        ),
    ],
)
def test_todo_supersede_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "supersede", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_supersede_options(args)

    assert str(exc_info.value) == expected


def test_todo_supersede_validation_accepts_successor_creation() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "supersede",
            "--goal-id",
            "example-goal",
            "--todo-id",
            "todo_example",
            "--next-agent-todo",
            "Continue.",
        ]
    )

    validate_todo_supersede_options(args)


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        (
            ["--decision-outcome", "approve"],
            "todo archive-completed does not support --decision-outcome",
        ),
        (
            ["--claimed-by", "codex-example"],
            "todo archive-completed does not support --claimed-by or --clear-claim",
        ),
        (
            ["--excluded-agent", "codex-example"],
            "todo archive-completed does not support executor exclusions",
        ),
        (
            ["--next-claimed-by", "codex-example"],
            "todo archive-completed does not support --next-claimed-by",
        ),
        (
            ["--next-task-repository", "git:github.com/example/repo"],
            "todo archive-completed does not support successor routing metadata",
        ),
        (
            ["--self-merged"],
            "todo archive-completed does not support --self-merged",
        ),
        (
            ["--no-follow-up"],
            "todo archive-completed does not support --no-follow-up",
        ),
        (
            ["--follow-up", "Continue."],
            "todo archive-completed does not support --follow-up; "
            "use `todo capture-followups`",
        ),
        (
            ["--successor-todo-id", "todo_successor"],
            "todo archive-completed does not support --successor-todo-id",
        ),
    ],
)
def test_todo_archive_completed_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "archive-completed", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_archive_completed_options(args)

    assert str(exc_info.value) == expected


def test_todo_archive_completed_validation_accepts_role_and_limit() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "archive-completed",
            "--goal-id",
            "example-goal",
            "--role",
            "user",
            "--max-active-done",
            "7",
        ]
    )

    validate_todo_archive_completed_options(args)


def test_todo_suggest_validation_preserves_exact_unsupported_diagnostic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "--format",
            "json",
            "todo",
            "suggest",
            "--goal-id",
            "example-goal",
            "--todo-id",
            "todo_example",
            "--note",
            "not accepted",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == (
        "todo suggest only accepts --goal-id, optional --project, --agent-id, "
        "--from, --limit, --trigger, --dry-run, and --format; unsupported: "
        "--todo-id, --note"
    )


def test_todo_suggest_validation_accepts_suggestion_scope_options() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "suggest",
            "--goal-id",
            "example-goal",
            "--agent-id",
            "codex-example",
            "--from",
            "recent-repo",
            "--limit",
            "3",
            "--trigger",
            "quality-watch",
        ]
    )

    validate_todo_suggest_options(args)


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        (
            ["--role", "agent"],
            "todo capture-followups always records agent todos; do not pass --role",
        ),
        (
            ["--claimed-by", "codex-example"],
            "todo capture-followups writes unclaimed todos; do not pass --claimed-by",
        ),
        (
            ["--todo-id", "todo_example", "--note", "not accepted"],
            "todo capture-followups only accepts --goal-id, --follow-up, optional "
            "--text shorthand, --evidence, routing metadata, --project, --state-file, "
            "and --dry-run; unsupported: --todo-id, --note",
        ),
    ],
)
def test_todo_capture_followups_validation_preserves_exact_diagnostics(
    extra_args: list[str],
    expected: str,
) -> None:
    args = build_parser().parse_args(
        ["todo", "capture-followups", "--goal-id", "example-goal", *extra_args]
    )

    with pytest.raises(ValueError) as exc_info:
        validate_todo_capture_followups_options(args)

    assert str(exc_info.value) == expected


def test_todo_capture_followups_validation_accepts_routing_options() -> None:
    args = build_parser().parse_args(
        [
            "todo",
            "capture-followups",
            "--goal-id",
            "example-goal",
            "--follow-up",
            "Continue.",
            "--text",
            "Then validate.",
            "--evidence",
            "tests/test_cli_argument_diagnostics.py",
            "--task-class",
            "advancement_task",
            "--action-kind",
            "implement",
            "--continuation-policy",
            "same_agent_non_delivery",
            "--required-write-scope",
            "tests/**",
            "--required-capability",
            "shell",
            "--target-capability",
            "quality",
            "--required-decision-scope",
            "merge",
            "--state-file",
            "ACTIVE_GOAL_STATE.md",
        ]
    )

    validate_todo_capture_followups_options(args)


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
