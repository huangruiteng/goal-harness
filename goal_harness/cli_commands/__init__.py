"""Modular CLI command registrations.

Command modules expose two small functions:

- ``register_*_command(subparsers)`` wires argparse for one command group.
- ``handle_*_command(args, print_payload)`` executes the parsed command.

The top-level CLI keeps global options, registry fallback, and dispatch order.
"""

from .doctor import handle_doctor_command, register_doctor_command
from .starter import (
    handle_demo_command,
    handle_new_project_prompt_command,
    register_starter_commands,
)

__all__ = [
    "handle_demo_command",
    "handle_doctor_command",
    "handle_new_project_prompt_command",
    "register_doctor_command",
    "register_starter_commands",
]
