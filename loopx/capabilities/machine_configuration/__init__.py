"""Typed, provider-neutral machine configuration contracts."""

from .contract import (
    MACHINE_CONFIGURATION_SCHEMA,
    MachineConfigurationNamespace,
    MachineConfigurationRegistry,
    machine_configuration_revision,
    normalize_machine_configuration,
    project_machine_configuration,
)

__all__ = [
    "MACHINE_CONFIGURATION_SCHEMA",
    "MachineConfigurationNamespace",
    "MachineConfigurationRegistry",
    "machine_configuration_revision",
    "normalize_machine_configuration",
    "project_machine_configuration",
]
