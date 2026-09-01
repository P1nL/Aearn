mod preview_host;

fn main() {
    tauri::Builder::default()
        .manage(preview_host::PreviewHostManager::default())
        .register_uri_scheme_protocol("aearn-preview", preview_host::protocol_response)
        .invoke_handler(tauri::generate_handler![
            preview_host::preview_host_create,
            preview_host::preview_host_update_source,
            preview_host::preview_host_set_bounds,
            preview_host::preview_host_recreate,
            preview_host::preview_host_close,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
