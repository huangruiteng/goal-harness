mod services;

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
                    .remote(origin.to_string())
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
                while !shutting_down_for_setup.load(Ordering::Acquire) {
                    match ServiceSet::start() {
                        Ok(mut started) => {
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
                            let message =
                                format!("LoopX 本地服务暂时无法启动：{error}。正在自动重试…");
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
    fn startup_surface_is_visible_and_names_automatic_recovery() {
        let html = include_str!("../../static/index.html");
        let script = include_str!("../../static/boot.js");

        assert!(html.contains("正在启动本地控制面"));
        assert!(html.contains("aria-busy=\"true\""));
        assert!(html.contains("aria-live=\"polite\""));
        assert!(script.contains("正在自动重试"));
        assert!(script.contains("window.loopxBootRetrying"));
    }
}
