from __future__ import annotations

from .contract import MachineConfigurationRegistry


def build_builtin_machine_configuration_registry() -> MachineConfigurationRegistry:
    # Imports stay at the composition boundary: the generic contract does not
    # depend on any consumer capability.
    from ..periodic_report.machine_defaults import (
        periodic_report_machine_configuration_namespace,
    )

    return MachineConfigurationRegistry().register(
        periodic_report_machine_configuration_namespace()
    )


__all__ = ["build_builtin_machine_configuration_registry"]
