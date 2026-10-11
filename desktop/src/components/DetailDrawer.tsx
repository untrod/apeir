import React, { useCallback, useEffect, useMemo, useState } from "react";
import { colors, typo, radius, shadow, space, btnPrimary, btnSecondary } from "../design";
import {
  approvalAction,
  fetchApprovals,
  fetchArtifact,
  fetchModelObservations,
  fetchNodes,
  fetchTasks,
  fetchTaskTimeline,
  fetchTaskVerification,
  fetchTrace,
  fetchTraceTimeline,
  testModel,
} from "../lib/api";
import { toast } from "./Toast";

export type DrawerView =
  | null
  | { kind: "task"; taskId: string }
  | { kind: "trace"; traceId: string }
  | { kind: "run"; runId: string }
  | { kind: "node"; nodeId: string }
  | { kind: "approval"; requestId: string }
  | { kind: "artifact"; artifactId: string }
  | { kind: "verification"; taskId: string }
  | { kind: "model-observations"; modelId: string };

interface DetailDrawerProps {
  view: DrawerView;
  onClose: () => void;
}

export function DetailDrawer({ view, onClose }: DetailDrawerProps) {
  if (!view) return null;

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 88 }} />
      <aside
        style={{
          position: "fixed",
          top: 44,
          right: 0,
          bottom: 104,
          width: 360,
          maxWidth: "calc(100vw - 48px)",
          background: colors.surface,
          borderLeft: `1px solid ${colors.border}`,
          boxShadow: shadow.drawer,
          zIndex: 89,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `${space.lg} ${space.xl}`, borderBottom: `1px solid ${colors.borderLight}` }}>
          <div>
            <div style={{ fontSize: typo.xs, color: colors.textTertiary, textTransform: "uppercase" }}>Inspector</div>
            <h2 style={{ margin: 0, fontSize: typo.lg, color: colors.text }}>{titleFor(view)}</h2>
          </div>
          <button onClick={onClose} title="Close" style={{ ...btnSecondary, padding: `${space.xs} ${space.sm}` }}>Close</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
          {view.kind === "task" && <TaskDetails taskId={view.taskId} />}
          {view.kind === "trace" && <TraceDetails traceId={view.traceId} />}
          {view.kind === "run" && <TaskTimelineDetails taskId={view.runId} />}
          {view.kind === "node" && <NodeDetails nodeId={view.nodeId} />}
          {view.kind === "approval" && <ApprovalDetails requestId={view.requestId} />}
          {view.kind === "artifact" && <ArtifactDetails artifactId={view.artifactId} />}
          {view.kind === "verification" && <VerificationDetails taskId={view.taskId} />}
          {view.kind === "model-observations" && <ModelObservationDetails modelId={view.modelId} />}
        </div>
      </aside>
    </>
  );
}

function titleFor(view: Exclude<DrawerView, null>): string {
  switch (view.kind) {
    case "task": return "Task Details";
    case "trace": return "Trace Timeline";
    case "run": return "Persisted Run Activity";
    case "node": return "Node Details";
    case "approval": return "Approval Request";
    case "artifact": return "Artifact";
    case "verification": return "Verification";
    case "model-observations": return "Model Observations";
  }
}

function TaskDetails({ taskId }: { taskId: string }) {
  const loader = useCallback(async () => {
    const response = await fetchTasks("", 200);
    return response.tasks?.find((task: any) => task.id === taskId || task.task_id === taskId) || null;
  }, [taskId]);
  const { data, loading, error } = useAsync(loader);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  if (!data) return <EmptyView text="Task not found in current runtime window." />;

  return <>
    <ObjectPanel data={data as unknown as Record<string, unknown>} preferred={["id", "task_id", "name", "status", "priority", "model_id", "node_id", "progress_pct", "created_at", "updated_at"]} />
    <h3>Recorded effect verification</h3>
    <VerificationDetails taskId={taskId} />
    <h3>Persisted activity</h3>
    <TaskTimelineDetails taskId={taskId} />
  </>;
}

function TraceDetails({ traceId }: { traceId: string }) {
  const loader = useCallback(async () => {
    const [trace, timeline] = await Promise.allSettled([fetchTrace(traceId), fetchTraceTimeline(traceId)]);
    return {
      trace: trace.status === "fulfilled" ? trace.value : null,
      timeline: timeline.status === "fulfilled" ? timeline.value : null,
      errors: [trace, timeline].flatMap(result => result.status === "rejected" ? [String(result.reason)] : []),
    };
  }, [traceId]);
  const { data, loading, error } = useAsync(loader);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  return <ObjectPanel data={{ trace_id: traceId, ...(data || {}) }} />;
}

function NodeDetails({ nodeId }: { nodeId: string }) {
  const loader = useCallback(async () => {
    const response = await fetchNodes();
    return response.find((node: any) => node.id === nodeId || node.node_id === nodeId) || null;
  }, [nodeId]);
  const { data, loading, error } = useAsync(loader);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  if (!data) return <EmptyView text="Node not found in current runtime window." />;
  return <ObjectPanel data={data as unknown as Record<string, unknown>} preferred={["id", "node_id", "name", "platform", "arch", "role", "online", "status", "last_seen"]} />;
}

function ApprovalDetails({ requestId }: { requestId: string }) {
  const [busy, setBusy] = useState(false);
  const loader = useCallback(async () => {
    const response = await fetchApprovals();
    return response.approvals?.find((approval: any) => approval.id === requestId || approval.request_id === requestId) || null;
  }, [requestId]);
  const { data, loading, error, reload } = useAsync(loader);

  const submit = async (action: "approve" | "deny") => {
    setBusy(true);
    try {
      await approvalAction(requestId, action);
      toast.success(action === "approve" ? "Approved" : "Denied", requestId);
      reload();
    } catch (error) {
      toast.error("Approval failed", error instanceof Error ? error.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {loading ? <LoadingView /> : error ? <ErrorView text={error} /> : data ? <ObjectPanel data={data as unknown as Record<string, unknown>} /> : <EmptyView text="Approval not found." />}
      <div style={{ display: "flex", gap: space.sm, marginTop: space.lg }}>
        <button disabled={busy || loading || !!error || !data} onClick={() => submit("approve")} style={{ ...btnPrimary, flex: 1, justifyContent: "center", background: colors.success }}>Approve Once</button>
        <button disabled={busy || loading || !!error || !data} onClick={() => submit("deny")} style={{ ...btnSecondary, flex: 1, justifyContent: "center", color: colors.danger, borderColor: colors.danger }}>Deny</button>
      </div>
    </div>
  );
}

function ModelObservationDetails({ modelId }: { modelId: string }) {
  const loader = useCallback(() => fetchModelObservations(modelId), [modelId]);
  const { data, loading, error } = useAsync(loader);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<Record<string, unknown> | null>(null);
  const runTest = async () => {
    setTesting(true);
    try {
      const result = await testModel(modelId);
      setTestResult(result as unknown as Record<string, unknown>);
      if (result.healthy) toast.success("Model connection verified", modelId);
      else toast.error("Model connection failed", result.error || modelId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown error";
      setTestResult({ healthy: false, error: message });
      toast.error("Model connection failed", message);
    } finally {
      setTesting(false);
    }
  };
  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  return (
    <div>
      <button
        type="button"
        disabled={testing}
        onClick={() => void runTest()}
        style={{ ...btnPrimary, width: "100%", justifyContent: "center", marginBottom: space.lg }}
      >
        {testing ? "Testing..." : "Test Connection"}
      </button>
      {testResult && (
        <div style={{ marginBottom: space.lg }}>
          <ObjectPanel data={testResult} />
        </div>
      )}
      <ObjectPanel data={{ model_id: modelId, ...(data || {}) }} />
    </div>
  );
}

function ArtifactDetails({ artifactId }: { artifactId: string }) {
  const loader = useCallback(() => fetchArtifact(artifactId), [artifactId]);
  const { data, loading, error } = useAsync(loader);
  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  return <ObjectPanel data={data || {}} />;
}

function VerificationDetails({ taskId }: { taskId: string }) {
  const loader = useCallback(() => fetchTaskVerification(taskId), [taskId]);
  const { data, loading, error } = useAsync(loader);
  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  return <>
    <p style={{ color: colors.textSecondary, fontSize: typo.sm }}>Recorded Runtime-service evidence. Evaluation scores and receipts do not establish a physical effect. This view does not acquire a new observation.</p>
    <ObjectPanel data={data || {}} preferred={["verdict", "verified", "committed", "scope", "effect_verification"]} />
  </>;
}

function TaskTimelineDetails({ taskId }: { taskId: string }) {
  const loader = useCallback(() => fetchTaskTimeline(taskId), [taskId]);
  const { data, loading, error } = useAsync(loader);
  if (loading) return <LoadingView />;
  if (error) return <ErrorView text={error} />;
  return <ObjectPanel data={data || {}} />;
}

function ObjectPanel({ data, preferred = [] }: { data: Record<string, unknown>; preferred?: string[] }) {
  const entries = useMemo(() => {
    const keys = [...preferred.filter((key) => key in data), ...Object.keys(data).filter((key) => !preferred.includes(key))];
    return keys.map((key) => [key, data[key]] as const);
  }, [data, preferred]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      {entries.map(([key, value]) => <Field key={key} label={key.replace(/_/g, " ")} value={formatValue(value)} />)}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ border: `1px solid ${colors.borderLight}`, borderRadius: radius.md, padding: space.md, background: colors.bg }}>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary, textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: typo.sm, color: colors.text, wordBreak: "break-word", whiteSpace: "pre-wrap" }}>{value}</div>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function LoadingView() {
  return <div style={{ color: colors.textTertiary, fontSize: typo.sm }}>Loading...</div>;
}

function EmptyView({ text }: { text: string }) {
  return <div style={{ color: colors.textTertiary, fontSize: typo.sm }}>{text}</div>;
}

function ErrorView({ text }: { text: string }) {
  return <div role="alert" style={{ color: colors.danger, fontSize: typo.sm }}>{text}</div>;
}

function useAsync<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setData(null);
    setError(null);
    loader()
      .then((value) => { if (active) setData(value); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loader, revision]);

  return { data, loading, error, reload };
}
