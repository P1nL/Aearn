use std::{
    collections::HashMap,
    fs,
    path::PathBuf,
    sync::{
        atomic::{AtomicU64, Ordering},
        Mutex,
    },
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tauri::{
    http::{header, Request, Response, StatusCode},
    webview::{DownloadEvent, NewWindowResponse, WebviewBuilder},
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, State, Url, Webview, WebviewUrl,
    Window,
};

const PREVIEW_EVENT_PREFIX: &str = "__AEARN_PREVIEW_EVENT__:";
const PREVIEW_EVENT_NAME: &str = "aearn-preview-event";
const PREVIEW_SCHEME: &str = "aearn-preview";
const MAX_SOURCE_CHARS: usize = 48_000;
const MAX_MESSAGE_CHARS: usize = 1_024;
const MAX_EVENT_KEY_CHARS: usize = 160;
const MAX_EVENT_PAYLOAD_BYTES: usize = 2_048;
const MAX_TITLE_BYTES: usize = 8_192;

#[derive(Default)]
pub struct PreviewHostManager {
    hosts: Mutex<HashMap<String, PreviewHostRecord>>,
    next_host_id: AtomicU64,
}

#[derive(Clone)]
struct PreviewHostRecord {
    owner_webview_label: String,
    webview_label: String,
    scope: PreviewScope,
    source: String,
    source_hash: String,
    generation: u64,
    nonce: String,
    bounds: PreviewBounds,
    visible: bool,
    last_event_sequence: u64,
    data_directory: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewScope {
    artifact_id: String,
    source_artifact_id: String,
    session_id: String,
    artifact_version: u64,
    language_id: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewBounds {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewCreateRequest {
    scope: PreviewScope,
    source: String,
    source_hash: String,
    bounds: PreviewBounds,
    visible: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewUpdateSourceRequest {
    host_id: String,
    nonce: String,
    scope: PreviewScope,
    source: String,
    source_hash: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewBoundsRequest {
    host_id: String,
    nonce: String,
    scope: PreviewScope,
    bounds: PreviewBounds,
    visible: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PreviewHostRequest {
    host_id: String,
    nonce: String,
    scope: PreviewScope,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewHostDescriptor {
    host_id: String,
    nonce: String,
    scope: PreviewScope,
    generation: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PreviewBridgeEnvelope {
    host_id: String,
    nonce: String,
    artifact_id: String,
    source_artifact_id: String,
    session_id: String,
    artifact_version: u64,
    generation: u64,
    sequence: u64,
    event: PreviewBridgeEvent,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum PreviewBridgeEvent {
    Ready,
    Console {
        level: PreviewConsoleLevel,
        message: String,
    },
    RuntimeError {
        message: String,
    },
    InteractionEvent {
        event_key: String,
        payload_json: Map<String, Value>,
    },
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
enum PreviewConsoleLevel {
    Log,
    Info,
    Warn,
    Error,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct PreviewHostEvent {
    host_id: String,
    nonce: String,
    scope: PreviewScope,
    generation: u64,
    sequence: u64,
    event: PreviewBridgeEvent,
}

impl PreviewHostManager {
    fn descriptor(record: &PreviewHostRecord, host_id: &str) -> PreviewHostDescriptor {
        PreviewHostDescriptor {
            host_id: host_id.to_string(),
            nonce: record.nonce.clone(),
            scope: record.scope.clone(),
            generation: record.generation,
        }
    }

    fn create_record(
        &self,
        owner_webview_label: &str,
        request: PreviewCreateRequest,
    ) -> Result<(String, PreviewHostRecord), String> {
        validate_scope(&request.scope)?;
        validate_source(&request.source, &request.source_hash)?;
        validate_bounds(request.bounds)?;
        let sequence = self.next_host_id.fetch_add(1, Ordering::Relaxed) + 1;
        let host_id = format!("host-{sequence}");
        let generation = 1;
        let nonce = generate_nonce(&host_id, &request.scope, generation);
        let record = PreviewHostRecord {
            owner_webview_label: owner_webview_label.to_string(),
            webview_label: preview_webview_label(&host_id, generation),
            scope: request.scope,
            source: request.source,
            source_hash: request.source_hash,
            generation,
            nonce,
            bounds: request.bounds,
            visible: request.visible,
            last_event_sequence: 0,
            data_directory: preview_data_directory(&host_id, generation),
        };
        Ok((host_id, record))
    }

    fn protocol_response(
        &self,
        webview_label: &str,
        request: &Request<Vec<u8>>,
    ) -> Response<Vec<u8>> {
        let Some(host_id) = request
            .uri()
            .path()
            .strip_prefix("/host/")
            .filter(|value| !value.is_empty() && !value.contains('/'))
        else {
            return plain_response(StatusCode::NOT_FOUND, "preview host not found");
        };
        let hosts = self.hosts.lock().expect("preview host state poisoned");
        let Some(record) = hosts.get(host_id) else {
            return plain_response(StatusCode::NOT_FOUND, "preview host not found");
        };
        if record.webview_label != webview_label || !request_query_matches(request, record) {
            return plain_response(StatusCode::FORBIDDEN, "preview host identity rejected");
        }
        preview_html_response(build_preview_host_html(host_id, record))
    }

    fn accept_title_event(&self, host_id: &str, title: &str) -> Option<PreviewHostEvent> {
        if title.len() > MAX_TITLE_BYTES || !title.starts_with(PREVIEW_EVENT_PREFIX) {
            return None;
        }
        let envelope: PreviewBridgeEnvelope =
            serde_json::from_str(&title[PREVIEW_EVENT_PREFIX.len()..]).ok()?;
        let mut hosts = self.hosts.lock().ok()?;
        let record = hosts.get_mut(host_id)?;
        if envelope.host_id != host_id
            || envelope.nonce != record.nonce
            || envelope.artifact_id != record.scope.artifact_id
            || envelope.source_artifact_id != record.scope.source_artifact_id
            || envelope.session_id != record.scope.session_id
            || envelope.artifact_version != record.scope.artifact_version
            || envelope.generation != record.generation
            || envelope.sequence == 0
            || envelope.sequence != record.last_event_sequence.saturating_add(1)
            || !validate_bridge_event(&envelope.event)
        {
            return None;
        }
        record.last_event_sequence = envelope.sequence;
        Some(PreviewHostEvent {
            host_id: host_id.to_string(),
            nonce: record.nonce.clone(),
            scope: record.scope.clone(),
            generation: record.generation,
            sequence: envelope.sequence,
            event: envelope.event,
        })
    }

    fn checked_record(&self, request: &PreviewHostRequest) -> Result<PreviewHostRecord, String> {
        validate_scope(&request.scope)?;
        let hosts = self
            .hosts
            .lock()
            .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?;
        let record = hosts
            .get(&request.host_id)
            .ok_or_else(|| "PREVIEW_HOST_NOT_FOUND".to_string())?;
        validate_host_identity(record, &request.nonce, &request.scope)?;
        Ok(record.clone())
    }
}

pub fn protocol_response(
    context: tauri::UriSchemeContext<'_, tauri::Wry>,
    request: Request<Vec<u8>>,
) -> Response<Vec<u8>> {
    context
        .app_handle()
        .state::<PreviewHostManager>()
        .protocol_response(context.webview_label(), &request)
}

#[tauri::command]
pub async fn preview_host_create(
    app: AppHandle,
    webview: Webview,
    manager: State<'_, PreviewHostManager>,
    request: PreviewCreateRequest,
) -> Result<PreviewHostDescriptor, String> {
    require_main_webview(&webview)?;
    let window = webview.window();
    let (host_id, record) = manager.create_record(webview.label(), request)?;
    let descriptor = PreviewHostManager::descriptor(&record, &host_id);
    manager
        .hosts
        .lock()
        .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?
        .insert(host_id.clone(), record.clone());
    if let Err(error) = create_preview_webview(&app, &window, &host_id, &record) {
        manager
            .hosts
            .lock()
            .ok()
            .and_then(|mut hosts| hosts.remove(&host_id));
        cleanup_data_directory(record.data_directory.clone());
        return Err(error);
    }
    Ok(descriptor)
}

#[tauri::command]
pub async fn preview_host_update_source(
    webview: Webview,
    manager: State<'_, PreviewHostManager>,
    request: PreviewUpdateSourceRequest,
) -> Result<PreviewHostDescriptor, String> {
    require_main_webview(&webview)?;
    validate_scope(&request.scope)?;
    validate_source(&request.source, &request.source_hash)?;
    let window = webview.window();
    let (record, previous) = {
        let mut hosts = manager
            .hosts
            .lock()
            .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?;
        let current = hosts
            .get_mut(&request.host_id)
            .ok_or_else(|| "PREVIEW_HOST_NOT_FOUND".to_string())?;
        validate_host_identity(current, &request.nonce, &request.scope)?;
        let previous = current.clone();
        current.generation += 1;
        current.nonce = generate_nonce(&request.host_id, &current.scope, current.generation);
        current.source = request.source;
        current.source_hash = request.source_hash;
        current.last_event_sequence = 0;
        (current.clone(), previous)
    };
    let target = preview_url(&request.host_id, &record)?;
    let native = find_webview(&window, &record.webview_label)
        .ok_or_else(|| "PREVIEW_HOST_WEBVIEW_NOT_FOUND".to_string())?;
    if native.navigate(target).is_err() {
        if let Ok(mut hosts) = manager.hosts.lock() {
            if hosts
                .get(&request.host_id)
                .is_some_and(|item| item.generation == record.generation)
            {
                hosts.insert(request.host_id.clone(), previous);
            }
        }
        return Err("PREVIEW_HOST_NAVIGATION_FAILED".to_string());
    }
    Ok(PreviewHostManager::descriptor(&record, &request.host_id))
}

#[tauri::command]
pub async fn preview_host_set_bounds(
    webview: Webview,
    manager: State<'_, PreviewHostManager>,
    request: PreviewBoundsRequest,
) -> Result<(), String> {
    require_main_webview(&webview)?;
    validate_scope(&request.scope)?;
    validate_bounds(request.bounds)?;
    let window = webview.window();
    let record = {
        let mut hosts = manager
            .hosts
            .lock()
            .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?;
        let record = hosts
            .get_mut(&request.host_id)
            .ok_or_else(|| "PREVIEW_HOST_NOT_FOUND".to_string())?;
        validate_host_identity(record, &request.nonce, &request.scope)?;
        record.bounds = request.bounds;
        record.visible = request.visible;
        record.clone()
    };
    apply_bounds(&window, &record)
}

#[tauri::command]
pub async fn preview_host_recreate(
    app: AppHandle,
    webview: Webview,
    manager: State<'_, PreviewHostManager>,
    request: PreviewHostRequest,
) -> Result<PreviewHostDescriptor, String> {
    require_main_webview(&webview)?;
    let window = webview.window();
    let previous = manager.checked_record(&request)?;
    if let Some(native) = find_webview(&window, &previous.webview_label) {
        let _ = native.hide();
        let _ = native.close();
    }
    let next = {
        let mut hosts = manager
            .hosts
            .lock()
            .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?;
        let current = hosts
            .get_mut(&request.host_id)
            .ok_or_else(|| "PREVIEW_HOST_NOT_FOUND".to_string())?;
        validate_host_identity(current, &request.nonce, &request.scope)?;
        current.generation += 1;
        current.nonce = generate_nonce(&request.host_id, &current.scope, current.generation);
        current.webview_label = preview_webview_label(&request.host_id, current.generation);
        current.data_directory = preview_data_directory(&request.host_id, current.generation);
        current.last_event_sequence = 0;
        current.clone()
    };
    if let Err(error) = create_preview_webview(&app, &window, &request.host_id, &next) {
        if let Ok(mut hosts) = manager.hosts.lock() {
            hosts.insert(request.host_id.clone(), previous);
        }
        return Err(error);
    }
    cleanup_data_directory(previous.data_directory);
    Ok(PreviewHostManager::descriptor(&next, &request.host_id))
}

#[tauri::command]
pub async fn preview_host_close(
    webview: Webview,
    manager: State<'_, PreviewHostManager>,
    request: PreviewHostRequest,
) -> Result<(), String> {
    require_main_webview(&webview)?;
    let window = webview.window();
    let record = manager.checked_record(&request)?;
    if let Some(native) = find_webview(&window, &record.webview_label) {
        let _ = native.hide();
        native
            .close()
            .map_err(|_| "PREVIEW_HOST_CLOSE_FAILED".to_string())?;
    }
    manager
        .hosts
        .lock()
        .map_err(|_| "PREVIEW_HOST_STATE_UNAVAILABLE".to_string())?
        .remove(&request.host_id);
    cleanup_data_directory(record.data_directory);
    Ok(())
}

fn create_preview_webview(
    app: &AppHandle,
    window: &Window,
    host_id: &str,
    record: &PreviewHostRecord,
) -> Result<(), String> {
    let url = preview_url(host_id, record)?;
    let host_id_for_navigation = host_id.to_string();
    let host_id_for_title = host_id.to_string();
    let app_for_title = app.clone();
    let builder = WebviewBuilder::new(&record.webview_label, WebviewUrl::CustomProtocol(url))
        .on_navigation(move |url| preview_navigation_allowed(url, &host_id_for_navigation))
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_download(|_, event| !matches!(event, DownloadEvent::Requested { .. }))
        .on_document_title_changed(move |_, title| {
            let manager = app_for_title.state::<PreviewHostManager>();
            if let Some(event) = manager.accept_title_event(&host_id_for_title, &title) {
                let _ = app_for_title.emit_to("main", PREVIEW_EVENT_NAME, event);
            }
        })
        .data_directory(record.data_directory.clone())
        .incognito(true)
        .devtools(false)
        .use_https_scheme(true);
    let native = window
        .add_child(
            builder,
            LogicalPosition::new(record.bounds.x, record.bounds.y),
            LogicalSize::new(record.bounds.width, record.bounds.height),
        )
        .map_err(|_| "PREVIEW_HOST_CREATE_FAILED".to_string())?;
    let visibility = if record.visible {
        native
            .show()
            .map_err(|_| "PREVIEW_HOST_SHOW_FAILED".to_string())
    } else {
        native
            .hide()
            .map_err(|_| "PREVIEW_HOST_HIDE_FAILED".to_string())
    };
    if let Err(error) = visibility {
        let _ = native.hide();
        let _ = native.close();
        return Err(error);
    }
    Ok(())
}

fn apply_bounds(window: &Window, record: &PreviewHostRecord) -> Result<(), String> {
    let native = find_webview(window, &record.webview_label)
        .ok_or_else(|| "PREVIEW_HOST_WEBVIEW_NOT_FOUND".to_string())?;
    native
        .set_position(LogicalPosition::new(record.bounds.x, record.bounds.y))
        .map_err(|_| "PREVIEW_HOST_POSITION_FAILED".to_string())?;
    native
        .set_size(LogicalSize::new(record.bounds.width, record.bounds.height))
        .map_err(|_| "PREVIEW_HOST_SIZE_FAILED".to_string())?;
    if record.visible {
        native
            .show()
            .map_err(|_| "PREVIEW_HOST_SHOW_FAILED".to_string())
    } else {
        native
            .hide()
            .map_err(|_| "PREVIEW_HOST_HIDE_FAILED".to_string())
    }
}

fn cleanup_data_directory(path: PathBuf) {
    std::thread::spawn(move || {
        let _ = fs::remove_dir_all(path);
    });
}

fn find_webview(window: &Window, label: &str) -> Option<Webview> {
    window
        .webviews()
        .into_iter()
        .find(|webview| webview.label() == label)
}

fn require_main_webview(webview: &Webview) -> Result<(), String> {
    if webview.label() == "main" && webview.window().label() == "main" {
        Ok(())
    } else {
        Err("PREVIEW_HOST_CALLER_REJECTED".to_string())
    }
}

fn validate_scope(scope: &PreviewScope) -> Result<(), String> {
    if !valid_identifier(&scope.artifact_id)
        || !valid_identifier(&scope.source_artifact_id)
        || !valid_identifier(&scope.session_id)
        || !valid_identifier(&scope.language_id)
        || scope.artifact_version == 0
    {
        return Err("PREVIEW_HOST_SCOPE_INVALID".to_string());
    }
    Ok(())
}

fn validate_host_identity(
    record: &PreviewHostRecord,
    nonce: &str,
    scope: &PreviewScope,
) -> Result<(), String> {
    if record.owner_webview_label != "main" || record.nonce != nonce || &record.scope != scope {
        return Err("PREVIEW_HOST_IDENTITY_REJECTED".to_string());
    }
    Ok(())
}

fn validate_source(source: &str, expected_hash: &str) -> Result<(), String> {
    if source.chars().count() > MAX_SOURCE_CHARS
        || !valid_sha256(expected_hash)
        || sha256_hex(source.as_bytes()) != expected_hash
    {
        return Err("PREVIEW_HOST_SOURCE_INVALID".to_string());
    }
    Ok(())
}

fn validate_bounds(bounds: PreviewBounds) -> Result<(), String> {
    if !bounds.x.is_finite()
        || !bounds.y.is_finite()
        || !bounds.width.is_finite()
        || !bounds.height.is_finite()
        || bounds.x < -20_000.0
        || bounds.y < -20_000.0
        || bounds.width < 1.0
        || bounds.height < 1.0
        || bounds.width > 20_000.0
        || bounds.height > 20_000.0
    {
        return Err("PREVIEW_HOST_BOUNDS_INVALID".to_string());
    }
    Ok(())
}

fn validate_bridge_event(event: &PreviewBridgeEvent) -> bool {
    match event {
        PreviewBridgeEvent::Ready => true,
        PreviewBridgeEvent::Console { message, .. }
        | PreviewBridgeEvent::RuntimeError { message } => {
            !message.is_empty() && message.chars().count() <= MAX_MESSAGE_CHARS
        }
        PreviewBridgeEvent::InteractionEvent {
            event_key,
            payload_json,
        } => {
            !event_key.is_empty()
                && event_key.chars().count() <= MAX_EVENT_KEY_CHARS
                && valid_identifier(event_key)
                && serde_json::to_vec(payload_json)
                    .is_ok_and(|value| value.len() <= MAX_EVENT_PAYLOAD_BYTES)
                && safe_json_value(&Value::Object(payload_json.clone()), 0)
        }
    }
}

fn safe_json_value(value: &Value, depth: usize) -> bool {
    if depth > 6 {
        return false;
    }
    match value {
        Value::Null | Value::Bool(_) | Value::String(_) => true,
        Value::Number(number) => number
            .as_f64()
            .is_some_and(|number| number.is_finite() && number.abs() <= 9_007_199_254_740_991.0),
        Value::Array(items) => {
            items.len() <= 64 && items.iter().all(|item| safe_json_value(item, depth + 1))
        }
        Value::Object(items) => {
            items.len() <= 64
                && items.iter().all(|(key, item)| {
                    !key.is_empty() && key.len() <= 160 && safe_json_value(item, depth + 1)
                })
        }
    }
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 160
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn preview_webview_label(host_id: &str, generation: u64) -> String {
    format!("aearn-preview-{host_id}-{generation}")
}

fn preview_data_directory(host_id: &str, generation: u64) -> PathBuf {
    std::env::temp_dir()
        .join("aearn-preview-hosts")
        .join(host_id)
        .join(format!("generation-{generation}"))
}

fn preview_url(host_id: &str, record: &PreviewHostRecord) -> Result<Url, String> {
    Url::parse(&format!(
        "{PREVIEW_SCHEME}://localhost/host/{host_id}?generation={}&nonce={}",
        record.generation, record.nonce
    ))
    .map_err(|_| "PREVIEW_HOST_URL_INVALID".to_string())
}

fn preview_navigation_allowed(url: &Url, host_id: &str) -> bool {
    let expected_path = format!("/host/{host_id}");
    let exact_protocol = url.scheme() == PREVIEW_SCHEME && url.host_str() == Some("localhost");
    let windows_protocol = matches!(url.scheme(), "http" | "https")
        && url.host_str() == Some("aearn-preview.localhost");
    let safe_port = match url.scheme() {
        PREVIEW_SCHEME => url.port().is_none(),
        "https" => url.port_or_known_default() == Some(443),
        "http" => url.port_or_known_default() == Some(80),
        _ => false,
    };
    let safe_url_shape = url.username().is_empty()
        && url.password().is_none()
        && safe_port
        && url.fragment().is_none();
    (exact_protocol || windows_protocol) && safe_url_shape && url.path() == expected_path
}

fn request_query_matches(request: &Request<Vec<u8>>, record: &PreviewHostRecord) -> bool {
    let Some(query) = request.uri().query() else {
        return false;
    };
    query == format!("generation={}&nonce={}", record.generation, record.nonce)
}

fn generate_nonce(host_id: &str, scope: &PreviewScope, generation: u64) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.as_nanos());
    sha256_hex(
        format!(
            "{host_id}:{}:{}:{}:{generation}:{nanos}",
            scope.artifact_id, scope.session_id, scope.artifact_version
        )
        .as_bytes(),
    )
}

fn sha256_hex(value: &[u8]) -> String {
    let digest = Sha256::digest(value);
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn plain_response(status: StatusCode, body: &str) -> Response<Vec<u8>> {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .header(header::CACHE_CONTROL, "no-store")
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .body(body.as_bytes().to_vec())
        .expect("valid preview protocol response")
}

fn preview_html_response(html: String) -> Response<Vec<u8>> {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
        .header(header::CACHE_CONTROL, "no-store, max-age=0")
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
        .header(header::REFERRER_POLICY, "no-referrer")
        .header(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), display-capture=(), fullscreen=(), payment=(), usb=()",
        )
        .header(
            header::CONTENT_SECURITY_POLICY,
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'; frame-src 'self'; child-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'",
        )
        .body(html.into_bytes())
        .expect("valid preview html response")
}

fn js_string(value: &str) -> String {
    serde_json::to_string(value)
        .expect("serializing preview source cannot fail")
        .replace('<', "\\u003c")
        .replace('>', "\\u003e")
        .replace('&', "\\u0026")
}

fn build_preview_host_html(host_id: &str, record: &PreviewHostRecord) -> String {
    let identity = serde_json::json!({
        "hostId": host_id,
        "nonce": record.nonce,
        "artifactId": record.scope.artifact_id,
        "sourceArtifactId": record.scope.source_artifact_id,
        "sessionId": record.scope.session_id,
        "artifactVersion": record.scope.artifact_version,
        "generation": record.generation,
    })
    .to_string()
    .replace('<', "\\u003c")
    .replace('>', "\\u003e")
    .replace('&', "\\u0026");
    PREVIEW_HOST_TEMPLATE
        .replace("__AEARN_IDENTITY__", &identity)
        .replace("__AEARN_SOURCE__", &js_string(&record.source))
        .replace("__AEARN_LANGUAGE__", &js_string(&record.scope.language_id))
        .replace("__AEARN_EVENT_PREFIX__", &js_string(PREVIEW_EVENT_PREFIX))
}

const PREVIEW_HOST_TEMPLATE: &str = r####"<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Aearn Preview</title>
  <style>
    html, body, #preview-frame { width: 100%; height: 100%; margin: 0; border: 0; background: #fff; }
    body { overflow: hidden; }
    #preview-frame { display: block; }
  </style>
</head>
<body>
  <iframe id="preview-frame" title="学习代码隔离预览" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>
  <script>
  (() => {
    'use strict';
    const identity = __AEARN_IDENTITY__;
    const learnerSource = __AEARN_SOURCE__;
    const language = __AEARN_LANGUAGE__;
    const eventPrefix = __AEARN_EVENT_PREFIX__;
    const frame = document.getElementById('preview-frame');
    let sequence = 0;
    const trim = (value, maximum) => Array.from(String(value ?? '')).slice(0, maximum).join('');
    const emit = (event) => {
      document.title = eventPrefix + JSON.stringify({ ...identity, sequence: ++sequence, event });
    };
    const instrumentation = `(() => {
      'use strict';
      const trim = (value, maximum) => Array.from(String(value ?? '')).slice(0, maximum).join('');
      const stringify = (value) => {
        try {
          if (typeof value === 'string') return value;
          if (value instanceof Error) return value.message;
          const serialized = JSON.stringify(value);
          return serialized === undefined ? String(value) : serialized;
        } catch { return String(value); }
      };
      const cryptoApi = globalThis.crypto;
      if (!cryptoApi || typeof cryptoApi.getRandomValues !== 'function') return;
      const tokenBytes = new Uint8Array(16);
      cryptoApi.getRandomValues(tokenBytes);
      const bridgeToken = Array.from(tokenBytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
      const postToParent = parent.postMessage.bind(parent);
      const report = (event) => postToParent({ __aearnPreview: true, bridge_token: bridgeToken, event }, '*');
      report({ kind: 'ready' });
      setInterval(() => report({ kind: 'ready' }), 750);
      for (const level of ['log', 'info', 'warn', 'error']) {
        const original = console[level]?.bind(console);
        console[level] = (...args) => {
          report({ kind: 'console', level, message: trim(args.map(stringify).join(' '), 1024) || '(empty)' });
          original?.(...args);
        };
      }
      addEventListener('error', (event) => report({ kind: 'runtime_error', message: trim(event.message || 'Runtime error', 1024) }));
      addEventListener('unhandledrejection', (event) => report({ kind: 'runtime_error', message: trim(stringify(event.reason) || 'Unhandled rejection', 1024) }));
      addEventListener('click', (event) => {
        if (!event.isTrusted) return;
        const target = event.target instanceof Element ? event.target.closest('[data-aearn-event]') : null;
        const eventKey = target?.getAttribute('data-aearn-event') || '';
        const payloadText = target?.getAttribute('data-aearn-event-payload') || '{}';
        try {
          const payload = JSON.parse(payloadText);
          if (/^[A-Za-z0-9_.:-]{1,160}$/.test(eventKey) && payload && typeof payload === 'object' && !Array.isArray(payload) && JSON.stringify(payload).length <= 2048) {
            report({ kind: 'interaction_event', event_key: eventKey, payload_json: payload });
          }
        } catch {}
      }, true);
    })();`;
    const instrumentTag = '<script>' + instrumentation + '<' + '/script>';
    const escapedSource = learnerSource.replaceAll('<' + '/script', '<\\/script');
    let documentSource;
    if (language === 'javascript' || language === 'js') {
      documentSource = '<!doctype html><meta charset="utf-8"><body><div id="app"></div>'
        + instrumentTag + '<script>' + escapedSource + '<' + '/script>';
    } else if (language === 'css') {
      documentSource = '<!doctype html><meta charset="utf-8"><body><div id="app"></div>'
        + instrumentTag + '<style>' + learnerSource + '</style>';
    } else {
      documentSource = instrumentTag + learnerSource;
    }
    let bridgeToken = null;
    const isBridgeToken = (value) => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
    addEventListener('message', (message) => {
      if (message.source !== frame.contentWindow || !message.data || message.data.__aearnPreview !== true ||
          Object.keys(message.data).length !== 3 || !isBridgeToken(message.data.bridge_token)) return;
      const event = message.data.event;
      const token = message.data.bridge_token;
      if (!event || typeof event.kind !== 'string') return;
      if (event.kind === 'ready' && Object.keys(event).length === 1) {
        if (bridgeToken !== null && bridgeToken !== token) return;
        bridgeToken = token;
        emit({ kind: 'ready' });
      } else if (bridgeToken === null || bridgeToken !== token) {
        return;
      } else if (event.kind === 'console' && ['log', 'info', 'warn', 'error'].includes(event.level) && typeof event.message === 'string') {
        emit({ kind: 'console', level: event.level, message: trim(event.message, 1024) || '(empty)' });
      } else if (event.kind === 'runtime_error' && typeof event.message === 'string') {
        emit({ kind: 'runtime_error', message: trim(event.message, 1024) || 'Runtime error' });
      } else if (event.kind === 'interaction_event' && typeof event.event_key === 'string' && /^[A-Za-z0-9_.:-]{1,160}$/.test(event.event_key) && event.payload_json && typeof event.payload_json === 'object' && !Array.isArray(event.payload_json) && JSON.stringify(event.payload_json).length <= 2048) {
        emit({ kind: 'interaction_event', event_key: event.event_key, payload_json: event.payload_json });
      }
    });
    frame.srcdoc = documentSource;
  })();
  </script>
</body>
</html>"####;

#[cfg(test)]
mod tests {
    use super::*;

    fn scope() -> PreviewScope {
        PreviewScope {
            artifact_id: "artifact-1".into(),
            source_artifact_id: "artifact-1".into(),
            session_id: "session-1".into(),
            artifact_version: 3,
            language_id: "html_css".into(),
        }
    }

    fn record() -> PreviewHostRecord {
        let source = "<button data-aearn-event=\"clicked\">ok</button>";
        PreviewHostRecord {
            owner_webview_label: "main".into(),
            webview_label: "aearn-preview-host-1-1".into(),
            scope: scope(),
            source: source.into(),
            source_hash: sha256_hex(source.as_bytes()),
            generation: 1,
            nonce: "a".repeat(64),
            bounds: PreviewBounds {
                x: 0.0,
                y: 0.0,
                width: 400.0,
                height: 300.0,
            },
            visible: true,
            last_event_sequence: 0,
            data_directory: PathBuf::new(),
        }
    }

    #[test]
    fn capability_targets_only_the_main_webview() {
        let capability: serde_json::Value =
            serde_json::from_str(include_str!("../capabilities/default.json")).unwrap();
        let build_script = include_str!("../build.rs");
        assert!(capability.get("windows").is_none());
        assert_eq!(
            capability
                .get("webviews")
                .and_then(|value| value.as_array())
                .unwrap(),
            &[serde_json::Value::String("main".into())]
        );
        assert!(!capability.to_string().contains("aearn-preview"));
        assert!(!capability.to_string().contains("\"*\""));
        assert!(build_script.contains("AppManifest::new().commands(APP_COMMANDS)"));
        let permissions = capability
            .get("permissions")
            .and_then(|value| value.as_array())
            .unwrap();
        for command in [
            "preview-host-create",
            "preview-host-update-source",
            "preview-host-set-bounds",
            "preview-host-recreate",
            "preview-host-close",
        ] {
            assert!(permissions.contains(&serde_json::Value::String(format!("allow-{command}"))));
            assert!(build_script.contains(&command.replace('-', "_")));
        }
    }

    #[test]
    fn host_uses_custom_protocol_and_script_only_sandbox() {
        let source = include_str!("preview_host.rs");
        assert!(source.contains("WebviewUrl::CustomProtocol(url)"));
        assert!(!source.contains(&["WebviewUrl::", "External(url)"].concat()));
        assert!(source.contains(".on_new_window(|_, _| NewWindowResponse::Deny)"));
        assert!(source.contains("DownloadEvent::Requested"));
        assert!(source.contains(".incognito(true)"));
        assert!(source.contains(".devtools(false)"));
        let html = build_preview_host_html("host-1", &record());
        assert!(html.contains("sandbox=\"allow-scripts\""));
        assert!(!html.contains("allow-same-origin"));
        assert!(!html.contains("allow-forms"));
        assert!(!html.contains("allow-popups"));
    }

    #[test]
    fn recreation_rotates_the_webview_environment_directory() {
        assert_ne!(
            preview_data_directory("host-1", 1),
            preview_data_directory("host-1", 2)
        );
        let source = include_str!("preview_host.rs");
        assert!(source.contains(
            "current.data_directory = preview_data_directory(&request.host_id, current.generation)"
        ));
    }

    #[test]
    fn protocol_csp_denies_network_forms_objects_and_external_frames() {
        let response = preview_html_response(build_preview_host_html("host-1", &record()));
        let csp = response
            .headers()
            .get(header::CONTENT_SECURITY_POLICY)
            .unwrap()
            .to_str()
            .unwrap();
        assert!(csp.contains("default-src 'none'"));
        assert!(csp.contains("connect-src 'none'"));
        assert!(csp.contains("form-action 'none'"));
        assert!(csp.contains("object-src 'none'"));
        assert!(csp.contains("base-uri 'none'"));
        assert!(csp.contains("frame-src 'self'"));
        assert!(!csp.contains("http:"));
        assert!(!csp.contains("https:"));
    }

    #[test]
    fn source_is_encoded_and_not_promoted_into_trusted_host_markup() {
        let mut record = record();
        record.source = "</script><script>window.__escaped = false</script>".into();
        record.source_hash = sha256_hex(record.source.as_bytes());
        let html = build_preview_host_html("host-1", &record);
        assert!(!html.contains("</script><script>window.__escaped = false</script>"));
        assert!(html.contains("\\u003c/script\\u003e"));
    }

    #[test]
    fn ready_heartbeat_originates_inside_the_learner_frame_event_loop() {
        let html = build_preview_host_html("host-1", &record());
        assert!(html.contains("frame.srcdoc = documentSource"));
        assert!(html.contains("setInterval(() => report({ kind: 'ready' }), 750)"));
        assert!(html.contains("bridge_token: bridgeToken"));
        assert!(html.contains("if (!event.isTrusted) return;"));
        assert!(html.contains("bridgeToken === null"));
        assert!(!html.contains("setInterval(() => emit({ kind: 'ready' }), 750)"));
        assert!(!html.contains("Worker("));
    }

    #[test]
    fn navigation_allows_only_the_exact_owned_custom_protocol_page() {
        assert!(preview_navigation_allowed(
            &Url::parse("aearn-preview://localhost/host/host-1?generation=1&nonce=x").unwrap(),
            "host-1"
        ));
        assert!(preview_navigation_allowed(
            &Url::parse("https://aearn-preview.localhost/host/host-1?generation=1&nonce=x")
                .unwrap(),
            "host-1"
        ));
        assert!(!preview_navigation_allowed(
            &Url::parse("https://example.com/").unwrap(),
            "host-1"
        ));
        assert!(!preview_navigation_allowed(
            &Url::parse("https://aearn-preview.localhost/host/host-2").unwrap(),
            "host-1"
        ));
        assert!(!preview_navigation_allowed(
            &Url::parse("https://aearn-preview.localhost:444/host/host-1").unwrap(),
            "host-1"
        ));
        assert!(!preview_navigation_allowed(
            &Url::parse("https://user@aearn-preview.localhost/host/host-1").unwrap(),
            "host-1"
        ));
        assert!(!preview_navigation_allowed(
            &Url::parse("https://aearn-preview.localhost/host/host-1#fragment").unwrap(),
            "host-1"
        ));
    }

    #[test]
    fn bridge_rejects_nonce_scope_version_replay_and_oversized_messages() {
        let manager = PreviewHostManager::default();
        manager
            .hosts
            .lock()
            .unwrap()
            .insert("host-1".into(), record());
        let valid = serde_json::json!({
            "hostId": "host-1",
            "nonce": "a".repeat(64),
            "artifactId": "artifact-1",
            "sourceArtifactId": "artifact-1",
            "sessionId": "session-1",
            "artifactVersion": 3,
            "generation": 1,
            "sequence": 1,
            "event": {"kind": "ready"}
        });
        let title = format!("{PREVIEW_EVENT_PREFIX}{valid}");
        assert!(manager.accept_title_event("host-1", &title).is_some());
        assert!(manager.accept_title_event("host-1", &title).is_none());

        for (key, value) in [
            ("nonce", serde_json::Value::String("b".repeat(64))),
            ("artifactId", serde_json::Value::String("artifact-2".into())),
            (
                "sourceArtifactId",
                serde_json::Value::String("artifact-2".into()),
            ),
            ("sessionId", serde_json::Value::String("session-2".into())),
            ("artifactVersion", serde_json::Value::Number(4.into())),
            ("generation", serde_json::Value::Number(2.into())),
        ] {
            let mut invalid = valid.clone();
            invalid[key] = value;
            invalid["sequence"] = serde_json::Value::Number(2.into());
            assert!(manager
                .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{invalid}"))
                .is_none());
        }

        let mut gap = valid.clone();
        gap["sequence"] = serde_json::Value::Number(3.into());
        gap["event"] = serde_json::json!({
            "kind": "interaction_event",
            "event_key": "demo.click.completed",
            "payload_json": {"count": 1}
        });
        assert!(manager
            .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{gap}"))
            .is_none());

        let mut interaction = valid.clone();
        interaction["sequence"] = serde_json::Value::Number(2.into());
        interaction["event"] = serde_json::json!({
            "kind": "interaction_event",
            "event_key": "demo.click.completed",
            "payload_json": {"count": 1}
        });
        assert!(manager
            .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{interaction}"))
            .is_some());

        let mut oversized = valid;
        oversized["sequence"] = serde_json::Value::Number(3.into());
        oversized["event"] = serde_json::json!({
            "kind": "runtime_error",
            "message": "x".repeat(MAX_MESSAGE_CHARS + 1)
        });
        assert!(manager
            .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{oversized}"))
            .is_none());

        let mut extra = serde_json::json!({
            "hostId": "host-1",
            "nonce": "a".repeat(64),
            "artifactId": "artifact-1",
            "sourceArtifactId": "artifact-1",
            "sessionId": "session-1",
            "artifactVersion": 3,
            "generation": 1,
            "sequence": 3,
            "event": {"kind": "ready"},
            "extra": true
        });
        assert!(manager
            .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{extra}"))
            .is_none());
        extra.as_object_mut().unwrap().remove("extra");
        extra["sequence"] = serde_json::Value::Number(0.into());
        assert!(manager
            .accept_title_event("host-1", &format!("{PREVIEW_EVENT_PREFIX}{extra}"))
            .is_none());
    }

    #[test]
    fn source_hash_and_bounds_fail_closed() {
        assert!(validate_source("ok", &sha256_hex(b"ok")).is_ok());
        assert!(validate_source("ok", &"0".repeat(64)).is_err());
        assert!(validate_bounds(PreviewBounds {
            x: 0.0,
            y: 0.0,
            width: 400.0,
            height: 300.0,
        })
        .is_ok());
        assert!(validate_bounds(PreviewBounds {
            x: 0.0,
            y: 0.0,
            width: 0.0,
            height: 300.0,
        })
        .is_err());
    }
}
