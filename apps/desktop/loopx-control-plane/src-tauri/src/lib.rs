mod services;

use services::ServiceSet;
use std::sync::{Arc, Mutex};
use tauri::{
    ipc::CapabilityBuilder, AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder,
};

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

    let builder = tauri::Builder::default()
        .plugin(
            tauri_plugin_single_instance::Builder::new()
                .dbus_id(APP_IDENTIFIER)
                .callback(|app, _args, _cwd| show_main_window(app))
                .build(),
        )
        .setup(move |app| {
            let started = match ServiceSet::start() {
                Ok(services) => services,
                Err(error) => {
                    // Soft gate: surface a service/runtime mismatch as a clear
                    // owner-facing reminder instead of panicking the shell.
                    let message = format!(
                        "LoopX 检测到正在运行的服务来自不同的安装版本，已停止本次启动。\n\n详情：{error}\n\n请先退出旧的 loopx dashboard 或 LoopX App，再重新打开 LoopX。"
                    );
                    let _ = rfd::MessageDialog::new()
                        .set_title("LoopX")
                        .set_description(&message)
                        .set_level(rfd::MessageLevel::Warning)
                        .show();
                    eprintln!("LoopX service error: {error}");
                    app.handle().exit(1);
                    return Ok(());
                }
            };
            *services_for_setup.lock().expect("service state lock") = Some(started);

            let origin: Url = web_origin.parse()?;
            app.add_capability(
                CapabilityBuilder::new("desktop-loopx-chat")
                    .remote(origin.to_string())
                    .window("main"),
            )?;

            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(origin))
                .title("LoopX")
                .inner_size(1280.0, 820.0)
                .min_inner_size(960.0, 640.0)
                .on_navigation(move |url| url.origin() == navigation_origin.origin())
                .build()?;
            Ok(())
        });

    let app = builder
        .build(tauri::generate_context!())
        .expect("failed to build LoopX desktop shell");
    app.run(move |_app, event| {
        if matches!(event, RunEvent::Exit | RunEvent::ExitRequested { .. }) {
            if let Ok(mut guard) = services.lock() {
                if let Some(current) = guard.as_mut() {
                    current.stop();
                }
                *guard = None;
            }
        }
    });
}
