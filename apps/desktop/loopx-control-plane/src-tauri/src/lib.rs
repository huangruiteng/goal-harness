mod bundled_runtime;
mod maintenance;
mod services;
mod update_backup;

use services::ServiceSet;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tauri::{
    ipc::CapabilityBuilder, AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_notification::NotificationExt;

const APP_IDENTIFIER: &str = "io.loopx.control-plane";

fn maintenance_origin(url: &Url) -> String {
    // Custom-protocol IPC carries the HTTP Origin header (no /chat/ path).
    // postMessage carries the page URL. Both must match the same exact origin.
    url.origin().ascii_serialization()
}

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

pub fn run() {
    // Release builds load the versioned LoopX Chat workspace that ships inside
    // the installed `loopx` release, so `loopx update` refreshes the frontend
    // and backend together instead of reusing a separately built asset bundle.
    #[cfg(dev)]
    let web_origin = "http://127.0.0.1:5173".to_string();
    #[cfg(not(dev))]
    let web_origin = "http://127.0.0.1:8767/chat/".to_string();
    let services = Arc::new(Mutex::new(None::<ServiceSet>));
    let services_for_setup = Arc::clone(&services);
    let navigation_origin: Url = web_origin.parse().expect("valid desktop origin");
    let shutting_down = Arc::new(AtomicBool::new(false));
    let shutting_down_for_setup = Arc::clone(&shutting_down);

    let builder = tauri::Builder::default()
        .manage(maintenance::Maintenance::default())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            maintenance::desktop_update,
            maintenance::desktop_update_status
        ])
        .plugin(
            tauri_plugin_single_instance::Builder::new()
                .dbus_id(APP_IDENTIFIER)
                .callback(|app, _args, _cwd| show_main_window(app))
                .build(),
        )
        .plugin(tauri_plugin_notification::init())
        .setup(move |app| {
            let origin: Url = web_origin.parse()?;
            app.add_capability(
                CapabilityBuilder::new("desktop-loopx-chat")
                    .remote(maintenance_origin(&origin))
                    .permission("allow-desktop-update")
                    .permission("allow-desktop-update-status")
                    .window("main"),
            )?;

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("LoopX")
                .inner_size(1280.0, 820.0)
                .min_inner_size(960.0, 640.0)
                .on_navigation(move |url| {
                    url.scheme() == "tauri" || url.origin() == navigation_origin.origin()
                })
                .build()?;

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                if maintenance::resume(&handle).is_err() {
                    if let Some(window) = handle.get_webview_window("main") {
                        let _ = window.eval(
                            "window.loopxBootFailed('本机组件尚未就绪，请展开恢复与更新，检查更新或修复当前版本。')",
                        );
                    }
                    return;
                }
                while !shutting_down_for_setup.load(Ordering::Acquire) {
                    match maintenance::start_services(&handle) {
                        Ok(None) => {
                            std::thread::sleep(std::time::Duration::from_millis(200));
                            continue;
                        }
                        Ok(Some(mut started)) => {
                            if shutting_down_for_setup.load(Ordering::Acquire) {
                                started.stop();
                                return;
                            }
                            let healed = started.healed;
                            *services_for_setup.lock().expect("service state lock") = Some(started);
                            if healed {
                                let _ = handle
                                    .notification()
                                    .builder()
                                    .title("LoopX")
                                    .body("已自动升级到当前 LoopX 版本，服务已重启。")
                                    .show();
                            }
                            if let Some(window) = handle.get_webview_window("main") {
                                let _ = window.navigate(origin);
                            }
                            return;
                        }
                        Err(error) => {
                            let message = "本地服务暂时无法启动，请检查安装或端口占用。";
                            eprintln!("LoopX service error: {error}");
                            if let Some(window) = handle.get_webview_window("main") {
                                if let Ok(encoded) = serde_json::to_string(&message) {
                                    let _ =
                                        window.eval(format!("window.loopxBootFailed({encoded})"));
                                }
                            }
                            for _ in 0..10 {
                                if shutting_down_for_setup.load(Ordering::Acquire) {
                                    return;
                                }
                                std::thread::sleep(std::time::Duration::from_millis(200));
                            }
                            if let Some(window) = handle.get_webview_window("main") {
                                let _ = window.eval("window.loopxBootRetrying()");
                            }
                        }
                    }
                }
            });
            Ok(())
        });

    let app = builder
        .build(tauri::generate_context!())
        .expect("failed to build LoopX desktop shell");
    app.run(move |_app, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            shutting_down.store(true, Ordering::Release);
            if let Ok(mut guard) = services.lock() {
                if let Some(current) = guard.as_mut() {
                    current.stop();
                }
                *guard = None;
            }
        }
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn maintenance_acl_accepts_both_transports_only_on_the_app_origin() {
        use tauri::utils::acl::RemoteUrlPattern;
        let page: tauri::Url = "http://127.0.0.1:8767/chat/".parse().unwrap();
        let old: RemoteUrlPattern = page.to_string().parse().unwrap();
        assert!(!old.test(&"http://127.0.0.1:8767".parse().unwrap()));
        let pattern: RemoteUrlPattern = super::maintenance_origin(&page).parse().unwrap();
        for allowed in [
            "http://127.0.0.1:8767",
            "http://127.0.0.1:8767/chat/?goal=x",
        ] {
            assert!(pattern.test(&allowed.parse().unwrap()), "{allowed}");
        }
        for denied in [
            "http://127.0.0.1:8766/chat/",
            "http://localhost:8767/chat/",
            "https://127.0.0.1:8767/chat/",
            "https://example.com/chat/",
        ] {
            assert!(!pattern.test(&denied.parse().unwrap()), "{denied}");
        }
    }

    #[test]
    fn startup_surface_is_visible_and_names_automatic_recovery() {
        let html = include_str!("../../static/index.html");
        let script = include_str!("../../static/boot.js");

        assert!(html.contains("正在启动本地控制面"));
        assert!(html.contains("aria-busy=\"true\""));
        assert!(html.contains("aria-live=\"polite\""));
        assert!(script.contains("desktop_update_status"));
        assert!(script.contains("window.loopxBootRetrying"));
    }
}
