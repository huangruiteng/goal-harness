#!/usr/bin/env python3
"""Offline smoke for the public SSH reverse-proxy supervisor example."""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "examples" / "ssh_reverse_proxy_supervisor.py"


def load_example():
    spec = importlib.util.spec_from_file_location(
        "loopx_ssh_reverse_proxy_supervisor",
        SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load SSH reverse-proxy supervisor example")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def example_config(module):
    return module.ProxyConfig(
        ssh_host="example-runtime",
        local_port=18080,
        remote_port=18081,
        ssh_binary="/usr/bin/ssh",
        retry_delay=1.0,
        upstream_connect_timeout=2.0,
        server_alive_interval=20,
        server_alive_count_max=4,
        cleanup_stale_listener=True,
    )


def assert_ipv4_precedes_ipv6(module) -> None:
    answers = [
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("2001:4860:4860::8888", 443, 0, 0),
        ),
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("8.8.8.8", 443),
        ),
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("192.0.2.10", 443),
        ),
    ]
    with mock.patch.object(module.socket, "getaddrinfo", return_value=answers):
        resolved = module._public_addresses("example.com", 443)
    assert [family for family, _address in resolved] == [
        socket.AF_INET,
        socket.AF_INET6,
    ], resolved


def assert_ssh_command_is_bounded(module) -> None:
    config = example_config(module)
    command = module.build_ssh_command(config)
    assert command[-3:] == [
        "-R",
        "127.0.0.1:18081:127.0.0.1:18080",
        "example-runtime",
    ], command
    assert "ExitOnForwardFailure=yes" in command, command
    assert "ServerAliveInterval=20" in command, command
    assert "ServerAliveCountMax=4" in command, command
    assert "0.0.0.0" not in " ".join(command), command

    cleanup = module._cleanup_command(config.remote_port)
    assert "127.0.0.1:$port" in cleanup, cleanup
    assert "owner-mismatch" in cleanup, cleanup
    assert "unexpected-process" in cleanup, cleanup
    assert "sshd|sshd-session" in cleanup, cleanup
    try:
        module._ssh_alias("-oProxyCommand=unexpected")
    except module.argparse.ArgumentTypeError:
        pass
    else:
        raise AssertionError("SSH aliases that look like options must be refused")


def assert_health_endpoint_is_local(module) -> None:
    config = example_config(module)
    server = module.ProxyServer((module.LOOPBACK_HOST, 0), config)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=2) as client:
            client.sendall(
                b"GET http://reverse-proxy-health.invalid/ HTTP/1.1\r\n"
                b"Host: reverse-proxy-health.invalid\r\n"
                b"Connection: close\r\n\r\n"
            )
            response = client.recv(4096)
        assert response.startswith(b"HTTP/1.1 204 No Content"), response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> int:
    module = load_example()
    assert_ipv4_precedes_ipv6(module)
    assert_ssh_command_is_bounded(module)
    assert_health_endpoint_is_local(module)
    print("ssh-reverse-proxy-supervisor-smoke ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
