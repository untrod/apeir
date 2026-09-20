/**
 * Desktop Bootstrap State Machine
 *
 * Manages the startup sequence for Nous Desktop. Each state has a
 * corresponding UI and timeout. No state renders a blank screen.
 *
 * State flow:
 *   shell_starting → loading_configuration → checking_environment
 *     → checking_runtime → starting_runtime → waiting_runtime
 *     → establishing_session → checking_workspace
 *     → checking_provider → checking_model_route
 *     → [onboarding_required] → ready
 *
 * Any state can transition to recoverable_error or fatal_error.
 */

export type BootstrapState =
  | "shell_starting"
  | "loading_configuration"
  | "checking_environment"
  | "checking_runtime"
  | "starting_runtime"
  | "waiting_runtime"
  | "establishing_session"
  | "checking_workspace"
  | "checking_provider"
  | "checking_model_route"
  | "onboarding_required"
  | "ready"
  | "recoverable_error"
  | "fatal_error";

export type DesktopSurface = "bootstrap" | "onboarding" | "dashboard" | "diagnostics";

export const ALLOWED_BOOTSTRAP_TRANSITIONS: Record<BootstrapState, readonly BootstrapState[]> = {
  shell_starting: ["loading_configuration", "recoverable_error", "fatal_error"],
  loading_configuration: ["checking_environment", "recoverable_error", "fatal_error"],
  checking_environment: ["checking_runtime", "recoverable_error", "fatal_error"],
  checking_runtime: ["starting_runtime", "establishing_session", "onboarding_required", "recoverable_error", "fatal_error"],
  starting_runtime: ["waiting_runtime", "recoverable_error", "fatal_error"],
  waiting_runtime: ["establishing_session", "recoverable_error", "fatal_error"],
  establishing_session: ["checking_workspace", "recoverable_error", "fatal_error"],
  checking_workspace: ["checking_provider", "recoverable_error", "fatal_error"],
  checking_provider: ["checking_model_route", "recoverable_error", "fatal_error"],
  checking_model_route: ["onboarding_required", "ready", "recoverable_error", "fatal_error"],
  onboarding_required: ["checking_runtime", "ready", "recoverable_error", "fatal_error"],
  ready: ["checking_runtime", "onboarding_required", "recoverable_error", "fatal_error"],
  recoverable_error: ["loading_configuration", "checking_runtime", "onboarding_required", "fatal_error"],
  fatal_error: ["loading_configuration"],
};

export function canTransitionBootstrap(from: BootstrapState, to: BootstrapState): boolean {
  return from === to || ALLOWED_BOOTSTRAP_TRANSITIONS[from].includes(to);
}

export function transitionBootstrap(
  status: BootstrapStatus,
  nextState: BootstrapState,
  patch: Partial<BootstrapStatus> = {},
): BootstrapStatus {
  if (!canTransitionBootstrap(status.state, nextState)) {
    throw new Error(`Invalid desktop bootstrap transition: ${status.state} -> ${nextState}`);
  }
  return {
    ...status,
    ...patch,
    state: nextState,
    progress: patch.progress ?? STATE_PROGRESS[nextState],
    progressMessage: patch.progressMessage ?? STATE_MESSAGES[nextState],
  };
}

export function selectDesktopSurface(
  status: BootstrapStatus,
  options: { fatal: boolean; onboarding: boolean; connected: boolean },
): DesktopSurface {
  if (options.fatal || status.state === "recoverable_error" || status.state === "fatal_error") return "diagnostics";
  if (options.onboarding || status.state === "onboarding_required") return "onboarding";
  if (status.state === "ready" || options.connected) return "dashboard";
  return "bootstrap";
}
export interface BootstrapStatus {
  state: BootstrapState;
  runtime: {
    reachable: boolean;
    running: boolean;
    version: string;
    port: number;
    host: string;
  };
  session: {
    established: boolean;
    tokenFingerprint: string;
  };
  workspace: {
    exists: boolean;
    path: string;
    valid: boolean;
  };
  provider: {
    configured: boolean;
    count: number;
  };
  modelRoute: {
    ready: boolean;
    defaultModel: string;
  };
  onboardingRequired: boolean;
  warnings: string[];
  errorCode: string | null;
  errorMessage: string | null;
  recoverable: boolean;
  progress: number; // 0-100
  progressMessage: string;
}

export interface BootstrapConfig {
  runtimeHost: string;
  runtimePort: number;
  autoStartRuntime: boolean;
  runtimeStartTimeoutMs: number;
  healthCheckIntervalMs: number;
  maxHealthCheckRetries: number;
  workspacePath: string;
  autoCreateWorkspace: boolean;
  requireProviderForDashboard: boolean;
}

const DEFAULT_BOOTSTRAP_CONFIG: BootstrapConfig = {
  runtimeHost: "127.0.0.1",
  runtimePort: 8770,
  autoStartRuntime: true,
  runtimeStartTimeoutMs: 15000,
  healthCheckIntervalMs: 300,
  maxHealthCheckRetries: 50,
  workspacePath: "",
  autoCreateWorkspace: true,
  requireProviderForDashboard: false,
};

export function createInitialStatus(): BootstrapStatus {
  return {
    state: "shell_starting",
    runtime: {
      reachable: false,
      running: false,
      version: "",
      port: 8770,
      host: "127.0.0.1",
    },
    session: {
      established: false,
      tokenFingerprint: "",
    },
    workspace: {
      exists: false,
      path: "",
      valid: false,
    },
    provider: {
      configured: false,
      count: 0,
    },
    modelRoute: {
      ready: false,
      defaultModel: "",
    },
    onboardingRequired: true,
    warnings: [],
    errorCode: null,
    errorMessage: null,
    recoverable: true,
    progress: 0,
    progressMessage: "Initializing...",
  };
}

export interface BootstrapStateHandlers {
  loadRuntimeSessionToken: () => Promise<string>;
  startRuntimeApi: () => Promise<string>;
  testConnection: () => Promise<boolean>;
  getRuntimeStatus: () => Promise<{
    running?: boolean;
    version?: string;
    providers?: number;
    workspace_available?: boolean;
    provider_configured?: boolean;
    ready?: boolean;
    session_required?: boolean;
    platform?: string;
    architecture?: string;
  } | null>;
  getWorkspaceStatus: () => Promise<{
    exists?: boolean;
    path?: string;
    valid?: boolean;
  } | null>;
  getProviderStatus: () => Promise<{
    configured?: boolean;
    count?: number;
  } | null>;
  getConfig: () => BootstrapConfig;
}

export const STATE_MESSAGES: Record<BootstrapState, string> = {
  shell_starting: "Starting Nous Desktop...",
  loading_configuration: "Loading configuration...",
  checking_environment: "Checking environment...",
  checking_runtime: "Checking Runtime API...",
  starting_runtime: "Starting Runtime API...",
  waiting_runtime: "Waiting for Runtime API...",
  establishing_session: "Establishing session...",
  checking_workspace: "Checking workspace...",
  checking_provider: "Checking provider configuration...",
  checking_model_route: "Checking model routing...",
  onboarding_required: "Setup required",
  ready: "Ready",
  recoverable_error: "Recoverable error",
  fatal_error: "Fatal error",
};

export const STATE_PROGRESS: Record<BootstrapState, number> = {
  shell_starting: 5,
  loading_configuration: 10,
  checking_environment: 20,
  checking_runtime: 30,
  starting_runtime: 40,
  waiting_runtime: 50,
  establishing_session: 60,
  checking_workspace: 70,
  checking_provider: 80,
  checking_model_route: 90,
  onboarding_required: 95,
  ready: 100,
  recoverable_error: 0,
  fatal_error: 0,
};

const ERROR_CODES: Record<string, { message: string; recoverable: boolean }> = {
  RUNTIME_NOT_RUNNING: {
    message: "The APEIR Runtime API is not running. It can be started automatically.",
    recoverable: true,
  },
  RUNTIME_START_FAILED: {
    message: "Could not start the APEIR Runtime API. Check that the nous CLI is installed.",
    recoverable: true,
  },
  RUNTIME_START_TIMEOUT: {
    message: "Runtime API did not become ready within the expected time.",
    recoverable: true,
  },
  SESSION_FAILED: {
    message: "Could not establish a session with the Runtime API.",
    recoverable: true,
  },
  SESSION_TOKEN_INVALID: {
    message: "The session token is invalid or expired.",
    recoverable: true,
  },
  WORKSPACE_MISSING: {
    message: "No workspace found. A default workspace can be created automatically.",
    recoverable: true,
  },
  WORKSPACE_PERMISSION: {
    message: "Cannot write to the workspace directory. Check file permissions.",
    recoverable: false,
  },
  CONFIG_CORRUPTED: {
    message: "Configuration files are corrupted. They will be reset to defaults.",
    recoverable: true,
  },
  PORT_CONFLICT: {
    message: "The configured port is already in use. An alternative port will be tried.",
    recoverable: true,
  },
  ENVIRONMENT_UNSUPPORTED: {
    message: "Your operating system or architecture may not be fully supported.",
    recoverable: false,
  },
  WEBVIEW_MISSING: {
    message: "WebView2 runtime is not available. Please install it from Microsoft.",
    recoverable: false,
  },
  UNKNOWN_ERROR: {
    message: "An unexpected error occurred during startup.",
    recoverable: true,
  },
};

export function getErrorInfo(
  code: string,
): { message: string; recoverable: boolean } {
  return ERROR_CODES[code] || ERROR_CODES.UNKNOWN_ERROR;
}

/** BootstrapResult — alias for BootstrapStatus, matches spec requirements. */
export type BootstrapResult = BootstrapStatus;

export function tokenFingerprint(token: string): string {
  if (!token || token.length < 8) return "none";
  return `${token.substring(0, 4)}...${token.substring(token.length - 4)}`;
}
