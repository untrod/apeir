import React, { useCallback, useEffect, useRef, useState } from "react";
import { colors, typo, radius, space, btnPrimary, btnSecondary } from "../design";
import { bindNativeRuntimeSession, isLocalRuntimeSelected, nativeRuntimeStatus } from "../lib/nativeRuntime";
import { captureRuntimeConnection, getRuntimeConfigVersion } from "../lib/api";
import { useRuntimeConfigVersion } from "../store";

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

export function CredentialSettings({ locale = "en", onDraftChange, hasOtherDrafts }: { locale?: "en" | "zh"; onDraftChange?: (dirty: boolean) => void; hasOtherDrafts?: () => boolean } = {}) {
  const version = useRuntimeConfigVersion();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const [credentials, setCredentials] = useState<CredentialStatus[]>([]);
  const [environmentName, setEnvironmentName] = useState("DEEPSEEK_API_KEY");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const active = useRef(false);
  useEffect(() => { onDraftChange?.(!!secret || busy); }, [secret, busy, onDraftChange]);
  useEffect(() => () => onDraftChange?.(false), [onDraftChange]);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  const refresh = useCallback(async () => {
    const check = captureRuntimeConnection();
    try {
      const status = await nativeRuntimeStatus();
      check();
      if (!isLocalRuntimeSelected(status.endpoint)) throw new Error("Select the local Runtime before managing its credentials.");
      const rows = await invoke<CredentialStatus[]>("list_provider_credentials");
      check();
      if (active.current && isLocalRuntimeSelected(status.endpoint)) { setCredentials(rows); setReady(true); }
    } catch (reason) {
      if (active.current && getRuntimeConfigVersion() === version) { setReady(false); setError(reason instanceof Error ? reason.message : String(reason)); }
    }
  }, [version]);

  useEffect(() => {
    setReady(false); setCredentials([]); setSecret(""); setError(""); setMessage(""); setRemoving(null);
    void refresh();
  }, [refresh]);

  const save = async () => {
    if (hasOtherDrafts?.()) { setError(t("Save or cancel drafts in other panels before restarting the local Runtime.", "请先保存或取消其他面板中的草稿，再重启本地运行时。")); return; }
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
      const pending = bindNativeRuntimeSession("store_provider_credential", {
        environmentName: environmentName.trim(),
        secret,
      }, { isActive: () => active.current });
      setSecret("");
      await pending;
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
    if (hasOtherDrafts?.()) { setError(t("Save or cancel drafts in other panels before restarting the local Runtime.", "请先保存或取消其他面板中的草稿，再重启本地运行时。")); return; }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await bindNativeRuntimeSession("remove_provider_credential", {
        environmentName: name,
      }, { isActive: () => active.current });
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
    <fieldset disabled={!ready || busy} style={{ display: "flex", flexDirection: "column", gap: space.md, border: 0, padding: 0, minWidth: 0 }}>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>
        {t("Keys stay in Windows Credential Manager; configuration stores references only.", "密钥保存在 Windows 凭据管理器中；配置仅保存引用。")}
        <p>{t("Saving or removing a credential restarts the local Runtime. Save other drafts first.", "保存或移除凭据会重启本地运行时；请先保存其他草稿。")}</p>
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
                  {credential.stored ? t("Stored", "已保存") : t("Reference unavailable", "引用不可用")}
                </div>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void remove(credential.environment_name)}
                style={{ ...btnSecondary, color: colors.danger }}
              >
                {removing === credential.environment_name ? t("Confirm Remove", "确认移除") : t("Remove", "移除")}
              </button>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ fontSize: typo.sm, color: colors.textSecondary }}>{t("No managed credentials.", "尚无托管凭据。")}</div>
      )}

      <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
        <span style={{ fontSize: typo.xs, color: colors.textSecondary }}>{t("Environment name", "环境变量名称")}</span>
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
        <span style={{ fontSize: typo.xs, color: colors.textSecondary }}>{t("Provider credential", "服务商密钥")}</span>
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
          {busy ? t("Applying...", "正在保存…") : t("Store or Rotate", "保存或更新")}
        </button>
      </div>
      {message && <div style={{ fontSize: typo.xs, color: colors.success }}>{message}</div>}
      {error && <div role="alert" style={{ fontSize: typo.xs, color: colors.danger }}>{error === "Local Runtime management requires the desktop application." ? t(error, "请在桌面应用中管理本地凭据；远程服务请使用该主机的安全后端。") : error === "Select the local Runtime before managing its credentials." ? t(error, "请先连接本地运行时，再管理其凭据。") : error}</div>}
    </fieldset>
  );
}
