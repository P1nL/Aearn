const APP_COMMANDS: &[&str] = &[
    "preview_host_create",
    "preview_host_update_source",
    "preview_host_set_bounds",
    "preview_host_recreate",
    "preview_host_close",
];

fn main() {
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(APP_COMMANDS)),
    )
    .expect("failed to build Tauri application manifest");
}
