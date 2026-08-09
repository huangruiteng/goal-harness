"""Dreaming and planning projections inside the `status` bounded context."""

from __future__ import annotations

from typing import Any

from ...operator_gate import normalize_operator_question
from ..goals.dreaming import (
    compact_dreaming_lane_badge as _compact_dreaming_lane_badge,
    compact_dreaming_proposal as _compact_dreaming_proposal,
    compact_server_planning_contract as _compact_server_planning_contract,
    dreaming_attention_fields as _dreaming_attention_fields,
)
from ..runtime.public_safety import (
    public_safe_compact_list,
    public_safe_compact_text,
)
from ..runtime.status_classifications import DREAMING_ADVISORY_CLASSIFICATIONS


def compact_server_planning_contract(value: Any) -> dict[str, Any]:
    return _compact_server_planning_contract(
        value,
        public_safe_compact_text=public_safe_compact_text,
        public_safe_compact_list=public_safe_compact_list,
    )


def compact_dreaming_proposal(run: dict[str, Any] | None) -> dict[str, Any] | None:
    return _compact_dreaming_proposal(
        run,
        dreaming_advisory_classifications=DREAMING_ADVISORY_CLASSIFICATIONS,
        public_safe_compact_text=public_safe_compact_text,
        public_safe_compact_list=public_safe_compact_list,
    )


def compact_dreaming_lane_badge(proposal: dict[str, Any] | None) -> dict[str, Any] | None:
    return _compact_dreaming_lane_badge(
        proposal,
        public_safe_compact_text=public_safe_compact_text,
    )


def dreaming_attention_fields(run: dict[str, Any] | None) -> dict[str, Any]:
    return _dreaming_attention_fields(
        run,
        dreaming_advisory_classifications=DREAMING_ADVISORY_CLASSIFICATIONS,
        public_safe_compact_text=public_safe_compact_text,
        public_safe_compact_list=public_safe_compact_list,
        normalize_operator_question=normalize_operator_question,
    )
