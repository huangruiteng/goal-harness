#!/usr/bin/env python3
"""Run a loopback-only HTTPS CONNECT proxy through an SSH reverse forward.

This example is intentionally provider-neutral. It gives a remote agent runtime
an outbound HTTPS path through its desktop host without copying credentials or
session state between machines.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import select
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

LOOPBACK_HOST = "127.0.0.1"
HEALTH_HOST = "reverse-proxy-health.invalid"
BUFFER_SIZE = 65536
HEADER_LIMIT = 65536


@dataclass(frozen=True)
class ProxyConfig:
    ssh_host: str
    local_port: int
    remote_port: int
    ssh_binary: str
    retry_delay: float
    upstream_connect_timeout: float
    server_alive_interval: int
    server_alive_count_max: int
    cleanup_stale_listener: bool


def _log(message: str, *, error: bool = False) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    print(
        f"{stamp} {message}",
        file=sys.stderr if error else sys.stdout,
        flush=True,
    )


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in 1024..65535")
    return port


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _ssh_alias(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise argparse.ArgumentTypeError(
            "SSH host must be a config alias containing only letters, digits, "
            "dots, underscores, or hyphens"
        )
    return value


def parse_args(argv: list[str] | None = None) -> ProxyConfig:
    default_ssh = "/usr/bin/ssh" if Path("/usr/bin/ssh").is_file() else "ssh"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ssh-host",
        required=True,
        type=_ssh_alias,
        help="SSH config alias for the remote runtime host",
    )
    parser.add_argument("--local-port", required=True, type=_port)
    parser.add_argument(
        "--remote-port",
        type=_port,
        help="remote loopback port; defaults to --local-port",
    )
    parser.add_argument("--ssh-binary", default=default_ssh)
    parser.add_argument("--retry-delay", default=5.0, type=_positive_float)
    parser.add_argument(
        "--upstream-connect-timeout",
        default=6.0,
        type=_positive_float,
    )
    parser.add_argument(
        "--server-alive-interval",
        default=30,
        type=_positive_int,
    )
    parser.add_argument(
        "--server-alive-count-max",
        default=3,
        type=_positive_int,
    )
    parser.add_argument(
        "--cleanup-stale-listener",
        action="store_true",
        help=(
            "after the managed tunnel exits, remove only a same-user sshd "
            "listener on the configured remote loopback port"
        ),
    )
    args = parser.parse_args(argv)
    ssh_binary = shutil.which(args.ssh_binary)
    if ssh_binary is None:
        parser.error(f"SSH binary is not executable: {args.ssh_binary}")
    return ProxyConfig(
        ssh_host=args.ssh_host,
        local_port=args.local_port,
        remote_port=args.remote_port or args.local_port,
        ssh_binary=ssh_binary,
        retry_delay=args.retry_delay,
        upstream_connect_timeout=args.upstream_connect_timeout,
        server_alive_interval=args.server_alive_interval,
        server_alive_count_max=args.server_alive_count_max,
        cleanup_stale_listener=args.cleanup_stale_listener,
    )


def _read_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > HEADER_LIMIT:
            raise ValueError("request headers are too large")
    return bytes(data)


def _split_authority(authority: str) -> tuple[str, int]:
    parsed = urlsplit(f"//{authority}")
    if not parsed.hostname:
        raise ValueError("CONNECT target is missing a host")
    return parsed.hostname, parsed.port or 443


def _public_addresses(host: str, port: int) -> list[tuple[int, tuple]]:
    addresses: list[tuple[int, tuple]] = []
    seen: set[tuple[int, tuple]] = set()
    for family, _socktype, _proto, _name, sockaddr in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    ):
        if family not in (socket.AF_INET, socket.AF_INET6):
            continue
        address = ipaddress.ip_address(sockaddr[0].split("%", 1)[0])
        candidate = (family, sockaddr)
        if address.is_global and candidate not in seen:
            seen.add(candidate)
            addresses.append(candidate)
    if not addresses:
        raise OSError("CONNECT target has no globally routable address")

    # Some VPNs leave globally scoped IPv6 DNS answers available while their
    # IPv6 route is unusable. Try IPv4 first, but retain IPv6 as a fallback.
    addresses.sort(key=lambda item: 0 if item[0] == socket.AF_INET else 1)
    return addresses


def _connect_public(config: ProxyConfig, host: str, port: int) -> socket.socket:
    last_error: OSError | None = None
    for family, sockaddr in _public_addresses(host, port):
        upstream = socket.socket(family, socket.SOCK_STREAM)
        upstream.settimeout(config.upstream_connect_timeout)
        try:
            upstream.connect(sockaddr)
            return upstream
        except OSError as exc:
            last_error = exc
            upstream.close()
    raise last_error or OSError("failed to connect to CONNECT target")


def _relay(client: socket.socket, upstream: socket.socket) -> None:
    for sock in (client, upstream):
        sock.settimeout(None)
    peers = {client: upstream, upstream: client}
    readable = [client, upstream]
    while readable:
        ready, _, failed = select.select(readable, [], readable)
        if failed:
            raise OSError("CONNECT relay socket failed")
        for source in ready:
            chunk = source.recv(BUFFER_SIZE)
            if chunk:
                peers[source].sendall(chunk)
                continue
            readable.remove(source)
            try:
                peers[source].shutdown(socket.SHUT_WR)
            except OSError:
                pass


class ProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address: tuple[str, int], config: ProxyConfig) -> None:
        self.proxy_config = config
        super().__init__(address, ProxyHandler)


class ProxyHandler(socketserver.BaseRequestHandler):
    server: ProxyServer

    def handle(self) -> None:
        client = self.request
        client.settimeout(30)
        upstream: socket.socket | None = None
        tunnel_established = False
        try:
            request = _read_headers(client)
            header_end = request.find(b"\r\n\r\n")
            if header_end < 0:
                raise ValueError("incomplete proxy request")
            head = request[:header_end].decode("iso-8859-1")
            lines = head.split("\r\n")
            method, target, _version = lines[0].split(" ", 2)
            host_header = next(
                (
                    line.split(":", 1)[1].strip()
                    for line in lines[1:]
                    if line.lower().startswith("host:")
                ),
                "",
            )
            parsed = urlsplit(target)
            request_host = parsed.hostname or host_header.split(":", 1)[0]
            if method.upper() == "GET" and request_host == HEALTH_HOST:
                client.sendall(
                    b"HTTP/1.1 204 No Content\r\n"
                    b"Content-Length: 0\r\n"
                    b"Connection: close\r\n\r\n"
                )
                return
            if method.upper() != "CONNECT":
                raise ValueError("proxy accepts only HTTPS CONNECT requests")
            host, port = _split_authority(target)
            if port != 443:
                raise ValueError("CONNECT is restricted to port 443")
            upstream = _connect_public(self.server.proxy_config, host, port)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            tunnel_established = True
            _relay(client, upstream)
        except (OSError, ValueError) as exc:
            _log(
                f"proxy_connection_error:{type(exc).__name__}:{exc}",
                error=True,
            )
            if not tunnel_established:
                try:
                    client.sendall(
                        b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n"
                    )
                except OSError:
                    pass
        finally:
            if upstream is not None:
                upstream.close()


def build_ssh_command(config: ProxyConfig) -> list[str]:
    reverse_forward = (
        f"{LOOPBACK_HOST}:{config.remote_port}:{LOOPBACK_HOST}:{config.local_port}"
    )
    return [
        config.ssh_binary,
        "-x",
        "-N",
        "-T",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ControlPersist=no",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ServerAliveInterval={config.server_alive_interval}",
        "-o",
        f"ServerAliveCountMax={config.server_alive_count_max}",
        "-o",
        "ConnectTimeout=10",
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        reverse_forward,
        config.ssh_host,
    ]


def _cleanup_command(remote_port: int) -> str:
    return f"""
port={remote_port}
pid=$(lsof -t -nP -iTCP@127.0.0.1:$port -sTCP:LISTEN 2>/dev/null | head -n 1)
if [ -z "$pid" ]; then
    pid=$(sudo -n lsof -t -nP -iTCP@127.0.0.1:$port -sTCP:LISTEN 2>/dev/null | head -n 1)
fi
if [ -z "$pid" ]; then
    printf 'none\\n'
    exit 0
fi
owner_uid=$(ps -p "$pid" -o uid= 2>/dev/null | tr -d ' ')
expected_uid=$(id -u)
comm=$(ps -p "$pid" -o comm= 2>/dev/null | tr -d ' ')
if [ "$owner_uid" != "$expected_uid" ]; then
    printf 'refused:%s:owner-mismatch\\n' "$pid" >&2
    exit 64
fi
case "$comm" in
    sshd|sshd-session) ;;
    *)
        printf 'refused:%s:unexpected-process\\n' "$pid" >&2
        exit 65
        ;;
esac
kill -TERM "$pid"
for delay in 1 1 1 1 1; do
    if ! lsof -a -p "$pid" -iTCP@127.0.0.1:$port -sTCP:LISTEN >/dev/null 2>&1; then
        printf 'terminated:%s\\n' "$pid"
        exit 0
    fi
    sleep "$delay"
done
printf 'timeout:%s\\n' "$pid" >&2
exit 66
""".strip()


def _remote_ssh_command(config: ProxyConfig, command: str) -> list[str]:
    return [
        config.ssh_binary,
        "-x",
        "-T",
        "-o",
        "ControlMaster=no",
        "-o",
        "ControlPath=none",
        "-o",
        "ControlPersist=no",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        config.ssh_host,
        command,
    ]


def remove_stale_remote_listener(config: ProxyConfig) -> bool:
    try:
        result = subprocess.run(
            _remote_ssh_command(config, _cleanup_command(config.remote_port)),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=25,
            close_fds=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        _log("stale_listener_cleanup_timeout", error=True)
        return False
    detail = (result.stdout or result.stderr).strip().replace("\n", ";")
    if result.returncode == 0:
        _log(f"stale_listener_cleanup:{detail or 'ok'}")
        return True
    _log(
        f"stale_listener_cleanup_failed:exit={result.returncode}:{detail}",
        error=True,
    )
    return False


def _terminate(process: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout)


def supervise(config: ProxyConfig) -> int:
    try:
        server = ProxyServer((LOOPBACK_HOST, config.local_port), config)
    except OSError as exc:
        _log(f"proxy_bind_failed:{exc.errno}", error=True)
        return 98
    server_thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"poll_interval": 0.2},
        name="reverse-connect-proxy",
        daemon=True,
    )
    server_thread.start()
    _log(f"proxy_ready:{LOOPBACK_HOST}:{config.local_port}")

    stopping = threading.Event()
    tunnel: subprocess.Popen[bytes] | None = None

    def stop(_signum: int, _frame: object) -> None:
        if stopping.is_set():
            return
        stopping.set()
        if tunnel is not None:
            _terminate(tunnel)
        server.shutdown()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    try:
        while not stopping.is_set():
            try:
                tunnel = subprocess.Popen(
                    build_ssh_command(config),
                    stdin=subprocess.DEVNULL,
                    close_fds=True,
                    env=os.environ.copy(),
                )
            except OSError as exc:
                _log(f"ssh_tunnel_start_failed:{exc.errno}", error=True)
                stopping.wait(config.retry_delay)
                continue
            return_code = tunnel.wait()
            _log(f"ssh_tunnel_exit:{return_code}", error=True)
            if stopping.is_set():
                break
            if config.cleanup_stale_listener:
                remove_stale_remote_listener(config)
            stopping.wait(config.retry_delay)
        return 0
    finally:
        if tunnel is not None:
            _terminate(tunnel)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)


def main(argv: list[str] | None = None) -> int:
    return supervise(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
