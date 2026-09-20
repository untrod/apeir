/**
 * DiagnosticPage — Displayed when errors occur, showing diagnostic information
 * and recovery options. Never renders a blank/white screen.
 */

import React, { useState, useEffect } from "react";
import { colors, typo, radius, space, card, btnPrimary, btnSecondary } from "../design";
import {
  testConnection,
  fetchStatus,
  api,
  getConfig,
  setConfig,
  type RuntimeStatus,
} from "../lib/api";

/** Lazy-load Tauri invoke — never top-level import to avoid module-load crashes. */
async function tauriInvoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Not running inside Tauri");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export interface DiagnosticState {
  errorTitle: string;
  errorSummary: string;
  errorCode: string;
  errorDetail?: string | null;
  componentStack?: string | null;
  runtimeStatus?: RuntimeStatus | null;
  recoverable: boolean;
  onRetry?: () => void;
  onRestartRuntime?: () => void;
  onResetSession?: () => void;
  onOpenLogs?: () => void;
  onResetUI?: () => void;
  onReturnToSetup?: () => void;
}

interface RuntimeDiag {
  running: boolean;
  reachable: boolean;
  version: string;
  providers: number;
}

interface WorkspaceDiag {
  exists: boolean;
  path: string;
}

interface ProviderDiag {
  configured: boolean;
  count: number;
}

export function DiagnosticPage(props: DiagnosticState) {
  const [showDetail, setShowDetail] = useState(false);
  const [runtimeDiag, setRuntimeDiag] = useState<RuntimeDiag>({
    running: false,
    reachable: false,
    version: "—",
    providers: 0,
  });
  const [workspaceDiag, setWorkspaceDiag] = useState<WorkspaceDiag>({
    exists: false,
    path: "—",
  });
  const [providerDiag, setProviderDiag] = useState<ProviderDiag>({
    configured: false,
    count: 0,
  });
  const [checking, setChecking] = useState(true);
  const [actionError, setActionError] = useState("");

  const returnToApplication = () => {
    if (props.onRetry) props.onRetry();
    else window.location.reload();
  };

  useEffect(() => {
    let cancelled = false;
    async function check() {
      // Check runtime connectivity
      try {
        const connected = await testConnection();
        if (!cancelled) {
          setRuntimeDiag((prev) => ({ ...prev, reachable: connected }));
          if (connected) {
            try {
              const status = await fetchStatus();
              if (!cancelled) {
                setRuntimeDiag({
                  running: status.running,
                  reachable: true,
                  version: status.version,
                  providers: status.providers,
                });
              }
            } catch {
              // Status fetch failed
            }
          }
        }
      } catch {
        // Test connection failed
      }

      try {
        const workspace = await api<{ exists: boolean; path: string }>("/api/v1/workspace/status");
        if (!cancelled) setWorkspaceDiag({ exists: !!workspace.exists, path: workspace.path || "—" });
      } catch {
        // Workspace diagnostics remain unavailable.
      }

      try {
        const provider = await api<{ configured: boolean; count: number }>("/api/v1/provider/status");
        if (!cancelled) setProviderDiag({ configured: !!provider.configured, count: provider.count || 0 });
      } catch {
        // Provider diagnostics remain unavailable.
      }
      if (!cancelled) setChecking(false);
    }
    check();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRestartRuntime = async () => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    try {
      setChecking(true);
      setActionError("");
      const token = await tauriInvoke<string>("restart_runtime_api");
      // Store the token so subsequent requests use it
      const cfg = getConfig();
      setConfig({ url: cfg.url, token });
      // Wait for runtime
      for (let i = 0; i < 30; i++) {
        if (await testConnection()) break;
        await new Promise((r) => setTimeout(r, 200));
      }
      const connected = await testConnection();
      setRuntimeDiag((prev) => ({ ...prev, reachable: connected, running: connected }));
      if (connected) returnToApplication();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Runtime restart failed.");
    } finally {
      setChecking(false);
    }
  };

  const handleResetSession = async () => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    try {
      const token = await tauriInvoke<string>("load_runtime_session_token");
      const cfg = getConfig();
      setConfig({ url: cfg.url, token });
      const connected = await testConnection();
      setRuntimeDiag((prev) => ({ ...prev, reachable: connected }));
      if (connected) returnToApplication();
    } catch {
      // Token load failed, try full restart
      await handleRestartRuntime();
    }
  };

  const handleOpenLogs = async () => {
    if ("__TAURI_INTERNALS__" in window) {
      try {
        await tauriInvoke("open_logs_directory").catch(() => {
          // Fallback: logs directory may not be available
        });
      } catch {
        // Best effort
      }
    }
  };

  const statusDot = (ok: boolean) => (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        marginRight: 6,
        background: ok ? colors.success : colors.danger,
      }}
    />
  );

  return (
    <div
      style={{
        minHeight: "100vh",
        background: colors.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: space.xl,
      }}
    >
      <div
        style={{
          ...card,
          maxWidth: 560,
          width: "100%",
        }}
      >
        {/* Error header */}
        <div style={{ textAlign: "center", marginBottom: space.xl }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: "50%",
              background: props.recoverable ? colors.warningSoft : colors.dangerSoft,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto",
              marginBottom: space.md,
              fontSize: 20,
            }}
          >
            {props.recoverable ? "!" : "X"}
          </div>
          <h2
            style={{
              fontSize: typo.xl,
              fontWeight: typo.bold,
              color: colors.text,
              margin: 0,
            }}
          >
            {props.errorTitle}
          </h2>
          <p
            style={{
              fontSize: typo.base,
              color: colors.textSecondary,
              margin: `${space.sm} 0 0 0`,
              lineHeight: typo.body,
            }}
          >
            {props.errorSummary}
          </p>
          <code
            style={{
              display: "inline-block",
              marginTop: space.sm,
              fontSize: typo.xs,
              fontFamily: typo.mono,
              color: colors.textTertiary,
              background: colors.inlineCodeBg,
              padding: "2px 8px",
              borderRadius: radius.sm,
            }}
          >
            {props.errorCode}
          </code>
        </div>

        {/* Diagnostics */}
        <div
          style={{
            background: colors.bg,
            borderRadius: radius.md,
            padding: space.lg,
            marginBottom: space.lg,
          }}
        >
          <h3
            style={{
              fontSize: typo.sm,
              fontWeight: typo.semibold,
              color: colors.textSecondary,
              margin: `0 0 ${space.md} 0`,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
            }}
          >
            System Diagnostics
          </h3>

          <table style={{ width: "100%", fontSize: typo.sm, borderCollapse: "collapse" }}>
            <tbody>
              <tr>
                <td
                  style={{
                    padding: "6px 0",
                    color: colors.textTertiary,
                    width: 140,
                  }}
                >
                  {statusDot(runtimeDiag.reachable)}
                  Runtime Status
                </td>
                <td style={{ color: colors.text }}>
                  {checking
                    ? "Checking..."
                    : runtimeDiag.reachable
                      ? `Connected (v${runtimeDiag.version})`
                      : "Not reachable"}
                </td>
              </tr>
              <tr>
                <td
                  style={{
                    padding: "6px 0",
                    color: colors.textTertiary,
                  }}
                >
                  {statusDot(runtimeDiag.running)}
                  Runtime Running
                </td>
                <td style={{ color: runtimeDiag.running ? colors.success : colors.danger }}>
                  {checking ? "Checking..." : runtimeDiag.running ? "Yes" : "No"}
                </td>
              </tr>
              <tr>
                <td
                  style={{
                    padding: "6px 0",
                    color: colors.textTertiary,
                  }}
                >
                  <span style={{ marginRight: 6 }}>P</span>
                  Providers
                </td>
                <td style={{ color: colors.text }}>
                  {runtimeDiag.providers > 0
                    ? `${runtimeDiag.providers} configured`
                    : "None configured"}
                </td>
              </tr>
              <tr>
                <td style={{ padding: "6px 0", color: colors.textTertiary }}>
                  {statusDot(workspaceDiag.exists)}
                  Workspace
                </td>
                <td style={{ color: colors.text, wordBreak: "break-all" }}>
                  {workspaceDiag.exists ? workspaceDiag.path : "Not configured"}
                </td>
              </tr>
              <tr>
                <td
                  style={{
                    padding: "6px 0",
                    color: colors.textTertiary,
                  }}
                >
                  <span style={{ marginRight: 6 }}>OS</span>
                  Platform
                </td>
                <td style={{ color: colors.text }}>
                  {navigator.platform || "Unknown"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Action buttons */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: space.sm,
          }}
        >
          {runtimeDiag.reachable && (
            <button onClick={returnToApplication} style={btnPrimary}>
              Return to Application
            </button>
          )}
          {props.recoverable && props.onRetry && (
            <button onClick={props.onRetry} style={runtimeDiag.reachable ? btnSecondary : btnPrimary}>
              Retry
            </button>
          )}

          {!("__TAURI_INTERNALS__" in window) ? null : (
            <>
              <button
                onClick={handleRestartRuntime}
                disabled={checking}
                style={{
                  ...btnSecondary,
                  justifyContent: "center",
                  opacity: checking ? 0.6 : 1,
                }}
              >
                {checking ? "Starting..." : "Restart Runtime"}
              </button>

              <button
                onClick={handleResetSession}
                disabled={checking}
                style={{
                  ...btnSecondary,
                  justifyContent: "center",
                  opacity: checking ? 0.6 : 1,
                }}
              >
                Re-establish Session
              </button>
            </>
          )}

          {props.onResetUI && (
            <button
              onClick={props.onResetUI}
              style={{
                ...btnSecondary,
                justifyContent: "center",
              }}
            >
              Reset Desktop UI State
            </button>
          )}

          {props.onReturnToSetup && (
            <button
              onClick={props.onReturnToSetup}
              style={{
                ...btnSecondary,
                justifyContent: "center",
              }}
            >
              Return to Setup
            </button>
          )}

          <button
            onClick={handleOpenLogs}
            style={{
              ...btnSecondary,
              justifyContent: "center",
            }}
          >
            Open Logs Directory
          </button>
          {actionError && (
            <div role="alert" style={{ color: colors.danger, fontSize: typo.sm }}>
              {actionError}
            </div>
          )}
        </div>

        {/* Technical details (collapsible) */}
        {(props.errorDetail || props.componentStack) && (
          <div style={{ marginTop: space.lg }}>
            <button
              onClick={() => setShowDetail(!showDetail)}
              style={{
                background: "none",
                border: "none",
                color: colors.accent,
                cursor: "pointer",
                fontSize: typo.sm,
                fontFamily: typo.font,
                padding: 0,
                textDecoration: "underline",
              }}
            >
              {showDetail ? "Hide" : "Show"} Technical Details
            </button>
            {showDetail && (
              <pre
                style={{
                  marginTop: space.sm,
                  padding: space.md,
                  background: colors.codeBg,
                  color: colors.codeText,
                  borderRadius: radius.md,
                  fontSize: typo.xs,
                  fontFamily: typo.mono,
                  overflowX: "auto",
                  maxHeight: 200,
                  overflowY: "auto",
                  lineHeight: typo.body,
                }}
              >
                {props.errorDetail}
                {props.componentStack &&
                  `\n\nComponent Stack:\n${props.componentStack}`}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
