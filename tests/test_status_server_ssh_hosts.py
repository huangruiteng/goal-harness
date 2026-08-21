from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading

from loopx.control_plane.status.ssh_host_catalog import configured_ssh_host_aliases
from loopx.status_server import DEFAULT_SSH_HOSTS_PATH, StatusHTTPServer, StatusRequestHandler


def _write_config(ssh_directory: Path) -> Path:
    included = ssh_directory / "conf.d"
    included.mkdir(parents=True)
    (included / "jump.conf").write_text(
        "Host jump-box\n  HostName 192.0.2.12\n",
        encoding="utf-8",
    )
    config = ssh_directory / "config"
    config.write_text(
        "\n".join(
            [
                "Include conf.d/*.conf",
                "Host workstation *.example !blocked",
                "  HostName 192.0.2.10",
                "Host workstation",
                "Host -oProxyCommand=unsafe",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return config


def test_configured_ssh_host_aliases_exposes_only_explicit_safe_aliases(tmp_path: Path) -> None:
    config = _write_config(tmp_path / ".ssh")

    assert configured_ssh_host_aliases(config) == ["jump-box", "workstation"]


def test_ssh_hosts_endpoint_returns_aliases_without_config_details(tmp_path: Path) -> None:
    config = _write_config(tmp_path / ".ssh")
    server = StatusHTTPServer(("127.0.0.1", 0), StatusRequestHandler)
    server.ssh_config_path = config
    server.verbose = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request(
            "GET",
            DEFAULT_SSH_HOSTS_PATH,
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert response.status == 200
    assert payload == {
        "ok": True,
        "schema_version": "ssh_host_catalog_v0",
        "hosts": [{"alias": "jump-box"}, {"alias": "workstation"}],
    }
    assert "192.0.2" not in json.dumps(payload)


def test_ssh_hosts_endpoint_rejects_non_loopback_browser_origin(tmp_path: Path) -> None:
    server = StatusHTTPServer(("127.0.0.1", 0), StatusRequestHandler)
    server.ssh_config_path = _write_config(tmp_path / ".ssh")
    server.verbose = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request(
            "GET",
            DEFAULT_SSH_HOSTS_PATH,
            headers={"Origin": "https://example.com"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert response.status == 403
    assert payload["ok"] is False
