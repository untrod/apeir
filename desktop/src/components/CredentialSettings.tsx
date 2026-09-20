import React, { useCallback, useEffect, useState } from "react";
import { colors, typo, radius, space, btnPrimary, btnSecondary } from "../design";
import { getConfig, setConfig } from "../lib/api";

export interface CredentialStatus {
  environment_name: string;
  stored: boolean;
}

export function credentialNameError(value: string): string {
  const name = value.trim();
  if (!name) return "Enter an environment variable name.";
  if (!/^[A-Z_][A-Z0-9_]{0,127}$/.test(name)) {
    return "Use uppercase letters, digits, and underscores.";
  }
  return "";
}

export function credentialSecretError(value: string): string {
  return value.trim().length >= 8 ? "" : "Enter a valid provider credential.";
}

async function invoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Credential management is available in the desktop application.");
  }
  const tauri = await import("@tauri-apps/api/core");
  return tauri.invoke<T>(command, args);
}

export function CredentialSettings() {
  const [credentials, setCredentials] = useState<CredentialStatus[]>([]);
  const [environmentName, setEnvironmentName] = useState("DEEPSEEK_API_KEY");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setCredentials(await invoke<CredentialStatus[]>("list_provider_credentials"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = async () => {
    const nameError = credentialNameError(environmentName);
    const valueError = credentialSecretError(secret);
    if (nameError || valueError) {
      setError(nameError || valueError);
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const token = await invoke<string>("store_provider_credential", {
        environmentName: environmentName.trim(),
        secret,
      });
      const config = getConfig();
      setConfig({ ...config, token });
      setSecret("");
      setMessage("Credential stored. Runtime restarted with the updated reference.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (name: string) => {
    if (removing !== name) {
      setRemoving(name);
      setMessage("Select Remove again to confirm credential revocation.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const token = await invoke<string>("remove_provider_credential", {
        environmentName: name,
      });
      const config = getConfig();
      setConfig({ ...config, token });
      setRemoving(null);
      setMessage("Credential reference revoked and Runtime restarted.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>
        Secrets are stored in Windows Credential Manager. Nous persists only the environment name.
      </div>

      {credentials.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
          {credentials.map((credential) => (
            <div
              key={credential.environment_name}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: space.md,
                border: `1px solid ${colors.borderLight}`,
                borderRadius: radius.md,
                padding: space.md,
                background: colors.bg,
              }}
            >
              <div>
                <div style={{ fontFamily: typo.mono, fontSize: typo.sm, color: colors.text }}>
                  {credential.environment_name}
                </div>
                <div style={{ fontSize: typo.xs, color: credential.stored ? colors.success : colors.warning }}>
                  {credential.stored ? "Stored" : "Reference unavailable"}
                </div>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void remove(credential.environment_name)}
                style={{ ...btnSecondary, color: colors.danger }}
              >
                {removing === credential.environment_name ? "Confirm Remove" : "Remove"}
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: typo.sm, color: colors.textSecondary }}>No managed credentials.</div>
      )}

      <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
        <span style={{ fontSize: typo.xs, color: colors.textSecondary }}>Environment name</span>
        <input
          value={environmentName}
          onChange={(event) => setEnvironmentName(event.target.value.toUpperCase())}
          autoComplete="off"
          spellCheck={false}
          style={{
            border: `1px solid ${colors.border}`,
            borderRadius: radius.md,
            padding: `${space.sm} ${space.md}`,
            background: colors.surface,
            color: colors.text,
            fontFamily: typo.mono,
          }}
        />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
        <span style={{ fontSize: typo.xs, color: colors.textSecondary }}>Provider credential</span>
        <input
          type="password"
          value={secret}
          onChange={(event) => setSecret(event.target.value)}
          autoComplete="new-password"
          style={{
            border: `1px solid ${colors.border}`,
            borderRadius: radius.md,
            padding: `${space.sm} ${space.md}`,
            background: colors.surface,
            color: colors.text,
          }}
        />
      </label>
      <div>
        <button type="button" disabled={busy} onClick={() => void save()} style={btnPrimary}>
          {busy ? "Applying..." : "Store or Rotate"}
        </button>
      </div>
      {message && <div style={{ fontSize: typo.xs, color: colors.success }}>{message}</div>}
      {error && <div role="alert" style={{ fontSize: typo.xs, color: colors.danger }}>{error}</div>}
    </div>
  );
}
