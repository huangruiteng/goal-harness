"""Registration and cross-language parity checks for the DSH observer provider."""

from __future__ import annotations

import json
import re
from pathlib import Path

from loopx.capabilities.catalog import (
    build_capability_catalog_packet,
    build_capability_detail_packet,
)
from loopx.capabilities.reliability_diagnostics import (
    CAPABILITY_ID,
    DSH_PROVIDER_ID,
    ENVELOPE_FIELDS,
    OBSERVER_ENVELOPE_SCHEMA_VERSION,
    OBSERVER_STATS_SCHEMA_VERSION,
    ObserverEventKind,
)
from loopx.capabilities.reliability_diagnostics.intake import STATS_FIELDS

ROOT = Path(__file__).resolve().parents[2]
OBSERVER_TS = ROOT / "packages/dsh-loopx-plugin/src/observer.ts"
DRIVER_TS = ROOT / "packages/dsh-loopx-plugin/src/driver.ts"
CORDIS_PATCH = ROOT / "packages/dsh-loopx-plugin/cordis.patch.yml"
PACKAGE_JSON = ROOT / "packages/dsh-loopx-plugin/package.json"
TSDOWN_CONFIG = ROOT / "packages/dsh-loopx-plugin/tsdown.config.ts"


def test_catalog_declares_dsh_provider_without_claiming_readiness() -> None:
    packet = build_capability_catalog_packet()
    summary = next(item for item in packet["capabilities"] if item["id"] == CAPABILITY_ID)
    assert summary["provider_id"] == "loopx-core"
    assert summary["implementation_provider_count"] == 1
    provider = next(item for item in packet["providers"] if item["id"] == DSH_PROVIDER_ID)
    assert provider == {
        "id": DSH_PROVIDER_ID,
        "origin": "extension",
        "declared": True,
        "installed": False,
        "enabled": False,
        "ready": False,
    }

    detail = build_capability_detail_packet(CAPABILITY_ID)["capability"]
    assert detail["default_enabled"] is False
    [implementation] = detail["implementation_providers"]
    assert implementation["provider_id"] == DSH_PROVIDER_ID
    assert implementation["protocol"] == OBSERVER_ENVELOPE_SCHEMA_VERSION
    assert implementation["provider_state"] == {
        "declared": True,
        "installed": False,
        "enabled": False,
        "ready": False,
    }


def test_typescript_observer_shares_field_names_and_has_no_control_path() -> None:
    source = OBSERVER_TS.read_text(encoding="utf-8")
    assert f"'{OBSERVER_ENVELOPE_SCHEMA_VERSION}'" in source
    assert f"'{OBSERVER_STATS_SCHEMA_VERSION}'" in source
    assert f"'{CAPABILITY_ID}'" in source
    assert f"'{DSH_PROVIDER_ID}'" in source
    for field in ENVELOPE_FIELDS | STATS_FIELDS:
        assert re.search(rf"\b{field}\b", source), field
    for kind in ObserverEventKind:
        assert f"'{kind.value}'" in source, kind

    # Physically separate from the continuation driver and its send path.
    assert "from './driver" not in source
    assert "from './cli" not in source
    assert "from './managed-runtime" not in source
    assert ".send(" not in source
    assert ".inbox" not in source
    assert "@deepseek-ai/dsh-agent" not in source
    assert "ctx.on('agent/" not in source
    assert "outbound_endpoints: []" in source
    assert "observation_entered_worker_context: false" in source
    assert "observation_entered_scheduler_inputs: false" in source


def test_observer_is_a_separate_default_off_plugin_row() -> None:
    driver = DRIVER_TS.read_text(encoding="utf-8")
    observer = OBSERVER_TS.read_text(encoding="utf-8")
    patch = CORDIS_PATCH.read_text(encoding="utf-8")
    build = TSDOWN_CONFIG.read_text(encoding="utf-8")
    manifest = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))

    assert "observer" not in driver.lower()
    assert "export const inject: readonly string[] = []" in observer
    assert "ctx.on('session/created'" in observer
    assert "ctx.on('session/event'" in observer
    assert "ctx.on('session/disposed'" in observer
    assert "loopx-shadow-observer" in patch
    assert "name: dsh-loopx-plugin/observer" in patch
    assert "observer: 'build-temp/host/observer.js'" in build
    assert manifest["exports"]["./observer"] == {
        "types": "./lib/types/observer.d.ts",
        "default": "./lib/observer.js",
    }
