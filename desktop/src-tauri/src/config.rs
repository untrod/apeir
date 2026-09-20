/// Application configuration management.
///
/// Manages the config directory structure at %LOCALAPPDATA%\Nous\ on Windows
/// and ensures consistent configuration across desktop and CLI surfaces.
use std::{env, fs, path::PathBuf};

type ConfigFactory = fn() -> serde_json::Value;
type ConfigFileSpec = (&'static str, ConfigFactory);

/// Root config directory: %LOCALAPPDATA%\Nous\config on Windows
pub fn config_dir() -> PathBuf {
    let base = if cfg!(target_os = "windows") {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
            .join("Nous")
    } else {
        let home = env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir);
        home.join(".config").join("Nous")
    };
    base.join("config")
}

/// Logs directory
pub fn logs_dir() -> PathBuf {
    let base = if cfg!(target_os = "windows") {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
            .join("Nous")
    } else {
        let home = env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir);
        home.join(".local").join("share").join("Nous")
    };
    base.join("logs")
}

/// Default app configuration
pub fn default_app_config() -> serde_json::Value {
    serde_json::json!({
        "schema_version": 1,
        "language": "zh-CN",
        "theme": "system",
        "runtime_auto_start": true,
        "open_on_login": false,
        "telemetry": false,
        "crash_report_upload": false,
        "local_logging": true,
        "log_level": "info",
        "workspace_auto_create": true,
        "workspace_path": "",
        "provider_required_for_dashboard": false,
        "offline_mode_available": true,
        "update_channel": "stable",
        "auto_update": false,
        "credential_storage": "system",
        "expose_runtime_to_lan": false,
        "runtime_bind_host": "127.0.0.1",
        "developer_tools": false,
        "first_run_completed": false
    })
}

/// Persist one application setting while preserving all other keys.
pub fn update_app_config(key: &str, value: serde_json::Value) -> Result<(), String> {
    let mut current = read_config_file("app.json").unwrap_or_else(default_app_config);
    let object = current
        .as_object_mut()
        .ok_or_else(|| "Application configuration is not a JSON object.".to_string())?;
    object.insert(key.to_string(), value);
    write_config_file("app.json", &current)
}

/// Default runtime configuration
pub fn default_runtime_config() -> serde_json::Value {
    serde_json::json!({
        "schema_version": 1,
        "runtime_host": "127.0.0.1",
        "runtime_port": 8770,
        "auto_start": true,
        "start_timeout_ms": 30000,
        "health_check_interval_ms": 300,
        "bind_host": "127.0.0.1",
        "expose_to_lan": false,
        "log_level": "info",
        "max_request_bytes": 1048576,
        "requests_per_minute": 120
    })
}

/// Ensure all application directories exist
pub fn ensure_app_dirs() -> Result<PathBuf, String> {
    let config = config_dir();
    let logs = logs_dir();
    let webview = config.parent().unwrap_or(&config).join("webview");
    let state = config.parent().unwrap_or(&config).join("state");

    for dir in &[&config, &logs, &webview, &state] {
        fs::create_dir_all(dir)
            .map_err(|e| format!("Cannot create directory {}: {}", dir.display(), e))?;
    }

    Ok(config)
}

/// Write a config file with atomic write semantics
pub fn write_config_file(name: &str, content: &serde_json::Value) -> Result<(), String> {
    let dir = config_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("Cannot create config dir: {e}"))?;
    let file_path = dir.join(name);
    let tmp_path = dir.join(format!(".{}.tmp", name));

    // Write to temp file first
    let json_str = serde_json::to_string_pretty(content)
        .map_err(|e| format!("Cannot serialize config: {e}"))?;
    fs::write(&tmp_path, json_str.as_bytes())
        .map_err(|e| format!("Cannot write config file: {e}"))?;

    // Atomic rename
    atomic_replace(&tmp_path, &file_path)?;

    Ok(())
}

#[cfg(target_os = "windows")]
fn atomic_replace(source: &std::path::Path, destination: &std::path::Path) -> Result<(), String> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    let source: Vec<u16> = source
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let moved = unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if moved == 0 {
        return Err(format!(
            "Cannot commit config file: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn atomic_replace(source: &std::path::Path, destination: &std::path::Path) -> Result<(), String> {
    fs::rename(source, destination).map_err(|error| format!("Cannot commit config file: {error}"))
}

/// Read a config file, returning None if it doesn't exist
pub fn read_config_file(name: &str) -> Option<serde_json::Value> {
    let file_path = config_dir().join(name);
    let content = fs::read_to_string(&file_path).ok()?;
    serde_json::from_str(&content).ok()
}

/// Initialize first-run configuration
pub fn initialize_default_configs() -> Result<(), String> {
    ensure_app_dirs()?;

    // Only write configs that don't exist yet (preserve user data)
    let files: &[ConfigFileSpec] = &[
        ("app.json", default_app_config),
        ("runtime.json", default_runtime_config),
    ];

    for (name, default_fn) in files {
        let file_path = config_dir().join(name);
        if !file_path.exists() {
            write_config_file(name, &default_fn())?;
        }
    }

    Ok(())
}
