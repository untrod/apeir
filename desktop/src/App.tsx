/**
 * Nous Desktop — Chat-first Experience Layer.
 *
 * Bootstrap flow:
 *   1. Check for saved session token
 *   2. Test runtime connection
 *   3. Check workspace, providers, model routes
 *   4. If onboarding needed → show OnboardingWizard
 *   5. If ready → show main dashboard
 *   6. Any error → show DiagnosticPage (never white screen)
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { injectDesignTokens, colors, typo, space, btnPrimary, btnSecondary } from "./design";
import { ThemeProvider, useTheme } from "./theme";
import { ToastProvider } from "./components/Toast";
import { ErrorBoundary, registerGlobalErrorHandlers } from "./components/ErrorBoundary";
import { BootstrapScreen } from "./components/BootstrapScreen";
import { DiagnosticPage, type DiagnosticState } from "./components/DiagnosticPage";
import { OnboardingWizard } from "./components/OnboardingWizard";
import { entityStore, eventClient } from "./store";
import {
  useConversations, useTasks, useNodes, useModels,
  usePendingApprovals, useStoreHydrated,
} from "./store";
import {
  api, testConnection, fetchTasks, fetchNodes, fetchModels, fetchApprovals, fetchConversations,
  fetchStatus, setConfig, getConfig,
} from "./lib/api";
import type { GlobalSearchResult, RuntimeEventEnvelope } from "./lib/api";
import {
  createInitialStatus,
  getErrorInfo,
  tokenFingerprint,
  transitionBootstrap,
  type BootstrapStatus,
  type BootstrapConfig,
} from "./lib/bootstrap";
import { migrateOldState, resetUIState, saveMigrationReport } from "./lib/migration";

// Components
import { StatusBar } from "./components/StatusBar";
import { Sidebar, type NavPage } from "./components/Sidebar";
import { SessionBar } from "./components/SessionBar";
import { DetailDrawer, type DrawerView } from "./components/DetailDrawer";
import { Inspector } from "./components/Inspector";
import { ConnectScreen } from "./components/ConnectScreen";
import { ChatView } from "./components/ChatView";
import { TaskCenter } from "./components/TaskCenter";
import { CommandPalette, createDefaultCommands } from "./components/CommandPalette";
import { RuntimeCard, TaskCard } from "./components/RuntimeCard";
import { CredentialSettings } from "./components/CredentialSettings";
import { DeveloperPlatform } from "./components/DeveloperPlatform";
import { DocumentWorkbench } from "./components/DocumentWorkbench";
import { EnvironmentInspector } from "./components/EnvironmentInspector";
import { SimulationWorkbench } from "./components/SimulationWorkbench";
import { errorMessage, fixedNumber } from "./lib/format";

// Design token injection (run once)
injectDesignTokens();

// Bootstrap Runner
async function runBootstrap(
  updateStatus: (fn: (prev: BootstrapStatus) => BootstrapStatus) => void,
  config: BootstrapConfig,
): Promise<void> {
  // Local mutable state for decisions later in the flow
  let workspaceCreated = false;

  const setState = (state: BootstrapStatus["state"], progressMsg?: string) => {
    updateStatus((prev) => transitionBootstrap(prev, state, {
      progressMessage: progressMsg || undefined,
    }));
  };

  // Phase 1: Load configuration
  setState("loading_configuration", "Loading configuration...");
  updateStatus((prev) => ({
    ...prev,
    progress: 10,
    runtime: { ...prev.runtime, host: config.runtimeHost, port: config.runtimePort },
  }));

  // Run old-state migration
  try {
    const report = migrateOldState();
    saveMigrationReport(report);
    if (report.errors.length > 0) {
      updateStatus((prev) => ({
        ...prev,
        warnings: [...prev.warnings, ...report.errors.map((e) => `Migration: ${e}`)],
      }));
    }
  } catch {
    // Non-critical
  }

  // Init app config dirs via Tauri
  if ("__TAURI_INTERNALS__" in window) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("init_app_config");
      if (config.autoCreateWorkspace) {
        const workspacePath = await invoke<string>("get_default_workspace_path");
        await invoke("create_default_workspace", { path: workspacePath });
        workspaceCreated = true;
      }
      const runtime = await invoke<{
        endpoint: string;
        ready: boolean;
        session_available: boolean;
      }>("get_runtime_process_status");
      let token = getConfig().token;
      if (runtime.session_available) {
        token = await invoke<string>("load_runtime_session_token");
      }
      setConfig({ url: runtime.endpoint, token });
      updateStatus((prev) => ({
        ...prev,
        runtime: { ...prev.runtime, reachable: runtime.ready, running: runtime.ready },
        session: {
          established: runtime.ready && !!token,
          tokenFingerprint: tokenFingerprint(token),
        },
      }));
    } catch {
      // Non-critical — config dirs will be created on first write
    }
  }

  // Phase 2: Check environment
  setState("checking_environment", "Checking environment...");
  updateStatus((prev) => ({ ...prev, progress: 20 }));

  // Phase 3: Check runtime
  setState("checking_runtime", "Checking Runtime API...");
  updateStatus((prev) => ({ ...prev, progress: 30 }));

  let connected = await testConnection();
  if (connected) {
    updateStatus((prev) => ({
      ...prev,
      runtime: { ...prev.runtime, reachable: true, running: true },
    }));

    // Get runtime status for version info
    try {
      const status = await fetchStatus();
      if (status) {
        updateStatus((prev) => ({
          ...prev,
          runtime: {
            ...prev.runtime,
            version: status.version,
            running: status.running,
          },
        }));
      }
    } catch {
      // Non-critical
    }
  }

  // Phase 4: Start runtime if needed
  if (!connected && config.autoStartRuntime) {
    setState("starting_runtime", "Starting Runtime API...");
    updateStatus((prev) => ({ ...prev, progress: 40 }));

    if ("__TAURI_INTERNALS__" in window) {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const token = await invoke<string>("start_runtime_api");
        if (token) {
          setConfig({ url: getConfig().url, token });
          updateStatus((prev) => ({
            ...prev,
            session: { ...prev.session, tokenFingerprint: tokenFingerprint(token) },
          }));
        }

        // Wait for runtime
        setState("waiting_runtime", "Waiting for Runtime API...");
        updateStatus((prev) => ({ ...prev, progress: 50 }));

        const deadline = Date.now() + config.runtimeStartTimeoutMs;
        while (Date.now() < deadline) {
          if (await testConnection()) {
            connected = true;
            break;
          }
          await new Promise((r) => setTimeout(r, config.healthCheckIntervalMs));
        }

        if (connected) {
          updateStatus((prev) => ({
            ...prev,
            runtime: { ...prev.runtime, reachable: true, running: true },
          }));
        } else {
          updateStatus((prev) => ({
            ...prev,
            state: "recoverable_error",
            errorCode: "RUNTIME_START_TIMEOUT",
            errorMessage: getErrorInfo("RUNTIME_START_TIMEOUT").message,
            recoverable: true,
          }));
          return;
        }
      } catch (e) {
        updateStatus((prev) => ({
          ...prev,
          state: "recoverable_error",
          errorCode: "RUNTIME_START_FAILED",
          errorMessage: errorMessage(e, getErrorInfo("RUNTIME_START_FAILED").message),
          recoverable: true,
        }));
        return;
      }
    }
  }

  if (!connected) {
    // Runtime not running and auto-start disabled or not in Tauri
    // Still allow limited mode — proceed to onboarding
    updateStatus((prev) => ({
      ...prev,
      runtime: { ...prev.runtime, reachable: false, running: false },
      warnings: [...prev.warnings, "Runtime API is not running. Some features will be unavailable."],
      state: "onboarding_required",
      onboardingRequired: true,
      progress: 95,
      progressMessage: "Setup required",
    }));
    return;
  }

  // Phase 5: Establish session
  setState("establishing_session", "Establishing session...");
  updateStatus((prev) => ({ ...prev, progress: 60 }));

  if ("__TAURI_INTERNALS__" in window) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const token = await invoke<string>("load_runtime_session_token");
      if (token) {
        setConfig({ url: getConfig().url, token });
        updateStatus((prev) => ({
          ...prev,
          session: { established: true, tokenFingerprint: tokenFingerprint(token) },
        }));
      }
    } catch {
      // Token may not be available yet
      updateStatus((prev) => ({
        ...prev,
        session: { ...prev.session, established: false },
        warnings: [...prev.warnings, "Could not load session token. Some features may require re-authentication."],
      }));
    }
  } else {
    // Dev mode — session from sessionStorage
    const cfg = getConfig();
    updateStatus((prev) => ({
      ...prev,
      session: {
        established: !!cfg.token,
        tokenFingerprint: tokenFingerprint(cfg.token),
      },
    }));
  }

  // Phase 6: Check workspace
  setState("checking_workspace", "Checking workspace...");
  updateStatus((prev) => ({ ...prev, progress: 70 }));

  let wsExists = false;
  try {
    const resp = await fetch(`${getConfig().url}/api/v1/workspace`, {
      headers: { Authorization: `Bearer ${getConfig().token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      const active = data?.data?.active;
      wsExists = !!active;
      updateStatus((prev) => ({
        ...prev,
        workspace: {
          exists: wsExists,
          path: active?.root || "",
          valid: !!active,
        },
      }));
    }
  } catch {
    updateStatus((prev) => ({
      ...prev,
      workspace: { exists: false, path: "", valid: false },
      warnings: [...prev.warnings, "Could not verify workspace. A default workspace will be created if needed."],
    }));
  }

  // Phase 7: Check providers
  setState("checking_provider", "Checking provider configuration...");
  updateStatus((prev) => ({ ...prev, progress: 80 }));

  try {
    const resp = await fetch(`${getConfig().url}/api/v1/providers`, {
      headers: { Authorization: `Bearer ${getConfig().token}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      const providers = data?.data?.providers || data?.data || [];
      const count = Array.isArray(providers) ? providers.length : 0;
      updateStatus((prev) => ({
        ...prev,
        provider: { configured: count > 0, count },
      }));
    }
  } catch {
    updateStatus((prev) => ({
      ...prev,
      provider: { configured: false, count: 0 },
    }));
  }

  // Phase 8: Check model route
  setState("checking_model_route", "Checking model routing...");
  updateStatus((prev) => ({ ...prev, progress: 90 }));

  // Phase 9: Auto-create workspace if needed
  if ("__TAURI_INTERNALS__" in window && config.autoCreateWorkspace && !wsExists && !workspaceCreated) {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const wsPath: string = await invoke("get_default_workspace_path");
      await invoke("create_default_workspace", { path: wsPath });
      workspaceCreated = true;
      updateStatus((prev) => ({
        ...prev,
        workspace: { exists: true, path: wsPath, valid: true },
      }));
    } catch {
      // Non-critical — user can create workspace during onboarding
    }
  }

  const onboardingCompleted = localStorage.getItem("nous_onboarding_completed") === "1" ||
    localStorage.getItem("nous_setup_complete") === "1";

  updateStatus((prev) => ({
    ...prev,
    state: onboardingCompleted ? "ready" : "onboarding_required",
    onboardingRequired: !onboardingCompleted,
    progress: onboardingCompleted ? 100 : 95,
    progressMessage: onboardingCompleted ? "Ready" : "Setup required",
  }));
}

// Page Components
function PageHeader({ title, subtitle, children }: { title: string; subtitle: string; children?: React.ReactNode }) {
  return (
    <div style={{
      padding: `${space.lg} ${space.xl}`, background: colors.surface,
      borderBottom: `1px solid ${colors.borderLight}`,
      display: "flex", alignItems: "center", justifyContent: "space-between",
      flexWrap: "wrap", gap: space.md,
    }}>
      <div>
        <h1 style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text, margin: 0 }}>{title}</h1>
        <p style={{ fontSize: typo.sm, color: colors.textSecondary, margin: `${space.xs} 0 0 0` }}>{subtitle}</p>
      </div>
      {children}
    </div>
  );
}

function EmptyView({ message }: { message: string }) {
  return (
    <div style={{ textAlign: "center", padding: space.xxxl, color: colors.textTertiary, fontSize: typo.md }}>
      {message}
    </div>
  );
}

function TasksPage({ onTaskClick, onTraceClick }: { onTaskClick: (taskId: string) => void; onTraceClick: (traceId: string) => void }) {
  const tasks = useTasks();
  const [filter, setFilter] = useState("");
  const statusFilters = ["", "running", "queued", "awaiting_approval", "verifying", "completed", "failed"];
  const filtered = filter ? tasks.filter((t) => t.status === filter) : tasks;
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <PageHeader title="Tasks" subtitle={`${tasks.length} total · ${filtered.length} shown`}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {statusFilters.map((s) => (
            <button key={s} onClick={() => setFilter(s)} style={{
              padding: `2px ${space.sm}`, borderRadius: "9999px",
              border: `1px solid ${filter === s ? colors.accent : colors.border}`,
              background: filter === s ? colors.accentSoft : "transparent",
              color: filter === s ? colors.accent : colors.textSecondary,
              fontSize: typo.xs, cursor: "pointer", fontFamily: typo.font,
            }}>{s || "all"}</button>
          ))}
        </div>
      </PageHeader>
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        {tasks.length === 0 ? <EmptyView message="No tasks yet. Send a message to create one." /> :
          filtered.map((task) => (
            <TaskCard key={task.id} title={task.name || task.id} status={task.status}
              subtitle={`Priority: ${task.priority} · ${task.model_id || "auto"}`}
              detail={{ task_id: task.id, model: task.model_id || "auto", priority: task.priority,
                progress: `${task.progress_pct}%`, steps: `${task.steps.filter((s) => s.status === "completed").length}/${task.steps.length}`,
                created: new Date(task.created_at).toLocaleString() }}
              progress={task.progress_pct} onClick={() => onTaskClick(task.id)} />
          ))}
      </div>
    </div>
  );
}

function NodesPage({ onNodeClick }: { onNodeClick: (nodeId: string) => void }) {
  const nodes = useNodes();
  const onlineCount = nodes.filter((n) => n.online).length;
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <PageHeader title="Nodes" subtitle={`${nodes.length} registered · ${onlineCount} online`} />
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        {nodes.length === 0 ? <EmptyView message="No nodes registered." /> :
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: space.lg }}>
            {nodes.map((node) => (
              <RuntimeCard key={node.id} variant="node" title={node.name}
                status={node.online ? "online" : "offline"}
                subtitle={`${node.platform} · ${node.arch} · ${node.role}`}
                detail={{ node_id: node.id, platform: node.platform, arch: node.arch, role: node.role,
                  last_seen: new Date(node.last_seen).toLocaleString(), capabilities: String(node.capabilities.length),
                  active_tasks: String(node.active_task_count), latency: node.network_latency_ms ? `${node.network_latency_ms}ms` : "—" }}
                onClick={() => onNodeClick(node.id)} />
            ))}
          </div>}
      </div>
    </div>
  );
}

function ModelsPage({ onModelClick }: { onModelClick: (modelId: string) => void }) {
  const models = useModels();
  const healthy = models.filter((m) => m.health === "healthy").length;
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <PageHeader title="Models" subtitle={`${models.length} configured · ${healthy} healthy`} />
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        {models.length === 0 ? <EmptyView message="No models configured. Add a provider to get started." /> :
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: space.lg }}>
            {models.map((model) => (
              <RuntimeCard key={model.id} variant="model" title={model.display_name}
                status={model.state} subtitle={`${model.provider_kind} · ${model.health}`}
                detail={{ model_id: model.id, provider: model.provider_id, health: model.health,
                  latency: `${fixedNumber(model.avg_latency_ms, 0)}ms`, cost: `$${fixedNumber(model.cost_per_1k_tokens_usd, 4)}/1k`,
                  capabilities: (model.capabilities || []).join(", "),
                  calibration: model.calibration ? `${fixedNumber(Number(model.calibration.overall_score || 0) * 100, 0)}%` : "—" }}
                onClick={() => onModelClick(model.id)} />
            ))}
          </div>}
      </div>
    </div>
  );
}

function WorkspacePage() {
  const approvals = usePendingApprovals();
  const [workspacePath, setWorkspacePath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadWorkspace() {
      try {
        if ("__TAURI_INTERNALS__" in window) {
          const { invoke } = await import("@tauri-apps/api/core");
          const configured = await invoke<string | null>("get_config", { key: "workspace_path" });
          if (!cancelled && configured) setWorkspacePath(configured);
          return;
        }
        const status = await api<{ path?: string }>("/api/v1/workspace/status");
        if (!cancelled) setWorkspacePath(status.path || "");
      } catch {
        // The page remains usable and can configure a workspace below.
      }
    }
    void loadWorkspace();
    return () => { cancelled = true; };
  }, []);

  const chooseWorkspace = async () => {
    if (!("__TAURI_INTERNALS__" in window) || busy) return;
    setBusy(true);
    setMessage("");
    setError("");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const selected = await invoke<string | null>("select_workspace_directory");
      if (!selected) {
        setMessage("No changes were made.");
        return;
      }
      const activated = await invoke<string>("create_default_workspace", { path: selected });
      const token = await invoke<string>("restart_runtime_api");
      setConfig({ url: getConfig().url, token });
      let connected = false;
      for (let attempt = 0; attempt < 40; attempt++) {
        if (await testConnection()) {
          connected = true;
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      if (!connected) throw new Error("Runtime did not restart with the selected workspace.");
      eventClient.stop();
      eventClient.start({ mode: "polling" });
      setWorkspacePath(activated);
      setMessage("Workspace activated. Runtime access is limited to this directory.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not activate the workspace.");
    } finally {
      setBusy(false);
    }
  };

  const openWorkspace = async () => {
    if (!("__TAURI_INTERNALS__" in window) || !workspacePath) return;
    setError("");
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      await invoke("open_workspace_directory");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not open the workspace.");
    }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <PageHeader title="Workspace" subtitle="A controlled filesystem boundary for Nous operations" />
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        <div style={{
          background: colors.surface,
          border: `1px solid ${colors.border}`,
          borderRadius: "14px",
          padding: space.xl,
          marginBottom: space.lg,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: space.lg, alignItems: "flex-start", flexWrap: "wrap" }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <h3 style={{ fontSize: typo.md, fontWeight: typo.semibold, color: colors.text, margin: 0 }}>Active directory</h3>
              <p style={{ fontSize: typo.sm, color: colors.textSecondary, margin: `${space.xs} 0 ${space.md} 0` }}>
                Nous can read or modify files only inside the directory you explicitly select. System directories and path escapes are blocked.
              </p>
              <code style={{
                display: "block",
                fontFamily: typo.mono,
                fontSize: typo.sm,
                color: workspacePath ? colors.text : colors.textTertiary,
                background: colors.inlineCodeBg,
                borderRadius: "8px",
                padding: `${space.sm} ${space.md}`,
                overflowWrap: "anywhere",
              }}>
                {workspacePath || "No workspace selected"}
              </code>
            </div>
            <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
              <button onClick={chooseWorkspace} disabled={busy} style={{ ...btnPrimary, opacity: busy ? 0.65 : 1 }}>
                {busy ? "Activating..." : "Choose folder"}
              </button>
              <button onClick={openWorkspace} disabled={!workspacePath || busy} style={{ ...btnSecondary, opacity: !workspacePath || busy ? 0.55 : 1 }}>
                Open folder
              </button>
            </div>
          </div>
          {message && <div style={{ marginTop: space.md, color: colors.success, fontSize: typo.sm }}>{message}</div>}
          {error && <div style={{ marginTop: space.md, color: colors.danger, fontSize: typo.sm }}>{error}</div>}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: space.lg }}>
          {[{ title: "Packs", desc: "Domain knowledge packs", action: "nous pack install", empty: true },
            { title: "Knowledge", desc: "Ingested documents", action: "nous knowledge add", empty: true },
            { title: "Files", desc: workspacePath ? "Bound to the active directory" : "Select a workspace directory", action: workspacePath ? "Workspace boundary active" : "Choose a folder above", empty: !workspacePath },
            { title: "Evidence", desc: `${approvals.length} pending approvals`, action: "View approvals", empty: approvals.length === 0, accent: approvals.length > 0 },
            { title: "Context Runtime", desc: "Active context snapshots", action: "Send a message to build context", empty: true },
            { title: "Experience", desc: "Learned patterns", action: "Run tasks to build experience", empty: true },
          ].map((card) => (
            <div key={card.title} style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: "14px", padding: space.xl }}>
              <h3 style={{ fontSize: typo.md, fontWeight: typo.semibold, margin: `0 0 ${space.xs} 0`, color: card.accent ? colors.warning : colors.text }}>{card.title}</h3>
              <p style={{ fontSize: typo.sm, color: colors.textSecondary, margin: `0 0 ${space.md} 0` }}>{card.desc}</p>
              <code style={{ fontFamily: typo.mono, fontSize: typo.xs, background: colors.inlineCodeBg, padding: "2px 6px", borderRadius: "6px", color: colors.textTertiary }}>{card.action}</code>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SettingsPage() {
  const [devMode, setDevMode] = useState(() => localStorage.getItem("nous_developer_mode") === "1");
  const { resolved, toggle: toggleTheme } = useTheme();
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      <PageHeader title="Settings" subtitle="Preferences and configuration" />
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        <div style={{ maxWidth: 560 }}>
          <div style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: "14px", padding: space.xl, marginBottom: space.lg }}>
            <h3 style={{ fontSize: typo.md, fontWeight: typo.semibold, margin: `0 0 ${space.md} 0`, color: colors.text }}>Provider Credentials</h3>
            <CredentialSettings />
          </div>
          {[
            { title: "Appearance", items: [{ label: "Theme", value: resolved === "dark" ? "Dark" : "Light", action: toggleTheme, actionLabel: resolved === "dark" ? "Use Light" : "Use Dark" }] },
            { title: "Developer", items: [{ label: "Developer Mode", value: devMode ? "On" : "Off", action: () => { const v = !devMode; setDevMode(v); localStorage.setItem("nous_developer_mode", v ? "1" : "0"); }, actionLabel: devMode ? "Turn Off" : "Turn On", desc: "Enables Inspector panel for runtime internals" }] },
            { title: "Provider", items: [{ label: "Configure Providers", value: "Manage API keys and models", action: () => { localStorage.removeItem("nous_onboarding_completed"); localStorage.removeItem("nous_setup_complete"); window.location.reload(); }, actionLabel: "Re-run Setup", desc: "Re-open the setup wizard to add or change providers" }] },
            { title: "Diagnostics", items: [
              { label: "Reset UI State", value: "Clear all local UI cache", action: () => { resetUIState(); window.location.reload(); }, actionLabel: "Reset", desc: "Clears cached UI state. Does not affect workspace data." },
            ]},
          ].map((section) => (
            <div key={section.title} style={{ background: colors.surface, border: `1px solid ${colors.border}`, borderRadius: "14px", padding: space.xl, marginBottom: space.lg }}>
              <h3 style={{ fontSize: typo.md, fontWeight: typo.semibold, margin: `0 0 ${space.md} 0`, color: colors.text }}>{section.title}</h3>
              {section.items.map((item) => (
                <div key={item.label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `${space.sm} 0`, borderBottom: `1px solid ${colors.borderLight}` }}>
                  <div>
                    <div style={{ fontSize: typo.base, color: colors.text }}>{item.label}</div>
                    {"desc" in item && item.desc && <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 2 }}>{item.desc}</div>}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
                    <span style={{ fontSize: typo.sm, color: colors.textSecondary }}>{item.value}</span>
                    {item.action && <button onClick={item.action} style={{ padding: `${space.xs} ${space.sm}`, fontSize: typo.xs, fontWeight: typo.medium, fontFamily: typo.font, cursor: "pointer", background: colors.accentSoft, color: colors.accent, border: `1px solid ${colors.accent}40`, borderRadius: "6px" }}>{item.actionLabel}</button>}
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Resource Dock
function ResourceDock() {
  const nodes = useNodes();
  const models = useModels();
  const tasks = useTasks();
  const onlineNodes = nodes.filter((n) => n.online);
  const enabledModels = models.filter((m) => m.state !== "disabled");
  const runningTasks = tasks.filter((t) => ["running", "queued", "awaiting_approval", "verifying"].includes(t.status));

  return (
    <div style={{ height: 104, flexShrink: 0, borderTop: `1px solid ${colors.borderLight}`, background: colors.surface,
      display: "grid", gridTemplateColumns: "1.1fr 1.8fr 0.8fr", gap: space.lg, padding: `${space.md} ${space.xl}` }}>
      <DockSection title="My Nodes" count={onlineNodes.length}>
        {onlineNodes.slice(0, 4).map((n) => <DockItem key={n.id} title={n.name} detail={`${n.platform} · ${n.role}`} active />)}
      </DockSection>
      <DockSection title="Common Models" count={enabledModels.length}>
        {enabledModels.slice(0, 5).map((m) => <DockItem key={m.id} title={m.display_name} detail={`${m.provider_kind} · ${m.health}`} active={m.health === "healthy"} />)}
      </DockSection>
      <DockSection title="System Status" count={runningTasks.length}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm, width: "100%" }}>
          <MiniDockStat label="Runtime" value="Ready" ok />
          <MiniDockStat label="Active" value={String(runningTasks.length)} ok={runningTasks.length === 0} />
        </div>
      </DockSection>
    </div>
  );
}

function DockSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: space.sm }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: typo.xs, color: colors.textTertiary }}>
        <span style={{ fontWeight: typo.semibold }}>{title}</span><span>{count}</span>
      </div>
      <div style={{ display: "flex", gap: space.sm, minWidth: 0, overflowX: "auto", paddingBottom: 2 }}>{children}</div>
    </section>
  );
}

function DockItem({ title, detail, active }: { title: string; detail: string; active: boolean }) {
  return (
    <div style={{ minWidth: 150, maxWidth: 190, border: `1px solid ${active ? colors.accentMuted : colors.borderLight}`,
      background: active ? colors.accentSoft : colors.bg, borderRadius: 8, padding: `${space.sm} ${space.md}` }}>
      <div style={{ fontSize: typo.sm, fontWeight: typo.semibold, color: colors.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{title}</div>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>{detail}</div>
    </div>
  );
}

function MiniDockStat({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div style={{ border: `1px solid ${colors.borderLight}`, background: colors.bg, borderRadius: 8, padding: space.sm }}>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2, fontSize: typo.sm, color: colors.text }}>
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: ok ? colors.success : colors.warning }} />{value}
      </div>
    </div>
  );
}

// Main App Shell
function AppShell() {
  const [bootstrapStatus, setBootstrapStatus] = useState<BootstrapStatus>(createInitialStatus());
  const [fatalDiag, setFatalDiag] = useState<DiagnosticState | null>(null);
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState<NavPage>("chat");
  const [drawer, setDrawer] = useState<DrawerView>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sessionBarCollapsed, setSessionBarCollapsed] = useState(true);
  const [activeConversationId, setActiveConversationId] = useState<string | undefined>();
  const { toggle: toggleTheme } = useTheme();
  const hydrated = useStoreHydrated();
  const tasks = useTasks();
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);

  // Register global error handlers
  useEffect(() => {
    return registerGlobalErrorHandlers((diag) => {
      setFatalDiag({ ...diag, onRetry: () => setFatalDiag(null) });
    });
  }, []);

  // Run bootstrap
  const bootstrapRan = useRef(false);
  useEffect(() => {
    if (bootstrapRan.current) return;
    bootstrapRan.current = true;

    runBootstrap((fn) => setBootstrapStatus((prev) => {
      const result = typeof fn === "function" ? fn(prev) : fn;
      return result;
    }), {
      runtimeHost: "127.0.0.1",
      runtimePort: 8770,
      autoStartRuntime: true,
      runtimeStartTimeoutMs: 15000,
      healthCheckIntervalMs: 300,
      maxHealthCheckRetries: 50,
      workspacePath: "",
      autoCreateWorkspace: true,
      requireProviderForDashboard: false,
    });
  }, [bootstrapAttempt]);

  const openRuntimeLogs = useCallback(async () => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("open_logs_directory");
  }, []);
  const retryBootstrap = useCallback(() => {
    bootstrapRan.current = false;
    setConnected(false);
    setBootstrapStatus(createInitialStatus());
    setBootstrapAttempt((attempt) => attempt + 1);
  }, []);

  // Handle bootstrap completion
  useEffect(() => {
    if (bootstrapStatus.state === "ready") {
      // Hydrate store and load data
      entityStore.hydrate().then(() => {
        Promise.allSettled([
          fetchTasks("", 100),
          fetchNodes(),
          fetchModels(),
          fetchApprovals(),
          fetchConversations(),
        ]).then(([tasksData, nodesData, modelsData, approvalsData, conversationsData]) => {
          if (tasksData.status === "fulfilled" && tasksData.value?.tasks) {
            entityStore.upsertTasks(tasksData.value.tasks as any);
          }
          if (nodesData.status === "fulfilled" && Array.isArray(nodesData.value)) {
            entityStore.upsertNodes(nodesData.value as any);
          }
          if (modelsData.status === "fulfilled" && modelsData.value?.models) {
            entityStore.upsertModels(modelsData.value.models as any);
          }
          if (approvalsData.status === "fulfilled" && approvalsData.value?.approvals) {
            entityStore.upsertApprovals(approvalsData.value.approvals as any);
          }
          if (conversationsData.status === "fulfilled" && conversationsData.value?.conversations) {
            entityStore.upsertConversations(conversationsData.value.conversations);
          }
          eventClient.start({ mode: "polling" });
        });
        setConnected(true);
      });
    } else if (bootstrapStatus.state === "onboarding_required") {
      setShowOnboarding(true);
      // Still attempt store hydration
      entityStore.hydrate().catch(() => {});
    }
  }, [bootstrapStatus.state]);

  // Poll for updates when connected
  useEffect(() => {
    if (!connected) return;
    const timer = setInterval(async () => {
      const [tasksData, nodesData, modelsData, approvalsData, conversationsData] = await Promise.allSettled([
        fetchTasks("", 50), fetchNodes(), fetchModels(), fetchApprovals(), fetchConversations(),
      ]);
      if (tasksData.status === "fulfilled" && tasksData.value?.tasks) entityStore.upsertTasks(tasksData.value.tasks as any);
      if (nodesData.status === "fulfilled" && Array.isArray(nodesData.value)) entityStore.upsertNodes(nodesData.value as any);
      if (modelsData.status === "fulfilled" && modelsData.value?.models) entityStore.upsertModels(modelsData.value.models as any);
      if (approvalsData.status === "fulfilled" && approvalsData.value?.approvals) entityStore.upsertApprovals(approvalsData.value.approvals as any);
      if (conversationsData.status === "fulfilled" && conversationsData.value?.conversations) entityStore.upsertConversations(conversationsData.value.conversations);
    }, 5000);
    return () => { clearInterval(timer); eventClient.stop(); };
  }, [connected]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === "k") { e.preventDefault(); setPaletteOpen((p) => !p); }
      if (mod && e.key === "i") { e.preventDefault(); setInspectorOpen((p) => !p); }
      if (e.key === "Escape") { if (drawer) setDrawer(null); else if (inspectorOpen) setInspectorOpen(false); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [drawer, inspectorOpen]);

  const handleEventClick = useCallback((event: RuntimeEventEnvelope) => {
    const p = event.payload || {};
    if (p.task_id) setDrawer({ kind: "task", taskId: String(p.task_id) });
    else if (p.trace_id) setDrawer({ kind: "trace", traceId: String(p.trace_id) });
    else if (event.event_type?.startsWith("node.") && p.node_id) setDrawer({ kind: "node", nodeId: String(p.node_id) });
  }, []);

  const handleSearchResult = useCallback((result: GlobalSearchResult) => {
    if (result.kind === "conversation") {
      setPage("chat");
      setActiveConversationId(result.id);
    } else if (result.kind === "run") {
      setDrawer({ kind: "trace", traceId: result.id });
    } else if (result.kind === "artifact") {
      setDrawer({ kind: "artifact", artifactId: result.id });
    } else if (result.kind === "file") {
      setPage("workspace");
    }
  }, []);

  const commands = createDefaultCommands(
    (p) => setPage(p as NavPage),
    { onToggleInspector: () => setInspectorOpen((p) => !p), onToggleTheme: toggleTheme, onNewSession: () => setPage("chat") },
  );

  // Render: Fatal Error
  if (fatalDiag) {
    return <DiagnosticPage {...fatalDiag} />;
  }

  // Render: Onboarding
  if (showOnboarding) {
    return (
      <OnboardingWizard
        onComplete={() => {
          setShowOnboarding(false);
          setConnected(true);
          // Re-run store hydration
          entityStore.hydrate().then(() => {
            Promise.allSettled([fetchTasks("", 100), fetchNodes(), fetchModels(), fetchApprovals(), fetchConversations()])
              .then(([tasksData, nodesData, modelsData, approvalsData, conversationsData]) => {
                if (tasksData.status === "fulfilled" && tasksData.value?.tasks) entityStore.upsertTasks(tasksData.value.tasks as any);
                if (nodesData.status === "fulfilled" && Array.isArray(nodesData.value)) entityStore.upsertNodes(nodesData.value as any);
                if (modelsData.status === "fulfilled" && modelsData.value?.models) entityStore.upsertModels(modelsData.value.models as any);
                if (approvalsData.status === "fulfilled" && approvalsData.value?.approvals) entityStore.upsertApprovals(approvalsData.value.approvals as any);
                if (conversationsData.status === "fulfilled" && conversationsData.value?.conversations) entityStore.upsertConversations(conversationsData.value.conversations);
                eventClient.start({ mode: "polling" });
              });
          });
        }}
        onSkip={() => {
          setShowOnboarding(false);
          setConnected(true);
          entityStore.hydrate().catch(() => {});
        }}
      />
    );
  }

  // Render: Bootstrap / Error
  if (bootstrapStatus.state === "recoverable_error" || bootstrapStatus.state === "fatal_error") {
    return (
      <BootstrapScreen
        status={bootstrapStatus}
        onRetry={retryBootstrap}
        onStartRuntime={async () => {
          if ("__TAURI_INTERNALS__" in window) {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              await invoke("start_runtime_api");
              retryBootstrap();
            } catch { /* Shown in UI */ }
          }
        }}
        onResetSession={async () => {
          if ("__TAURI_INTERNALS__" in window) {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              await invoke("load_runtime_session_token");
              retryBootstrap();
            } catch { /* Shown in UI */ }
          }
        }}
        onCreateWorkspace={retryBootstrap}
        onOpenLogs={openRuntimeLogs}
        onResetUI={() => { resetUIState(); retryBootstrap(); }}
        onProceedToOnboarding={() => setShowOnboarding(true)}
        onProceedToDashboard={() => setConnected(true)}
      />
    );
  }

  if (bootstrapStatus.state !== "ready" && !connected) {
    return (
      <BootstrapScreen
        status={bootstrapStatus}
        onRetry={retryBootstrap}
        onStartRuntime={async () => {
          if ("__TAURI_INTERNALS__" in window) {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              await invoke("start_runtime_api");
              retryBootstrap();
            } catch { /* Shown in UI */ }
          }
        }}
        onResetSession={async () => {
          if ("__TAURI_INTERNALS__" in window) {
            try {
              const { invoke } = await import("@tauri-apps/api/core");
              await invoke("load_runtime_session_token");
            } catch { /* Shown in UI */ }
          }
        }}
        onCreateWorkspace={() => {}}
        onOpenLogs={openRuntimeLogs}
        onResetUI={() => { resetUIState(); retryBootstrap(); }}
        onProceedToOnboarding={() => setShowOnboarding(true)}
        onProceedToDashboard={() => setConnected(true)}
      />
    );
  }

  // Render: Main Dashboard
  return (
    <>
      <StatusBar onSearch={() => setPaletteOpen(true)} />
      <div style={{ display: "flex", flex: 1, overflow: "hidden", height: `calc(100vh - ${page === "chat" ? 44 : 148}px)` }}>
        <Sidebar currentPage={page} onNavigate={setPage} inspectorOpen={inspectorOpen}
          onToggleInspector={() => setInspectorOpen(!inspectorOpen)}
          taskCount={tasks.filter((t) => ["running", "queued", "awaiting_approval"].includes(t.status)).length}
          collapsed={sidebarCollapsed} onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)} />
        {page === "chat" && (
          <SessionBar activeId={activeConversationId} onSelect={(id) => setActiveConversationId(id)}
            onNew={() => setActiveConversationId(undefined)} collapsed={sessionBarCollapsed}
            onToggleCollapse={() => setSessionBarCollapsed(!sessionBarCollapsed)} />
        )}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
          <div style={{ flex: inspectorOpen ? "40%" : "1", overflow: "hidden", transition: "flex 0.3s ease" }}>
            {page === "chat" && <ChatView conversationId={activeConversationId} onConversationCreated={setActiveConversationId} onCardClick={handleEventClick} onTraceClick={(traceId) => setDrawer({ kind: "trace", traceId })} />}
            {page === "tasks" && <TaskCenter onTaskClick={(id) => setDrawer({ kind: "task", taskId: id })} onTraceClick={(traceId) => setDrawer({ kind: "trace", traceId })} />}
            {page === "develop" && <DeveloperPlatform />}
            {page === "documents" && <DocumentWorkbench />}
            {page === "environments" && <EnvironmentInspector />}
            {page === "simulations" && <SimulationWorkbench />}
            {page === "nodes" && <NodesPage onNodeClick={(id) => setDrawer({ kind: "node", nodeId: id })} />}
            {page === "models" && <ModelsPage onModelClick={(id) => setDrawer({ kind: "model-observations", modelId: id })} />}
            {page === "workspace" && <WorkspacePage />}
            {page === "settings" && <SettingsPage />}
          </div>
          <Inspector visible={inspectorOpen} onClose={() => setInspectorOpen(false)} />
        </div>
        <DetailDrawer view={drawer} onClose={() => setDrawer(null)} />
      </div>
      {page !== "chat" && <ResourceDock />}
      <CommandPalette
        commands={commands}
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSearchResult={handleSearchResult}
      />
    </>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppShell />
      </ToastProvider>
    </ThemeProvider>
  );
}
