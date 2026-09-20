/**
 * OnboardingWizard — First-use setup wizard for Nous Desktop.
 *
 * Steps:
 *   1. Welcome — product intro, language selection
 *   2. Environment Check — OS, arch, runtime, WebView2, permissions
 *   3. Workspace — default, select existing, or create new
 *   4. Provider — select from templates (no API key yet)
 *   5. Credential — Windows Credential Manager or environment reference
 *   6. Model Selection — choose models per capability
 *   7. Connection Test — verify provider connectivity
 *   8. Summary — review configuration
 *   9. Complete — save and enter dashboard
 */

import React, { useCallback, useEffect, useState } from "react";
import { colors, typo, radius, space, card, input, btnPrimary, btnSecondary } from "../design";
import { testConnection, api, getConfig, setConfig } from "../lib/api";

/** Lazy-load Tauri invoke — never top-level import to avoid module-load crashes. */
async function tauriInvoke<T = unknown>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (!("__TAURI_INTERNALS__" in window)) {
    throw new Error("Not running inside Tauri");
  }
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

// Provider Templates
interface ProviderTemplate {
  providerId: string;
  displayName: string;
  serviceType: string;
  defaultBaseUrl: string;
  credentialType: "api_key" | "oauth" | "none";
  modelCatalogEndpoint: string;
  supportedCapabilities: string[];
  timeout: number;
  retryPolicy: { maxRetries: number; backoffMs: number };
  documentationLabel: string;
}

const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  {
    providerId: "openai",
    displayName: "OpenAI",
    serviceType: "cloud",
    defaultBaseUrl: "https://api.openai.com/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "embedding", "vision", "tool_calling", "structured_output"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "platform.openai.com",
  },
  {
    providerId: "anthropic",
    displayName: "Anthropic",
    serviceType: "cloud",
    defaultBaseUrl: "https://api.anthropic.com/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "vision", "tool_calling", "reviewer", "planner"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "console.anthropic.com",
  },
  {
    providerId: "deepseek",
    displayName: "DeepSeek",
    serviceType: "cloud",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "tool_calling"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "platform.deepseek.com",
  },
  {
    providerId: "moonshot",
    displayName: "Moonshot / Kimi",
    serviceType: "cloud",
    defaultBaseUrl: "https://api.moonshot.cn/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "tool_calling"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "platform.moonshot.cn",
  },
  {
    providerId: "dashscope",
    displayName: "Alibaba Qwen / DashScope",
    serviceType: "cloud",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "embedding", "vision", "tool_calling"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "dashscope.console.aliyun.com",
  },
  {
    providerId: "zhipu",
    displayName: "Zhipu GLM",
    serviceType: "cloud",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "vision", "tool_calling", "embedding"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "open.bigmodel.cn",
  },
  {
    providerId: "gemini",
    displayName: "Google Gemini",
    serviceType: "cloud",
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "vision", "embedding", "tool_calling"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "aistudio.google.com",
  },
  {
    providerId: "openrouter",
    displayName: "OpenRouter",
    serviceType: "cloud",
    defaultBaseUrl: "https://openrouter.ai/api/v1",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "reasoning", "vision", "tool_calling"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "openrouter.ai",
  },
  {
    providerId: "ollama",
    displayName: "Ollama (Local)",
    serviceType: "local",
    defaultBaseUrl: "http://localhost:11434/v1",
    credentialType: "none",
    modelCatalogEndpoint: "/api/tags",
    supportedCapabilities: ["chat", "completion", "embedding"],
    timeout: 300,
    retryPolicy: { maxRetries: 1, backoffMs: 2000 },
    documentationLabel: "ollama.com",
  },
  {
    providerId: "openai_compatible",
    displayName: "OpenAI Compatible",
    serviceType: "custom",
    defaultBaseUrl: "",
    credentialType: "api_key",
    modelCatalogEndpoint: "/models",
    supportedCapabilities: ["chat", "completion", "embedding"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "",
  },
  {
    providerId: "custom",
    displayName: "Custom Provider",
    serviceType: "custom",
    defaultBaseUrl: "",
    credentialType: "api_key",
    modelCatalogEndpoint: "",
    supportedCapabilities: ["chat"],
    timeout: 120,
    retryPolicy: { maxRetries: 3, backoffMs: 1000 },
    documentationLabel: "",
  },
];

const PROVIDER_CREDENTIAL_ENVIRONMENTS: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  deepseek: "DEEPSEEK_API_KEY",
  moonshot: "MOONSHOT_API_KEY",
  dashscope: "DASHSCOPE_API_KEY",
  zhipu: "ZHIPU_API_KEY",
  gemini: "GEMINI_API_KEY",
  openrouter: "OPENROUTER_API_KEY",
};

function defaultCredentialEnvironment(providerId: string): string {
  return (
    PROVIDER_CREDENTIAL_ENVIRONMENTS[providerId] ||
    `${providerId.replace(/[^a-zA-Z0-9]+/g, "_").toUpperCase()}_API_KEY`
  );
}

const ENVIRONMENT_NAME_PATTERN = /^[A-Z_][A-Z0-9_]{0,127}$/;

export function credentialEnvironmentError(name: string): string {
  if (!name) return "required";
  if (!ENVIRONMENT_NAME_PATTERN.test(name)) return "invalid";
  // A long opaque value without separators is almost always a pasted secret,
  // not a human-readable environment-variable name.
  if (name.length >= 24 && !name.includes("_")) return "secret";
  return "";
}

export function credentialValueError(value: string): string {
  return value.trim().length >= 8 ? "" : "required";
}
const CAPABILITY_LABELS: Record<string, string> = {
  chat: "Default Chat",
  reasoning: "Reasoning",
  planner: "Planning",
  reviewer: "Review",
  embedding: "Embedding",
  vision: "Vision",
  tool_calling: "Tool Calling",
  structured_output: "Structured Output",
  completion: "Completion",
};

const PROVIDER_DEFAULT_MODELS: Record<string, Record<string, string>> = {
  openai: { default: "gpt-4o-mini" },
  anthropic: { default: "claude-sonnet-4-5" },
  deepseek: { default: "deepseek-chat", reasoning: "deepseek-reasoner" },
  moonshot: { default: "moonshot-v1-auto" },
  dashscope: { default: "qwen-plus" },
  zhipu: { default: "glm-4-flash" },
  gemini: { default: "gemini-2.0-flash" },
  openrouter: { default: "openai/gpt-4o-mini" },
  ollama: { default: "llama3.2" },
};

function defaultModelAssignments(providerId: string, capabilities: string[]): Record<string, string> {
  const defaults = PROVIDER_DEFAULT_MODELS[providerId] || {};
  return Object.fromEntries(
    capabilities.map((capability) => [capability, defaults[capability] || defaults.default || ""]),
  );
}

interface EnvCheckItem {
  label: string;
  status: "ok" | "warning" | "error" | "checking";
  detail: string;
  fixable: boolean;
}

interface OnboardingWizardProps {
  onComplete: () => void;
  onSkip: () => void;
}

type WizardStep = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

export function OnboardingWizard({ onComplete, onSkip }: OnboardingWizardProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [language, setLanguage] = useState<"zh-CN" | "en">("zh-CN");

  // Step 1: Welcome
  // Step 2: Environment checks
  const [envChecks, setEnvChecks] = useState<EnvCheckItem[]>([]);

  // Step 3: Workspace
  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaceAction, setWorkspaceAction] = useState<"default" | "existing" | "new">("default");

  // Step 4: Provider
  const [selectedProviderId, setSelectedProviderId] = useState("");

  // Step 5: Credential
  const [credentialMode, setCredentialMode] = useState<"system" | "environment">("system");
  const [credentialSecret, setCredentialSecret] = useState("");
  const [credentialStored, setCredentialStored] = useState(false);
  const [credentialSaving, setCredentialSaving] = useState(false);
  const [credentialEnvName, setCredentialEnvName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");

  // Step 6: Model selection
  const [selectedModels, setSelectedModels] = useState<Record<string, string>>({});
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [modelFetchError, setModelFetchError] = useState("");

  // Step 7: Connection test
  const [testResults, setTestResults] = useState<{ name: string; ok: boolean; detail: string }[]>([]);
  const [testing, setTesting] = useState(false);
  const [setupError, setSetupError] = useState("");

  // Step 8: Summary — auto-generated
  // Step 9: Complete

  const t = useCallback((en: string, zh: string) => (language === "zh-CN" ? zh : en), [language]);

  // Run environment checks
  useEffect(() => {
    if (step !== 2) return;
    const checks: EnvCheckItem[] = [];

    // OS check
    const platform = navigator.platform || "";
    checks.push({
      label: t("Operating System", "操作系统"),
      status: platform.includes("Win") ? "ok" : "warning",
      detail: platform || "Unknown",
      fixable: false,
    });

    // Architecture
    checks.push({
      label: t("Architecture", "架构"),
      status: "ok",
      detail: navigator.userAgent.includes("ARM") || navigator.userAgent.includes("arm") ? "ARM64" : "x64",
      fixable: false,
    });

    // WebView2
    checks.push({
      label: "WebView2",
      status: "ok",
      detail: t("Available", "可用"),
      fixable: false,
    });

    // Runtime check (async)
    checks.push({
      label: t("APEIR Runtime", "APEIR Runtime"),
      status: "checking",
      detail: t("Checking...", "检查中..."),
      fixable: true,
    });

    setEnvChecks(checks);

    // Async check runtime
    testConnection().then((ok) => {
      setEnvChecks((prev) =>
        prev.map((c) =>
          c.label === "APEIR Runtime" || c.label === "APEIR Runtime"
            ? {
                ...c,
                status: ok ? "ok" : "warning",
                detail: ok ? t("Running", "运行中") : t("Not running", "未运行"),
              }
            : c,
        ),
      );
    });

    // Default workspace path — resolve from Tauri if available
    if ("__TAURI_INTERNALS__" in window) {
      tauriInvoke<string>("get_default_workspace_path")
        .then((p) => setWorkspacePath(p))
        .catch(() => setWorkspacePath("%USERPROFILE%\\NousWorkspace"));
    } else {
      setWorkspacePath("%USERPROFILE%\\NousWorkspace");
    }
  }, [step, t]);

  // Fetch models when provider selected
  const fetchModelsForProvider = useCallback(async (providerId: string) => {
    setModelFetchError("");
    setAvailableModels([]);
    const template = PROVIDER_TEMPLATES.find((p) => p.providerId === providerId);
    if (!template) return;
    try {
      const result = await api<{ models?: { id?: string; model_id?: string; display_name?: string }[] }>(
        "/api/v1/models",
      );
      if (result?.models) {
        setAvailableModels(
          result.models.map((m) => m.id || m.model_id || m.display_name || "").filter(Boolean),
        );
      }
    } catch {
      setModelFetchError(
        t(
          "Could not fetch model list. You can enter model IDs manually.",
          "无法获取模型列表。您可以手动输入模型 ID。",
        ),
      );
    }
  }, [t]);

  useEffect(() => {
    if (step === 6 && selectedProviderId) {
      fetchModelsForProvider(selectedProviderId);
    }
  }, [step, selectedProviderId, fetchModelsForProvider]);

  // Connection test
  const runConnectionTest = useCallback(async () => {
    setTesting(true);
    setTestResults([]);
    const template = PROVIDER_TEMPLATES.find((p) => p.providerId === selectedProviderId);
    const credentialRequired = template?.credentialType !== "none";
    const environmentError = credentialRequired && credentialMode === "environment"
      ? credentialEnvironmentError(credentialEnvName)
      : "";
    const systemCredentialReady = credentialMode === "system" && credentialStored;
    const configurationOk = Boolean(
      template &&
      baseUrl &&
      (
        !credentialRequired ||
        (credentialMode === "system" ? systemCredentialReady : !environmentError)
      ),
    );
    const primaryModel = selectedModels.chat || selectedModels.reasoning || Object.values(selectedModels).find(Boolean) || "";
    const results: { name: string; ok: boolean; detail: string }[] = [
      {
        name: t("Configuration", "配置检查"),
        ok: configurationOk,
        detail: configurationOk
          ? t("Configuration is valid", "配置格式有效")
          : t("Complete the Provider and credential fields", "请补全服务商与凭据字段"),
      },
    ];

    if (!configurationOk || !template) {
      setTestResults(results);
      setTesting(false);
      return;
    }

    try {
      const result = await api<{
        ok?: boolean;
        status?: string;
        latency_ms?: number;
      }>("/api/v1/providers/validate", {
        method: "POST",
        body: JSON.stringify({
          provider_id: template.providerId,
          name: template.displayName,
          api_base_url: baseUrl || template.defaultBaseUrl,
          credential_ref: credentialEnvName ? `env:${credentialEnvName}` : "",
          capabilities: template.supportedCapabilities,
          model: primaryModel,
          capability_models: selectedModels,
        }),
      });
      const ok = Boolean(result.ok);
      results.push({
        name: t("Provider connection", "服务商连接"),
        ok,
        detail: result.status || (ok ? t("Connected", "连接成功") : t("Connection failed", "连接失败")),
      });
      results.push({
        name: t("Latency", "延迟"),
        ok: ok && Number(result.latency_ms || 0) < 10000,
        detail: result.latency_ms ? `${Math.round(result.latency_ms)} ms` : t("Not measured", "未测量"),
      });
    } catch (error) {
      results.push({
        name: t("Provider connection", "服务商连接"),
        ok: false,
        detail: error instanceof Error ? error.message : t("Connection failed", "连接失败"),
      });
    } finally {
      setTestResults(results);
      setTesting(false);
    }
  }, [baseUrl, credentialEnvName, credentialMode, credentialStored, selectedModels, selectedProviderId, t]);

  useEffect(() => {
    if (step === 7) {
      runConnectionTest();
    }
  }, [step, runConnectionTest]);

  // Save configuration
  const saveConfiguration = async (): Promise<boolean> => {
    const template = PROVIDER_TEMPLATES.find((provider) => provider.providerId === selectedProviderId);
    setSetupError("");

    if (template) {
      try {
        const primaryModel = selectedModels.chat || selectedModels.reasoning || Object.values(selectedModels).find(Boolean) || "";
        await api("/api/v1/providers", {
          method: "POST",
          body: JSON.stringify({
            provider_id: template.providerId,
            name: template.displayName,
            api_base_url: baseUrl || template.defaultBaseUrl,
            credential_ref: credentialEnvName ? `env:${credentialEnvName}` : "",
            capabilities: template.supportedCapabilities,
            model: primaryModel,
            capability_models: selectedModels,
          }),
        });
      } catch (error) {
        setSetupError(
          error instanceof Error
            ? error.message
            : t("Provider configuration could not be saved.", "无法保存服务商配置。"),
        );
        return false;
      }
    }

    try {
      localStorage.setItem("nous_onboarding_completed", "1");
      localStorage.setItem("nous_setup_complete", "1");
      localStorage.setItem("nous_provider_id", selectedProviderId);
      localStorage.setItem("nous_workspace_path", workspacePath);
      localStorage.setItem("nous_language", language);
    } catch {
      // Runtime-owned configuration is already saved; UI markers are optional.
    }
    return true;
  };

  const handleComplete = async () => {
    if (await saveConfiguration()) {
      onComplete();
    } else {
      setStep(8);
    }
  };
  // Render
  const stepIndicator = (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        gap: 6,
        marginBottom: space.xl,
      }}
    >
      {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((s) => (
        <div
          key={s}
          style={{
            width: s === step ? 24 : 8,
            height: 8,
            borderRadius: 4,
            background: s === step ? colors.accent : s < step ? colors.accentMuted : colors.borderLight,
            transition: "all 0.3s ease",
          }}
        />
      ))}
    </div>
  );

  const stepHeader = (title: string, subtitle: string) => (
    <div style={{ textAlign: "center", marginBottom: space.xl }}>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: 0 }}>
        {title}
      </h2>
      <p style={{ fontSize: typo.sm, color: colors.textSecondary, margin: `${space.xs} 0 0 0` }}>
        {subtitle}
      </p>
    </div>
  );

  const selectedTemplate = PROVIDER_TEMPLATES.find((provider) => provider.providerId === selectedProviderId);
  const credentialRequired = selectedTemplate?.credentialType !== "none";
  const credentialError = credentialRequired && credentialMode === "environment"
    ? credentialEnvironmentError(credentialEnvName)
    : "";
  const credentialSecretError = credentialRequired && credentialMode === "system"
    ? credentialValueError(credentialSecret)
    : "";
  const canContinue =
    (step !== 3 || Boolean(workspacePath.trim())) &&
    (step !== 4 || Boolean(selectedProviderId && baseUrl.trim())) &&
    (step !== 5 || (!credentialError && !credentialSecretError)) &&
    (step !== 7 || (!testing && testResults.some((result) => result.name === t("Provider connection", "服务商连接") && result.ok)));

  const advanceStep = async () => {
    if (step === 5 && credentialRequired && credentialMode === "system") {
      setCredentialSaving(true);
      setSetupError("");
      try {
        const token = await tauriInvoke<string>("store_provider_credential", {
          environmentName: credentialEnvName,
          secret: credentialSecret,
        });
        setConfig({ ...getConfig(), token });
        setCredentialSecret("");
        setCredentialStored(true);
      } catch (error) {
        setSetupError(
          error instanceof Error
            ? error.message
            : t("Credential could not be stored.", "无法保存凭据。"),
        );
        setCredentialSaving(false);
        return;
      }
      setCredentialSaving(false);
    }
    setStep((current) => (current + 1) as WizardStep);
  };

  const navButtons = (
    <div style={{ display: "flex", gap: space.sm, justifyContent: "center", marginTop: space.xl }}>
      {step > 1 && (
        <button onClick={() => setStep((s) => (s - 1) as WizardStep)} style={btnSecondary}>
          ← {t("Back", "上一步")}
        </button>
      )}
      {step < 9 && (
        <button
          onClick={advanceStep}
          style={{ ...btnPrimary, opacity: canContinue ? 1 : 0.55 }}
          disabled={!canContinue || credentialSaving}
        >
          {credentialSaving ? t("Saving...", "保存中...") : t("Next", "下一步")} →
        </button>
      )}
    </div>
  );

  const container: React.CSSProperties = {
    minHeight: "100vh",
    background: colors.bg,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: space.xl,
  };

  const contentBox: React.CSSProperties = {
    ...card,
    maxWidth: 540,
    width: "100%",
    maxHeight: "85vh",
    overflowY: "auto",
  };

  // Step 1: Welcome
  if (step === 1) {
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 48, marginBottom: space.lg }}>●</div>
            <h1 style={{ fontSize: typo.xxl, fontWeight: typo.bold, color: colors.text, margin: 0 }}>
              {t("Welcome to Nous", "欢迎使用 Nous")}
            </h1>
            <p
              style={{
                fontSize: typo.md,
                color: colors.textSecondary,
                margin: `${space.md} 0`,
                lineHeight: typo.relaxed,
              }}
            >
              {t(
                "Local-first, secure, auditable AI runtime. Your data stays on your device.",
                "本地优先、安全、可审计的 AI 运行时。您的数据保留在您的设备上。",
              )}
            </p>

            <div
              style={{
                display: "flex",
                gap: space.sm,
                justifyContent: "center",
                marginBottom: space.xl,
              }}
            >
              <button
                onClick={() => setLanguage("zh-CN")}
                style={{
                  ...btnSecondary,
                  background: language === "zh-CN" ? colors.accentSoft : undefined,
                  border: `1px solid ${language === "zh-CN" ? colors.accent : colors.border}`,
                }}
              >
                中文
              </button>
              <button
                onClick={() => setLanguage("en")}
                style={{
                  ...btnSecondary,
                  background: language === "en" ? colors.accentSoft : undefined,
                  border: `1px solid ${language === "en" ? colors.accent : colors.border}`,
                }}
              >
                English
              </button>
            </div>

            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: space.md,
                marginBottom: space.xl,
                textAlign: "left",
              }}
            >
              {[
                { icon: "01", title: t("Local First", "本地优先"), desc: t("Data remains under your control", "数据始终由您控制") },
                { icon: "02", title: t("Secure", "安全"), desc: t("Reference-based credentials", "基于引用的凭据管理") },
                { icon: "03", title: t("Auditable", "可审计"), desc: t("Full execution trace", "完整执行追踪") },
                { icon: "04", title: t("Offline Ready", "离线可用"), desc: t("Core Runtime works offline", "核心运行时支持离线使用") },
              ].map((item) => (
                <div
                  key={item.title}
                  style={{
                    padding: space.md,
                    background: colors.bg,
                    borderRadius: radius.md,
                  }}
                >
                  <div style={{ fontSize: 20, marginBottom: space.xs }}>{item.icon}</div>
                  <div style={{ fontSize: typo.sm, fontWeight: typo.semibold, color: colors.text }}>
                    {item.title}
                  </div>
                  <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>
                    {item.desc}
                  </div>
                </div>
              ))}
            </div>

            <button onClick={() => setStep(2)} style={{ ...btnPrimary, padding: `${space.md} ${space.xxl}`, fontSize: typo.md }}>
              {t("Start Setup", "开始设置")} →
            </button>

            <div style={{ marginTop: space.lg }}>
              <button
                onClick={onSkip}
                style={{
                  background: "none",
                  border: "none",
                  color: colors.textTertiary,
                  cursor: "pointer",
                  fontSize: typo.sm,
                  fontFamily: typo.font,
                  textDecoration: "underline",
                }}
              >
                {t("Skip setup (limited mode)", "跳过设置（受限模式）")}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Step 2: Environment Check
  if (step === 2) {
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          {stepHeader(
            t("Environment Check", "环境检查"),
            t("Verifying your system is ready for Nous", "验证您的系统是否已准备好运行 Nous"),
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
            {envChecks.map((check) => (
              <div
                key={check.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: space.md,
                  background: colors.bg,
                  borderRadius: radius.md,
                }}
              >
                <div>
                  <div style={{ fontSize: typo.base, fontWeight: typo.medium, color: colors.text }}>
                    {check.status === "checking" && "⏳ "}
                    {check.status === "ok" && "[OK] "}
                    {check.status === "warning" && "[!] "}
                    {check.status === "error" && "[X] "}
                    {check.label}
                  </div>
                  <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 2 }}>
                    {check.detail}
                  </div>
                </div>
                {check.fixable && check.status === "warning" && (
                  <button
                    onClick={async () => {
                      if ("__TAURI_INTERNALS__" in window) {
                        try {
                          await tauriInvoke("start_runtime_api");
                        } catch {
                          // Will retry
                        }
                      }
                    }}
                    style={{
                      ...btnSecondary,
                      fontSize: typo.xs,
                      padding: `${space.xs} ${space.sm}`,
                    }}
                  >
                    {t("Fix", "修复")}
                  </button>
                )}
              </div>
            ))}
          </div>
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 3: Workspace
  if (step === 3) {
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          {stepHeader(
            t("Workspace", "工作区"),
            t("Choose where to store your conversations, tasks, and files", "选择存储对话、任务和文件的位置"),
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
            {[
              {
                action: "default" as const,
                title: t("Default Location", "默认位置"),
                desc: workspacePath,
                icon: "01",
              },
              {
                action: "existing" as const,
                title: t("Select Existing", "选择已有工作区"),
                desc: t("Use an existing workspace", "使用已有工作区"),
                icon: "02",
              },
              {
                action: "new" as const,
                title: t("Create New", "创建新工作区"),
                desc: t("Specify a custom path", "指定自定义路径"),
                icon: "03",
              },
            ].map((opt) => (
              <button
                key={opt.action}
                onClick={() => setWorkspaceAction(opt.action)}
                style={{
                  ...btnSecondary,
                  justifyContent: "flex-start",
                  padding: space.lg,
                  textAlign: "left",
                  border: `1px solid ${workspaceAction === opt.action ? colors.accent : colors.border}`,
                  background: workspaceAction === opt.action ? colors.accentSoft : colors.surface,
                }}
              >
                <span style={{ fontSize: 24, marginRight: space.md }}>{opt.icon}</span>
                <div>
                  <div style={{ fontSize: typo.base, fontWeight: typo.medium, color: colors.text }}>
                    {opt.title}
                  </div>
                  <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 2 }}>
                    {opt.desc}
                  </div>
                </div>
              </button>
            ))}
          </div>
          {workspaceAction === "new" && (
            <div style={{ marginTop: space.md }}>
              <input
                type="text"
                value={workspacePath}
                onChange={(e) => setWorkspacePath(e.target.value)}
                placeholder={t("Enter workspace path...", "输入工作区路径...")}
                style={{ ...input, marginTop: space.sm }}
              />
            </div>
          )}
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 4: Provider Selection
  if (step === 4) {
    return (
      <div style={container}>
        <div style={{ ...contentBox, maxWidth: 640 }}>
          {stepIndicator}
          {stepHeader(
            t("Model Provider", "模型服务商"),
            t("Select your AI model provider. Its credential reference is configured next.", "选择您的 AI 模型服务商，下一步配置凭据引用。"),
          )}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
              gap: space.sm,
              maxHeight: 400,
              overflowY: "auto",
            }}
          >
            {PROVIDER_TEMPLATES.map((p) => (
              <button
                key={p.providerId}
                onClick={() => {
                  setSelectedProviderId(p.providerId);
                  setBaseUrl(p.defaultBaseUrl);
                  setCredentialMode("system");
                  setCredentialSecret("");
                  setCredentialStored(false);
                  setCredentialEnvName(
                    p.credentialType === "none" ? "" : defaultCredentialEnvironment(p.providerId),
                  );
                  setSelectedModels(defaultModelAssignments(p.providerId, p.supportedCapabilities));
                }}
                style={{
                  ...btnSecondary,
                  justifyContent: "flex-start",
                  padding: space.md,
                  textAlign: "left",
                  border: `1px solid ${selectedProviderId === p.providerId ? colors.accent : colors.border}`,
                  background: selectedProviderId === p.providerId ? colors.accentSoft : colors.surface,
                  flexDirection: "column",
                  alignItems: "flex-start",
                  gap: 4,
                }}
              >
                <div style={{ fontSize: typo.base, fontWeight: typo.semibold, color: colors.text }}>
                  {p.displayName}
                </div>
                <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>
                  {p.serviceType}
                  {p.documentationLabel ? ` · ${p.documentationLabel}` : ""}
                </div>
              </button>
            ))}
          </div>
          {selectedProviderId && (
            <div style={{ marginTop: space.md }}>
              <label style={{ fontSize: typo.xs, color: colors.textSecondary, display: "block", marginBottom: 4 }}>
                {t("API Base URL (editable)", "API Base URL（可修改）")}
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                style={input}
              />
              {credentialError && (
                <div role="alert" style={{ marginTop: space.sm, color: colors.danger, fontSize: typo.xs }}>
                  {credentialError === "secret"
                    ? t(
                        "This looks like an API key. Enter the environment-variable name instead.",
                        "该内容看起来像 API Key，请填写环境变量名称。",
                      )
                    : t(
                        "Use a name such as DEEPSEEK_API_KEY. Do not paste the key itself.",
                        "请使用 DEEPSEEK_API_KEY 这类名称，不要粘贴密钥本身。",
                      )}
                </div>
              )}
            </div>
          )}
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 5: Credential Reference
  if (step === 5) {
    const template = PROVIDER_TEMPLATES.find((p) => p.providerId === selectedProviderId);
    const credentialRequired = template?.credentialType !== "none";
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          {stepHeader(
            t("Provider Credential", "服务商凭据"),
            credentialRequired
              ? t(
                  "Store the API key securely, or use an existing environment variable.",
                  "安全保存 API Key，或使用已有的环境变量。",
                )
              : t("This local provider does not require an API key.", "此本地服务商不需要 API Key。"),
          )}
          {credentialRequired && (
            <div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm, marginBottom: space.lg }}>
                {([
                  ["system", t("Windows Credential Manager", "Windows 凭据管理器")],
                  ["environment", t("Environment variable", "环境变量")],
                ] as const).map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => {
                      setCredentialMode(mode);
                      setSetupError("");
                    }}
                    style={{
                      ...btnSecondary,
                      justifyContent: "center",
                      minHeight: 46,
                      borderColor: credentialMode === mode ? colors.accent : colors.border,
                      background: credentialMode === mode ? colors.accentSoft : colors.surface,
                      color: credentialMode === mode ? colors.accent : colors.textSecondary,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {credentialMode === "system" ? (
                <>
                  <label style={{ fontSize: typo.sm, color: colors.textSecondary, display: "block", marginBottom: 4 }}>
                    API Key
                  </label>
                  <input
                    type="password"
                    value={credentialSecret}
                    onChange={(event) => {
                      setCredentialSecret(event.target.value.trim());
                      setCredentialStored(false);
                    }}
                    placeholder={t("Paste the provider API key", "粘贴服务商 API Key")}
                    autoComplete="new-password"
                    spellCheck={false}
                    style={input}
                  />
                  {credentialSecretError && (
                    <div role="alert" style={{ marginTop: space.xs, color: colors.danger, fontSize: typo.xs }}>
                      {t("Enter a valid API key.", "请输入有效的 API Key。")}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <label style={{ fontSize: typo.sm, color: colors.textSecondary, display: "block", marginBottom: 4 }}>
                    {t("Environment variable name", "环境变量名称")}
                  </label>
                  <input
                    type="text"
                    value={credentialEnvName}
                    onChange={(event) => setCredentialEnvName(event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, ""))}
                    placeholder="DEEPSEEK_API_KEY"
                    autoComplete="off"
                    spellCheck={false}
                    style={input}
                  />
                  {credentialError && (
                    <div role="alert" style={{ marginTop: space.xs, color: colors.danger, fontSize: typo.xs }}>
                      {t("Use a name such as DEEPSEEK_API_KEY.", "请输入类似 DEEPSEEK_API_KEY 的变量名。")}
                    </div>
                  )}
                </>
              )}
              <div
                style={{
                  marginTop: space.lg,
                  padding: space.md,
                  background: colors.infoSoft,
                  borderRadius: radius.md,
                  fontSize: typo.xs,
                  color: colors.info,
                  lineHeight: typo.body,
                }}
              >
                {credentialMode === "system"
                  ? t(
                      "The key is encrypted by Windows Credential Manager. Nous configuration stores only its reference.",
                      "密钥由 Windows 凭据管理器加密保存，Nous 配置中只记录引用。",
                    )
                  : t(
                      "Nous stores only an env:NAME reference. Restart Nous after changing the environment variable.",
                      "Nous 只保存 env:变量名 引用；修改环境变量后请重启 Nous。",
                    )}
              </div>
              {setupError && (
                <div role="alert" style={{ marginTop: space.md, padding: space.md, borderRadius: radius.md, background: colors.dangerSoft, color: colors.danger, fontSize: typo.sm }}>
                  {setupError}
                </div>
              )}
            </div>
          )}
          {navButtons}
        </div>
      </div>
    );
  }
  // Step 6: Model Selection
  if (step === 6) {
    const template = PROVIDER_TEMPLATES.find((p) => p.providerId === selectedProviderId);
    const recommendedModels = Object.values(PROVIDER_DEFAULT_MODELS[selectedProviderId] || {});
    const modelOptions = Array.from(new Set([...availableModels, ...recommendedModels].filter(Boolean)));
    return (
      <div style={container}>
        <div style={{ ...contentBox, maxWidth: 720 }}>
          {stepIndicator}
          {stepHeader(
            t("Model Selection", "模型选择"),
            t("Assign models for different capabilities", "为不同能力分配模型"),
          )}
          {modelFetchError && (
            <div
              style={{
                padding: space.md,
                background: colors.warningSoft,
                borderRadius: radius.md,
                color: colors.warning,
                fontSize: typo.sm,
                marginBottom: space.md,
              }}
            >
              {modelFetchError}
            </div>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: space.sm }}>
            {(template?.supportedCapabilities || ["chat"]).map((cap) => (
              <div
                key={cap}
                style={{
                  padding: space.md,
                  border: `1px solid ${colors.borderLight}`,
                  borderRadius: radius.md,
                  background: colors.surface,
                }}
              >
                <label htmlFor={`model-${cap}`} style={{ fontSize: typo.sm, fontWeight: typo.semibold, color: colors.text }}>
                  {CAPABILITY_LABELS[cap] || cap}
                </label>
                <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 2, marginBottom: space.sm }}>
                  {t("Choose a model or keep automatic routing", "选择模型，留空则由 Runtime 自动路由")}
                </div>
                <input
                  id={`model-${cap}`}
                  list={`models-${cap}`}
                  type="text"
                  placeholder={t("Automatic", "自动选择")}
                  value={selectedModels[cap] || ""}
                  onChange={(event) =>
                    setSelectedModels((previous) => ({ ...previous, [cap]: event.target.value }))
                  }
                  style={input}
                />
                <datalist id={`models-${cap}`}>
                  {modelOptions.map((model) => <option key={model} value={model} />)}
                </datalist>
              </div>
            ))}
          </div>
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 7: Connection Test
  if (step === 7) {
    const allOk = testResults.length > 0 && testResults.every((r) => r.ok);
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          {stepHeader(
            t("Connection Test", "连接测试"),
            t("Verifying your provider connection", "验证服务商连接"),
          )}
          {testResults.map((r, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: space.md,
                background: colors.bg,
                borderRadius: radius.md,
                marginBottom: space.sm,
              }}
            >
              <div>
                <div style={{ fontSize: typo.base, fontWeight: typo.medium, color: colors.text }}>
                  {r.ok ? "[OK] " : "[X] "}
                  {r.name}
                </div>
                <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 2 }}>
                  {r.detail}
                </div>
              </div>
            </div>
          ))}
          {testing && (
            <div style={{ textAlign: "center", color: colors.textTertiary, padding: space.md }}>
              {t("Testing...", "测试中...")}
            </div>
          )}
          <div style={{ display: "flex", gap: space.sm, justifyContent: "center", marginTop: space.lg }}>
            <button onClick={runConnectionTest} disabled={testing} style={btnSecondary}>
              {t("Re-test", "重新测试")}
            </button>
          </div>
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 8: Summary
  if (step === 8) {
    const template = PROVIDER_TEMPLATES.find((p) => p.providerId === selectedProviderId);
    const modelList = Object.entries(selectedModels)
      .filter(([, v]) => v)
      .map(([k, v]) => `${CAPABILITY_LABELS[k] || k}: ${v}`);
    return (
      <div style={container}>
        <div style={contentBox}>
          {stepIndicator}
          {stepHeader(
            t("Configuration Summary", "配置摘要"),
            t("Review your settings before completing setup", "完成设置前检查您的配置"),
          )}
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: space.sm,
              fontSize: typo.sm,
            }}
          >
            {[
              { label: t("Workspace", "工作区"), value: workspacePath },
              { label: t("Provider", "服务商"), value: template?.displayName || t("Not selected", "未选择") },
              { label: t("Base URL", "Base URL"), value: baseUrl || t("Not set", "未设置") },
              {
                label: t("Credential", "凭据"),
                value: credentialMode === "system"
                  ? t("Windows Credential Manager", "Windows 凭据管理器")
                  : credentialEnvName ? `env:${credentialEnvName}` : t("Not set", "未设置"),
              },
              { label: t("Models", "模型"), value: modelList.length > 0 ? modelList.join(", ") : t("Auto", "自动") },
              { label: t("Runtime", "运行时"), value: "http://127.0.0.1:8770" },
              { label: t("Language", "语言"), value: language === "zh-CN" ? "中文" : "English" },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: `${space.sm} 0`,
                  borderBottom: `1px solid ${colors.borderLight}`,
                }}
              >
                <span style={{ color: colors.textTertiary }}>{item.label}</span>
                <span style={{ color: colors.text, textAlign: "right", maxWidth: "60%" }}>
                  {item.value}
                </span>
              </div>
            ))}
          </div>
          {setupError && (
            <div role="alert" style={{ marginTop: space.md, padding: space.md, borderRadius: radius.md, background: colors.dangerSoft, color: colors.danger, fontSize: typo.sm }}>
              {setupError}
            </div>
          )}
          {navButtons}
        </div>
      </div>
    );
  }

  // Step 9: Complete
  if (step === 9) {
    return (
      <div style={container}>
        <div style={contentBox}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: typo.sm, letterSpacing: 2, color: colors.accent, marginBottom: space.lg }}>
              NOUS READY
            </div>
            {stepHeader(
              t("Setup Complete!", "设置完成！"),
              t("You're ready to start using Nous.", "您已准备好开始使用 Nous。"),
            )}
            <p
              style={{
                fontSize: typo.sm,
                color: colors.textSecondary,
                margin: `${space.md} 0`,
                lineHeight: typo.body,
              }}
            >
              {t(
                "Your first conversation has been created. Type your message below to get started.",
                "您的第一个对话已创建。在下方输入消息开始使用。",
              )}
            </p>
            <div
              style={{
                padding: space.md,
                background: colors.bg,
                borderRadius: radius.md,
                marginBottom: space.xl,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: space.sm,
                  padding: space.md,
                  background: colors.surface,
                  borderRadius: radius.md,
                  border: `1px solid ${colors.borderLight}`,
                }}
              >
                <input
                  type="text"
                  placeholder={t("Type your first message...", "输入您的第一条消息...")}
                  disabled
                  style={{
                    ...input,
                    border: "none",
                    padding: 0,
                    background: "transparent",
                  }}
                />
              </div>
            </div>
            <button onClick={handleComplete} style={{ ...btnPrimary, padding: `${space.md} ${space.xxl}`, fontSize: typo.md }}>
              {t("Enter Nous", "进入 Nous")} →
            </button>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
