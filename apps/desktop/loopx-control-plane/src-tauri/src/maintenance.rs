//! App-owned update transaction. No browser-supplied commands, paths or URLs.
use crate::bundled_runtime;
use serde_json::{json, Value};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Duration,
};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Default)]
pub struct Maintenance {
    busy: AtomicBool,
    supervision: tauri::async_runtime::Mutex<()>,
    snapshot: Mutex<Value>,
    pending: Mutex<Option<(String, Update)>>,
    last_failure: Mutex<Value>,
    install_journal_discarded: AtomicBool,
}
impl Maintenance {
    fn acquire(&self) -> Result<BusyGuard<'_>, String> {
        self.busy
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| "update_busy")?;
        Ok(BusyGuard(&self.busy))
    }
    fn publish(&self, phase: &str, details: Value) -> Value {
        let value = json!({"phase": phase, "details": details});
        if matches!(phase, "error" | "runtime_required" | "service_error") {
            *self.last_failure.lock().unwrap() = value.clone();
        }
        *self.snapshot.lock().unwrap() = value.clone();
        value
    }

    // Service supervision and maintenance must never replace/start different
    // runtime versions concurrently. A failed connection is not an install.
    fn reconcile_services<T>(
        &self,
        start: impl FnOnce() -> Result<T, String>,
    ) -> Result<Option<T>, String> {
        if self.busy.load(Ordering::Acquire) {
            return Ok(None);
        }
        let Ok(_guard) = self.supervision.try_lock() else {
            return Ok(None);
        };
        if self.busy.load(Ordering::Acquire) {
            return Ok(None);
        }
        let phase = self.snapshot.lock().unwrap()["phase"]
            .as_str()
            .unwrap_or("idle")
            .to_string();
        if phase == "restart_required" {
            return Ok(None);
        }
        let observing_update = matches!(phase.as_str(), "connecting" | "service_error");
        match start() {
            Ok(services) => {
                if observing_update {
                    self.publish("ready", json!({}));
                }
                Ok(Some(services))
            }
            Err(error) => {
                if observing_update {
                    self.publish("service_error", json!({"code":"service_start_failed"}));
                }
                Err(error)
            }
        }
    }
}
struct BusyGuard<'a>(&'a AtomicBool);
impl Drop for BusyGuard<'_> {
    fn drop(&mut self) {
        self.0.store(false, Ordering::Release);
    }
}

fn allow_action(phase: &str, action: &str) -> Result<(), String> {
    if phase == "restart_required" && action != "restart" {
        return Err("restart_required".into());
    }
    Ok(())
}
fn endpoint(channel: &str) -> Result<tauri::Url, String> {
    Ok(match channel {
        "stable" => "https://github.com/huangruiteng/loopx/releases/download/desktop-stable/desktop-updater.json",
        "main" => "https://github.com/huangruiteng/loopx/releases/download/desktop-main/desktop-updater.json",
        _ => return Err("invalid_update_channel".into()),
    }.parse().unwrap())
}

fn check_error(error: tauri_plugin_updater::Error) -> &'static str {
    use tauri_plugin_updater::Error;
    match error {
        // The plugin discards non-success HTTP status codes, so this cannot
        // distinguish an unpublished feed (404) from an unavailable server.
        Error::ReleaseNotFound => "update_feed_unavailable",
        Error::Serialization(_) => "update_feed_invalid",
        Error::TargetNotFound(_) | Error::TargetsNotFound(_) => "update_platform_unavailable",
        Error::Reqwest(error) if error.is_timeout() => "update_check_timeout",
        Error::Reqwest(error) if error.is_decode() => "update_feed_invalid",
        Error::Reqwest(_) => "update_network_failed",
        _ => "update_check_failed",
    }
}
#[tauri::command]
pub fn desktop_update_status(app: AppHandle, state: State<'_, Maintenance>) -> Value {
    let snapshot = state.snapshot.lock().unwrap().clone();
    let last_failure = state.last_failure.lock().unwrap().clone();
    json!({"state": snapshot, "last_failure": last_failure, "app_version": app.package_info().version.to_string(), "runtime": bundled_runtime::identity(&app).ok(), "rollback_available": crate::update_backup::available(&app)})
}
#[tauri::command]
pub async fn desktop_update(
    app: AppHandle,
    action: String,
    channel: String,
) -> Result<Value, String> {
    if cfg!(dev) || !cfg!(target_os = "macos") {
        return Err("platform_update_not_supported".into());
    }
    let url = endpoint(&channel)?;
    if !matches!(
        action.as_str(),
        "check" | "apply" | "repair" | "restart" | "rollback"
    ) {
        return Err("invalid_update_action".into());
    }
    let state = app.state::<Maintenance>();
    let _guard = state.acquire()?;
    // An explicit action takes priority over the next retry, while awaiting
    // the current bounded service attempt instead of failing with update_busy.
    let _supervision = state.supervision.lock().await;
    allow_action(
        state.snapshot.lock().unwrap()["phase"]
            .as_str()
            .unwrap_or("idle"),
        &action,
    )?;
    if action == "restart" {
        if state.snapshot.lock().unwrap()["phase"] != "restart_required" {
            return Err("restart_not_ready".into());
        }
        app.restart();
    }
    let outcome = perform(&app, &action, &channel, url).await;
    if let Err(error) = &outcome {
        state.publish_failure(error, &channel);
    }
    outcome
}
impl Maintenance {
    // App-install failures discard the stale continuation journal (see
    // perform); surface that in the failure diagnostics exactly once.
    fn publish_failure(&self, code: &str, channel: &str) -> Value {
        let mut details = json!({"code": code, "channel": channel});
        if code == "app_install_failed" {
            details["journal_discarded"] = self
                .install_journal_discarded
                .swap(false, Ordering::AcqRel)
                .into();
        }
        self.publish("error", details)
    }
}
async fn perform(
    app: &AppHandle,
    action: &str,
    channel: &str,
    url: tauri::Url,
) -> Result<Value, String> {
    let state = app.state::<Maintenance>();
    if action == "check" {
        state.publish("checking", json!({"channel":channel}));
        *state.pending.lock().unwrap() = None;
        let main_channel = channel == "main";
        let update = app
            .updater_builder()
            .version_comparator(move |current, remote| {
                if main_channel && !current.pre.as_str().starts_with("main.") {
                    remote.version.pre.as_str().starts_with("main.")
                } else {
                    remote.version > current
                }
            })
            .endpoints(vec![url])
            .map_err(|_| "update_unavailable")?
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "update_unavailable")?
            .check()
            .await
            .map_err(check_error)?;
        let details = json!({"channel":channel,"version":update.as_ref().map(|v| &v.version),"current_version":app.package_info().version.to_string()});
        let phase = if update.is_some() {
            "available"
        } else {
            "up_to_date"
        };
        *state.pending.lock().unwrap() = update.map(|u| (channel.to_string(), u));
        return Ok(state.publish(phase, details));
    }
    if action == "rollback" {
        state.publish("installing_app", json!({}));
        let handle = app.clone();
        tauri::async_runtime::spawn_blocking(move || crate::update_backup::restore(&handle))
            .await
            .map_err(|_| "rollback_failed")??;
        return Ok(state.publish("restart_required", json!({})));
    }
    if action == "repair" {
        state.publish("installing_runtime", json!({}));
        let handle = app.clone();
        tauri::async_runtime::spawn_blocking(move || {
            bundled_runtime::record_pending(
                &handle,
                &handle.package_info().version.to_string(),
                "bundled",
            )?;
            bundled_runtime::resume_pending(&handle).map(|_| ())
        })
        .await
        .map_err(|_| "runtime_install_failed")??;
        return Ok(state.publish("restart_required", json!({})));
    }
    let update = state
        .pending
        .lock()
        .unwrap()
        .as_ref()
        .filter(|(c, _)| c == channel)
        .map(|(_, u)| u.clone())
        .ok_or("update_check_required")?;
    state.publish("downloading", json!({"version":update.version}));
    let mut received = 0u64;
    let bytes = update
        .download(
            |chunk, total| {
                received += chunk as u64;
                state.publish(
                    "downloading",
                    json!({"received":received,"total":total,"version":update.version}),
                );
            },
            || {},
        )
        .await
        .map_err(|_| "update_download_or_signature_failed")?;
    // Archive signature is now verified. Persist continuation before replacement.
    state.publish("installing_app", json!({"version":update.version}));
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || crate::update_backup::prepare(&handle))
        .await
        .map_err(|_| "backup_failed")??;
    bundled_runtime::record_pending(app, &update.version, channel)?;
    let target = update.version.clone();
    // A JoinError (task panic/cancellation) is an unknown-state failure just
    // like an install error: both must clear the same verification below, so
    // neither returns ahead of the recovery decision.
    let installed: Result<(), String> =
        tauri::async_runtime::spawn_blocking(move || update.install(bytes))
            .await
            .map_err(|_| "app_install_failed".to_string())
            .and_then(|result| result.map_err(|_| "app_install_failed".to_string()));
    if installed.is_err() {
        // The pinned macOS installer renames the old App away before moving
        // the new one in, so a failed install does not by itself prove the
        // previously installed App is still in place. Only a verified
        // previous App (bundle present, runtime still pairing with it) may
        // discard the journal and promise a safe restart; anything else keeps
        // the journal and surfaces the distinct recovery state so the
        // verified backup remains the rollback path.
        let (code, may_discard_journal) = install_failure_recovery(
            failed_install_left_previous_app_usable(app),
        );
        if may_discard_journal {
            state.install_journal_discarded.store(
                matches!(bundled_runtime::discard_journal(app), Ok(true) | Ok(false)),
                Ordering::Release,
            );
        }
        return Err(code.into());
    }
    *state.pending.lock().unwrap() = None;
    Ok(state.publish("restart_required", json!({"version":target})))
}

// A safe-restart promise after a failed app replacement requires the running
// App's bundle to still be present -- the pinned macOS updater's install_inner
// performs rename(old App -> temporary) before rename(new App -> original), so
// the second rename failing leaves the original location empty -- and the
// installed runtime to still pair with this App's bundled snapshot. Reuses the
// rollback boundary's bundle verification instead of a second layout rule.
fn failed_install_left_previous_app_usable(app: &AppHandle) -> bool {
    crate::update_backup::app_bundle().is_ok()
        && runtime_revisions_pair(
            bundled_runtime::identity(app).ok().as_ref(),
            crate::services::runtime_identity_for_executable(&crate::services::loopx_executable())
                .as_ref(),
        )
}

// Recovery classification for a failed app replacement: only a verified
// previous App may discard the journal and carry the safe-restart promise;
// an unverified failure keeps the journal under the distinct incomplete code
// so the recovery panel keeps offering the verified backup rollback.
fn install_failure_recovery(previous_app_usable: bool) -> (&'static str, bool) {
    if previous_app_usable {
        ("app_install_failed", true)
    } else {
        ("app_install_incomplete", false)
    }
}
pub fn resume(app: &AppHandle) -> Result<(), String> {
    let result = resume_runtime(app);
    if let Err(error) = &result {
        if error != "runtime_setup_required" {
            app.state::<Maintenance>()
                .publish("error", json!({"code":error}));
        }
    }
    result
}

// True when the installed runtime's source_revision equals the bundled
// snapshot's. Any missing identity counts as unpaired: fail closed.
fn runtime_revisions_pair(bundled: Option<&Value>, installed: Option<&Value>) -> bool {
    match (bundled, installed) {
        (Some(bundled), Some(installed)) => {
            bundled["source_revision"] == installed["source_revision"]
        }
        _ => false,
    }
}

// Shared App/runtime pairing gate for both release startup entrances: the
// journal-absent path and the start that just discarded a stale journal may
// connect only when the installed runtime pairs with the bundled snapshot.
fn require_paired_runtime(state: &Maintenance, app: &AppHandle) -> Result<(), String> {
    let bundled = bundled_runtime::identity(app)?;
    let installed = crate::services::runtime_identity_for_executable(
        &crate::services::loopx_executable(),
    );
    if !runtime_revisions_pair(Some(&bundled), installed.as_ref()) {
        state.publish(
            "runtime_required",
            json!({
                "code":"runtime_setup_required",
                "installed_identity_available": installed.is_some(),
                "revision_matches": false
            }),
        );
        return Err("runtime_setup_required".into());
    }
    Ok(())
}

// Startup decision after the journal has been resolved. The pairing gate is
// injected so headless tests drive the exact release startup branches: a
// discarded stale journal may connect only through the same gate the
// no-journal entrance enforces, and a failed gate leaves services stopped.
fn startup_after_resume(
    state: &Maintenance,
    resolved: Result<bundled_runtime::Resume, String>,
    pairing_gate: impl FnOnce() -> Result<(), String>,
) -> Result<(), String> {
    match resolved {
        Ok(bundled_runtime::Resume::Applied) | Ok(bundled_runtime::Resume::Absent) => {
            state.publish("connecting", json!({}));
            Ok(())
        }
        Ok(bundled_runtime::Resume::StaleDiscarded) => {
            pairing_gate()?;
            state.publish("connecting", json!({}));
            Ok(())
        }
        Err(error) => {
            state.publish("error", json!({"code":error}));
            Err(error)
        }
    }
}

fn resume_runtime(app: &AppHandle) -> Result<(), String> {
    // Development intentionally pairs a live frontend with a developer-selected
    // runtime; it must neither replace itself nor force release installation.
    if cfg!(dev) || !cfg!(target_os = "macos") {
        return Ok(());
    }
    let state = app.state::<Maintenance>();
    let _guard = state.acquire()?;
    if !bundled_runtime::journal(app)?.exists() {
        return require_paired_runtime(&state, app);
    }
    state.publish("installing_runtime", json!({}));
    let resolved = bundled_runtime::resume_pending(app);
    startup_after_resume(&state, resolved, || require_paired_runtime(&state, app))
}
pub fn start_services(app: &AppHandle) -> Result<Option<crate::services::ServiceSet>, String> {
    app.state::<Maintenance>()
        .reconcile_services(|| crate::services::ServiceSet::start().map_err(|e| e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn diagnostics_retain_failure_after_successful_update_check() {
        let state = Maintenance::default();
        let failure = state.publish("error", json!({"code":"runtime_install_exit_23"}));
        state.publish("checking", json!({}));
        state.publish("up_to_date", json!({}));
        assert_eq!(*state.last_failure.lock().unwrap(), failure);
        let next = state.publish("runtime_required", json!({"code":"runtime_setup_required"}));
        assert_eq!(*state.last_failure.lock().unwrap(), next);
    }
    #[test]
    fn check_failures_preserve_actionable_categories_without_diagnostics() {
        use tauri_plugin_updater::Error;
        assert_eq!(
            check_error(Error::ReleaseNotFound),
            "update_feed_unavailable"
        );
        assert_eq!(
            check_error(Error::TargetNotFound("private-target".into())),
            "update_platform_unavailable"
        );
        assert_eq!(
            check_error(Error::Network("private-diagnostic".into())),
            "update_check_failed"
        );
        let invalid = serde_json::from_str::<Value>("invalid").unwrap_err();
        assert_eq!(
            check_error(Error::Serialization(invalid)),
            "update_feed_invalid"
        );
    }
    #[test]
    fn transaction_is_singleflight_and_released_on_unwind() {
        let state = Maintenance::default();
        let guard = state.acquire().unwrap();
        assert!(state.acquire().is_err());
        drop(guard);
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = state.acquire().unwrap();
            panic!("simulated task failure");
        }));
        assert!(state.acquire().is_ok());
    }
    #[test]
    fn replaced_app_requires_restart_before_another_transaction() {
        for action in ["check", "apply", "repair", "rollback"] {
            assert!(allow_action("restart_required", action).is_err());
        }
        assert!(allow_action("restart_required", "restart").is_ok());
    }
    #[test]
    fn endpoints_are_closed_and_https() {
        assert_eq!(endpoint("main").unwrap().scheme(), "https");
        assert_eq!(endpoint("stable").unwrap().host_str(), Some("github.com"));
        assert!(endpoint("https://example.com").is_err());
        assert!(endpoint("main;whoami").is_err());
    }
    #[test]
    fn status_survives_webview_reload() {
        let state = Maintenance::default();
        state.publish("downloading", json!({"received":12,"total":24}));
        assert_eq!(state.snapshot.lock().unwrap()["details"]["received"], 12);
    }

    #[test]
    fn service_failure_releases_recovery_and_later_success_is_ready() {
        let state = Maintenance::default();
        state.publish("connecting", json!({}));
        assert!(state
            .reconcile_services::<()>(|| Err("occupied port".into()))
            .is_err());
        assert_eq!(state.snapshot.lock().unwrap()["phase"], "service_error");
        assert!(
            state.acquire().is_ok(),
            "recovery transaction must be available"
        );
        assert_eq!(state.reconcile_services(|| Ok(())).unwrap(), Some(()));
        assert_eq!(state.snapshot.lock().unwrap()["phase"], "ready");
    }

    #[test]
    fn service_retry_cannot_race_maintenance_or_restart() {
        let state = Maintenance::default();
        let guard = state.acquire().unwrap();
        assert_eq!(
            state
                .reconcile_services::<()>(|| panic!("must not start"))
                .unwrap(),
            None
        );
        drop(guard);
        state.publish("restart_required", json!({}));
        assert_eq!(
            state
                .reconcile_services::<()>(|| panic!("must not start"))
                .unwrap(),
            None
        );
    }

    #[test]
    fn install_failures_report_journal_discard_exactly_once() {
        let state = Maintenance::default();
        state.install_journal_discarded.store(true, Ordering::Release);
        let failure = state.publish_failure("app_install_failed", "stable");
        assert_eq!(failure["details"]["journal_discarded"], true);
        // The diagnostics flag is consumed with the failure it describes.
        let repeat = state.publish_failure("app_install_failed", "stable");
        assert_eq!(repeat["details"]["journal_discarded"], false);
    }

    #[test]
    fn unrelated_failures_do_not_report_journal_discard() {
        let state = Maintenance::default();
        state.install_journal_discarded.store(true, Ordering::Release);
        let failure = state.publish_failure("update_network_failed", "stable");
        assert!(failure["details"].get("journal_discarded").is_none());
        // Unrelated failures leave the flag for the install failure that owns it.
        let install = state.publish_failure("app_install_failed", "stable");
        assert_eq!(install["details"]["journal_discarded"], true);
    }

    #[test]
    fn pairing_requires_both_identities_to_agree() {
        let bundled = |revision: &str| json!({"source_revision": revision});
        assert!(runtime_revisions_pair(
            Some(&bundled("a")),
            Some(&bundled("a"))
        ));
        assert!(!runtime_revisions_pair(
            Some(&bundled("a")),
            Some(&bundled("b"))
        ));
        // A missing installed runtime identity (or a missing bundle identity)
        // is never paired: fail closed.
        assert!(!runtime_revisions_pair(Some(&bundled("a")), None));
        assert!(!runtime_revisions_pair(None, Some(&bundled("a"))));
    }

    #[test]
    fn stale_journal_start_connects_only_through_the_pairing_gate() {
        // Stale journal + paired App/runtime: the start may connect.
        let state = Maintenance::default();
        assert!(startup_after_resume(
            &state,
            Ok(bundled_runtime::Resume::StaleDiscarded),
            || Ok(())
        )
        .is_ok());
        assert_eq!(state.snapshot.lock().unwrap()["phase"], "connecting");

        // Stale journal + mismatched or missing runtime identity: no
        // connecting; the gate's runtime_required state stands (an Err from
        // resume keeps the service startup thread on the boot-failure path,
        // so no service starts).
        let state = Maintenance::default();
        assert_eq!(
            startup_after_resume(&state, Ok(bundled_runtime::Resume::StaleDiscarded), || {
                Err("runtime_setup_required".into())
            }),
            Err("runtime_setup_required".into())
        );
        assert_ne!(
            state.snapshot.lock().unwrap()["phase"],
            json!("connecting")
        );
    }

    #[test]
    fn applied_journals_connect_and_resume_errors_surface_without_connecting() {
        for resolved in [Ok(bundled_runtime::Resume::Applied), Ok(bundled_runtime::Resume::Absent)]
        {
            let state = Maintenance::default();
            assert_eq!(
                startup_after_resume(&state, resolved, || panic!("gate must not rerun")),
                Ok(())
            );
            assert_eq!(state.snapshot.lock().unwrap()["phase"], "connecting");
        }
        let state = Maintenance::default();
        assert_eq!(
            startup_after_resume(&state, Err("update_state_invalid".into()), || Ok(())),
            Err("update_state_invalid".into())
        );
        assert_eq!(
            state.snapshot.lock().unwrap()["phase"],
            json!("error")
        );
        assert_eq!(
            state.snapshot.lock().unwrap()["details"]["code"],
            json!("update_state_invalid")
        );
    }

    #[test]
    fn only_verified_previous_apps_keep_the_safe_restart_promise() {
        // Verified App bundle + pairing runtime: safe-restart class, journal
        // may be discarded.
        assert_eq!(
            install_failure_recovery(true),
            ("app_install_failed", true)
        );
        // Unknown state (second rename failed, original location emptied, or
        // identity unavailable): keep the journal under the recovery code.
        assert_eq!(
            install_failure_recovery(false),
            ("app_install_incomplete", false)
        );
    }

    #[test]
    fn partially_removed_app_keeps_the_journal_as_incomplete() {
        // Review round 3 counterexample, through the same boundary the
        // safe-restart predicate uses: the pinned macOS updater's failed
        // replacement leaves Info.plist (and the runtime identity) behind
        // while the executable is gone. The layout verification
        // failed_install_left_previous_app_usable reuses must reject this
        // bundle, so the failure classifies as app_install_incomplete and
        // the journal is retained for the verified-backup rollback.
        let dir = tempfile::tempdir().unwrap();
        let contents = dir.path().join("Partial.app/Contents");
        std::fs::create_dir_all(contents.join("MacOS")).unwrap();
        std::fs::write(contents.join("Info.plist"), "plist").unwrap();
        let executable = contents.join("MacOS/loopx-control-plane");
        std::fs::write(&executable, "binary").unwrap();
        assert!(crate::update_backup::app_bundle_at(&executable).is_ok());
        // The partial removal: executable deleted, Info.plist survives.
        std::fs::remove_file(&executable).unwrap();
        // The predicate's bundle term fails exactly as it would for the
        // running App's deleted binary, and the recovery classification
        // keeps the journal instead of promising a safe restart.
        let usable = crate::update_backup::app_bundle_at(&executable).is_ok();
        assert!(!usable);
        assert_eq!(
            install_failure_recovery(usable),
            ("app_install_incomplete", false)
        );
    }
}
