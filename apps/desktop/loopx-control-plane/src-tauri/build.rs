fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&["desktop_update", "desktop_update_status"]),
    ))
    .expect("desktop build")
}
