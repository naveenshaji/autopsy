use serde_json::Value;
use std::{
    process::Command,
    sync::{Arc, Mutex},
    time::Instant,
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

    let mut payload = parse_json_stdout(&output.stdout)?;
    if let Value::Object(ref mut object) = payload {
        object.insert(
            "observatory".to_string(),
            serde_json::json!({
                "elapsed_ms": started.elapsed().as_millis(),
                "args": args,
                "serialized_cli": true
            }),
        );
    }
    Ok(payload)
}

async fn run_autopsy_json(
    state: State<'_, ObservatoryState>,
    args: Vec<String>,
) -> ObservatoryResult<Value> {
    let lock = state.cli_lock.clone();
    tauri::async_runtime::spawn_blocking(move || run_autopsy_json_sync(args, lock))
        .await
        .map_err(|error| ObservatoryError::Join(error.to_string()))?
}

#[tauri::command]
async fn autopsy_health(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["health".into()]).await
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
    )
    .await
}

#[tauri::command]
async fn autopsy_consult(
    state: State<'_, ObservatoryState>,
    query: String,
    limit: Option<u32>,
    inspect_limit: Option<u32>,
) -> ObservatoryResult<Value> {
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
        ],
    )
    .await
}

#[tauri::command]
async fn autopsy_item(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["item".into(), stable_key]).await
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
    )
    .await
}

#[tauri::command]
async fn autopsy_timeline(
    state: State<'_, ObservatoryState>,
    stable_key: String,
) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["timeline".into(), stable_key]).await
}

#[tauri::command]
async fn autopsy_backup(state: State<'_, ObservatoryState>) -> ObservatoryResult<Value> {
    run_autopsy_json(state, vec!["backup".into()]).await
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
