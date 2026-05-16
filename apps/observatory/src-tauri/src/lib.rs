use serde_json::Value;
use std::{
    collections::HashMap,
    process::Command,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, State,
};
use thiserror::Error;

#[derive(Clone)]
struct ObservatoryState {
    cli_lock: Arc<Mutex<()>>,
    cache: Arc<Mutex<HashMap<String, CacheEntry>>>,
}

#[derive(Clone)]
struct CacheEntry {
    created_at: Instant,
    payload: Value,
}

#[derive(Debug, Error)]
enum ObservatoryError {
    #[error("Autopsy CLI lock failed")]
    Lock,
    #[error("Autopsy CLI failed: {0}")]
    Cli(String),
    #[error("Autopsy output was not valid JSON: {0}")]
    Json(String),
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

fn command_cache_key(args: &[String]) -> String {
    args.join("\u{1f}")
}

fn stamp_payload(mut payload: Value, args: &[String], elapsed_ms: u128, cache_hit: bool) -> Value {
    if let Value::Object(ref mut object) = payload {
        object.insert(
            "observatory".to_string(),
            serde_json::json!({
                "elapsed_ms": elapsed_ms,
                "args": args,
                "serialized_cli": true,
                "cache_hit": cache_hit
            }),
        );
    }
    payload
}

fn parse_json_stdout(stdout: &[u8]) -> ObservatoryResult<Value> {
    let text = String::from_utf8_lossy(stdout).trim().to_string();
    serde_json::from_str::<Value>(&text).map_err(|error| {
        let preview: String = text.chars().take(800).collect();
        ObservatoryError::Json(format!("{error}; stdout preview: {preview}"))
    })
}

fn run_autopsy_json_sync(args: Vec<String>, lock: Arc<Mutex<()>>) -> ObservatoryResult<Value> {
    let _guard = lock.lock().map_err(|_| ObservatoryError::Lock)?;
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
            "args={args:?}; status={}; elapsed_ms={}; stderr={}; stdout={}",
            output.status,
            started.elapsed().as_millis(),
            stderr.chars().take(1200).collect::<String>(),
            stdout.chars().take(600).collect::<String>()
        )));
    }

    let payload = parse_json_stdout(&output.stdout)?;
    Ok(stamp_payload(
        payload,
        &args,
        started.elapsed().as_millis(),
        false,
    ))
}

async fn run_autopsy_json(
    state: State<'_, ObservatoryState>,
    args: Vec<String>,
    cacheable: bool,
) -> ObservatoryResult<Value> {
    let cache_key = command_cache_key(&args);
    if cacheable {
        let hit = state
            .cache
            .lock()
            .map_err(|_| ObservatoryError::Lock)?
            .get(&cache_key)
            .filter(|entry| entry.created_at.elapsed() <= CACHE_TTL)
            .cloned();

        if let Some(entry) = hit {
            return Ok(stamp_payload(entry.payload, &args, 0, true));
        }
    }

    let lock = state.cli_lock.clone();
    let cache = state.cache.clone();
    let cache_args = args.clone();
    let cache_key_for_write = cache_key.clone();
    let payload = tauri::async_runtime::spawn_blocking(move || run_autopsy_json_sync(args, lock))
        .await
        .map_err(|error| ObservatoryError::Join(error.to_string()))??;

    if cacheable {
        cache.lock().map_err(|_| ObservatoryError::Lock)?.insert(
            cache_key_for_write,
            CacheEntry {
                created_at: Instant::now(),
                payload: payload.clone(),
            },
        );
    }

    let elapsed_ms = payload
        .get("observatory")
        .and_then(|value| value.get("elapsed_ms"))
        .and_then(Value::as_u64)
        .map(u128::from)
        .unwrap_or(0);
    Ok(stamp_payload(payload, &cache_args, elapsed_ms, false))
}

#[tauri::command]
async fn autopsy_health(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["health".into()], true).await
}

#[tauri::command]
async fn autopsy_status(
    state: State<'_, ObservatoryState>,
    limit: Option<u32>,
    section_limit: Option<u32>,
) -> ObservatoryResult<Value> {
    run_autopsy_json(
        state,
        vec![
            "status".into(),
            "--current-only".into(),
            "--limit".into(),
            limit.unwrap_or(8).to_string(),
            "--section-limit".into(),
            section_limit.unwrap_or(4).to_string(),
        ],
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
    run_autopsy_json(
        state,
        vec![
            "consult".into(),
            "--current-only".into(),
            "--query".into(),
            query,
            "--limit".into(),
            limit.unwrap_or(5).to_string(),
            "--inspect-limit".into(),
            inspect_limit.unwrap_or(3).to_string(),
            "--route".into(),
            route.into(),
        ],
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_item(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["item".into(), stable_key], true).await
}

#[tauri::command]
async fn autopsy_neighbors(
    state: State<'_, ObservatoryState>,
    stable_key: String,
    limit: Option<u32>,
) -> ObservatoryResult<Value> {
    run_autopsy_json(
        state,
        vec![
            "neighbors".into(),
            "--stable-key".into(),
            stable_key,
            "--limit".into(),
            limit.unwrap_or(16).to_string(),
        ],
        true,
    )
    .await
}

#[tauri::command]
async fn autopsy_timeline(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["timeline".into(), stable_key], true).await
}

#[tauri::command]
async fn autopsy_backup(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["backup".into()], false).await
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
            cli_lock: Arc::new(Mutex::new(())),
            cache: Arc::new(Mutex::new(HashMap::new())),
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
