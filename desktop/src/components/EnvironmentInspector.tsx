import React, { useCallback, useEffect, useMemo, useState } from "react";

import { btnPrimary, btnSecondary, card, colors, input, radius, space, typo } from "../design";
import {
  ApiError,
  approvalAction,
  createEnvironment,
  destroyEnvironment,
  fetchEnvironmentLogs,
  fetchEnvironments,
  fetchEnvironmentStatus,
  runEnvironment,
  startEnvironment,
  stopEnvironment,
  type EnvironmentCommandRequest,
  type EnvironmentCreateRequest,
  type EnvironmentRecord,
  type EnvironmentRunResult,
  type EnvironmentRuntimeStatus,
} from "../lib/api";
import { errorMessage } from "../lib/format";

type Pending =
  | { kind: "create"; approvalId: string; request: EnvironmentCreateRequest }
  | { kind: "start" | "stop" | "destroy"; approvalId: string; environmentId: string }
  | { kind: "run"; approvalId: string; environmentId: string; request: EnvironmentCommandRequest };

export function EnvironmentInspector() {
  const [status, setStatus] = useState<EnvironmentRuntimeStatus | null>(null);
  const [environments, setEnvironments] = useState<EnvironmentRecord[]>([]);
  const [selected, setSelected] = useState("");
  const [environmentType, setEnvironmentType] = useState<EnvironmentCreateRequest["environment_type"]>("local_sandbox");
  const [image, setImage] = useState("ubuntu:24.04");
  const [cpu, setCpu] = useState(1);
  const [memory, setMemory] = useState(512);
  const [lifetime, setLifetime] = useState(3600);
  const [mountMode, setMountMode] = useState<"none" | "read-only" | "read-write" | "artifact-output-only">("none");
  const [mountSource, setMountSource] = useState("project");
  const [mountTarget, setMountTarget] = useState("/model-workspace/project");
  const [argvText, setArgvText] = useState('["python", "-V"]');
  const [commandResult, setCommandResult] = useState<EnvironmentRunResult | null>(null);
  const [logs, setLogs] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [nextStatus, nextEnvironments] = await Promise.all([
      fetchEnvironmentStatus(),
      fetchEnvironments(),
    ]);
    setStatus(nextStatus);
    setEnvironments(nextEnvironments.environments);
    if (!selected && nextEnvironments.environments[0]?.environment_id) {
      setSelected(nextEnvironments.environments[0].environment_id);
    }
  }, [selected]);

  useEffect(() => {
    void refresh().catch((cause) => setError(errorMessage(cause, "Environment Runtime is unavailable.")));
  }, [refresh]);

  const current = useMemo(
    () => environments.find((item) => item.environment_id === selected) || null,
    [environments, selected],
  );

  const requestFromForm = (): EnvironmentCreateRequest => ({
    environment_type: environmentType,
    provider: environmentType === "local_sandbox" ? "local-sandbox" : "oci",
    image: environmentType === "oci_container" ? image.trim() : "",
    os: environmentType === "oci_container" ? "linux" : "windows",
    cpu_limit: cpu,
    memory_limit_mb: memory,
    gpu_policy: "none",
    network_policy: { mode: "none", allowed_hosts: [] },
    filesystem_policy: { read_only_root: true, temporary_filesystem_mb: 64 },
    device_policy: { gpu: "none", devices: [] },
    workspace_mounts:
      environmentType === "oci_container" && mountMode !== "none"
        ? [{ source: mountSource.trim(), target: mountTarget.trim(), mode: mountMode }]
        : [],
    lifetime_seconds: lifetime,
  });

  const captureApproval = (cause: unknown, value: Pending): boolean => {
    if (!(cause instanceof ApiError) || cause.code !== "NOUS_APPROVAL_REQUIRED") return false;
    const approvalId = String(cause.details?.approval_request_id || "");
    if (!approvalId) return false;
    setPending({ ...value, approvalId } as Pending);
    return true;
  };

  const executeCreate = async (request: EnvironmentCreateRequest) => {
    setBusy(true);
    setError("");
    try {
      const result = await createEnvironment(request);
      setSelected(result.environment_id);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "create", approvalId: "", request })) {
        setError(errorMessage(cause, "Environment creation failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeLifecycle = async (
    kind: "start" | "stop" | "destroy",
    environmentId: string,
  ) => {
    setBusy(true);
    setError("");
    try {
      if (kind === "start") await startEnvironment(environmentId);
      else if (kind === "stop") await stopEnvironment(environmentId);
      else await destroyEnvironment(environmentId);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind, approvalId: "", environmentId })) {
        setError(errorMessage(cause, `Environment ${kind} failed.`));
      }
    } finally {
      setBusy(false);
    }
  };

  const commandFromEditor = (): EnvironmentCommandRequest => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(argvText);
    } catch {
      throw new Error("Command must be a valid JSON argv array.");
    }
    if (!Array.isArray(parsed) || !parsed.length || !parsed.every((item) => typeof item === "string")) {
      throw new Error("Command must be a non-empty JSON string array.");
    }
    return { argv: parsed, cwd: ".", timeout_seconds: 60, max_output_bytes: 1_000_000 };
  };

  const executeRun = async (environmentId: string, request: EnvironmentCommandRequest) => {
    setBusy(true);
    setError("");
    setCommandResult(null);
    try {
      const result = await runEnvironment(environmentId, request);
      setCommandResult(result);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "run", approvalId: "", environmentId, request })) {
        setError(errorMessage(cause, "Environment command failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const approveAndContinue = async () => {
    if (!pending || busy) return;
    const reviewed = pending;
    setBusy(true);
    setError("");
    try {
      await approvalAction(reviewed.approvalId, "approve");
      setBusy(false);
      if (reviewed.kind === "create") await executeCreate(reviewed.request);
      else if (reviewed.kind === "run") await executeRun(reviewed.environmentId, reviewed.request);
      else await executeLifecycle(reviewed.kind, reviewed.environmentId);
    } catch (cause) {
      setError(errorMessage(cause, "Approval could not be applied."));
      setBusy(false);
    }
  };

  const requestRun = () => {
    if (!selected) return;
    try {
      void executeRun(selected, commandFromEditor());
    } catch (cause) {
      setError(errorMessage(cause, "Command is invalid."));
    }
  };

  const openLogs = async () => {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      setLogs((await fetchEnvironmentLogs(selected)).text || "No provider logs.");
    } catch (cause) {
      setError(errorMessage(cause, "Environment logs are unavailable."));
    } finally {
      setBusy(false);
    }
  };

  const local = status?.providers.find((item) => item.provider_id === "local-sandbox");
  const oci = status?.providers.find((item) => item.provider_id === "oci");

  return (
    <div style={{ height: "100%", overflowY: "auto", background: colors.bg, padding: space.xl }}>
      <div style={{ maxWidth: 1180, margin: "0 auto", display: "grid", gap: space.lg }}>
        <section style={{ ...card, display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text }}>Environments</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: space.xs }}>
              Environment Contract - approval - provider - EventStream - Artifact evidence
            </div>
          </div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm }}>
            {status
              ? `${status.environments} environments - Local ${local?.available ? "ready" : "unavailable"} - OCI ${oci?.available ? oci.engine || "ready" : "not installed"}`
              : "Checking providers..."}
          </div>
        </section>

        {local && !local.hard_network_isolation && (
          <section style={{ ...card, borderColor: colors.warning, background: colors.warningSoft, color: colors.textSecondary, fontSize: typo.sm }}>
            LocalSandbox is integrated-host only: process/resource limits are active, but Windows network and filesystem namespace isolation are not hard boundaries. OCI remains the production isolation target.
          </section>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "minmax(320px, 0.85fr) minmax(0, 1.45fr)", gap: space.lg }}>
          <section style={card}>
            <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.md }}>Create environment</div>
            <label style={labelStyle}>Provider type</label>
            <select
              aria-label="Environment type"
              value={environmentType}
              onChange={(event) => setEnvironmentType(event.target.value as EnvironmentCreateRequest["environment_type"])}
              style={input}
            >
              <option value="local_sandbox">Local sandbox</option>
              <option value="oci_container">OCI Linux container</option>
            </select>
            {environmentType === "oci_container" && (
              <>
                <label style={labelStyle}>OCI image</label>
                <input aria-label="OCI image" value={image} onChange={(event) => setImage(event.target.value)} style={input} />
                {!oci?.available && <div style={warningStyle}>Docker/Podman is not installed; creation is allowed, start will fail closed.</div>}
              </>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm }}>
              <div><label style={labelStyle}>CPU limit</label><input aria-label="CPU limit" type="number" min={0.1} max={64} step={0.1} value={cpu} onChange={(event) => setCpu(Number(event.target.value))} style={input} /></div>
              <div><label style={labelStyle}>Memory MiB</label><input aria-label="Memory limit" type="number" min={64} max={131072} value={memory} onChange={(event) => setMemory(Number(event.target.value))} style={input} /></div>
            </div>
            <label style={labelStyle}>Lifetime seconds</label>
            <input aria-label="Lifetime seconds" type="number" min={60} max={604800} value={lifetime} onChange={(event) => setLifetime(Number(event.target.value))} style={input} />
            {environmentType === "oci_container" && (
              <>
                <label style={labelStyle}>Workspace mount</label>
                <select aria-label="Workspace mount mode" value={mountMode} onChange={(event) => setMountMode(event.target.value as typeof mountMode)} style={input}>
                  <option value="none">No host workspace</option>
                  <option value="read-only">Read-only</option>
                  <option value="read-write">Read-write</option>
                  <option value="artifact-output-only">Artifact output only</option>
                </select>
                {mountMode !== "none" && (
                  <div style={{ display: "grid", gap: space.sm, marginTop: space.sm }}>
                    <input aria-label="Mount source" value={mountSource} onChange={(event) => setMountSource(event.target.value)} style={input} />
                    <input aria-label="Mount target" value={mountTarget} onChange={(event) => setMountTarget(event.target.value)} style={input} />
                  </div>
                )}
              </>
            )}
            <div style={policyStyle}>Network: OFF - privileged: FALSE - devices: NONE - root filesystem: READ-ONLY</div>
            <button
              onClick={() => void executeCreate(requestFromForm())}
              disabled={busy || (environmentType === "oci_container" && !image.trim())}
              style={{ ...btnPrimary, marginTop: space.md, opacity: busy ? 0.55 : 1 }}
            >
              {busy ? "Working..." : "Create governed environment"}
            </button>
          </section>

          <section style={card}>
            <div style={{ color: colors.text, fontWeight: typo.semibold }}>Inspect and control</div>
            <select aria-label="Environment library" value={selected} onChange={(event) => { setSelected(event.target.value); setLogs(""); setCommandResult(null); }} style={{ ...input, marginTop: space.md }}>
              <option value="">Select an environment</option>
              {environments.map((item) => (
                <option key={item.environment_id} value={item.environment_id}>
                  {item.environment_id.slice(-12)} - {item.environment_type} - {item.state}
                </option>
              ))}
            </select>

            {current && (
              <div style={{ display: "grid", gap: space.sm, marginTop: space.md }}>
                <div style={detailGrid}>
                  <Detail label="Status" value={current.state} />
                  <Detail label="Provider" value={current.provider} />
                  <Detail label="Image" value={current.image || "host"} />
                  <Detail label="OS / Arch" value={`${current.os} / ${current.architecture || "native"}`} />
                  <Detail label="CPU / RAM" value={`${current.cpu_limit} CPU / ${current.memory_limit_mb} MiB`} />
                  <Detail label="Network" value={current.network_policy.mode} />
                  <Detail label="Workspace mounts" value={String(current.workspace_mounts.length)} />
                  <Detail label="Lifetime" value={`${current.lifetime_seconds}s`} />
                </div>
                {current.last_error && <div style={warningStyle}>{current.last_error}</div>}
                <div style={{ display: "flex", flexWrap: "wrap", gap: space.sm }}>
                  {["created", "stopped", "failed"].includes(current.state) && <button onClick={() => void executeLifecycle("start", current.environment_id)} disabled={busy} style={btnPrimary}>Start</button>}
                  {["ready", "running", "suspended"].includes(current.state) && <button onClick={() => void executeLifecycle("stop", current.environment_id)} disabled={busy} style={btnSecondary}>Stop</button>}
                  {current.state !== "destroyed" && <button onClick={() => void executeLifecycle("destroy", current.environment_id)} disabled={busy} style={{ ...btnSecondary, color: colors.danger }}>Destroy</button>}
                  <button onClick={() => void openLogs()} disabled={busy} style={btnSecondary}>Open logs</button>
                </div>
                {current.state === "ready" && (
                  <div style={{ borderTop: `1px solid ${colors.borderLight}`, paddingTop: space.md }}>
                    <label style={labelStyle}>Argv JSON (no shell)</label>
                    <textarea aria-label="Environment command" value={argvText} onChange={(event) => setArgvText(event.target.value)} rows={3} style={{ ...input, resize: "vertical", fontFamily: "monospace" }} />
                    <button onClick={requestRun} disabled={busy} style={{ ...btnPrimary, marginTop: space.sm }}>Run in environment</button>
                  </div>
                )}
              </div>
            )}

            {commandResult && (
              <div style={{ marginTop: space.md, border: `1px solid ${commandResult.ok ? colors.success : colors.danger}`, borderRadius: radius.md, padding: space.md, color: colors.text, fontSize: typo.sm }}>
                Exit {commandResult.exit_code} - Artifact {commandResult.artifact_id}<br />
                <span style={{ color: colors.textTertiary }}>{commandResult.artifact.location}</span>
                <pre style={preStyle}>{commandResult.stdout || commandResult.stderr || "(no output)"}</pre>
              </div>
            )}
            {logs && <pre style={{ ...preStyle, marginTop: space.md }}>{logs}</pre>}
          </section>
        </div>

        {pending && (
          <section style={{ ...card, borderColor: colors.warning, background: colors.warningSoft }}>
            <div style={{ color: colors.text, fontWeight: typo.semibold }}>Explicit approval required</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.sm, margin: `${space.sm} 0` }}>
              Review the scoped Environment effect. Approval is single-use and Nous retries the identical request.
            </div>
            <button onClick={() => void approveAndContinue()} disabled={busy} style={btnPrimary}>
              Approve once and {pending.kind}
            </button>
          </section>
        )}
        {error && <section style={{ ...card, color: colors.danger, borderColor: colors.danger }}>{error}</section>}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div><div style={{ color: colors.textTertiary, fontSize: typo.xs }}>{label}</div><div style={{ color: colors.text, fontSize: typo.sm, marginTop: 2 }}>{value}</div></div>;
}

const labelStyle: React.CSSProperties = { display: "block", color: colors.textSecondary, fontSize: typo.xs, marginTop: space.md, marginBottom: space.xs };
const warningStyle: React.CSSProperties = { color: colors.warning, fontSize: typo.xs, marginTop: space.sm };
const policyStyle: React.CSSProperties = { color: colors.textTertiary, fontSize: typo.xs, lineHeight: 1.6, marginTop: space.md };
const detailGrid: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: space.md, padding: space.md, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md };
const preStyle: React.CSSProperties = { whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 260, overflow: "auto", background: colors.bg, color: colors.text, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md, padding: space.md, fontSize: typo.xs };
