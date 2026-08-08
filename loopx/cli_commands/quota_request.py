from __future__ import annotations

import argparse

from ..control_plane.todos.contract import TODO_CONTINUATION_POLICY_VALUES

QUOTA_SHOULD_RUN_DETAIL_SECTIONS = (
    "scheduler",
    "agent-todos",
    "user-todos",
    "goal-boundary",
    "vision",
)
QUOTA_MONITOR_POLL_DETAIL_SECTIONS = ("decisions",)
QUOTA_DETAIL_SECTIONS = (
    *QUOTA_SHOULD_RUN_DETAIL_SECTIONS,
    *QUOTA_MONITOR_POLL_DETAIL_SECTIONS,
)


def register_quota_monitor_poll_request_arguments(
    quota_parser: argparse.ArgumentParser,
) -> None:
    quota_parser.add_argument("--todo-id", help="Monitor todo id for `quota monitor-poll` metadata writeback.")
    quota_parser.add_argument("--target-key", help="Stable monitor target key for `quota monitor-poll` metadata writeback.")
    quota_parser.add_argument("--result-hash", help="Public-safe result hash observed by `quota monitor-poll`.")
    quota_parser.add_argument("--material-change", action="store_true", help="Mark a monitor poll as a material transition instead of unchanged evidence.")
    quota_parser.add_argument("--cadence", help="Monitor cadence used to compute the next due timestamp, e.g. 30m, 2h, or 1d.")
    quota_parser.add_argument("--next-due-at", help="Explicit ISO timestamp for the next monitor poll.")
    quota_parser.add_argument("--next-agent-todo", help="Agent follow-up todo to add when `--material-change` is set.")
    quota_parser.add_argument(
        "--next-action-kind",
        help="Explicit action kind for a material monitor's --next-agent-todo successor.",
    )
    quota_parser.add_argument(
        "--next-task-repository",
        help=(
            "Credential-free Git repository identity for a material monitor's "
            "--next-agent-todo successor."
        ),
    )
    quota_parser.add_argument(
        "--next-required-capability",
        dest="next_required_capabilities",
        action="append",
        help=(
            "Execution capability required by a material monitor's --next-agent-todo "
            "successor. Repeat for multiple capabilities."
        ),
    )
    quota_parser.add_argument(
        "--next-continuation-policy",
        choices=sorted(TODO_CONTINUATION_POLICY_VALUES),
        help=(
            "Continuation policy for a material monitor's --next-agent-todo successor. "
            "Defaults to independent_handoff."
        ),
    )
    quota_parser.add_argument(
        "--next-target-key",
        help=(
            "Stable public-safe target key for a material monitor's --next-agent-todo "
            "successor. Defaults to a deterministic monitor-transition key."
        ),
    )
    quota_parser.add_argument("--next-user-todo", help="User follow-up todo to add when `--material-change` is set.")
    quota_parser.add_argument(
        "--next-user-task-class",
        choices=["user_gate", "user_action"],
        help=(
            "Required with monitor-poll `--next-user-todo`: user_gate for a "
            "blocking owner decision or user_action for a visible reminder "
            "that must not block the bound agent lane."
        ),
    )
    quota_parser.add_argument("--next-claimed-by", help="Registered agent id to claim the `--next-agent-todo` follow-up.")


def validate_quota_command_request(args: argparse.Namespace) -> None:
    command = args.quota_command
    if command not in {"status", "plan"} and not args.goal_id:
        raise ValueError(f"`loopx quota {command}` requires --goal-id")
    scheduler_commands = {
        "scheduler-ack",
        "scheduler-ack-current",
        "scheduler-fail-current",
    }
    if command in scheduler_commands and not args.agent_id:
        raise ValueError(f"`loopx quota {command}` requires --agent-id")
    if command == "void-slot" and not args.void_generated_at:
        raise ValueError("`loopx quota void-slot` requires --void-generated-at")
    if (
        command not in {"status", "plan", "should-run"}
        and args.dry_run
        and args.execute
    ):
        raise ValueError(
            f"`loopx quota {command}` accepts only one of --dry-run or --execute"
        )


def quota_detail_sections_from_args(args: argparse.Namespace) -> frozenset[str]:
    sections = set(getattr(args, "include_details", None) or ())
    if bool(getattr(args, "include_scheduler_detail", False)):
        sections.add("scheduler")
    if "all" in sections:
        sections.update(
            QUOTA_MONITOR_POLL_DETAIL_SECTIONS
            if args.quota_command == "monitor-poll"
            else QUOTA_SHOULD_RUN_DETAIL_SECTIONS
        )
        sections.discard("all")
    return frozenset(sections)
