import { btnPrimary, btnSecondary } from "../design";
import type { BootstrapStatus } from "../lib/bootstrap";
import { STATE_MESSAGES } from "../lib/bootstrap";
import { useTheme } from "../theme";
import { AppMark } from "./AppMark";

interface BootstrapScreenProps {
  status: BootstrapStatus;
  onRetry: () => void;
  onStartRuntime: () => void;
  onResetSession: () => void;
  onCreateWorkspace: () => void;
  onOpenLogs: () => void;
  onResetUI: () => void;
  onProceedToOnboarding: () => void;
  onProceedToDashboard: () => void;
}

export function BootstrapScreen({ status, onRetry, onStartRuntime, onResetSession,
  onOpenLogs, onResetUI, onProceedToOnboarding, onProceedToDashboard }: BootstrapScreenProps) {
  const { locale } = useTheme();
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const isError = status.state === "recoverable_error" || status.state === "fatal_error";
  const needsSetup = status.state === "onboarding_required";
  const busy = !isError && !needsSetup && status.state !== "ready";
  const unknown = t("Not confirmed", "尚未确认");

  return <main className="startup-screen">
    <div className="startup-content">
      <AppMark size={72} opening={busy} />
      <h1>APEIR Studio</h1>
      <p role={isError ? "alert" : "status"} className={`startup-message ${isError ? "startup-error" : ""}`}>
        {isError ? t("Your workspace could not be opened.", "暂时无法打开工作空间。") :
          needsSetup ? t("Choose a workspace to begin.", "选择工作空间，即可开始。") :
            t("Opening your workspace…", "正在打开工作空间…")}
      </p>
      <div className="startup-actions">
        {isError && status.recoverable && <button onClick={onRetry} style={btnPrimary}>{t("Try again", "重试")}</button>}
        {isError && <button onClick={onOpenLogs} style={btnSecondary}>{t("Open logs", "查看日志")}</button>}
        {needsSetup && <button onClick={onProceedToOnboarding} style={btnPrimary}>{t("Choose workspace", "选择工作空间")}</button>}
        {status.state === "ready" && <button onClick={onProceedToDashboard} style={btnPrimary}>{t("Open Studio", "进入 Studio")}</button>}
      </div>
      <details className="startup-details">
        <summary>{t("Connection details", "连接详情")}</summary>
        <dl>
          <dt>{t("Startup", "启动阶段")}</dt><dd>{status.progressMessage || STATE_MESSAGES[status.state]}</dd>
          <dt>Runtime</dt><dd>{status.runtime.reachable ? t("Connected", "已连接") : unknown}</dd>
          <dt>{t("Session", "会话")}</dt><dd>{status.session.established ? t("Authenticated", "已认证") : unknown}</dd>
          <dt>{t("Workspace", "工作空间")}</dt><dd>{status.workspace.valid ? status.workspace.path : unknown}</dd>
          <dt>{t("Models", "模型")}</dt><dd>{status.provider.configured ? t("Configured; inference not tested", "已配置，尚未测试推理") : t("Not configured", "未配置")}</dd>
        </dl>
        {status.errorCode && <p><code>{status.errorCode}</code></p>}
        {status.errorMessage && <p>{status.errorMessage}</p>}
        {status.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
        {isError && status.recoverable && <div className="startup-actions">
          <button onClick={onStartRuntime} style={btnSecondary}>{t("Start local service", "启动本地服务")}</button>
          <button onClick={onResetSession} style={btnSecondary}>{t("Reconnect session", "重新连接会话")}</button>
        </div>}
        {isError && <div className="startup-actions">
          <button onClick={() => {
            if (window.confirm(t("Reset saved interface settings?", "重置已保存的界面设置？"))) onResetUI();
          }} style={btnSecondary}>{t("Reset interface settings", "重置界面设置")}</button>
        </div>}
      </details>
    </div>
  </main>;
}
