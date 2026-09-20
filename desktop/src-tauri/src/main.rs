// APEIR desktop backend.

#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use serde::Serialize;
use std::{
    env, fs,
    fs::OpenOptions,
    io::{Read, Write},
    net::{TcpStream, ToSocketAddrs},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};
use tauri::{
    menu::{Menu, MenuItem, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent, State,
};

mod config;
mod credentials;

#[cfg(target_os = "windows")]
use std::os::windows::{io::AsRawHandle, process::CommandExt};

#[cfg(target_os = "windows")]
use windows_sys::Win32::{
    Foundation::{CloseHandle, HANDLE},
    System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, IsProcessInJob,
        JobObjectExtendedLimitInformation, SetInformationJobObject,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    },
};

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Default)]
struct RuntimeManager {
    child: Mutex<Option<Child>>,
    nousd_child: Mutex<Option<Child>>,
    kernel_token: Mutex<Option<String>>,
    #[cfg(target_os = "windows")]
    job_handle: Mutex<Option<usize>>,
}

#[cfg(target_os = "windows")]
impl Drop for RuntimeManager {
    fn drop(&mut self) {
        if let Ok(mut handle) = self.job_handle.lock() {
            if let Some(handle) = handle.take() {
                unsafe {
                    CloseHandle(handle as HANDLE);
                }
            }
        }
    }
}

/// Default port for nousd NKI server (separate from runtime-api port 8770).
const NOUSD_DEFAULT_PORT: u16 = 8771;

#[cfg(target_os = "windows")]
fn assign_to_runtime_job(manager: &RuntimeManager, child: &Child) -> Result<(), String> {
    let mut guard = manager
        .job_handle
        .lock()
        .map_err(|_| "Runtime process job is unavailable.".to_string())?;
    let handle = match *guard {
        Some(handle) => handle as HANDLE,
        None => {
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if handle.is_null() {
                return Err(format!(
                    "Could not create the Runtime process job: {}",
                    std::io::Error::last_os_error()
                ));
            }
            let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &limits as *const _ as *const std::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if configured == 0 {
                unsafe {
                    CloseHandle(handle);
                }
                return Err(format!(
                    "Could not configure the Runtime process job: {}",
                    std::io::Error::last_os_error()
                ));
            }
            *guard = Some(handle as usize);
            handle
        }
    };
    let assigned = unsafe { AssignProcessToJobObject(handle, child.as_raw_handle() as HANDLE) };
    if assigned == 0 {
        let mut inherited_job = 0;
        let probed = unsafe {
            IsProcessInJob(
                child.as_raw_handle() as HANDLE,
                std::ptr::null_mut(),
                &mut inherited_job,
            )
        };
        if probed != 0 && inherited_job != 0 {
            log::warn!(
                "Runtime child already belongs to an external Windows job; using explicit lifecycle shutdown"
            );
            return Ok(());
        }
        return Err(format!(
            "Could not attach a Runtime child to the process job: {}",
            std::io::Error::last_os_error()
        ));
    }
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn assign_to_runtime_job(_manager: &RuntimeManager, _child: &Child) -> Result<(), String> {
    Ok(())
}

#[derive(Serialize)]
struct RuntimeProcessStatus {
    endpoint: String,
    ready: bool,
    port_open: bool,
    session_available: bool,
    managed_by_desktop: bool,
    pid: Option<u32>,
    log_path: String,
}

#[derive(Serialize)]
struct ProviderCredentialStatus {
    environment_name: String,
    stored: bool,
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn session_token_path() -> PathBuf {
    if let Some(path) = env::var_os("NOUS_SESSION_TOKEN_FILE") {
        return PathBuf::from(path);
    }
    let root = if cfg!(target_os = "windows") {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
    } else {
        env::var_os("XDG_RUNTIME_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
    };
    root.join("Nous").join("runtime-session.token")
}

fn app_data_dir() -> PathBuf {
    if cfg!(target_os = "windows") {
        env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
            .join("Nous")
    } else {
        env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
            .join(".local")
            .join("share")
            .join("Nous")
    }
}

fn logs_dir() -> PathBuf {
    app_data_dir().join("logs")
}

fn runtime_log_path() -> PathBuf {
    logs_dir().join("runtime-api.log")
}

fn nousd_log_path() -> PathBuf {
    logs_dir().join("nousd.log")
}

fn nousd_data_dir() -> PathBuf {
    app_data_dir().join("kernel")
}

fn configured_workspace_path() -> Option<PathBuf> {
    let config = config::read_config_file("app.json")?;
    let path = PathBuf::from(config.get("workspace_path")?.as_str()?);
    if path.is_dir() {
        Some(path)
    } else {
        None
    }
}

fn configured_credential_environment_names() -> Vec<String> {
    config::read_config_file("app.json")
        .and_then(|value| value.get("credential_environment_names").cloned())
        .and_then(|value| serde_json::from_value::<Vec<String>>(value).ok())
        .unwrap_or_default()
        .into_iter()
        .filter_map(|name| credentials::validate_environment_name(&name).ok())
        .collect()
}

fn load_stored_provider_credentials() -> Result<Vec<(String, String)>, String> {
    configured_credential_environment_names()
        .into_iter()
        .filter_map(|name| match credentials::load(&name) {
            Ok(Some(value)) => Some(Ok((name, value))),
            Ok(None) => None,
            Err(error) => Some(Err(error)),
        })
        .collect()
}

fn credential_allowlist(credentials: &[(String, String)]) -> String {
    credentials
        .iter()
        .map(|(name, _)| name.as_str())
        .collect::<Vec<_>>()
        .join(",")
}

fn runtime_address() -> (String, u16) {
    let runtime =
        config::read_config_file("runtime.json").unwrap_or_else(config::default_runtime_config);
    let host = runtime
        .get("runtime_host")
        .and_then(|value| value.as_str())
        .unwrap_or("127.0.0.1")
        .to_string();
    let port = runtime
        .get("runtime_port")
        .and_then(|value| value.as_u64())
        .and_then(|value| u16::try_from(value).ok())
        .filter(|value| *value > 0)
        .unwrap_or(8770);
    (host, port)
}

fn connect_runtime(host: &str, port: u16, timeout: Duration) -> Option<TcpStream> {
    let addresses = format!("{host}:{port}").to_socket_addrs().ok()?;
    for address in addresses {
        if let Ok(stream) = TcpStream::connect_timeout(&address, timeout) {
            return Some(stream);
        }
    }
    None
}

fn runtime_is_ready(host: &str, port: u16) -> bool {
    let Some(mut stream) = connect_runtime(host, port, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(700)));
    let request =
        format!("GET /ready HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200")
}

fn runtime_session_is_valid(host: &str, port: u16, token: &str) -> bool {
    let Some(mut stream) = connect_runtime(host, port, Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(1000)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(1000)));
    let request = format!(
        "GET /api/v1/status HTTP/1.1\r\nHost: {host}:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200")
}

fn read_runtime_token() -> Result<String, String> {
    let token = fs::read_to_string(session_token_path())
        .map_err(|_| "No local Runtime session was found.".to_string())?;
    let token = token.trim().to_string();
    if token.len() != 64 || !token.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("The local Runtime session token is invalid.".to_string());
    }
    Ok(token)
}

#[tauri::command]
fn get_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn show_window(window: tauri::WebviewWindow) {
    let _ = window.show();
    let _ = window.set_focus();
}

#[tauri::command]
fn load_runtime_session_token() -> Result<String, String> {
    read_runtime_token()
}

fn find_nous_executable() -> Result<(String, Vec<String>, bool), String> {
    // Installed builds must always prefer their bundled Runtime. Development
    // overrides are consulted only when no packaged sidecar is present.
    if let Ok(executable_path) = env::current_exe() {
        let sidecar_name = if cfg!(target_os = "windows") {
            "nous-runtime.exe"
        } else {
            "nous-runtime"
        };
        if let Some(parent) = executable_path.parent() {
            for candidate in [
                parent.join(sidecar_name),
                parent.join("resources").join(sidecar_name),
                parent.join("binaries").join(sidecar_name),
            ] {
                if candidate.is_file() {
                    return Ok((candidate.to_string_lossy().to_string(), vec![], true));
                }
            }
        }
    }

    if let Some(path) = env::var_os("NOUS_CLI_PATH") {
        let executable = PathBuf::from(path);
        if executable.is_file() {
            return Ok((executable.to_string_lossy().to_string(), vec![], false));
        }
    }
    if let Ok(executable_path) = env::current_exe() {
        let base_dirs = vec![
            executable_path
                .parent()
                .map(PathBuf::from)
                .unwrap_or_default(),
            executable_path
                .parent()
                .and_then(|path| path.parent())
                .map(PathBuf::from)
                .unwrap_or_default(),
            executable_path
                .parent()
                .and_then(|path| path.parent().and_then(|parent| parent.parent()))
                .map(PathBuf::from)
                .unwrap_or_default(),
        ];
        for base in &base_dirs {
            let nous_executable = base.join(".venv").join("Scripts").join("nous.exe");
            if nous_executable.is_file() {
                return Ok((nous_executable.to_string_lossy().to_string(), vec![], false));
            }
            let python_executable = base.join(".venv").join("Scripts").join("python.exe");
            if python_executable.is_file() {
                return Ok((
                    python_executable.to_string_lossy().to_string(),
                    vec!["-m".to_string(), "nous_runtime.cli.main".to_string()],
                    false,
                ));
            }
        }
    }

    Err("APEIR CLI was not found. Set NOUS_CLI_PATH to the installed apeir executable.".to_string())
}

fn find_kernel_sidecars() -> Result<(PathBuf, PathBuf), String> {
    let daemon_name = if cfg!(target_os = "windows") {
        "nousd.exe"
    } else {
        "nousd"
    };
    let worker_name = if cfg!(target_os = "windows") {
        "nous-provider-worker.exe"
    } else {
        "nous-provider-worker"
    };
    if let Ok(executable_path) = env::current_exe() {
        if let Some(parent) = executable_path.parent() {
            for directory in [
                parent.to_path_buf(),
                parent.join("resources"),
                parent.join("binaries"),
            ] {
                let daemon = directory.join(daemon_name);
                let worker = directory.join(worker_name);
                if daemon.is_file() && worker.is_file() {
                    return Ok((daemon, worker));
                }
            }
        }
    }

    if let (Some(daemon), Some(worker)) = (
        env::var_os("NOUS_KERNEL_PATH"),
        env::var_os("NOUS_PROVIDER_WORKER_PATH"),
    ) {
        let daemon = PathBuf::from(daemon);
        let worker = PathBuf::from(worker);
        if daemon.is_file() && worker.is_file() {
            return Ok((daemon, worker));
        }
    }

    Err(
        "APEIR Runtime sidecars were not found. Install nousd and nous-provider-worker together, or set NOUS_KERNEL_PATH and NOUS_PROVIDER_WORKER_PATH."
            .to_string(),
    )
}

fn nousd_is_ready(port: u16) -> bool {
    // Simple TCP connectivity check — the Python NKI client does real health verification.
    connect_runtime("127.0.0.1", port, Duration::from_millis(300)).is_some()
}

fn start_nousd_inner(manager: &RuntimeManager) -> Result<u16, String> {
    let port = std::env::var("NOUS_KERNEL_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(NOUSD_DEFAULT_PORT);

    if nousd_is_ready(port) {
        let (managed, _) = managed_nousd_status(manager)?;
        if managed {
            return Ok(port);
        }
        return Err(format!(
            "Port {port} is owned by a different Runtime. Stop it or configure another kernel port."
        ));
    }

    let (executable, worker) = find_kernel_sidecars()?;
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(nousd_log_path())
        .map_err(|error| format!("Could not open nousd log: {error}"))?;
    let error_log = log_file
        .try_clone()
        .map_err(|error| format!("Could not prepare nousd error log: {error}"))?;

    fs::create_dir_all(nousd_data_dir())
        .map_err(|error| format!("Could not create kernel data directory: {error}"))?;

    let journal_path = nousd_data_dir().join("journal.db");
    let listen_address = format!("127.0.0.1:{port}");
    let session_token = format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    );

    let mut command = Command::new(&executable);
    command
        .arg("serve")
        .arg(&journal_path)
        .arg(&worker)
        .arg(&listen_address)
        .env("NOUS_NKI_TOKEN", &session_token)
        .env("RUST_LOG", "nousd=info")
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(error_log));
    let provider_credentials = load_stored_provider_credentials()?;
    let credential_allowlist = credential_allowlist(&provider_credentials);
    command
        .envs(provider_credentials)
        .env("NOUS_ALLOWED_CREDENTIALS", credential_allowlist);

    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = command.spawn().map_err(|error| {
        format!("APEIR Runtime could not be started ({error}). Verify both Runtime sidecars.")
    })?;
    if let Err(error) = assign_to_runtime_job(manager, &child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }

    match manager.nousd_child.lock() {
        Ok(mut guard) => {
            *guard = Some(child);
        }
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err("nousd process manager is unavailable.".to_string());
        }
    }
    match manager.kernel_token.lock() {
        Ok(mut token) => {
            *token = Some(session_token);
        }
        Err(_) => {
            let _ = stop_nousd_inner(manager);
            return Err("Runtime session manager is unavailable.".to_string());
        }
    }

    for _ in 0..50 {
        if nousd_is_ready(port) {
            log::info!("nousd kernel daemon ready on port {port}");
            return Ok(port);
        }
        match managed_nousd_status(manager) {
            Ok((true, _)) => {}
            Ok((false, _)) => {
                let _ = manager.kernel_token.lock().map(|mut token| token.take());
                return Err(format!(
                    "nousd kernel daemon exited during startup. Review {}.",
                    nousd_log_path().display()
                ));
            }
            Err(error) => {
                let _ = stop_nousd_inner(manager);
                return Err(error);
            }
        }
        thread::sleep(Duration::from_millis(200));
    }

    let _ = stop_nousd_inner(manager);
    Err(format!(
        "nousd kernel daemon did not become ready within 10 seconds. Review {}.",
        nousd_log_path().display()
    ))
}

fn stop_nousd_inner(manager: &RuntimeManager) -> Result<(), String> {
    let process_result = match manager.nousd_child.lock() {
        Ok(mut guard) => {
            if let Some(mut child) = guard.take() {
                terminate_managed_child(&mut child)
            } else {
                Ok(())
            }
        }
        Err(_) => Err("nousd process manager is unavailable.".to_string()),
    };
    let _ = manager.kernel_token.lock().map(|mut token| token.take());
    process_result
}

fn managed_nousd_status(manager: &RuntimeManager) -> Result<(bool, Option<u32>), String> {
    let mut guard = manager
        .nousd_child
        .lock()
        .map_err(|_| "nousd process manager is unavailable.".to_string())?;
    let Some(child) = guard.as_mut() else {
        return Ok((false, None));
    };
    match child.try_wait() {
        Ok(None) => Ok((true, Some(child.id()))),
        Ok(Some(_)) => {
            guard.take();
            Ok((false, None))
        }
        Err(error) => Err(format!("Could not inspect nousd process: {error}")),
    }
}

fn managed_child_status(manager: &RuntimeManager) -> Result<(bool, Option<u32>), String> {
    let mut guard = manager
        .child
        .lock()
        .map_err(|_| "Runtime process manager is unavailable.".to_string())?;
    let Some(child) = guard.as_mut() else {
        return Ok((false, None));
    };
    match child.try_wait() {
        Ok(None) => Ok((true, Some(child.id()))),
        Ok(Some(_)) => {
            guard.take();
            Ok((false, None))
        }
        Err(error) => Err(format!("Could not inspect the Runtime process: {error}")),
    }
}

fn start_runtime_api_inner(manager: &RuntimeManager) -> Result<String, String> {
    config::ensure_app_dirs()?;
    config::initialize_default_configs()?;
    fs::create_dir_all(logs_dir())
        .map_err(|error| format!("Could not create the Runtime log directory: {error}"))?;

    let (host, port) = runtime_address();
    let port_text = port.to_string();
    if runtime_is_ready(&host, port) {
        let token = read_runtime_token().map_err(|_| {
            "A APEIR Runtime is already running, but its local session cannot be loaded. Restart Runtime from diagnostics.".to_string()
        })?;
        if runtime_session_is_valid(&host, port, &token) {
            return Ok(token);
        }
        return Err(
            "A different APEIR Runtime owns this port and rejected the local session. Stop that Runtime or change the configured port, then retry.".to_string(),
        );
    }
    if connect_runtime(&host, port, Duration::from_millis(300)).is_some() {
        return Err(format!(
            "Port {port} is already used by another application. Change runtime_port in the desktop Runtime configuration."
        ));
    }

    let (managed, _) = managed_child_status(manager)?;
    if managed {
        return Err(
            "The desktop Runtime process is still starting. Wait a moment and retry.".to_string(),
        );
    }

    // Validate every fallible Runtime prerequisite before starting the kernel.
    // This keeps early configuration, credential, and log failures side-effect
    // free instead of leaving a managed nousd process behind.
    let (executable, extra_args, bundled) = find_nous_executable()?;
    let runtime_credentials = load_stored_provider_credentials()?;
    let log_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(runtime_log_path())
        .map_err(|error| format!("Could not open the Runtime log: {error}"))?;
    let error_log = log_file
        .try_clone()
        .map_err(|error| format!("Could not prepare the Runtime error log: {error}"))?;

    // The kernel is authoritative and must be ready before the application
    // Runtime receives its private NKI session.
    let nousd_port = start_nousd_inner(manager)?;
    let kernel_token = match manager.kernel_token.lock() {
        Ok(token) => match token.clone() {
            Some(token) => token,
            None => {
                let _ = stop_nousd_inner(manager);
                return Err("Runtime session was not established.".to_string());
            }
        },
        Err(_) => {
            let _ = stop_nousd_inner(manager);
            return Err("Runtime session manager is unavailable.".to_string());
        }
    };

    let mut command = Command::new(&executable);
    command
        .args(&extra_args)
        .args([
            "runtime-api",
            "start",
            "--host",
            &host,
            "--port",
            &port_text,
        ])
        .env_remove("NOUS_API_TOKEN")
        .env_remove("NOUS_AUTH_TOKEN")
        .stdin(Stdio::null())
        .stdout(Stdio::from(log_file))
        .stderr(Stdio::from(error_log));
    command.envs(runtime_credentials);
    command
        .env(
            "NOUS_KERNEL_ENDPOINT",
            format!("tcp://127.0.0.1:{nousd_port}"),
        )
        .env("NOUS_NKI_TOKEN", kernel_token);
    if let Some(workspace) = configured_workspace_path() {
        command
            .current_dir(&workspace)
            .env("NOUS_WORKSPACE_ROOT", workspace);
    } else if !bundled {
        if let Some(workspace) = env::var_os("NOUS_WORKSPACE_ROOT") {
            command.current_dir(workspace);
        }
    }
    #[cfg(target_os = "windows")]
    command.creation_flags(CREATE_NO_WINDOW);

    let mut child = command.spawn().map_err(|error| {
        let _ = stop_nousd_inner(manager);
        format!(
            "APEIR Runtime could not be started ({error}). Verify NOUS_CLI_PATH and open the Runtime log for details."
        )
    })?;
    if let Err(error) = assign_to_runtime_job(manager, &child) {
        let _ = child.kill();
        let _ = child.wait();
        let _ = stop_nousd_inner(manager);
        return Err(error);
    }
    match manager.child.lock() {
        Ok(mut guard) => {
            *guard = Some(child);
        }
        Err(_) => {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stop_nousd_inner(manager);
            return Err("Runtime process manager is unavailable.".to_string());
        }
    }

    for _ in 0..150 {
        if runtime_is_ready(&host, port) {
            if let Ok(token) = read_runtime_token() {
                if runtime_session_is_valid(&host, port, &token) {
                    return Ok(token);
                }
            }
        }
        match managed_child_status(manager) {
            Ok((true, _)) => {}
            Ok((false, _)) => {
                let _ = stop_runtime_api_inner(manager);
                return Err(format!(
                    "APEIR Runtime exited during startup. Review {}.",
                    runtime_log_path().display()
                ));
            }
            Err(error) => {
                let _ = stop_runtime_api_inner(manager);
                return Err(error);
            }
        }
        thread::sleep(Duration::from_millis(200));
    }

    let _ = stop_runtime_api_inner(manager);
    Err(format!(
        "APEIR Runtime did not become ready within 30 seconds. Review {}.",
        runtime_log_path().display()
    ))
}

#[cfg(target_os = "windows")]
fn terminate_managed_child(child: &mut Child) -> Result<(), String> {
    if child
        .try_wait()
        .map_err(|error| format!("Could not inspect the desktop-managed Runtime: {error}"))?
        .is_some()
    {
        return Ok(());
    }

    let pid = child.id().to_string();
    let status = Command::new("taskkill")
        .args(["/PID", &pid, "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .status()
        .map_err(|error| format!("Could not terminate Runtime process tree: {error}"))?;
    if !status.success() {
        return Err(format!(
            "Could not terminate Runtime process tree for PID {pid}."
        ));
    }
    let _ = child.wait();
    Ok(())
}

#[cfg(not(target_os = "windows"))]
fn terminate_managed_child(child: &mut Child) -> Result<(), String> {
    child
        .kill()
        .map_err(|error| format!("Could not stop the desktop-managed Runtime: {error}"))?;
    let _ = child.wait();
    Ok(())
}
fn stop_runtime_api_inner(manager: &RuntimeManager) -> Result<(), String> {
    let runtime_result = match manager.child.lock() {
        Ok(mut guard) => {
            if let Some(mut child) = guard.take() {
                terminate_managed_child(&mut child)
            } else {
                Ok(())
            }
        }
        Err(_) => Err("Runtime process manager is unavailable.".to_string()),
    };
    let kernel_result = stop_nousd_inner(manager);
    let _ = fs::remove_file(session_token_path());

    match (runtime_result, kernel_result) {
        (Ok(()), Ok(())) => Ok(()),
        (Err(runtime_error), Ok(())) => Err(runtime_error),
        (Ok(()), Err(kernel_error)) => Err(kernel_error),
        (Err(runtime_error), Err(kernel_error)) => Err(format!(
            "{runtime_error} Kernel shutdown also failed: {kernel_error}"
        )),
    }
}

#[tauri::command]
fn start_runtime_api(manager: State<'_, RuntimeManager>) -> Result<String, String> {
    start_runtime_api_inner(&manager)
}

#[tauri::command]
fn restart_runtime_api(manager: State<'_, RuntimeManager>) -> Result<String, String> {
    stop_runtime_api_inner(&manager)?;
    start_runtime_api_inner(&manager)
}

#[tauri::command]
fn stop_runtime_api(manager: State<'_, RuntimeManager>) -> Result<(), String> {
    stop_runtime_api_inner(&manager)
}

#[tauri::command]
fn store_provider_credential(
    environment_name: String,
    secret: String,
    manager: State<'_, RuntimeManager>,
) -> Result<String, String> {
    let environment_name = credentials::validate_environment_name(&environment_name)?;
    let previous = credentials::load(&environment_name)?;
    credentials::store(&environment_name, &secret)?;

    let mut names = configured_credential_environment_names();
    if !names.iter().any(|name| name == &environment_name) {
        names.push(environment_name.clone());
        names.sort();
        names.dedup();
        if let Err(error) =
            config::update_app_config("credential_environment_names", serde_json::json!(names))
        {
            if let Some(previous) = previous {
                let _ = credentials::store(&environment_name, &previous);
            } else {
                let _ = credentials::remove(&environment_name);
            }
            return Err(error);
        }
    }

    stop_runtime_api_inner(&manager)?;
    start_runtime_api_inner(&manager)
}

#[tauri::command]
fn list_provider_credentials() -> Result<Vec<ProviderCredentialStatus>, String> {
    configured_credential_environment_names()
        .into_iter()
        .map(|environment_name| {
            let stored = credentials::load(&environment_name)?.is_some();
            Ok(ProviderCredentialStatus {
                environment_name,
                stored,
            })
        })
        .collect()
}

#[tauri::command]
fn remove_provider_credential(
    environment_name: String,
    manager: State<'_, RuntimeManager>,
) -> Result<String, String> {
    let environment_name = credentials::validate_environment_name(&environment_name)?;
    let previous = credentials::load(&environment_name)?;
    credentials::remove(&environment_name)?;

    let names = configured_credential_environment_names()
        .into_iter()
        .filter(|name| name != &environment_name)
        .collect::<Vec<_>>();
    if let Err(error) =
        config::update_app_config("credential_environment_names", serde_json::json!(names))
    {
        if let Some(secret) = previous {
            let _ = credentials::store(&environment_name, &secret);
        }
        return Err(error);
    }

    stop_runtime_api_inner(&manager)?;
    start_runtime_api_inner(&manager)
}

#[tauri::command]
fn get_runtime_process_status(
    manager: State<'_, RuntimeManager>,
) -> Result<RuntimeProcessStatus, String> {
    let (host, port) = runtime_address();
    let port_open = connect_runtime(&host, port, Duration::from_millis(300)).is_some();
    let ready = runtime_is_ready(&host, port);
    let session_available = read_runtime_token()
        .map(|token| runtime_session_is_valid(&host, port, &token))
        .unwrap_or(false);
    let (managed_by_desktop, pid) = managed_child_status(&manager)?;
    Ok(RuntimeProcessStatus {
        endpoint: format!("http://{host}:{port}"),
        ready,
        port_open,
        session_available,
        managed_by_desktop,
        pid,
        log_path: runtime_log_path().to_string_lossy().to_string(),
    })
}

// Kernel process commands.

#[derive(Serialize)]
struct NousdProcessStatus {
    ready: bool,
    port: u16,
    managed_by_desktop: bool,
    pid: Option<u32>,
    log_path: String,
}

#[tauri::command]
fn start_nousd(manager: State<'_, RuntimeManager>) -> Result<u16, String> {
    start_nousd_inner(&manager)
}

#[tauri::command]
fn stop_nousd(manager: State<'_, RuntimeManager>) -> Result<(), String> {
    stop_nousd_inner(&manager)
}

#[tauri::command]
fn get_nousd_status(manager: State<'_, RuntimeManager>) -> Result<NousdProcessStatus, String> {
    let port = std::env::var("NOUS_KERNEL_PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(NOUSD_DEFAULT_PORT);
    let ready = nousd_is_ready(port);
    let (managed_by_desktop, pid) = managed_nousd_status(&manager)?;
    Ok(NousdProcessStatus {
        ready,
        port,
        managed_by_desktop,
        pid,
        log_path: nousd_log_path().to_string_lossy().to_string(),
    })
}

#[tauri::command]
fn open_logs_directory() -> Result<String, String> {
    let directory = logs_dir();
    fs::create_dir_all(&directory)
        .map_err(|error| format!("Could not create the log directory: {error}"))?;
    opener::open(&directory).map_err(|error| format!("Could not open logs directory: {error}"))?;
    Ok(directory.to_string_lossy().to_string())
}

#[tauri::command]
fn get_app_data_dir() -> Result<String, String> {
    let directory = app_data_dir();
    fs::create_dir_all(&directory)
        .map_err(|error| format!("Could not create the application data directory: {error}"))?;
    Ok(directory.to_string_lossy().to_string())
}

#[tauri::command]
fn get_default_workspace_path() -> Result<String, String> {
    if let Some(path) = configured_workspace_path() {
        return Ok(path.to_string_lossy().to_string());
    }
    let home = if cfg!(target_os = "windows") {
        env::var_os("USERPROFILE")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                env::var_os("HOMEDRIVE")
                    .and_then(|drive| {
                        env::var_os("HOMEPATH").map(|path| PathBuf::from(drive).join(path))
                    })
                    .unwrap_or_else(env::temp_dir)
            })
    } else {
        env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(env::temp_dir)
    };
    Ok(home.join("NousWorkspace").to_string_lossy().to_string())
}

#[tauri::command]
fn init_app_config() -> Result<String, String> {
    config::ensure_app_dirs()?;
    config::initialize_default_configs()?;
    Ok("ok".to_string())
}

#[tauri::command]
fn get_config(key: String) -> Result<serde_json::Value, String> {
    let app_config =
        config::read_config_file("app.json").unwrap_or_else(config::default_app_config);
    if key.is_empty() {
        Ok(app_config)
    } else {
        Ok(app_config
            .get(&key)
            .cloned()
            .unwrap_or(serde_json::Value::Null))
    }
}

fn validate_workspace_root(path: &str) -> Result<PathBuf, String> {
    let requested = PathBuf::from(path.trim());
    if path.trim().is_empty() || !requested.is_absolute() {
        return Err("Choose an absolute workspace directory.".to_string());
    }
    fs::create_dir_all(&requested)
        .map_err(|error| format!("Cannot create workspace directory: {error}"))?;
    let root = fs::canonicalize(&requested)
        .map_err(|error| format!("Cannot resolve workspace directory: {error}"))?;
    if root.parent().is_none() {
        return Err("A filesystem root cannot be used as a workspace.".to_string());
    }
    if let Some(home) = env::var_os(if cfg!(target_os = "windows") {
        "USERPROFILE"
    } else {
        "HOME"
    }) {
        if fs::canonicalize(home).ok().as_ref() == Some(&root) {
            return Err("Choose a project directory, not the entire home directory.".to_string());
        }
    }
    let application_data = fs::canonicalize(app_data_dir()).unwrap_or_else(|_| app_data_dir());
    if root.starts_with(application_data) {
        return Err("The APEIR application-data directory cannot be a workspace.".to_string());
    }
    if cfg!(target_os = "windows") {
        for variable in ["WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"] {
            if let Some(protected) =
                env::var_os(variable).and_then(|value| fs::canonicalize(value).ok())
            {
                if root.starts_with(protected) {
                    return Err("A protected Windows directory cannot be a workspace.".to_string());
                }
            }
        }
    }
    Ok(workspace_user_path(&root))
}

fn workspace_user_path(path: &Path) -> PathBuf {
    if !cfg!(target_os = "windows") {
        return path.to_path_buf();
    }
    let text = path.to_string_lossy();
    if let Some(network_path) = text.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{network_path}"));
    }
    if let Some(local_path) = text.strip_prefix(r"\\?\") {
        return PathBuf::from(local_path);
    }
    path.to_path_buf()
}

fn initialize_workspace(root: &Path) -> Result<String, String> {
    // The Desktop reserves only the selected root. The Python Runtime is the
    // sole writer for workspace.json and .nous/workspaces.json at startup.
    fs::create_dir_all(root)
        .map_err(|error| format!("Cannot create workspace directory: {error}"))?;
    Ok(root.to_string_lossy().to_string())
}

#[tauri::command]
fn select_workspace_directory() -> Result<Option<String>, String> {
    Ok(rfd::FileDialog::new()
        .set_title("Choose an APEIR workspace")
        .pick_folder()
        .map(|path| path.to_string_lossy().to_string()))
}

#[tauri::command]
fn open_workspace_directory() -> Result<String, String> {
    let root =
        configured_workspace_path().ok_or_else(|| "No workspace is configured.".to_string())?;
    opener::open(&root).map_err(|error| format!("Could not open workspace: {error}"))?;
    Ok(root.to_string_lossy().to_string())
}

#[tauri::command]
fn open_safe_target(target: String) -> Result<String, String> {
    let value = target.trim();
    if value.is_empty() || value.chars().any(char::is_control) {
        return Err("The link target is invalid.".to_string());
    }
    let lower = value.to_ascii_lowercase();
    if lower.starts_with("http://") || lower.starts_with("https://") {
        opener::open(value).map_err(|error| format!("Could not open the web link: {error}"))?;
        return Ok("external-browser".to_string());
    }
    if lower.starts_with("data:")
        || lower.starts_with("blob:")
        || lower.starts_with("javascript:")
        || lower.starts_with("file:")
    {
        return Err("WebView download and executable link schemes are blocked.".to_string());
    }
    let root =
        configured_workspace_path().ok_or_else(|| "No workspace is configured.".to_string())?;
    let requested = PathBuf::from(value);
    let candidate = if requested.is_absolute() {
        requested
    } else {
        root.join(requested)
    };
    let root = fs::canonicalize(root)
        .map_err(|error| format!("Could not resolve the workspace: {error}"))?;
    let candidate = fs::canonicalize(candidate)
        .map_err(|_| "The workspace file does not exist.".to_string())?;
    if !candidate.starts_with(&root) || !candidate.is_file() {
        return Err("Only existing files inside the active workspace can be opened.".to_string());
    }
    opener::open(&candidate)
        .map_err(|error| format!("Could not open the workspace file: {error}"))?;
    Ok(candidate.to_string_lossy().to_string())
}

#[tauri::command]
fn create_default_workspace(path: String) -> Result<String, String> {
    let root = validate_workspace_root(&path)?;
    let activated = initialize_workspace(&root)?;

    env::set_var("NOUS_WORKSPACE_ROOT", &root);
    config::update_app_config(
        "workspace_path",
        serde_json::Value::String(root.to_string_lossy().to_string()),
    )?;
    Ok(activated)
}

fn main() {
    let app = tauri::Builder::default()
        .manage(RuntimeManager::default())
        .setup(|app| {
            let show = MenuItem::with_id(app, "show", "Show APEIR", true, None::<&str>)?;
            let status = MenuItem::with_id(
                app,
                "status",
                "Runtime status is shown in the application",
                false,
                None::<&str>,
            )?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &status, &separator, &quit])?;

            let mut tray = TrayIconBuilder::with_id("main")
                .menu(&menu)
                .tooltip("APEIR")
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => show_main_window(app),
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
                });

            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app.handle())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_version,
            show_window,
            load_runtime_session_token,
            start_runtime_api,
            restart_runtime_api,
            stop_runtime_api,
            store_provider_credential,
            list_provider_credentials,
            remove_provider_credential,
            get_runtime_process_status,
            open_logs_directory,
            get_app_data_dir,
            get_default_workspace_path,
            select_workspace_directory,
            open_workspace_directory,
            open_safe_target,
            create_default_workspace,
            init_app_config,
            get_config,
            start_nousd,
            stop_nousd,
            get_nousd_status,
        ])
        .build(tauri::generate_context!())
        .expect("failed to build APEIR");
    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            let manager = handle.state::<RuntimeManager>();
            if let Err(error) = stop_runtime_api_inner(&manager) {
                log::error!("Runtime shutdown failed: {error}");
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{
        credential_allowlist, initialize_workspace, runtime_session_is_valid,
        validate_workspace_root,
    };
    use std::{
        env, fs,
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    fn session_server(status: &str, expected_token: &str) -> (u16, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test listener");
        let port = listener.local_addr().expect("test address").port();
        let status = status.to_string();
        let expected_header = format!("Authorization: Bearer {expected_token}");
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept test request");
            let mut request = [0_u8; 4096];
            let size = stream.read(&mut request).expect("read test request");
            let request = String::from_utf8_lossy(&request[..size]);
            assert!(request.contains(&expected_header));
            let body = "{}";
            let response = format!(
                "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream
                .write_all(response.as_bytes())
                .expect("write test response");
        });
        (port, handle)
    }

    #[test]
    fn kernel_credential_allowlist_contains_names_only() {
        let credentials = vec![
            ("DEEPSEEK_API_KEY".to_string(), "secret-one".to_string()),
            ("OPENAI_API_KEY".to_string(), "secret-two".to_string()),
        ];

        let allowlist = credential_allowlist(&credentials);

        assert_eq!(allowlist, "DEEPSEEK_API_KEY,OPENAI_API_KEY");
        assert!(!allowlist.contains("secret"));
    }

    #[test]
    fn runtime_session_validation_accepts_authenticated_runtime() {
        let token = "a".repeat(64);
        let (port, handle) = session_server("200 OK", &token);
        assert!(runtime_session_is_valid("127.0.0.1", port, &token));
        handle.join().expect("join test server");
    }

    #[test]
    fn runtime_session_validation_rejects_foreign_runtime() {
        let token = "b".repeat(64);
        let (port, handle) = session_server("401 Unauthorized", &token);
        assert!(!runtime_session_is_valid("127.0.0.1", port, &token));
        handle.join().expect("join test server");
    }

    #[test]
    fn workspace_initialization_reserves_root_without_writing_metadata() {
        let root = env::temp_dir().join(format!(
            "nous-workspace-test-{}",
            uuid::Uuid::new_v4().simple()
        ));
        let validated =
            validate_workspace_root(root.to_str().expect("test path")).expect("validate workspace");
        if cfg!(target_os = "windows") {
            assert!(!validated.to_string_lossy().starts_with(r"\\?\"));
        }
        initialize_workspace(&validated).expect("reserve workspace");

        assert!(validated.is_dir());
        assert!(!validated.join("workspace.json").exists());
        assert!(!validated.join(".nous").join("workspaces.json").exists());

        let temp_root = fs::canonicalize(env::temp_dir()).expect("canonical temp directory");
        let cleanup_root = fs::canonicalize(&validated).expect("canonical test workspace");
        assert!(cleanup_root.starts_with(temp_root));
        fs::remove_dir_all(cleanup_root).expect("remove isolated test workspace");
    }

    #[test]
    fn workspace_selection_rejects_relative_paths() {
        assert!(validate_workspace_root("relative-workspace").is_err());
    }
}
