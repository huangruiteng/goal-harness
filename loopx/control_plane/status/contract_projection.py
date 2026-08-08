"""Status contract projection inside the `status` bounded context."""

from __future__ import annotations

from typing import Any

from ..work_items.status_contract import (
    build_contract_health_projection as _build_contract_health_projection,
    build_status_contract as _build_status_contract,
)


STATUS_CONTRACT_SCHEMA_VERSION = 2
MINIMUM_DASHBOARD_STATUS_CONTRACT_SCHEMA_VERSION = 2
STATUS_CONTRACT_RELOAD_HINT = "scripts/macos-dashboard-launchagent.sh restart"
STATUS_CONTRACT_SIGNAL_LIMIT = 3


def build_status_contract() -> dict[str, Any]:
    return _build_status_contract(
        schema_version=STATUS_CONTRACT_SCHEMA_VERSION,
        minimum_dashboard_schema_version=MINIMUM_DASHBOARD_STATUS_CONTRACT_SCHEMA_VERSION,
        reload_hint=STATUS_CONTRACT_RELOAD_HINT,
    )


def build_contract_health_projection(contract: dict[str, Any]) -> dict[str, Any]:
    return _build_contract_health_projection(
        contract,
        signal_limit=STATUS_CONTRACT_SIGNAL_LIMIT,
    )
