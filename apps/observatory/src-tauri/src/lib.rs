use fs2::FileExt;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    fs::{self, OpenOptions},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State,
};
use thiserror::Error;

#[derive(Clone)]
struct ObservatoryState {
    process_lock: Arc<Mutex<()>>,
    cache: Arc<Mutex<HashMap<String, CacheEntry>>>,
    worker_runtime: Arc<Mutex<Option<WorkerRuntime>>>,
}

#[derive(Clone)]
struct CacheEntry {
    created_at: Instant,
    payload: Value,
}

#[derive(Clone, Debug)]
struct WorkerRuntime {
    python: PathBuf,
    worker: PathBuf,
    tool: PathBuf,
}

#[derive(Clone, Debug, Deserialize)]
struct WorkerInfo {
    base_url: String,
    token: String,
    pid: Option<u32>,
}

#[derive(Debug, Error)]
enum ObservatoryError {
    #[error("Autopsy lock failed")]
    Lock,
    #[error("Autopsy worker failed: {0}")]
    Worker(String),
    #[error("Autopsy CLI failed: {0}")]
    Cli(String),
    #[error("Autopsy output was not valid JSON: {0}")]
    Json(String),
    #[error("I/O failed: {0}")]
    Io(String),
    #[error("HTTP request failed: {0}")]
    Http(String),
    #[error("Background task failed: {0}")]
    Join(String),
}

impl serde::Serialize for ObservatoryError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::ser::Serializer,
    {
        serializer.serialize_str(self.to_string().as_ref())
    }
}

type ObservatoryResult<T> = Result<T, ObservatoryError>;

const CACHE_TTL: Duration = Duration::from_secs(20);
const WORKER_STARTUP_TIMEOUT: Duration = Duration::from_secs(12);

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn app_support_dir() -> PathBuf {
    env::var_os("AUTOPSY_APP_SUPPORT_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            home_dir()
                .join("Library")
                .join("Application Support")
                .join("Autopsy")
        })
}

fn default_workspace_root() -> PathBuf {
    env::var_os("AUTOPSY_UNIFIED_MEMORY_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|| home_dir().join("github").join("codex"))
}

fn info_file() -> PathBuf {
    app_support_dir().join("CLI").join("ml-worker.json")
}

fn lock_file() -> PathBuf {
    app_support_dir().join("CLI").join("ml-worker.lock")
}

fn worker_log_file() -> PathBuf {
    app_support_dir()
        .join("CLI")
        .join("observatory-worker.stderr.log")
}

fn falkordb_lite_path() -> PathBuf {
    env::var_os("AUTOPSY_FALKORDB_LITE_PATH")
        .map(PathBuf::from)
        .unwrap_or_else(|| app_support_dir().join("FalkorDB").join("autopsy-memory.db"))
}

fn falkordb_lite_settings_file() -> PathBuf {
    PathBuf::from(format!(
        "{}.settings",
        falkordb_lite_path().to_string_lossy()
    ))
}

fn source_python_path() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest_dir.parent()?.parent()?.parent()?;
    let source = repo_root.join("src");
    if source.join("autopsy_memory").exists() {
        Some(source)
    } else {
        None
    }
}

fn pythonpath_with_source() -> Option<String> {
    let mut entries = Vec::new();
    if let Some(source) = source_python_path() {
        entries.push(source.to_string_lossy().to_string());
    }
    if let Some(existing) = env::var_os("PYTHONPATH") {
        let existing = existing.to_string_lossy().to_string();
        if !existing.is_empty() {
            entries.push(existing);
        }
    }
    if entries.is_empty() {
        None
    } else {
        Some(entries.join(if cfg!(windows) { ";" } else { ":" }))
    }
}

fn python_candidates() -> Vec<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(path) = env::var_os("AUTOPSY_PYTHON") {
        candidates.push(PathBuf::from(path));
    }
    candidates.push(
        app_support_dir()
            .join("Python")
            .join("runtime")
            .join("bin")
            .join("python"),
    );
    candidates.push(PathBuf::from(
        "/opt/homebrew/opt/autopsy-memory/venv/bin/python",
    ));
    candidates.push(PathBuf::from(
        "/usr/local/opt/autopsy-memory/venv/bin/python",
    ));
    if let Some(paths) = env::var_os("PATH") {
        for directory in env::split_paths(&paths) {
            candidates.push(directory.join("python3"));
        }
    }
    candidates.push(PathBuf::from("/opt/homebrew/bin/python3"));
    candidates.push(PathBuf::from("/usr/local/bin/python3"));
    candidates.push(PathBuf::from("/usr/bin/python3"));

    let mut unique = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for candidate in candidates {
        let key = candidate.to_string_lossy().to_string();
        if seen.insert(key) {
            unique.push(candidate);
        }
    }
    unique
}

fn discover_runtime_with_python(python: &Path) -> Option<WorkerRuntime> {
    if !python.exists() {
        return None;
    }
    let code = r#"
import importlib
import json
for module_name in ("redislite.falkordb_client", "falkordb", "redis", "autopsy_memory.worker", "autopsy_memory.cli"):
    importlib.import_module(module_name)
import autopsy_memory.worker as worker
import autopsy_memory.cli as cli
print(json.dumps({"worker": worker.__file__, "tool": cli.__file__}))
"#;
    let mut command = Command::new(python);
    command.arg("-c").arg(code);
    if let Some(pythonpath) = pythonpath_with_source() {
        command.env("PYTHONPATH", pythonpath);
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let value: Value = serde_json::from_slice(&output.stdout).ok()?;
    let worker = env::var_os("AUTOPSY_WORKER_SCRIPT")
        .map(PathBuf::from)
        .or_else(|| {
            value
                .get("worker")
                .and_then(Value::as_str)
                .map(PathBuf::from)
        })?;
    let tool = env::var_os("AUTOPSY_MEMORY_TOOL")
        .map(PathBuf::from)
        .or_else(|| value.get("tool").and_then(Value::as_str).map(PathBuf::from))?;
    Some(WorkerRuntime {
        python: python.to_path_buf(),
        worker,
        tool,
    })
}

fn resolve_worker_runtime(state: &ObservatoryState) -> ObservatoryResult<WorkerRuntime> {
    if let Some(runtime) = state
        .worker_runtime
        .lock()
        .map_err(|_| ObservatoryError::Lock)?
        .clone()
    {
        return Ok(runtime);
    }

    let candidates = python_candidates();
    for candidate in &candidates {
        if let Some(runtime) = discover_runtime_with_python(candidate) {
            *state
                .worker_runtime
                .lock()
                .map_err(|_| ObservatoryError::Lock)? = Some(runtime.clone());
            return Ok(runtime);
        }
    }

    let searched = candidates
        .iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect::<Vec<_>>()
        .join(", ");
    Err(ObservatoryError::Worker(format!(
        "no Python runtime could import autopsy_memory.worker, falkordb, redis, and redislite; searched: {searched}"
    )))
}

fn default_worker_environment() -> HashMap<String, String> {
    let mut values = HashMap::new();
    values.insert(
        "AUTOPSY_UNIFIED_MEMORY".to_string(),
        env::var("AUTOPSY_UNIFIED_MEMORY").unwrap_or_else(|_| "1".to_string()),
    );
    values.insert(
        "AUTOPSY_UNIFIED_MEMORY_ROOT".to_string(),
        env::var("AUTOPSY_UNIFIED_MEMORY_ROOT")
            .unwrap_or_else(|_| default_workspace_root().to_string_lossy().to_string()),
    );
    values.insert("AUTOPSY_MEMORY_BACKEND".to_string(), "falkordb".to_string());
    values.insert("AUTOPSY_FALKORDB_ENABLED".to_string(), "1".to_string());
    values.insert(
        "AUTOPSY_FALKORDB_GRAPH_NAME".to_string(),
        env::var("AUTOPSY_FALKORDB_GRAPH_NAME").unwrap_or_else(|_| "autopsy_memory".to_string()),
    );
    if env::var_os("AUTOPSY_FALKORDB_HOST").is_none()
        && env::var_os("AUTOPSY_FALKORDB_PORT").is_none()
    {
        values.insert(
            "AUTOPSY_FALKORDB_LITE_PATH".to_string(),
            falkordb_lite_path().to_string_lossy().to_string(),
        );
    }
    values
}

fn read_worker_info() -> Option<WorkerInfo> {
    let text = fs::read_to_string(info_file()).ok()?;
    serde_json::from_str(&text).ok()
}

fn clear_worker_info() {
    let _ = fs::remove_file(info_file());
}

#[cfg(target_family = "unix")]
fn terminate_pid(pid: Option<u32>) {
    if let Some(pid) = pid {
        if pid > 0 && pid != std::process::id() {
            let _ = Command::new("kill")
                .arg("-TERM")
                .arg(pid.to_string())
                .output();
        }
    }
}

#[cfg(target_family = "windows")]
fn terminate_pid(pid: Option<u32>) {
    if let Some(pid) = pid {
        if pid > 0 && pid != std::process::id() {
            let _ = Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/T", "/F"])
                .output();
        }
    }
}

fn worker_health_check(info: &WorkerInfo, timeout: Duration) -> bool {
    let client = match reqwest::blocking::Client::builder()
        .timeout(timeout)
        .build()
    {
        Ok(client) => client,
        Err(_) => return false,
    };
    let url = format!("{}/health", info.base_url.trim_end_matches('/'));
    let response = client
        .get(url)
        .header("x-autopsy-token", &info.token)
        .send();
    let Ok(response) = response else {
        return false;
    };
    if !response.status().is_success() {
        return false;
    }
    let Ok(payload) = response.json::<Value>() else {
        return false;
    };
    payload.get("ok").and_then(Value::as_bool).unwrap_or(false)
}

fn token() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    format!("{:x}{:x}", nanos, std::process::id())
}

fn start_worker_locked(state: &ObservatoryState) -> ObservatoryResult<WorkerInfo> {
    if let Some(info) =
        read_worker_info().filter(|info| worker_health_check(info, Duration::from_secs(2)))
    {
        return Ok(info);
    }

    if let Some(info) = read_worker_info() {
        terminate_pid(info.pid);
    }
    clear_worker_info();

    let runtime = resolve_worker_runtime(state)?;
    if !runtime.worker.exists() {
        return Err(ObservatoryError::Worker(format!(
            "Autopsy worker script not found: {}",
            runtime.worker.display()
        )));
    }
    if !runtime.tool.exists() {
        return Err(ObservatoryError::Worker(format!(
            "Autopsy memory tool not found: {}",
            runtime.tool.display()
        )));
    }

    if let Some(parent) = info_file().parent() {
        fs::create_dir_all(parent).map_err(|error| ObservatoryError::Io(error.to_string()))?;
    }
    if let Some(parent) = worker_log_file().parent() {
        fs::create_dir_all(parent).map_err(|error| ObservatoryError::Io(error.to_string()))?;
    }

    let token = token();
    let stderr = OpenOptions::new()
        .create(true)
        .append(true)
        .open(worker_log_file())
        .map_err(|error| ObservatoryError::Io(error.to_string()))?;
    let mut command = Command::new(&runtime.python);
    command
        .arg(&runtime.worker)
        .arg("--token")
        .arg(&token)
        .arg("--info-file")
        .arg(info_file())
        .envs(default_worker_environment())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::from(stderr));
    if let Some(pythonpath) = pythonpath_with_source() {
        command.env("PYTHONPATH", pythonpath);
    }
    let child = command.spawn().map_err(|error| {
        ObservatoryError::Worker(format!("failed to start Autopsy worker: {error}"))
    })?;

    let started = Instant::now();
    while started.elapsed() < WORKER_STARTUP_TIMEOUT {
        if let Some(info) = read_worker_info() {
            if info.token == token && worker_health_check(&info, Duration::from_millis(500)) {
                return Ok(info);
            }
        }
        thread::sleep(Duration::from_millis(100));
    }

    terminate_pid(Some(child.id()));
    clear_worker_info();
    Err(ObservatoryError::Worker(format!(
        "Autopsy worker did not become healthy. See {}",
        worker_log_file().display()
    )))
}

fn ensure_worker(state: &ObservatoryState) -> ObservatoryResult<WorkerInfo> {
    if let Some(info) =
        read_worker_info().filter(|info| worker_health_check(info, Duration::from_secs(2)))
    {
        return Ok(info);
    }

    if let Some(parent) = lock_file().parent() {
        fs::create_dir_all(parent).map_err(|error| ObservatoryError::Io(error.to_string()))?;
    }
    let lock = OpenOptions::new()
        .create(true)
        .read(true)
        .write(true)
        .open(lock_file())
        .map_err(|error| ObservatoryError::Io(error.to_string()))?;
    lock.lock_exclusive()
        .map_err(|error| ObservatoryError::Io(error.to_string()))?;
    let result = start_worker_locked(state);
    let _ = lock.unlock();
    result
}

fn worker_payload(state: &ObservatoryState, request: Value) -> ObservatoryResult<Value> {
    let runtime = resolve_worker_runtime(state)?;
    let workspace = default_workspace_root().to_string_lossy().to_string();
    Ok(json!({
        "tool_path": runtime.tool.to_string_lossy(),
        "workspace": workspace,
        "cwd": workspace,
        "request": request
    }))
}

fn response_error_message(text: &str) -> String {
    serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|value| {
            value
                .get("error")
                .and_then(Value::as_str)
                .map(str::to_string)
        })
        .filter(|message| !message.is_empty())
        .unwrap_or_else(|| text.chars().take(1200).collect())
}

fn is_stale_falkor_socket_error(message: &str) -> bool {
    let lowered = message.to_lowercase();
    lowered.contains("redis.socket")
        && (lowered.contains("connection refused")
            || lowered.contains("no such file")
            || lowered.contains("error 2 connecting")
            || lowered.contains("stale"))
}

fn is_stale_worker_route_error(message: &str) -> bool {
    let lowered = message.trim().to_lowercase();
    lowered == "not found"
        || lowered.contains("404")
        || lowered.contains("attempted relative import with no known parent package")
}

fn backup_stale_falkor_settings() -> Option<PathBuf> {
    let settings = falkordb_lite_settings_file();
    if !settings.exists() {
        return None;
    }
    let suffix = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    let backup = settings.with_file_name(format!(
        "{}.stale-{suffix}",
        settings.file_name()?.to_string_lossy()
    ));
    fs::rename(&settings, &backup).ok()?;
    Some(backup)
}

fn recover_stale_falkor_socket(info: &WorkerInfo) {
    terminate_pid(info.pid);
    clear_worker_info();
    let _ = backup_stale_falkor_settings();
}

fn post_worker_request(info: &WorkerInfo, path: &str, payload: &Value) -> ObservatoryResult<Value> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .map_err(|error| ObservatoryError::Http(error.to_string()))?;
    let url = format!("{}{}", info.base_url.trim_end_matches('/'), path);
    let response = client
        .post(url)
        .header("content-type", "application/json")
        .header("x-autopsy-token", &info.token)
        .json(payload)
        .send()
        .map_err(|error| ObservatoryError::Http(error.to_string()))?;
    let status = response.status();
    let text = response
        .text()
        .map_err(|error| ObservatoryError::Http(error.to_string()))?;
    if !status.is_success() {
        return Err(ObservatoryError::Worker(response_error_message(&text)));
    }
    serde_json::from_str(&text).map_err(|error| {
        ObservatoryError::Json(format!(
            "{error}; worker response preview: {}",
            text.chars().take(800).collect::<String>()
        ))
    })
}

fn worker_request(
    state: &ObservatoryState,
    path: &str,
    request: Value,
    retry_on_stale_socket: bool,
) -> ObservatoryResult<Value> {
    let info = ensure_worker(state)?;
    let payload = worker_payload(state, request)?;
    match post_worker_request(&info, path, &payload) {
        Ok(payload) => Ok(payload),
        Err(ObservatoryError::Worker(message))
            if retry_on_stale_socket && is_stale_falkor_socket_error(&message) =>
        {
            recover_stale_falkor_socket(&info);
            worker_request(state, path, payload_for_retry(&payload), false)
        }
        Err(ObservatoryError::Worker(message))
            if retry_on_stale_socket && is_stale_worker_route_error(&message) =>
        {
            terminate_pid(info.pid);
            clear_worker_info();
            worker_request(state, path, payload_for_retry(&payload), false)
        }
        Err(ObservatoryError::Http(_)) if retry_on_stale_socket => {
            terminate_pid(info.pid);
            clear_worker_info();
            let request = payload_for_retry(&payload);
            worker_request(state, path, request, false)
        }
        Err(error) => Err(error),
    }
}

fn payload_for_retry(payload: &Value) -> Value {
    payload.get("request").cloned().unwrap_or_else(|| json!({}))
}

fn cache_key(source: &str, operation: &Value) -> String {
    format!(
        "{source}:{}",
        serde_json::to_string(operation).unwrap_or_else(|_| "<invalid>".to_string())
    )
}

fn stamp_payload(
    mut payload: Value,
    operation: &Value,
    elapsed_ms: u128,
    cache_hit: bool,
    source: &str,
) -> Value {
    if let Value::Object(ref mut object) = payload {
        object.insert(
            "observatory".to_string(),
            json!({
                "elapsed_ms": elapsed_ms,
                "operation": operation,
                "source": source,
                "worker_rpc": source == "worker",
                "cli_process": source == "cli",
                "cache_hit": cache_hit
            }),
        );
    }
    payload
}

fn cached_payload(state: &ObservatoryState, key: &str) -> ObservatoryResult<Option<Value>> {
    Ok(state
        .cache
        .lock()
        .map_err(|_| ObservatoryError::Lock)?
        .get(key)
        .filter(|entry| entry.created_at.elapsed() <= CACHE_TTL)
        .map(|entry| entry.payload.clone()))
}

fn store_cache(state: &ObservatoryState, key: String, payload: Value) -> ObservatoryResult<()> {
    state
        .cache
        .lock()
        .map_err(|_| ObservatoryError::Lock)?
        .insert(
            key,
            CacheEntry {
                created_at: Instant::now(),
                payload,
            },
        );
    Ok(())
}

fn run_worker_json_sync(
    state: ObservatoryState,
    path: String,
    request: Value,
    cacheable: bool,
) -> ObservatoryResult<Value> {
    let operation = json!({"path": path, "request": request});
    let key = cache_key("worker", &operation);
    if cacheable {
        if let Some(payload) = cached_payload(&state, &key)? {
            return Ok(stamp_payload(payload, &operation, 0, true, "worker"));
        }
    }

    let started = Instant::now();
    let payload = worker_request(
        &state,
        operation["path"].as_str().unwrap_or(""),
        operation["request"].clone(),
        true,
    )?;
    let elapsed_ms = started.elapsed().as_millis();
    if cacheable {
        store_cache(&state, key, payload.clone())?;
    }
    Ok(stamp_payload(
        payload, &operation, elapsed_ms, false, "worker",
    ))
}

async fn run_worker_json(
    state: State<'_, ObservatoryState>,
    path: impl Into<String>,
    request: Value,
    cacheable: bool,
) -> ObservatoryResult<Value> {
    let state = state.inner().clone();
    let path = path.into();
    tauri::async_runtime::spawn_blocking(move || {
        run_worker_json_sync(state, path, request, cacheable)
    })
    .await
    .map_err(|error| ObservatoryError::Join(error.to_string()))?
}

fn parse_json_stdout(stdout: &[u8]) -> ObservatoryResult<Value> {
    let text = String::from_utf8_lossy(stdout).trim().to_string();
    serde_json::from_str::<Value>(&text).map_err(|error| {
        let preview: String = text.chars().take(800).collect();
        ObservatoryError::Json(format!("{error}; stdout preview: {preview}"))
    })
}

fn run_autopsy_cli_json_sync(args: Vec<String>, lock: Arc<Mutex<()>>) -> ObservatoryResult<Value> {
    let _guard = lock.lock().map_err(|_| ObservatoryError::Lock)?;
    let operation = json!({"command": "autopsy", "args": args.clone()});
    let started = Instant::now();
    let output = Command::new("autopsy")
        .args(&args)
        .env("AUTOPSY_UNIFIED_MEMORY", "1")
        .output()
        .map_err(|error| ObservatoryError::Cli(format!("failed to start autopsy: {error}")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        return Err(ObservatoryError::Cli(format!(
            "operation={operation}; status={}; elapsed_ms={}; stderr={}; stdout={}",
            output.status,
            started.elapsed().as_millis(),
            stderr.chars().take(1200).collect::<String>(),
            stdout.chars().take(600).collect::<String>()
        )));
    }

    let payload = parse_json_stdout(&output.stdout)?;
    Ok(stamp_payload(
        payload,
        &operation,
        started.elapsed().as_millis(),
        false,
        "cli",
    ))
}

async fn run_autopsy_cli_json(
    state: State<'_, ObservatoryState>,
    args: Vec<String>,
) -> ObservatoryResult<Value> {
    let lock = state.process_lock.clone();
    tauri::async_runtime::spawn_blocking(move || run_autopsy_cli_json_sync(args, lock))
        .await
        .map_err(|error| ObservatoryError::Join(error.to_string()))?
}

#[tauri::command]
async fn autopsy_health(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_worker_json(state, "/memory/health", json!({}), true).await
}

#[tauri::command]
async fn autopsy_status(
    state: State<'_, ObservatoryState>,
    limit: Option<u32>,
    section_limit: Option<u32>,
) -> ObservatoryResult<Value> {
    run_worker_json(
        state,
        "/memory/status",
        json!({
            "limit": limit.unwrap_or(8),
            "section_limit": section_limit.unwrap_or(4),
            "recent_days": 21
        }),
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_consult(
    state: State<'_, ObservatoryState>,
    query: String,
    limit: Option<u32>,
    inspect_limit: Option<u32>,
    route: Option<String>,
) -> ObservatoryResult<Value> {
    let route = match route.as_deref() {
        Some("auto") => "auto",
        Some("status") => "status",
        Some("hybrid") => "hybrid",
        Some("lexical") | None => "lexical",
        Some(_) => "lexical",
    };
    run_worker_json(
        state,
        "/memory/consult",
        json!({
            "query": query,
            "current_only": true,
            "limit": limit.unwrap_or(5),
            "inspect_limit": inspect_limit.unwrap_or(3),
            "route": route
        }),
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_item(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_worker_json(
        state,
        "/memory/graph/item",
        json!({ "stable_key": stable_key }),
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_neighbors(
    state: State<'_, ObservatoryState>,
    stable_key: String,
    limit: Option<u32>,
) -> ObservatoryResult<Value> {
    run_worker_json(
        state,
        "/memory/neighbors",
        json!({
            "stable_key": stable_key,
            "relation_limit": limit.unwrap_or(16)
        }),
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_timeline(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_worker_json(
        state,
        "/memory/timeline",
        json!({ "stable_key": stable_key }),
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_backup(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_autopsy_cli_json(state, vec!["backup".into()]).await
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn install_tray(app: &mut tauri::App) -> tauri::Result<()> {
    let open_item = MenuItem::with_id(app, "open", "Open Observatory", true, None::<&str>)?;
    let health_item = MenuItem::with_id(app, "run_health", "Run Health", true, None::<&str>)?;
    let backup_item = MenuItem::with_id(app, "run_backup", "Run Backup", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_item, &health_item, &backup_item, &quit_item])?;

    TrayIconBuilder::with_id("autopsy-observatory")
        .tooltip("Autopsy Observatory")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_main_window(app),
            "run_health" => {
                show_main_window(app);
                let _ = app.emit("observatory://run-health", ());
            }
            "run_backup" => {
                show_main_window(app);
                let _ = app.emit("observatory://run-backup", ());
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .manage(ObservatoryState {
            process_lock: Arc::new(Mutex::new(())),
            cache: Arc::new(Mutex::new(HashMap::new())),
            worker_runtime: Arc::new(Mutex::new(None)),
        })
        .invoke_handler(tauri::generate_handler![
            autopsy_health,
            autopsy_status,
            autopsy_consult,
            autopsy_item,
            autopsy_neighbors,
            autopsy_timeline,
            autopsy_backup
        ])
        .setup(|app| {
            install_tray(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Autopsy Observatory");
}
