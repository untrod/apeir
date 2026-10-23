import { getConfig, getRuntimeConfigVersion, setConfig } from "./api";

type SessionCommand = "load_runtime_session_token" | "start_runtime_api" |
  "restart_runtime_api" | "store_provider_credential" | "remove_provider_credential";

interface LocalRuntimeStatus {
  endpoint: string;
  ready: boolean;
  session_available: boolean;
}

function localEndpoint(value: string): URL {
  const url = new URL(value);
  if (url.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname) ||
      url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("Select the local Runtime before managing its session or credentials.");
  }
  return url;
}

export function isLocalRuntimeSelected(endpoint: string): boolean {
  try {
    return localEndpoint(getConfig().url).port === localEndpoint(endpoint).port;
  } catch {
    return false;
  }
}

export async function nativeRuntimeStatus(): Promise<LocalRuntimeStatus> {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Local Runtime management requires the desktop application.");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  const status = await invoke<LocalRuntimeStatus>("get_runtime_process_status");
  const endpoint = localEndpoint(status.endpoint).origin;
  return { ...status, endpoint };
}

// Bind the native host's session to its reported loopback endpoint, never to
// a form field or whichever Controller happens to be selected after an await.
export async function bindNativeRuntimeSession(
  command: SessionCommand,
  args?: Record<string, unknown>,
  options: { activateLocal?: boolean; isActive?: () => boolean } = {},
): Promise<{ token: string; endpoint: string; version: number }> {
  const version = getRuntimeConfigVersion();
  const original = getConfig();
  const check = () => {
    const current = getConfig();
    if (options.isActive?.() === false || getRuntimeConfigVersion() !== version ||
        current.url !== original.url || current.token !== original.token) {
      throw new Error("Runtime connection changed or view closed. Inspect the original local Runtime state before retrying.");
    }
  };
  const before = await nativeRuntimeStatus();
  check();
  if (!options.activateLocal && !isLocalRuntimeSelected(before.endpoint)) {
    throw new Error("Select the local Runtime before managing its session or credentials.");
  }
  // Only the explicit Connect-screen start action may switch from remote to
  // local. Credential updates and recovery never change another Controller.
  if (options.activateLocal && command !== "start_runtime_api") {
    throw new Error("Only Start Local Runtime may select another endpoint.");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  check();
  const token = await invoke<string>(command, args);
  check();
  const after = await nativeRuntimeStatus();
  check();
  if (after.endpoint !== before.endpoint || after.ready !== true ||
      after.session_available !== true || typeof token !== "string" || !token.trim()) {
    throw new Error("Local Runtime session could not be verified. Inspect diagnostics before retrying; the original action may have completed.");
  }
  const committedVersion = version + Number(original.url !== after.endpoint || original.token !== token);
  setConfig({ url: after.endpoint, token });
  const committed = getConfig();
  if (getRuntimeConfigVersion() !== committedVersion || committed.url !== after.endpoint || committed.token !== token) {
    throw new Error("Runtime connection changed while publishing the native session. Inspect the original local Runtime state before retrying.");
  }
  return { token, endpoint: after.endpoint, version: committedVersion };
}
