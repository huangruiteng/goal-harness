from __future__ import annotations

import subprocess
from unittest import mock

import pytest

from loopx.control_plane.status.ssh_tunnel import ensure_ssh_source


def test_ensure_ssh_source_opens_tunnel_and_returns_status_url() -> None:
    calls: list[list[str]] = []
    probe_count = 0

    def fake_loopback(port: int, **kwargs: object) -> bool:
        nonlocal probe_count
        probe_count += 1
        return probe_count >= 2

    with mock.patch(
        "loopx.control_plane.status.ssh_tunnel.configured_ssh_host_aliases",
        return_value=["ark-devbox"],
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel._loopback_status_ok", fake_loopback
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel._remote_status_ok", return_value=True
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel.subprocess.run",
        side_effect=lambda args, **kwargs: calls.append(list(args)),
    ):
        result = ensure_ssh_source("ark-devbox", 8877, wait_seconds=0.01)

    assert result == {
        "ok": True,
        "status_url": "http://127.0.0.1:8877/status.json",
        "tunnel_required": True,
        "remote_started": False,
    }
    tunnel_call = calls[0]
    assert tunnel_call[0] == "ssh"
    assert "-L" in tunnel_call
    assert "8877:127.0.0.1:8766" in tunnel_call
    assert "ark-devbox" in tunnel_call
    # The alias and port are passed as separate argv entries, never through a shell.
    assert "; " not in " ".join(tunnel_call)


def test_ensure_ssh_source_starts_remote_status_when_missing() -> None:
    probe_count = 0

    def fake_loopback(port: int, **kwargs: object) -> bool:
        nonlocal probe_count
        probe_count += 1
        return probe_count >= 4

    with mock.patch(
        "loopx.control_plane.status.ssh_tunnel.configured_ssh_host_aliases",
        return_value=["ark-devbox"],
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel._loopback_status_ok", fake_loopback
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel._remote_status_ok", return_value=False
    ), mock.patch(
        "loopx.control_plane.status.ssh_tunnel._start_remote_status", return_value=None
    ) as start_remote, mock.patch(
        "loopx.control_plane.status.ssh_tunnel.subprocess.run", return_value=None
    ):
        result = ensure_ssh_source("ark-devbox", 8877, wait_seconds=0.01)

    start_remote.assert_called_once_with("ark-devbox")
    assert result["remote_started"] is True


def test_ensure_ssh_source_rejects_unknown_alias() -> None:
    with mock.patch(
        "loopx.control_plane.status.ssh_tunnel.configured_ssh_host_aliases",
        return_value=["ark-devbox"],
    ):
        with pytest.raises(ValueError, match="unknown SSH host alias"):
            ensure_ssh_source("evil-host;id", 8877)


def test_ensure_ssh_source_rejects_invalid_port() -> None:
    with mock.patch(
        "loopx.control_plane.status.ssh_tunnel.configured_ssh_host_aliases",
        return_value=["ark-devbox"],
    ):
        with pytest.raises(ValueError, match="local tunnel port"):
            ensure_ssh_source("ark-devbox", 22)
        with pytest.raises(ValueError, match="local tunnel port"):
            ensure_ssh_source("ark-devbox", "8877")
