use command_group::{CommandGroup, GroupChild};
use std::{
    env,
    ffi::OsStr,
    fmt, fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

const STARTUP_TIMEOUT: Duration = Duration::from_secs(15);
const PROBE_TIMEOUT: Duration = Duration::from_millis(500);
const MAX_PROBE_RESPONSE_BYTES: u64 = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ServiceKind {
    Status,
    Chat,
}

impl ServiceKind {
    fn label(self) -> &'static str {
        match self {
            Self::Status => "status",
            Self::Chat => "chat",
        }
    }

    fn port(self) -> u16 {
        match self {
            Self::Status => 8766,
            Self::Chat => 8767,
        }
    }

    fn probe_path(self) -> &'static str {
        match self {
            Self::Status => "/",
            Self::Chat => "/api/chat/capabilities",
        }
    }

    fn expected_fingerprint(self) -> (&'static str, &'static str) {
        match self {
            Self::Status => ("source", "serve-status"),
            Self::Chat => ("schema_version", "loopx_chat_capabilities_v1"),
        }
    }

    fn command_args(self) -> Vec<String> {
        match self {
            Self::Status => vec![
                "serve-status",
                "--global-registry",
                "--host",
                "127.0.0.1",
                "--port",
                "8766",
                "--limit",
                "80",
            ],
            Self::Chat => vec![
                "chat",
                "--global-registry",
                "--host",
                "127.0.0.1",
                "--port",
                "8767",
                "--no-open",
            ],
        }
        .into_iter()
        .map(str::to_string)
        .collect()
    }
}

#[derive(Debug, Eq, PartialEq)]
enum Probe {
    Matching,
    Unavailable,
    Foreign,
    Stale,
}

#[derive(Debug)]
pub struct ServiceError(String);

impl fmt::Display for ServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for ServiceError {}

struct OwnedService {
    child: GroupChild,
}

impl OwnedService {
    fn stop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct ServiceSet {
    owned: Vec<OwnedService>,
    /// True when a stale LoopX service was restarted so the running frontend
    /// was transparently moved onto the current installed release.
    pub healed: bool,
}

impl ServiceSet {
    pub fn start() -> Result<Self, ServiceError> {
        let mut services = Self {
            owned: Vec::new(),
            healed: false,
        };
        for kind in [ServiceKind::Status, ServiceKind::Chat] {
            if let Err(error) = services.ensure(kind) {
                services.stop();
                return Err(error);
            }
        }
        Ok(services)
    }

    fn ensure(&mut self, kind: ServiceKind) -> Result<(), ServiceError> {
        let executable = loopx_executable();
        let expected_runtime_identity = runtime_identity_for_executable(&executable);
        let stale_deadline = Instant::now() + STARTUP_TIMEOUT;
        loop {
            match probe(kind, expected_runtime_identity.as_ref()) {
                Probe::Matching => return Ok(()),
                Probe::Foreign => {
                    return Err(ServiceError(format!(
                        "port {} is occupied by a service that is not LoopX {}",
                        kind.port(),
                        kind.label()
                    )));
                }
                Probe::Stale => {
                    // Self-heal: the port is owned by a LoopX service from a
                    // different installed release (for example after a
                    // `loopx update`). Terminate that stale listener and keep
                    // waiting up to the startup timeout so a LaunchAgent-managed
                    // service (KeepAlive + throttle) has time to restart on the
                    // current release; unknown (Foreign) processes keep the
                    // hard error.
                    terminate_stale_listener(kind, &executable, kind.port())?;
                    self.healed = true;
                    if Instant::now() >= stale_deadline {
                        return Err(ServiceError(format!(
                            "port {} is serving LoopX {} from a different installed runtime and could not be restarted",
                            kind.port(),
                            kind.label()
                        )));
                    }
                    thread::sleep(Duration::from_millis(200));
                }
                Probe::Unavailable => break,
            }
        }

        let mut command = Command::new(&executable);
        command
            .args(kind.command_args())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        let child = command.group_spawn().map_err(|error| {
            ServiceError(format!(
                "could not start LoopX {} with `{executable}`: {error}",
                kind.label()
            ))
        })?;
        self.owned.push(OwnedService { child });

        let deadline = Instant::now() + STARTUP_TIMEOUT;
        while Instant::now() < deadline {
            match probe(kind, expected_runtime_identity.as_ref()) {
                Probe::Matching => return Ok(()),
                Probe::Foreign => {
                    return Err(ServiceError(format!(
                        "LoopX {} startup reached an unexpected service on port {}",
                        kind.label(),
                        kind.port()
                    )));
                }
                Probe::Stale => {
                    terminate_stale_listener(kind, &executable, kind.port())?;
                    self.healed = true;
                    thread::sleep(Duration::from_millis(200));
                }
                Probe::Unavailable => thread::sleep(Duration::from_millis(100)),
            }
        }
        Err(ServiceError(format!(
            "LoopX {} did not become ready on port {}",
            kind.label(),
            kind.port()
        )))
    }

    pub fn stop(&mut self) {
        for service in self.owned.iter_mut().rev() {
            service.stop();
        }
        self.owned.clear();
    }
}

impl Drop for ServiceSet {
    fn drop(&mut self) {
        self.stop();
    }
}

#[derive(Debug, Eq, PartialEq)]
struct ListenerProcess {
    pid: i32,
    command_line: String,
}

#[derive(Debug, Eq, PartialEq)]
enum LoopxProcessInvocation {
    DirectExecutable,
    PythonModule,
    ManagedReleaseLauncher,
}

/// Stable process fingerprint emitted by release launchers. The Desktop must
/// not couple stale-service recovery to the launcher's current Python module:
/// changing `loopx.cli` to `loopx.entrypoint` must not strand an older daemon.
const MANAGED_RELEASE_LAUNCHER_MARKER: &str = "LOOPX_MANAGED_RELEASE_LAUNCHER_V1";
const LEGACY_CLI_LAUNCHER_MARKER: &str = r#"runpy.run_module("loopx.cli", run_name="__main__")"#;
const ENTRYPOINT_LAUNCHER_MODULE_MARKER: &str = r#""loopx.entrypoint""#;
const DYNAMIC_MODULE_LAUNCH_MARKER: &str = r#"runpy.run_module(module, run_name="__main__")"#;
const RELEASE_ARGV_ZERO_MARKER: &str =
    r#"sys.argv[0] = os.path.join(release_root, "scripts", "loopx")"#;

fn terminate_stale_listener(
    kind: ServiceKind,
    loopx_executable: &str,
    port: u16,
) -> Result<(), ServiceError> {
    #[cfg(not(windows))]
    {
        let processes = listener_processes(port)?;
        let pids = verified_loopx_listener_pids(kind, loopx_executable, port, &processes)?;
        for pid in pids {
            let current = inspect_process(pid, port)?;
            verified_loopx_listener_pids(kind, loopx_executable, port, &[current])?;
            let status = Command::new("kill")
                .arg(pid.to_string())
                .status()
                .map_err(|error| {
                    ServiceError(format!(
                        "could not stop stale LoopX {} listener on port {port}: {error}",
                        kind.label()
                    ))
                })?;
            if !status.success() {
                return Err(ServiceError(format!(
                    "could not stop stale LoopX {} listener on port {port}",
                    kind.label()
                )));
            }
        }
        Ok(())
    }
    #[cfg(windows)]
    {
        let _ = (kind, loopx_executable, port);
        Err(ServiceError(format!(
            "port {port} is serving stale LoopX {}; automatic replacement is unavailable on Windows",
            kind.label()
        )))
    }
}

#[cfg(not(windows))]
fn listener_processes(port: u16) -> Result<Vec<ListenerProcess>, ServiceError> {
    let selector = format!("-iTCP:{port}");
    let output = Command::new("lsof")
        .args(["-nP", "-t", "-a", selector.as_str(), "-sTCP:LISTEN"])
        .output()
        .map_err(|error| {
            ServiceError(format!(
                "could not inspect the listener on port {port}: {error}"
            ))
        })?;
    if !output.status.success() {
        return Err(ServiceError(format!(
            "could not identify the stale LoopX listener on port {port}"
        )));
    }

    let mut pids = Vec::new();
    for line in String::from_utf8_lossy(&output.stdout).lines() {
        let pid = line.trim().parse::<i32>().map_err(|_| {
            ServiceError(format!(
                "could not parse the listener process on port {port}"
            ))
        })?;
        if !pids.contains(&pid) {
            pids.push(pid);
        }
    }
    if pids.is_empty() {
        return Err(ServiceError(format!(
            "could not identify the stale LoopX listener on port {port}"
        )));
    }

    pids.into_iter()
        .map(|pid| inspect_process(pid, port))
        .collect()
}

#[cfg(not(windows))]
fn inspect_process(pid: i32, port: u16) -> Result<ListenerProcess, ServiceError> {
    let output = Command::new("ps")
        .args(["-ww", "-p", &pid.to_string(), "-o", "args="])
        .output()
        .map_err(|error| {
            ServiceError(format!(
                "could not inspect the stale listener process on port {port}: {error}"
            ))
        })?;
    let command_line = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if !output.status.success() || command_line.is_empty() {
        return Err(ServiceError(format!(
            "could not inspect the stale listener process on port {port}"
        )));
    }
    Ok(ListenerProcess { pid, command_line })
}

fn verified_loopx_listener_pids(
    kind: ServiceKind,
    loopx_executable: &str,
    port: u16,
    processes: &[ListenerProcess],
) -> Result<Vec<i32>, ServiceError> {
    if processes.is_empty()
        || processes.iter().any(|process| {
            !is_expected_loopx_listener_command(kind, loopx_executable, port, &process.command_line)
        })
    {
        return Err(ServiceError(format!(
            "refusing to stop the listener on port {port} because its process is not a confirmed LoopX {} command",
            kind.label()
        )));
    }
    Ok(processes.iter().map(|process| process.pid).collect())
}

fn is_expected_loopx_listener_command(
    kind: ServiceKind,
    loopx_executable: &str,
    port: u16,
    command_line: &str,
) -> bool {
    let arguments = command_line.split_ascii_whitespace().collect::<Vec<_>>();
    let is_loopx =
        classify_loopx_process_invocation(loopx_executable, command_line, &arguments).is_some();
    let expected_command = match kind {
        ServiceKind::Status => "serve-status",
        ServiceKind::Chat => "chat",
    };
    let has_command = arguments.contains(&expected_command);
    let expected_port = port.to_string();
    let has_port = arguments
        .windows(2)
        .any(|pair| pair[0] == "--port" && pair[1] == expected_port)
        || arguments
            .iter()
            .any(|argument| *argument == format!("--port={port}"));
    is_loopx && has_command && has_port
}

fn classify_loopx_process_invocation(
    loopx_executable: &str,
    command_line: &str,
    arguments: &[&str],
) -> Option<LoopxProcessInvocation> {
    let interpreter_is_python = arguments
        .first()
        .and_then(|argument| Path::new(argument).file_name())
        .and_then(OsStr::to_str)
        .is_some_and(|name| name.to_ascii_lowercase().starts_with("python"));
    let executable_is_direct = arguments
        .first()
        .is_some_and(|argument| paths_refer_to_same_file(argument, loopx_executable))
        || (interpreter_is_python
            && arguments
                .get(1)
                .is_some_and(|argument| paths_refer_to_same_file(argument, loopx_executable)));
    if executable_is_direct {
        return Some(LoopxProcessInvocation::DirectExecutable);
    }
    if interpreter_is_python
        && arguments
            .windows(2)
            .any(|pair| pair == ["-m", "loopx.cli"] || pair == ["-m", "loopx.entrypoint"])
    {
        return Some(LoopxProcessInvocation::PythonModule);
    }

    if interpreter_is_python
        && arguments.contains(&"-c")
        && is_managed_release_launcher(command_line)
    {
        return Some(LoopxProcessInvocation::ManagedReleaseLauncher);
    }
    None
}

fn is_managed_release_launcher(command_line: &str) -> bool {
    if !command_line.contains("LOOPX_RELEASE_ROOT") {
        return false;
    }

    // New release launchers carry an entrypoint-independent marker. Preserve
    // both historical templates so an App installed after this fix can still
    // replace daemons started before the marker existed.
    command_line.contains(MANAGED_RELEASE_LAUNCHER_MARKER)
        || command_line.contains(LEGACY_CLI_LAUNCHER_MARKER)
        || (command_line.contains(ENTRYPOINT_LAUNCHER_MODULE_MARKER)
            && command_line.contains(DYNAMIC_MODULE_LAUNCH_MARKER)
            && command_line.contains(RELEASE_ARGV_ZERO_MARKER))
}

fn paths_refer_to_same_file(candidate: &str, expected: &str) -> bool {
    candidate == expected
        || fs::canonicalize(candidate)
            .ok()
            .zip(fs::canonicalize(expected).ok())
            .is_some_and(|(candidate, expected)| candidate == expected)
}

fn loopx_executable() -> String {
    if let Ok(configured) = env::var("LOOPX_BIN") {
        if !configured.trim().is_empty() {
            return resolve_executable_path(&configured, env::var_os("PATH").as_deref())
                .unwrap_or_else(|| PathBuf::from(configured))
                .to_string_lossy()
                .into_owned();
        }
    }
    let mut candidates = vec![
        PathBuf::from("/usr/local/bin/loopx"),
        PathBuf::from("/opt/homebrew/bin/loopx"),
    ];
    if let Some(home) = env::var_os("HOME") {
        candidates.insert(0, PathBuf::from(home).join(".local/bin/loopx"));
    }
    candidates
        .into_iter()
        .find(|candidate| candidate.is_file())
        .or_else(|| resolve_executable_path("loopx", env::var_os("PATH").as_deref()))
        .map(|candidate| candidate.to_string_lossy().into_owned())
        .unwrap_or_else(|| "loopx".to_string())
}

fn resolve_executable_path(executable: &str, search_path: Option<&OsStr>) -> Option<PathBuf> {
    let requested = PathBuf::from(executable);
    if requested.components().count() > 1 {
        return requested.is_file().then_some(requested);
    }
    let search_path = search_path?;
    for directory in env::split_paths(search_path) {
        let candidate = directory.join(&requested);
        if candidate.is_file() {
            return Some(candidate);
        }
        #[cfg(windows)]
        if requested.extension().is_none() {
            for extension in ["COM", "EXE", "BAT", "CMD"] {
                let candidate = directory.join(format!("{executable}.{extension}"));
                if candidate.is_file() {
                    return Some(candidate);
                }
            }
        }
    }
    None
}

fn runtime_identity_from_manifest(manifest: &serde_json::Value) -> Option<serde_json::Value> {
    let release_id = manifest.get("release_id")?.as_str()?;
    let package_version = manifest.get("package")?.get("version")?.as_str()?;
    let source_revision = manifest
        .get("source")
        .and_then(|source| source.get("git_commit"))
        .and_then(serde_json::Value::as_str);
    Some(serde_json::json!({
        "schema_version": "loopx_runtime_identity_v1",
        "package_version": package_version,
        "release_id": release_id,
        "source_revision": source_revision,
    }))
}

fn runtime_identity_for_executable(executable: &str) -> Option<serde_json::Value> {
    runtime_identity_for_executable_with_path(executable, env::var_os("PATH").as_deref())
}

fn runtime_identity_for_executable_with_path(
    executable: &str,
    search_path: Option<&OsStr>,
) -> Option<serde_json::Value> {
    let resolved = resolve_executable_path(executable, search_path)?;
    let canonical = fs::canonicalize(resolved).ok()?;
    let release_root = canonical.parent()?.parent()?;
    let manifest = fs::read_to_string(Path::new(release_root).join("release.json")).ok()?;
    let payload = serde_json::from_str::<serde_json::Value>(&manifest).ok()?;
    runtime_identity_from_manifest(&payload)
}

fn probe(kind: ServiceKind, expected_runtime_identity: Option<&serde_json::Value>) -> Probe {
    probe_on_port(kind, kind.port(), expected_runtime_identity)
}

fn probe_on_port(
    kind: ServiceKind,
    port: u16,
    expected_runtime_identity: Option<&serde_json::Value>,
) -> Probe {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = match TcpStream::connect_timeout(&address, PROBE_TIMEOUT) {
        Ok(stream) => stream,
        Err(_) => return Probe::Unavailable,
    };
    let _ = stream.set_read_timeout(Some(PROBE_TIMEOUT));
    let _ = stream.set_write_timeout(Some(PROBE_TIMEOUT));
    let request = format!(
        "GET {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n",
        kind.probe_path(),
        port
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return Probe::Foreign;
    }
    let mut response = String::new();
    if stream
        .take(MAX_PROBE_RESPONSE_BYTES + 1)
        .read_to_string(&mut response)
        .is_err()
        || response.len() as u64 > MAX_PROBE_RESPONSE_BYTES
    {
        return Probe::Foreign;
    }
    classify_response(kind, &response, expected_runtime_identity)
}

fn classify_response(
    kind: ServiceKind,
    response: &str,
    expected_runtime_identity: Option<&serde_json::Value>,
) -> Probe {
    let Some((headers, body)) = response.split_once("\r\n\r\n") else {
        return Probe::Foreign;
    };
    let Some(status_line) = headers.lines().next() else {
        return Probe::Foreign;
    };
    let mut status_parts = status_line.split_ascii_whitespace();
    let version = status_parts.next();
    let status = status_parts.next();
    if !matches!(version, Some("HTTP/1.0" | "HTTP/1.1")) || status != Some("200") {
        return Probe::Foreign;
    }

    let Ok(payload) = serde_json::from_str::<serde_json::Value>(body) else {
        return Probe::Foreign;
    };
    let (field, expected) = kind.expected_fingerprint();
    if payload
        .as_object()
        .and_then(|object| object.get(field))
        .and_then(serde_json::Value::as_str)
        == Some(expected)
    {
        if let Some(expected) = expected_runtime_identity {
            if payload.get("runtime_identity") != Some(expected) {
                return Probe::Stale;
            }
        }
        return Probe::Matching;
    }
    Probe::Foreign
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn service_commands_stay_loopback_and_global() {
        let status = ServiceKind::Status.command_args();
        let chat = ServiceKind::Chat.command_args();

        assert!(status
            .windows(2)
            .any(|pair| pair == ["--host", "127.0.0.1"]));
        assert!(chat.windows(2).any(|pair| pair == ["--host", "127.0.0.1"]));
        assert!(status
            .iter()
            .any(|argument| argument == "--global-registry"));
        assert!(chat.iter().any(|argument| argument == "--global-registry"));
        assert!(chat.iter().any(|argument| argument == "--no-open"));
    }

    #[test]
    fn configured_loopx_binary_takes_precedence() {
        std::env::set_var("LOOPX_BIN", "/fixture/loopx");
        assert_eq!(loopx_executable(), "/fixture/loopx");
        std::env::remove_var("LOOPX_BIN");
    }

    #[test]
    fn service_fingerprints_reject_unknown_responses() {
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"source\":\"other\"}",
                None,
            ),
            Probe::Foreign
        );
        assert_eq!(
            classify_response(
                ServiceKind::Chat,
                "HTTP/1.1 200 OK\r\n\r\n{\"schema_version\":\"other\"}",
                None,
            ),
            Probe::Foreign
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\nX-LoopX: {\"source\":\"serve-status\"}\r\n\r\n{\"source\":\"other\"}",
                None,
            ),
            Probe::Foreign
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"nested\":{\"source\":\"serve-status\"}}",
                None,
            ),
            Probe::Foreign
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 201 Created\r\n\r\n{\"source\":\"serve-status\"}",
                None,
            ),
            Probe::Foreign
        );
    }

    #[test]
    fn service_fingerprints_accept_only_expected_loopx_payloads() {
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"source\": \"serve-status\"}",
                None,
            ),
            Probe::Matching
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.0 200 OK\r\n\r\n{\n  \"source\": \"serve-status\"\n}",
                None,
            ),
            Probe::Matching
        );
        assert_eq!(
            classify_response(
                ServiceKind::Chat,
                "HTTP/1.1 200 OK\r\n\r\n{\"schema_version\":\"loopx_chat_capabilities_v1\"}",
                None,
            ),
            Probe::Matching
        );
    }

    #[test]
    fn service_fingerprints_reject_stale_loopx_runtime() {
        let expected = serde_json::json!({
            "schema_version": "loopx_runtime_identity_v1",
            "package_version": "0.5.1",
            "release_id": "new-release",
            "source_revision": "new-revision",
        });
        assert_eq!(
            classify_response(
                ServiceKind::Chat,
                "HTTP/1.1 200 OK\r\n\r\n{\"schema_version\":\"loopx_chat_capabilities_v1\",\"runtime_identity\":{\"schema_version\":\"loopx_runtime_identity_v1\",\"package_version\":\"0.5.0\",\"release_id\":\"old-release\",\"source_revision\":\"old-revision\"}}",
                Some(&expected),
            ),
            Probe::Stale
        );
        assert_eq!(
            classify_response(
                ServiceKind::Status,
                "HTTP/1.1 200 OK\r\n\r\n{\"source\":\"serve-status\"}",
                Some(&expected),
            ),
            Probe::Stale
        );
    }

    #[test]
    fn manifest_runtime_identity_is_public_and_exact() {
        let manifest = serde_json::json!({
            "release_id": "20260821T164921Z",
            "package": {"version": "0.5.1"},
            "source": {"git_commit": "62647e2e299d"},
        });

        assert_eq!(
            runtime_identity_from_manifest(&manifest),
            Some(serde_json::json!({
                "schema_version": "loopx_runtime_identity_v1",
                "package_version": "0.5.1",
                "release_id": "20260821T164921Z",
                "source_revision": "62647e2e299d",
            }))
        );
    }

    #[test]
    fn path_resolved_loopx_binary_keeps_runtime_fence_enabled() {
        let unique = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock must follow the Unix epoch")
            .as_nanos();
        let release_root = env::temp_dir().join(format!(
            "loopx-runtime-identity-{}-{unique}",
            std::process::id()
        ));
        let scripts_dir = release_root.join("scripts");
        fs::create_dir_all(&scripts_dir).expect("fixture scripts directory");
        let executable_name = if cfg!(windows) { "loopx.EXE" } else { "loopx" };
        fs::write(scripts_dir.join(executable_name), b"fixture").expect("fixture loopx executable");
        fs::write(
            release_root.join("release.json"),
            r#"{"release_id":"path-release","package":{"version":"0.5.1"},"source":{"git_commit":"path-revision"}}"#,
        )
        .expect("fixture release manifest");

        let identity =
            runtime_identity_for_executable_with_path("loopx", Some(scripts_dir.as_os_str()));
        fs::remove_dir_all(&release_root).expect("remove runtime identity fixture");

        assert_eq!(
            identity,
            Some(serde_json::json!({
                "schema_version": "loopx_runtime_identity_v1",
                "package_version": "0.5.1",
                "release_id": "path-release",
                "source_revision": "path-revision",
            }))
        );
    }
}

#[cfg(test)]
#[path = "services_tests.rs"]
mod supervisor_tests;
