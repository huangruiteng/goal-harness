"""Goal-scoped Decision Context capability contracts."""

from .assembler import (
    DECISION_CONTEXT_ASSEMBLY_SCHEMA_VERSION,
    DECISION_CURSOR_CHECKPOINT_SCHEMA_VERSION,
    DecisionAuthorityEvidence,
    DecisionContextAssembly,
    DecisionEvidenceCollection,
    DecisionEvidenceRecords,
    DecisionRecallEvidence,
    assemble_decision_evidence,
)
from .architecture import (
    DECISION_CONTEXT_ARCHITECTURE_SCHEMA_VERSION,
    build_decision_context_architecture_packet,
)
from .profile import (
    DECISION_CONTEXT_ACTIVATION_STATUS_SCHEMA_VERSION,
    DECISION_CONTEXT_PROFILE_SCHEMA_VERSION,
    DecisionContextProfile,
    DecisionSourceProviderBinding,
    load_decision_context_profile,
    normalize_decision_context_profile,
    resolve_decision_context_activation,
)
from .packets import (
    DECISION_EVIDENCE_PACKET_SCHEMA_VERSION,
    DECISION_OUTCOME_RECEIPT_SCHEMA_VERSION,
    DECISION_PROPOSAL_SCHEMA_VERSION,
    build_decision_evidence_packet,
    build_decision_outcome_receipt,
    build_decision_proposal,
)
from .sources import (
    DECISION_SOURCE_MANIFEST_SCHEMA_VERSION,
    DECISION_SOURCE_SCAN_RECEIPT_SCHEMA_VERSION,
    DecisionSourceExactRead,
    DecisionSourceItem,
    DecisionSourceProvider,
    DecisionSourceScan,
    DecisionSourceSpec,
    build_decision_source_item_refs,
    build_decision_source_manifest,
)
from .providers import (
    LOCAL_FILE_SOURCE_ADAPTER,
    LocalFileDecisionSourceProvider,
    build_decision_source_provider,
    decision_source_provider_registered,
    register_decision_source_provider,
)
from .runtime import (
    assemble_profile_decision_evidence,
    load_private_decision_cursors,
)

__all__ = [
    "DECISION_CONTEXT_ASSEMBLY_SCHEMA_VERSION",
    "DECISION_CONTEXT_ARCHITECTURE_SCHEMA_VERSION",
    "DECISION_CONTEXT_ACTIVATION_STATUS_SCHEMA_VERSION",
    "DECISION_CURSOR_CHECKPOINT_SCHEMA_VERSION",
    "DECISION_EVIDENCE_PACKET_SCHEMA_VERSION",
    "DECISION_OUTCOME_RECEIPT_SCHEMA_VERSION",
    "DECISION_PROPOSAL_SCHEMA_VERSION",
    "DECISION_CONTEXT_PROFILE_SCHEMA_VERSION",
    "DECISION_SOURCE_MANIFEST_SCHEMA_VERSION",
    "DECISION_SOURCE_SCAN_RECEIPT_SCHEMA_VERSION",
    "DecisionAuthorityEvidence",
    "DecisionContextAssembly",
    "DecisionContextProfile",
    "DecisionEvidenceCollection",
    "DecisionEvidenceRecords",
    "DecisionRecallEvidence",
    "DecisionSourceExactRead",
    "DecisionSourceProviderBinding",
    "DecisionSourceItem",
    "DecisionSourceProvider",
    "DecisionSourceScan",
    "DecisionSourceSpec",
    "LOCAL_FILE_SOURCE_ADAPTER",
    "LocalFileDecisionSourceProvider",
    "assemble_decision_evidence",
    "assemble_profile_decision_evidence",
    "build_decision_context_architecture_packet",
    "build_decision_evidence_packet",
    "build_decision_outcome_receipt",
    "build_decision_proposal",
    "build_decision_source_item_refs",
    "build_decision_source_manifest",
    "build_decision_source_provider",
    "decision_source_provider_registered",
    "load_decision_context_profile",
    "load_private_decision_cursors",
    "normalize_decision_context_profile",
    "register_decision_source_provider",
    "resolve_decision_context_activation",
]
