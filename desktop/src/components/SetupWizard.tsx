/**
 * SetupWizard — First-run onboarding wizard.
 *
 * Multi-step flow:
 *   1. Welcome & Identity
 *   2. Primary Node designation
 *   3. Provider & Model configuration
 *   4. Local model setup (optional)
 *   5. Device binding & Health Check
 *   6. First Chat
 *
 * Supports interrupt recovery: each step persists progress to localStorage.
 * Errors at any step can be repaired without restarting the entire flow.
 */

import React, { useState, useEffect, useCallback } from "react";
import { colors, typo, radius, shadow, space, card, btnPrimary, btnSecondary, input as inputStyle } from "../design";
import { testConnection, setConfig, getConfig, scanNodes, fetchModels } from "../lib/api";


// Types


type StepId = "welcome" | "node" | "provider" | "local_model" | "health_check" | "first_chat";

interface StepState {
  completed: boolean;
  data: Record<string, string>;
}

const STEP_ORDER: StepId[] = ["welcome", "node", "provider", "local_model", "health_check", "first_chat"];

const STEP_LABELS: Record<StepId, string> = {
  welcome: "Welcome",
  node: "Primary Node",
  provider: "Provider & Model",
  local_model: "Local Model",
  health_check: "Health Check",
  first_chat: "First Chat",
};


// Persistence


const STORAGE_KEY = "nous_setup_wizard";

function loadProgress(): { currentStep: StepId; steps: Record<string, StepState> } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function saveProgress(currentStep: StepId, steps: Record<string, StepState>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ currentStep, steps }));
  } catch { /* quota */ }
}

function clearProgress(): void {
  localStorage.removeItem(STORAGE_KEY);
}


// Wizard


interface SetupWizardProps {
  onComplete: () => void;
}

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const saved = loadProgress();
  const [currentStep, setCurrentStep] = useState<StepId>(saved?.currentStep || "welcome");
  const [steps, setSteps] = useState<Record<string, StepState>>(saved?.steps || {});
  const [error, setError] = useState<string | null>(null);

  const markStepComplete = useCallback((step: StepId, data: Record<string, string> = {}) => {
    setSteps((prev) => {
      const next = { ...prev, [step]: { completed: true, data } };
      const idx = STEP_ORDER.indexOf(step);
      const nextStep = idx < STEP_ORDER.length - 1 ? STEP_ORDER[idx + 1] : step;
      setCurrentStep(nextStep);
      saveProgress(nextStep, next);
      return next;
    });
  }, []);

  const goToStep = (step: StepId) => {
    setCurrentStep(step);
    saveProgress(step, steps);
  };

  const handleComplete = () => {
    clearProgress();
    onComplete();
  };

  const stepIndex = STEP_ORDER.indexOf(currentStep);
  const progressPct = Math.round(((stepIndex) / (STEP_ORDER.length - 1)) * 100);

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      height: "100vh", background: colors.bg,
    }}>
      <div style={{ width: 520, maxWidth: "90vw" }}>
        {/* Progress */}
        <div style={{ marginBottom: space.xl }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: space.sm }}>
            {STEP_ORDER.map((sid, i) => (
              <div key={sid} style={{
                textAlign: "center", flex: 1,
                opacity: i <= stepIndex ? 1 : 0.3,
                transition: "opacity 0.3s",
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: "50%",
                  background: steps[sid]?.completed ? colors.success : i === stepIndex ? colors.accent : colors.border,
                  color: colors.textInverse, display: "inline-flex",
                  alignItems: "center", justifyContent: "center",
                  fontSize: typo.xs, fontWeight: typo.bold,
                }}>
                  {steps[sid]?.completed ? "✓" : i + 1}
                </div>
                <div style={{ fontSize: "9px", color: colors.textTertiary, marginTop: 2 }}>
                  {STEP_LABELS[sid]}
                </div>
              </div>
            ))}
          </div>
          <div style={{ height: 3, background: colors.borderLight, borderRadius: "9999px", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progressPct}%`, background: colors.accent, borderRadius: "9999px", transition: "width 0.4s" }} />
          </div>
        </div>

        {/* Step content */}
        <div style={{ ...card, minHeight: 300 }}>
          {error && (
            <div style={{
              padding: space.md, marginBottom: space.md,
              background: colors.dangerSoft, color: colors.danger,
              borderRadius: radius.md, fontSize: typo.sm,
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span>{error}</span>
              <button onClick={() => setError(null)} style={{ background: "none", border: "none", color: colors.danger, cursor: "pointer", fontSize: typo.md }}>×</button>
            </div>
          )}

          {currentStep === "welcome" && (
            <WelcomeStep onNext={(data) => markStepComplete("welcome", data)} />
          )}
          {currentStep === "node" && (
            <NodeStep onNext={(data) => markStepComplete("node", data)} onError={setError} />
          )}
          {currentStep === "provider" && (
            <ProviderStep onNext={(data) => markStepComplete("provider", data)}
              onSkip={() => markStepComplete("provider", { skipped: "true" })} />
          )}
          {currentStep === "local_model" && (
            <LocalModelStep onNext={(data) => markStepComplete("local_model", data)} onError={setError}
              onSkip={() => markStepComplete("local_model", { skipped: "true" })} />
          )}
          {currentStep === "health_check" && (
            <HealthCheckStep onNext={(data) => markStepComplete("health_check", data)} onError={setError} />
          )}
          {currentStep === "first_chat" && (
            <FirstChatStep onComplete={handleComplete} />
          )}
        </div>

        {/* Step navigation */}
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: space.md }}>
          <button
            onClick={() => { const idx = STEP_ORDER.indexOf(currentStep); if (idx > 0) goToStep(STEP_ORDER[idx - 1]); }}
            disabled={stepIndex === 0}
            style={{ ...btnSecondary, opacity: stepIndex === 0 ? 0.4 : 1, fontSize: typo.sm }}
          >
            ← Back
          </button>
          <button onClick={handleComplete} style={{ ...btnSecondary, fontSize: typo.sm }}>
            Skip Setup
          </button>
        </div>
      </div>
    </div>
  );
}


// Step: Welcome


function WelcomeStep({ onNext }: { onNext: (data: Record<string, string>) => void }) {
  const [name, setName] = useState("");
  return (
    <div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Welcome to Nous
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, lineHeight: typo.relaxed, margin: `0 0 ${space.xl} 0` }}>
        Nous is a chat-first AI control plane. Plan, execute, and verify tasks across your nodes — all from one conversation.
      </p>
      <label style={{ fontSize: typo.sm, fontWeight: typo.medium, color: colors.text, display: "block", marginBottom: space.xs }}>
        What should we call this workspace?
      </label>
      <input
        value={name} onChange={(e) => setName(e.target.value)}
        placeholder="My Workspace"
        style={{ ...inputStyle, marginBottom: space.lg }}
        onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) onNext({ name: name.trim() }); }}
      />
      <button onClick={() => name.trim() && onNext({ name: name.trim() })} disabled={!name.trim()}
        style={{ ...btnPrimary, width: "100%", justifyContent: "center", opacity: name.trim() ? 1 : 0.5 }}>
        Continue
      </button>
    </div>
  );
}


// Step: Primary Node


function NodeStep({ onNext, onError }: { onNext: (data: Record<string, string>) => void; onError: (e: string) => void }) {
  const [scanning, setScanning] = useState(false);
  const [nodesFound, setNodesFound] = useState(0);

  const handleScan = async () => {
    setScanning(true);
    try {
      const result = await scanNodes();
      setNodesFound(result?.nodes_found || 0);
      if (result?.nodes_found === 0) {
        onError("No nodes found on the network. Ensure devices are on the same LAN or connect manually.");
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : "Scan failed");
    } finally {
      setScanning(false);
    }
  };

  return (
    <div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Connect Your Primary Node
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, lineHeight: typo.relaxed, margin: `0 0 ${space.xl} 0` }}>
        The Primary node hosts the APEIR Runtime. Workers share compute. Scan your local network to discover devices.
      </p>
      <button onClick={handleScan} disabled={scanning}
        style={{ ...btnPrimary, width: "100%", justifyContent: "center", marginBottom: space.md }}>
        {scanning ? "Scanning..." : "Scan Network"}
      </button>
      {nodesFound > 0 && (
        <div style={{ padding: space.md, background: colors.successSoft, color: colors.success, borderRadius: radius.md, marginBottom: space.md, fontSize: typo.sm }}>
          Found {nodesFound} device{nodesFound > 1 ? "s" : ""} on the network.
        </div>
      )}
      <button onClick={() => onNext({})} style={{ ...btnPrimary, width: "100%", justifyContent: "center", background: colors.accent }}>
        Continue
      </button>
    </div>
  );
}


// Step: Provider


function ProviderStep({ onNext, onSkip }: {
  onNext: (data: Record<string, string>) => void;
  onSkip: () => void;
}) {
  const [provider, setProvider] = useState("openai");
  const environmentVariables: Record<string, string> = {
    openai: "OPENAI_API_KEY",
    claude: "ANTHROPIC_API_KEY",
    deepseek: "DEEPSEEK_API_KEY",
    ollama: "No credential required",
  };

  return (
    <div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Configure a Model Provider
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, lineHeight: typo.relaxed, margin: `0 0 ${space.md} 0` }}>
        Provider credentials are managed by APEIR Runtime, not stored in the desktop application.
      </p>
      <select value={provider} onChange={(event) => setProvider(event.target.value)}
        style={{ ...inputStyle, marginBottom: space.md }}>
        <option value="openai">OpenAI</option>
        <option value="claude">Anthropic Claude</option>
        <option value="deepseek">DeepSeek</option>
        <option value="ollama">Ollama</option>
      </select>
      <div style={{ padding: space.md, background: colors.infoSoft, color: colors.info, borderRadius: radius.md, marginBottom: space.md, fontSize: typo.sm, lineHeight: typo.relaxed }}>
        <div>Run <code style={{ fontFamily: typo.mono }}>nous provider add</code> in a terminal.</div>
        <div>Credential reference: <code style={{ fontFamily: typo.mono }}>{environmentVariables[provider]}</code></div>
        <div>Enter the environment variable name only. Never paste an API key into that field.</div>
      </div>
      <div style={{ display: "flex", gap: space.sm }}>
        <button onClick={() => onNext({ provider, setup: "runtime" })}
          style={{ ...btnPrimary, flex: 1, justifyContent: "center" }}>
          Provider Configured
        </button>
        <button onClick={onSkip} style={{ ...btnSecondary, flex: 1, justifyContent: "center", fontSize: typo.sm }}>
          Skip
        </button>
      </div>
    </div>
  );
}


// Step: Local Model


function LocalModelStep({ onNext, onError, onSkip }: {
  onNext: (data: Record<string, string>) => void;
  onError: (e: string) => void;
  onSkip: () => void;
}) {
  return (
    <div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Local Model (Optional)
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, lineHeight: typo.relaxed, margin: `0 0 ${space.xl} 0` }}>
        Run models locally for sensitive data. Requires GPU with sufficient VRAM or a worker node.
      </p>
      <div style={{ padding: space.md, background: colors.infoSoft, color: colors.info, borderRadius: radius.md, marginBottom: space.md, fontSize: typo.sm }}>
        Local model setup is managed through the CLI: <code style={{ fontFamily: typo.mono, background: colors.inlineCodeBg, padding: "1px 4px", borderRadius: "4px" }}>nous model install</code>
      </div>
      <div style={{ display: "flex", gap: space.sm }}>
        <button onClick={() => onNext({ local: "cli" })} style={{ ...btnPrimary, flex: 1, justifyContent: "center" }}>
          I'll set up via CLI
        </button>
        <button onClick={onSkip} style={{ ...btnSecondary, flex: 1, justifyContent: "center" }}>Skip</button>
      </div>
    </div>
  );
}


// Step: Health Check


function HealthCheckStep({ onNext, onError }: {
  onNext: (data: Record<string, string>) => void;
  onError: (e: string) => void;
}) {
  const [checks, setChecks] = useState<{ label: string; ok: boolean; detail: string }[]>([]);
  const [running, setRunning] = useState(true);

  useEffect(() => {
    const run = async () => {
      const results: { label: string; ok: boolean; detail: string }[] = [];

      // Runtime health
      try {
        const ok = await testConnection();
        results.push({ label: "Runtime", ok, detail: ok ? "Connected" : "Unreachable" });
      } catch {
        results.push({ label: "Runtime", ok: false, detail: "Connection failed" });
      }

      // Models
      try {
        const models = await fetchModels();
        const healthy = models?.models?.filter((model) => model.health === "healthy").length || 0;
        results.push({ label: "Models", ok: healthy > 0, detail: `${healthy} healthy` });
      } catch {
        results.push({ label: "Models", ok: false, detail: "No models available" });
      }

      setChecks(results);
      setRunning(false);

      const allOk = results.every((r) => r.ok);
      if (allOk) {
        setTimeout(() => onNext({ health: "passed" }), 1000);
      }
    };
    run();
  }, [onNext]);

  return (
    <div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Health Check
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, margin: `0 0 ${space.xl} 0` }}>
        {running ? "Verifying your APEIR Runtime setup..." : "Health check complete."}
      </p>
      {checks.map((c) => (
        <div key={c.label} style={{
          display: "flex", alignItems: "center", gap: space.sm,
          padding: `${space.sm} 0`, borderBottom: `1px solid ${colors.borderLight}`,
        }}>
          <span>{c.ok ? "✅" : running ? "⏳" : "❌"}</span>
          <span style={{ fontWeight: typo.medium, color: colors.text }}>{c.label}</span>
          <span style={{ marginLeft: "auto", fontSize: typo.sm, color: c.ok ? colors.success : colors.danger }}>
            {c.detail}
          </span>
        </div>
      ))}
      {!running && checks.some((c) => !c.ok) && (
        <button onClick={() => onNext({ health: "partial" })} style={{ ...btnPrimary, width: "100%", justifyContent: "center", marginTop: space.lg }}>
          Continue Anyway
        </button>
      )}
    </div>
  );
}


// Step: First Chat


function FirstChatStep({ onComplete }: { onComplete: () => void }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{ fontSize: typo.sm, letterSpacing: 2, color: colors.accent, marginBottom: space.md }}>NOUS READY</div>
      <h2 style={{ fontSize: typo.xl, fontWeight: typo.bold, color: colors.text, margin: `0 0 ${space.sm} 0` }}>
        Vous êtes prêt.
      </h2>
      <p style={{ fontSize: typo.base, color: colors.textSecondary, lineHeight: typo.relaxed, margin: `0 0 ${space.xl} 0` }}>
        Your APEIR Runtime is configured and ready. Start chatting to plan, execute, and verify tasks across your nodes.
      </p>
      <button onClick={onComplete} style={{ ...btnPrimary, padding: `${space.md} ${space.xxl}`, fontSize: typo.md }}>
        Start Chatting
      </button>
    </div>
  );
}
