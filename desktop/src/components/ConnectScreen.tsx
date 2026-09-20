/**
 * ConnectScreen — Connection setup when APEIR Runtime is not reachable.
 */

import React, { useEffect, useState } from "react";
import { colors, typo, radius, shadow, space, card, input, btnPrimary } from "../design";
import { setConfig, testConnection } from "../lib/api";
import { SetupWizard } from "./SetupWizard";

/** Lazy-load Tauri invoke — never top-level import to avoid module-load crashes. */
async function tauriInvoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Not running inside Tauri");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

interface ConnectScreenProps {
  onConnected: () => void;
}

export function ConnectScreen({ onConnected }: ConnectScreenProps) {
  const [url, setUrl] = useState("http://localhost:8770");
  const [token, setToken] = useState("");
  const [checking, setChecking] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [showWizard, setShowWizard] = useState(false);

  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    tauriInvoke<string>("load_runtime_session_token")
      .then(async (sessionToken) => {
        setToken(sessionToken);
        setConfig({ url: "http://localhost:8770", token: sessionToken });
        if (await testConnection()) onConnected();
      })
      .catch(() => undefined);
  }, [onConnected]);

  const handleConnect = async () => {
    setChecking(true);
    setError("");
    setConfig({ url: url.replace(/\/$/, ""), token });
    const ok = await testConnection();
    if (ok) {
      localStorage.setItem("nous_setup_complete", "1");
      onConnected();
    } else {
      setError("Cannot authenticate with APEIR Runtime. Check the URL and local session token.");
    }
    setChecking(false);
  };

  const handleStartLocal = async () => {
    setStarting(true);
    setError("");
    try {
      const sessionToken = await tauriInvoke<string>("start_runtime_api");
      setToken(sessionToken);
      const normalizedUrl = url.replace(/\/$/, "");
      setConfig({ url: normalizedUrl, token: sessionToken });
      for (let attempt = 0; attempt < 12; attempt += 1) {
        if (await testConnection()) {
          localStorage.setItem("nous_setup_complete", "1");
          onConnected();
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      setError("APEIR Runtime started, but the authenticated API is not ready.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setStarting(false);
    }
  };

  if (showWizard) {
    return <SetupWizard onComplete={() => { localStorage.setItem("nous_setup_complete", "1"); setShowWizard(false); onConnected(); }} />;
  }

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: "100vh", background: colors.bg,
    }}>
      <div style={{
        ...card,
        width: 400, maxWidth: "90vw",
        textAlign: "center",
      }}>
        {/* Logo */}
        <div style={{
          fontSize: "32px", marginBottom: space.md,
        }}>
          ●
        </div>
        <h1 style={{
          fontSize: typo.xl, fontWeight: typo.bold, color: colors.text,
          margin: `0 0 ${space.xs} 0`,
        }}>
          APEIR Runtime
        </h1>
        <p style={{
          fontSize: typo.sm, color: colors.textSecondary,
          margin: `0 0 ${space.xl} 0`, lineHeight: typo.relaxed,
        }}>
          Connect to your APEIR Runtime server to begin.
        </p>

        {/* Form */}
        <div style={{ textAlign: "left", marginBottom: space.lg }}>
          <label style={{
            display: "block",
            fontSize: typo.xs, fontWeight: typo.semibold,
            color: colors.textSecondary, marginBottom: 4,
          }}>
            Server URL
          </label>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="http://localhost:8770"
            style={{ ...input, marginBottom: space.md }}
          />

          <label style={{
            display: "block",
            fontSize: typo.xs, fontWeight: typo.semibold,
            color: colors.textSecondary, marginBottom: 4,
          }}>
            Auth Token
          </label>
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Bearer token..."
            style={input}
          />
        </div>

        {error && (
          <div style={{
            padding: space.sm,
            marginBottom: space.md,
            background: colors.dangerSoft,
            color: colors.danger,
            borderRadius: radius.md,
            fontSize: typo.sm,
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleConnect}
          disabled={checking || !url}
          style={{
            ...btnPrimary,
            width: "100%",
            justifyContent: "center",
            padding: `${space.md} ${space.lg}`,
            fontSize: typo.md,
            opacity: checking || !url ? 0.6 : 1,
          }}
        >
          {checking ? "Connecting..." : "Connect"}
        </button>

        {"__TAURI_INTERNALS__" in window && (
          <button
            onClick={handleStartLocal}
            disabled={starting}
            style={{
              ...btnPrimary,
              width: "100%",
              justifyContent: "center",
              marginTop: space.sm,
              background: colors.text,
              opacity: starting ? 0.6 : 1,
            }}
          >
            {starting ? "Starting local Runtime..." : "Start Local Runtime"}
          </button>
        )}

        <div style={{ textAlign: "center", marginTop: space.lg }}>
          <button onClick={() => setShowWizard(true)} style={{
            background: "none", border: "none", color: colors.accent, cursor: "pointer",
            fontSize: typo.sm, fontFamily: typo.font, textDecoration: "underline",
          }}>
            First time? Run setup wizard →
          </button>
        </div>
      </div>
    </div>
  );
}
