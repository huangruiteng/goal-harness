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
#[tauri::command]
pub fn desktop_update_status(app: AppHandle, state: State<'_, Maintenance>) -> Value {
    json!({"state": state.snapshot.lock().unwrap().clone(), "app_version": app.package_info().version.to_string(), "runtime": bundled_runtime::identity(&app).ok(), "rollback_available": crate::update_backup::available(&app)})
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
        state.publish("error", json!({"code":error,"channel":channel}));
    }
    outcome
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
            .map_err(|_| "update_check_failed")?;
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
            bundled_runtime::resume_pending(&handle)
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
    tauri::async_runtime::spawn_blocking(move || update.install(bytes))
        .await
        .map_err(|_| "app_install_failed")?
        .map_err(|_| "app_install_failed")?;
    *state.pending.lock().unwrap() = None;
    Ok(state.publish("restart_required", json!({"version":target})))
}
pub fn resume(app: &AppHandle) -> Result<(), String> {
    // Development intentionally pairs a live frontend with a developer-selected
    // runtime; it must neither replace itself nor force release installation.
    if cfg!(dev) || !cfg!(target_os = "macos") {
        return Ok(());
    }
    let state = app.state::<Maintenance>();
    let _guard = state.acquire()?;
    if !bundled_runtime::journal(app)?.exists() {
        {
            let bundled = bundled_runtime::identity(app)?;
            let installed = crate::services::runtime_identity_for_executable(
                &crate::services::loopx_executable(),
            );
            if installed.as_ref().map(|v| &v["source_revision"])
                != Some(&bundled["source_revision"])
            {
                state.publish("runtime_required", json!({}));
                return Err("runtime_setup_required".into());
            }
        }
        return Ok(());
    }
    state.publish("installing_runtime", json!({}));
    let result = bundled_runtime::resume_pending(app);
    match result {
        Ok(()) => {
            state.publish("connecting", json!({}));
            Ok(())
        }
        Err(error) => {
            state.publish("error", json!({"code":error}));
            Err(error)
        }
    }
}
pub fn start_services(app: &AppHandle) -> Result<Option<crate::services::ServiceSet>, String> {
    app.state::<Maintenance>()
        .reconcile_services(|| crate::services::ServiceSet::start().map_err(|e| e.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
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
        assert!(state.reconcile_services::<()>(|| Err("occupied port".into())).is_err());
        assert_eq!(state.snapshot.lock().unwrap()["phase"], "service_error");
        assert!(state.acquire().is_ok(), "recovery transaction must be available");
        assert_eq!(state.reconcile_services(|| Ok(())).unwrap(), Some(()));
        assert_eq!(state.snapshot.lock().unwrap()["phase"], "ready");
    }

    #[test]
    fn service_retry_cannot_race_maintenance_or_restart() {
        let state = Maintenance::default();
        let guard = state.acquire().unwrap();
        assert_eq!(state.reconcile_services::<()>(|| panic!("must not start")).unwrap(), None);
        drop(guard);
        state.publish("restart_required", json!({}));
        assert_eq!(state.reconcile_services::<()>(|| panic!("must not start")).unwrap(), None);
    }
}
