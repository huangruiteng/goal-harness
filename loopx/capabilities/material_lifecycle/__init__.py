"""Goal-scoped Material Lifecycle capability contracts."""

from .apply import (
    MATERIAL_MIGRATION_APPLY_RECEIPT_SCHEMA_VERSION,
    MATERIAL_MIGRATION_ROLLBACK_RECEIPT_SCHEMA_VERSION,
    MaterialAuthoritySnapshot,
    MaterialAuthorityTransition,
    MaterialDualReadReconciliation,
    MaterialMigrationApplyProvider,
    MaterialStagedStore,
    apply_material_migration,
    rollback_material_migration,
)
from .architecture import (
    MATERIAL_LIFECYCLE_ARCHITECTURE_SCHEMA_VERSION,
    build_material_lifecycle_architecture_packet,
)
from .decision_planning import (
    MATERIAL_EXPLORE_INTENT_SCHEMA_VERSION,
    MaterialDecisionPlanning,
    MaterialDecisionPolicy,
    MaterialDecisionPolicyResult,
    build_material_explore_intent,
    plan_material_decision_actions,
)
from .explore_execution import (
    MATERIAL_EXPLORE_EXECUTION_RECEIPT_SCHEMA_VERSION,
    MaterialExploreCandidate,
    MaterialExploreExecution,
    execute_material_explore_intent,
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
from .rebuild import (
    MATERIAL_RANKED_ENTRY_REBUILD_APPLY_RECEIPT_SCHEMA_VERSION,
    MATERIAL_RANKED_ENTRY_REBUILD_PLAN_SCHEMA_VERSION,
    build_material_ranked_entry_rebuild_apply_receipt,
    build_material_ranked_entry_rebuild_plan,
    derive_material_ranked_entry_ref,
)

__all__ = [
    "MATERIAL_EXPLORE_INTENT_SCHEMA_VERSION",
    "MATERIAL_EXPLORE_EXECUTION_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_LIFECYCLE_ARCHITECTURE_SCHEMA_VERSION",
    "MATERIAL_LIFECYCLE_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_LIFECYCLE_STATES",
    "MATERIAL_MIGRATION_APPLY_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_MIGRATION_PLAN_SCHEMA_VERSION",
    "MATERIAL_MIGRATION_ROLLBACK_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_RANKED_ENTRY_REBUILD_APPLY_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_RANKED_ENTRY_REBUILD_PLAN_SCHEMA_VERSION",
    "MATERIAL_RERANK_APPLY_RECEIPT_SCHEMA_VERSION",
    "MATERIAL_RERANK_PROPOSAL_SCHEMA_VERSION",
    "MATERIAL_STORE_INVENTORY_SCHEMA_VERSION",
    "MaterialAuthoritySnapshot",
    "MaterialAuthorityTransition",
    "MaterialDecisionPlanning",
    "MaterialDecisionPolicy",
    "MaterialDecisionPolicyResult",
    "MaterialExploreCandidate",
    "MaterialExploreExecution",
    "MaterialDualReadReconciliation",
    "MaterialInventoryProvider",
    "MaterialMigrationApplyProvider",
    "MaterialMigrationPreparation",
    "MaterialStagedStore",
    "MaterialStoreSnapshot",
    "apply_material_migration",
    "build_material_explore_intent",
    "build_material_lifecycle_architecture_packet",
    "build_material_lifecycle_receipt",
    "build_material_migration_plan",
    "build_material_ranked_entry_rebuild_apply_receipt",
    "build_material_ranked_entry_rebuild_plan",
    "build_material_rerank_apply_receipt",
    "build_material_rerank_proposal",
    "build_material_store_inventory",
    "derive_material_ranked_entry_ref",
    "execute_material_explore_intent",
    "plan_material_decision_actions",
    "prepare_material_migration",
    "rollback_material_migration",
]
