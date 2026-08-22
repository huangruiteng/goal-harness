"""Unified public-connector registry for LoopX.

Manages the supported / pending public connectors (layered L0-L5, see the
finance research docs/16 blueprint), their value tiers, usage counters, and an
evolving value-priority ranking so any consumer can discover and rank
connectors in one place.
"""

from .catalog_entry import CONNECTOR_REGISTRY_CATALOG_ENTRY
from .core import (
    BUILTIN_CONNECTOR_CATALOG,
    CONNECTOR_REGISTRY_SCHEMA_VERSION,
    default_registry_path,
    list_connectors,
    load_connector_registry,
    rank_connectors,
    record_connector_use,
    register_connector,
    save_connector_registry,
)

__all__ = [
    "BUILTIN_CONNECTOR_CATALOG",
    "CONNECTOR_REGISTRY_CATALOG_ENTRY",
    "CONNECTOR_REGISTRY_SCHEMA_VERSION",
    "default_registry_path",
    "list_connectors",
    "load_connector_registry",
    "rank_connectors",
    "record_connector_use",
    "register_connector",
    "save_connector_registry",
]
