"""Goal-scoped Material Lifecycle capability contracts."""

from .architecture import (
    MATERIAL_LIFECYCLE_ARCHITECTURE_SCHEMA_VERSION,
    build_material_lifecycle_architecture_packet,
)
from .inventory import (
    MATERIAL_LIFECYCLE_STATES,
    MATERIAL_MIGRATION_PLAN_SCHEMA_VERSION,
    MATERIAL_STORE_INVENTORY_SCHEMA_VERSION,
    build_material_migration_plan,
    build_material_store_inventory,
)
from .lifecycle import (
    MATERIAL_LIFECYCLE_RECEIPT_SCHEMA_VERSION,
    build_material_lifecycle_receipt,
)
from .preparation import (
    MaterialInventoryProvider,
    MaterialMigrationPreparation,
    MaterialStoreSnapshot,
    prepare_material_migration,
)
from .ranking import (
    MATERIAL_RERANK_APPLY_RECEIPT_SCHEMA_VERSION,
    MATERIAL_RERANK_PROPOSAL_SCHEMA_VERSION,
    build_material_rerank_apply_receipt,
    build_material_rerank_proposal,
)

__all__ = [
    "MATERIAL_LIFECYCLE_ARCHITECTURE_SCHEMA_VERSION",
    "MATERIAL_LIFECYCLE_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_LIFECYCLE_STATES",
    "MATERIAL_MIGRATION_PLAN_SCHEMA_VERSION",
    "MATERIAL_RERANK_APPLY_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_RERANK_PROPOSAL_SCHEMA_VERSION",
    "MATERIAL_STORE_INVENTORY_SCHEMA_VERSION",
    "MaterialInventoryProvider",
    "MaterialMigrationPreparation",
    "MaterialStoreSnapshot",
    "build_material_lifecycle_architecture_packet",
    "build_material_lifecycle_receipt",
    "build_material_migration_plan",
    "build_material_rerank_apply_receipt",
    "build_material_rerank_proposal",
    "build_material_store_inventory",
    "prepare_material_migration",
]
