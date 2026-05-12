/// Vanilla — Tauri application library
///
/// Handles:
/// - Sidecar lifecycle: spawn the Python FastAPI process, read its port
///   from stdout, emit "sidecar-ready" event to frontend
/// - Plugin registration (shell, fs, dialog, global-shortcut, clipboard)
/// - Global hotkeys: Ctrl+Shift+Space (voice), Ctrl+Shift+V (clip clipboard)
/// - Tauri command handlers

use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_updater::UpdaterExt;

/// Shared state holding the sidecar's dynamic port.
/// Populated by spawn_sidecar() and readable via the get_sidecar_port command.
/// This lets the frontend pull the port on mount even if it missed the
/// one-shot "sidecar-ready" Tauri event (race condition on fast machines).
#[derive(Clone)]
struct SidecarPort(Arc<Mutex<Option<u16>>>);

/// Return the sidecar port if it has been assigned, or None if the sidecar
/// hasn't started yet. The frontend calls this on mount as a fallback.
#[tauri::command]
fn get_sidecar_port(state: tauri::State<SidecarPort>) -> Option<u16> {
    *state.0.lock().unwrap()
}

/// Check GitHub Releases for a newer version of VanillaDB.
/// Returns `{ available: false }` if up-to-date, or
/// `{ available: true, version: "x.y.z", notes: "..." }` if an update is ready.
#[tauri::command]
async fn check_for_update(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    match updater.check().await {
        Ok(Some(update)) => Ok(serde_json::json!({
            "available": true,
            "version": update.version,
            "current_version": update.current_version,
            "notes": update.body.unwrap_or_default(),
        })),
        Ok(None) => Ok(serde_json::json!({ "available": false })),
        Err(e) => Err(e.to_string()),
    }
}

/// Download and install the latest update, then relaunch.
/// This is a fire-and-forget call — the app will restart on success.
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "No update available".to_string())?;

    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| e.to_string())
}

/// Get the app's data directory path (for SQLite, config, etc.)
#[tauri::command]
fn get_app_data_dir(app: tauri::AppHandle) -> Result<String, String> {
    let path = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("Failed to get app data dir: {}", e))?;
    Ok(path.to_string_lossy().to_string())
}

/// Spawn the Python sidecar and emit the port to the frontend.
///
/// The sidecar prints "VANILLA_PORT:<port>" to stdout on startup.
/// We capture that, store it in SidecarPort managed state (so the frontend
/// can pull it on mount), and also emit "sidecar-ready" for reactivity.
///
/// PYTHONUNBUFFERED=1 ensures PyInstaller's stdout isn't line-buffered
/// when running as a subprocess (without a TTY).
fn spawn_sidecar(app: &tauri::AppHandle, port_state: Arc<Mutex<Option<u16>>>) {
    let app_handle = app.clone();

    tauri::async_runtime::spawn(async move {
        let shell = app_handle.shell();

        let sidecar_result = shell.sidecar("vanilla-sidecar");
        let sidecar_cmd = match sidecar_result {
            Ok(cmd) => cmd,
            Err(e) => {
                eprintln!("[sidecar] Failed to create sidecar command: {}", e);
                return;
            }
        };

        // PYTHONUNBUFFERED=1 prevents PyInstaller stdout buffering when the
        // process is spawned without a TTY (which Tauri's shell plugin does).
        let sidecar_cmd = sidecar_cmd.env("PYTHONUNBUFFERED", "1");

        let spawn_result = sidecar_cmd.spawn();
        let (mut rx, _child) = match spawn_result {
            Ok(result) => result,
            Err(e) => {
                eprintln!("[sidecar] Failed to spawn sidecar: {}", e);
                return;
            }
        };

        // Read events from the sidecar process
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    let line = line.trim();

                    // Parse port from "VANILLA_PORT:<port>"
                    if let Some(port_str) = line.strip_prefix("VANILLA_PORT:") {
                        if let Ok(port) = port_str.trim().parse::<u16>() {
                            println!("[sidecar] Listening on port {}", port);
                            // Store in managed state so frontend can pull it on mount
                            *port_state.lock().unwrap() = Some(port);
                            // Also emit for reactivity (frontend may already be listening)
                            if let Err(e) = app_handle.emit("sidecar-ready", port) {
                                eprintln!("[sidecar] Failed to emit sidecar-ready: {}", e);
                            }
                        }
                    } else if !line.is_empty() {
                        // Forward other sidecar logs (useful for debugging)
                        println!("[sidecar] {}", line);
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    eprintln!("[sidecar-err] {}", line.trim());
                }
                CommandEvent::Terminated(status) => {
                    eprintln!(
                        "[sidecar] Process terminated with code {:?}",
                        status.code
                    );
                    break;
                }
                _ => {}
            }
        }
    });
}

/// Register global hotkeys:
///   Ctrl+Shift+Space → voice:start (press) / voice:stop (release)
///   Ctrl+Shift+V     → tray:clip-clipboard
fn register_shortcuts(app: &tauri::AppHandle) {
    let app_handle = app.clone();

    let voice_shortcut = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::Space,
    );
    let clip_shortcut = Shortcut::new(
        Some(Modifiers::CONTROL | Modifiers::SHIFT),
        Code::KeyV,
    );

    if let Err(e) = app_handle.global_shortcut().on_shortcuts(
        [voice_shortcut, clip_shortcut],
        move |app, shortcut, event| {
            if shortcut.mods == Modifiers::CONTROL | Modifiers::SHIFT
                && shortcut.key == Code::Space
            {
                match event.state() {
                    ShortcutState::Pressed => {
                        let _ = app.emit("voice:start", ());
                    }
                    ShortcutState::Released => {
                        let _ = app.emit("voice:stop", ());
                    }
                }
            } else if shortcut.mods == Modifiers::CONTROL | Modifiers::SHIFT
                && shortcut.key == Code::KeyV
            {
                if event.state() == ShortcutState::Pressed {
                    let _ = app.emit("tray:clip-clipboard", ());
                }
            }
        },
    ) {
        eprintln!("[shortcuts] Failed to register global shortcuts: {}", e);
    }
}

pub fn run() {
    let port_state = SidecarPort(Arc::new(Mutex::new(None)));

    tauri::Builder::default()
        .manage(port_state.clone())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            get_app_data_dir,
            check_for_update,
            install_update,
            get_sidecar_port,
        ])
        .setup(move |app| {
            // Register global keyboard shortcuts
            register_shortcuts(&app.handle().clone());

            // Spawn the sidecar unless VANILLA_NO_SIDECAR=1 (for manual dev workflows).
            if std::env::var("VANILLA_NO_SIDECAR").is_err() {
                spawn_sidecar(&app.handle().clone(), port_state.0.clone());
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
