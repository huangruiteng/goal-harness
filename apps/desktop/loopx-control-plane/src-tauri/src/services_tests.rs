use super::*;

#[cfg(not(windows))]
fn spawn_listener_fixture(
    executable: &Path,
    command: &str,
    port: u16,
    payload: &str,
) -> std::process::Child {
    use std::os::unix::fs::PermissionsExt;

    let source = format!(
        r#"#!/usr/bin/env python3
import socket

payload = {payload:?}.encode("utf-8")
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", {port}))
server.listen(8)
while True:
    connection, _ = server.accept()
    connection.recv(65536)
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        + f"Content-Length: {{len(payload)}}\r\n".encode("ascii")
        + b"Connection: close\r\n\r\n"
        + payload
    )
    connection.sendall(response)
    connection.close()
"#
    );
    fs::write(executable, source).expect("write listener fixture");
    let mut permissions = fs::metadata(executable)
        .expect("listener fixture metadata")
        .permissions();
    permissions.set_mode(0o755);
    fs::set_permissions(executable, permissions).expect("make listener fixture executable");
    Command::new(executable)
        .args([command, "--host", "127.0.0.1", "--port", &port.to_string()])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("spawn listener fixture")
}

#[cfg(not(windows))]
fn reserve_loopback_port() -> u16 {
    std::net::TcpListener::bind(("127.0.0.1", 0))
        .expect("reserve loopback port")
        .local_addr()
        .expect("reserved loopback address")
        .port()
}

#[cfg(not(windows))]
fn wait_for_probe(
    kind: ServiceKind,
    port: u16,
    expected_runtime_identity: Option<&serde_json::Value>,
    expected_probe: Probe,
) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if probe_on_port(kind, port, expected_runtime_identity) == expected_probe {
            return;
        }
        thread::sleep(Duration::from_millis(50));
    }
    panic!("fixture on port {port} did not reach {expected_probe:?}");
}

#[test]
fn stale_listener_process_must_match_loopx_command_and_port() {
    let executable = "/fixture/bin/loopx";
    assert!(is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/usr/bin/python3 /fixture/bin/loopx serve-status --global-registry --host 127.0.0.1 --port 8766",
    ));
    assert!(is_expected_loopx_listener_command(
        ServiceKind::Chat,
        executable,
        8767,
        "/usr/bin/python3 -m loopx.cli chat --global-registry --host 127.0.0.1 --port=8767 --no-open",
    ));
    assert!(is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        r#"/opt/loopx/bin/python -c import os\012import runpy\012release_root = os.environ["LOOPX_RELEASE_ROOT"]\012runpy.run_module("loopx.cli", run_name="__main__")\012 --registry /tmp/registry.json serve-status --global-registry --host 127.0.0.1 --port 8766 --limit 80"#,
    ));
    assert!(is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        r#"/opt/loopx/bin/python -c import os\012import runpy\012release_root = os.environ["LOOPX_RELEASE_ROOT"]\012sys.argv[0] = os.path.join(release_root, "scripts", "loopx")\012module = (\012    "loopx.entrypoint"\012    if os.path.isfile(os.path.join(release_root, "loopx", "entrypoint.py"))\012    else "loopx.cli"\012)\012runpy.run_module(module, run_name="__main__")\012 --registry /tmp/registry.json serve-status --global-registry --host 127.0.0.1 --port 8766 --limit 80"#,
    ));
    assert!(is_expected_loopx_listener_command(
        ServiceKind::Chat,
        executable,
        8767,
        r#"/opt/loopx/bin/python -c LOOPX_MANAGED_RELEASE_LAUNCHER_V1 = True\012release_root = os.environ["LOOPX_RELEASE_ROOT"]\012runpy.run_module(next_module, run_name="__main__")\012 --registry /tmp/registry.json chat --global-registry --host 127.0.0.1 --port 8767 --no-open"#,
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/tmp/not-loopx serve-status --port 8766",
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/tmp/not-loopx --config /fixture/bin/loopx serve-status --port 8766",
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/bin/sh -m loopx.cli serve-status --port 8766",
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/usr/bin/python3 /fixture/bin/loopx chat --port 8766",
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        "/usr/bin/python3 /fixture/bin/loopx serve-status --port 8767",
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        r#"/opt/loopx/bin/python -c runpy.run_module("other.cli", run_name="__main__") serve-status --port 8766"#,
    ));
    assert!(!is_expected_loopx_listener_command(
        ServiceKind::Status,
        executable,
        8766,
        r#"/opt/loopx/bin/python -c release_root = os.environ["LOOPX_RELEASE_ROOT"]\012print("loopx.entrypoint")\012runpy.run_module(module, run_name="__main__") serve-status --port 8766"#,
    ));
}

#[test]
fn release_launchers_publish_the_stable_process_fingerprint() {
    let posix_launcher = include_str!("../../../../../scripts/loopx");
    let portable_entry = include_str!("../../../../../scripts/loopx_entry.py");

    assert!(posix_launcher.contains(MANAGED_RELEASE_LAUNCHER_MARKER));
    assert!(portable_entry.contains(MANAGED_RELEASE_LAUNCHER_MARKER));
}

#[test]
fn stale_listener_verification_rejects_the_entire_pid_set_on_mismatch() {
    let executable = "/fixture/bin/loopx";
    let confirmed = ListenerProcess {
        pid: 11,
        command_line: format!("{executable} serve-status --port 8766"),
    };
    assert_eq!(
        verified_loopx_listener_pids(ServiceKind::Status, executable, 8766, &[confirmed])
            .expect("confirmed LoopX listener"),
        vec![11]
    );

    let mixed = [
        ListenerProcess {
            pid: 11,
            command_line: format!("{executable} serve-status --port 8766"),
        },
        ListenerProcess {
            pid: 12,
            command_line: "foreign-server --port 8766".to_string(),
        },
    ];
    let error = verified_loopx_listener_pids(ServiceKind::Status, executable, 8766, &mixed)
        .expect_err("mixed ownership must fail closed");
    assert!(error.to_string().contains("refusing to stop"));
}

#[cfg(not(windows))]
#[test]
fn service_supervisor_reuses_matching_replaces_stale_and_rejects_foreign() {
    let unique = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("clock must follow the Unix epoch")
        .as_nanos();
    let fixture_root = env::temp_dir().join(format!(
        "loopx-service-supervisor-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir_all(&fixture_root).expect("create service supervisor fixture");
    let current_identity = serde_json::json!({
        "schema_version": "loopx_runtime_identity_v1",
        "package_version": "0.5.1",
        "release_id": "current-release",
        "source_revision": "current-revision",
    });

    let matching_port = reserve_loopback_port();
    let matching_executable = fixture_root.join("matching-loopx");
    let matching_payload = serde_json::json!({
        "source": "serve-status",
        "runtime_identity": current_identity,
    })
    .to_string();
    let mut matching = spawn_listener_fixture(
        &matching_executable,
        "serve-status",
        matching_port,
        &matching_payload,
    );
    wait_for_probe(
        ServiceKind::Status,
        matching_port,
        Some(&current_identity),
        Probe::Matching,
    );
    assert!(matching
        .try_wait()
        .expect("matching fixture status")
        .is_none());
    matching.kill().expect("stop matching fixture");
    matching.wait().expect("reap matching fixture");

    let stale_port = reserve_loopback_port();
    let stale_executable = fixture_root.join("loopx");
    let stale_payload = serde_json::json!({
        "source": "serve-status",
        "runtime_identity": {
            "schema_version": "loopx_runtime_identity_v1",
            "package_version": "0.5.0",
            "release_id": "stale-release",
            "source_revision": "stale-revision",
        },
    })
    .to_string();
    let mut stale = spawn_listener_fixture(
        &stale_executable,
        "serve-status",
        stale_port,
        &stale_payload,
    );
    wait_for_probe(
        ServiceKind::Status,
        stale_port,
        Some(&current_identity),
        Probe::Stale,
    );
    let stale_processes = listener_processes(stale_port).expect("inspect stale listener fixture");
    assert!(
        stale_processes
            .iter()
            .all(|process| is_expected_loopx_listener_command(
                ServiceKind::Status,
                stale_executable.to_string_lossy().as_ref(),
                stale_port,
                &process.command_line,
            )),
        "fixture process must classify as LoopX: {stale_processes:?}"
    );
    terminate_stale_listener(
        ServiceKind::Status,
        stale_executable.to_string_lossy().as_ref(),
        stale_port,
    )
    .expect("replace confirmed stale LoopX listener");
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline && stale.try_wait().expect("stale fixture status").is_none() {
        thread::sleep(Duration::from_millis(50));
    }
    assert!(stale
        .try_wait()
        .expect("stale fixture final status")
        .is_some());

    let foreign_port = reserve_loopback_port();
    let foreign_executable = fixture_root.join("foreign-server");
    let mut foreign = spawn_listener_fixture(
        &foreign_executable,
        "serve-status",
        foreign_port,
        r#"{"source":"other"}"#,
    );
    wait_for_probe(
        ServiceKind::Status,
        foreign_port,
        Some(&current_identity),
        Probe::Foreign,
    );
    let error = terminate_stale_listener(
        ServiceKind::Status,
        stale_executable.to_string_lossy().as_ref(),
        foreign_port,
    )
    .expect_err("foreign listener must be rejected");
    assert!(error.to_string().contains("refusing to stop"));
    assert!(foreign
        .try_wait()
        .expect("foreign fixture status")
        .is_none());
    foreign.kill().expect("stop foreign fixture");
    foreign.wait().expect("reap foreign fixture");

    fs::remove_dir_all(&fixture_root).expect("remove service supervisor fixture");
}
