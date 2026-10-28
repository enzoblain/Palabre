#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // Requests to the Palabre server go through Rust: no CORS or mixed-content limits
        // for a server on the local network (http://)
        .plugin(tauri_plugin_http::init())
        // Links in messages open in the system browser
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("error while running Palabre");
}
