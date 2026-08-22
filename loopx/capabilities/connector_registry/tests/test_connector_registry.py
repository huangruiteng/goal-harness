from __future__ import annotations

import json
from pathlib import Path

from loopx.capabilities.connector_registry.core import (
    BUILTIN_CONNECTOR_CATALOG,
    list_connectors,
    load_connector_registry,
    rank_connectors,
    record_connector_use,
    register_connector,
    save_connector_registry,
)


def test_builtin_catalog_covers_layers(tmp_path: Path) -> None:
    layers = {c["layer"] for c in BUILTIN_CONNECTOR_CATALOG}
    assert layers == {"L0", "L1", "L2", "L3", "L4", "L5"}
    ids = [c["id"] for c in BUILTIN_CONNECTOR_CATALOG]
    assert len(ids) == len(set(ids))
    assert "cninfo-announcement" in ids
    assert "ark-web-search" in ids


def test_register_use_rank_persists(tmp_path: Path) -> None:
    path = tmp_path / "connector-registry.json"
    state = load_connector_registry(path)
    result = register_connector(state, "probe-connector", status="supported",
                                value_tier="P0", layer="L1", kind="announcement")
    state2 = {**state, "connectors": result["connectors"], "usage": result["usage_map"]}
    used = record_connector_use(state2, "probe-connector", ok=True, ms=120)
    state3 = {**state2, "connectors": used["connectors"], "usage": used["usage_map"]}
    save_connector_registry(state3, path)

    reloaded = load_connector_registry(path)
    entry = next(c for c in reloaded["connectors"] if c["id"] == "probe-connector")
    assert entry["status"] == "supported"
    assert reloaded["usage"]["probe-connector"]["count"] == 1
    assert reloaded["usage"]["probe-connector"]["ok"] == 1

    ranked = rank_connectors(reloaded)
    top = ranked[0]
    assert top["score"] > 0
    packet = list_connectors(reloaded)
    assert packet["summary"]["supported"] >= 1
    assert json.dumps(packet, ensure_ascii=False)
