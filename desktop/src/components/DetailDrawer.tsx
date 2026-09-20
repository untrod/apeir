import React, { useCallback, useEffect, useMemo, useState } from "react";
import { colors, typo, radius, shadow, space, btnPrimary, btnSecondary } from "../design";
import {
  approvalAction,
  fetchApprovals,
  fetchModelObservations,
  fetchNodes,
  fetchTasks,
  fetchTrace,
  fetchTraceTimeline,
  testModel,
} from "../lib/api";
import { toast } from "./Toast";

export type DrawerView =
  | null
  | { kind: "task"; taskId: string }
  | { kind: "trace"; traceId: string }
  | { kind: "node"; nodeId: string }
  | { kind: "approval"; requestId: string }
  | { kind: "artifact"; artifactId: string }
  | { kind: "verification"; capabilityId: string }
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
          {view.kind === "node" && <NodeDetails nodeId={view.nodeId} />}
          {view.kind === "approval" && <ApprovalDetails requestId={view.requestId} />}
          {view.kind === "artifact" && <PlaceholderDetails title="Artifact" id={view.artifactId} />}
          {view.kind === "verification" && <PlaceholderDetails title="Verification" id={view.capabilityId} />}
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
  const { data, loading } = useAsync(loader);

  if (loading) return <LoadingView />;
  if (!data) return <EmptyView text="Task not found in current runtime window." />;

  return <ObjectPanel data={data as unknown as Record<string, unknown>} preferred={["id", "task_id", "name", "status", "priority", "model_id", "node_id", "progress_pct", "created_at", "updated_at"]} />;
}

function TraceDetails({ traceId }: { traceId: string }) {
  const loader = useCallback(async () => {
    const [trace, timeline] = await Promise.allSettled([fetchTrace(traceId), fetchTraceTimeline(traceId)]);
    return {
      trace: trace.status === "fulfilled" ? trace.value : null,
      timeline: timeline.status === "fulfilled" ? timeline.value : null,
    };
  }, [traceId]);
  const { data, loading } = useAsync(loader);

  if (loading) return <LoadingView />;
  return <ObjectPanel data={{ trace_id: traceId, ...(data || {}) }} />;
}

function NodeDetails({ nodeId }: { nodeId: string }) {
  const loader = useCallback(async () => {
    const response = await fetchNodes();
    return response.find((node: any) => node.id === nodeId || node.node_id === nodeId) || null;
  }, [nodeId]);
  const { data, loading } = useAsync(loader);

  if (loading) return <LoadingView />;
  if (!data) return <EmptyView text="Node not found in current runtime window." />;
  return <ObjectPanel data={data as unknown as Record<string, unknown>} preferred={["id", "node_id", "name", "platform", "arch", "role", "online", "status", "last_seen"]} />;
}

function ApprovalDetails({ requestId }: { requestId: string }) {
  const [busy, setBusy] = useState(false);
  const loader = useCallback(async () => {
    const response = await fetchApprovals();
    return response.approvals?.find((approval: any) => approval.id === requestId || approval.request_id === requestId) || null;
  }, [requestId]);
  const { data, loading, reload } = useAsync(loader);

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
      {loading ? <LoadingView /> : data ? <ObjectPanel data={data as unknown as Record<string, unknown>} /> : <EmptyView text="Approval not found." />}
      <div style={{ display: "flex", gap: space.sm, marginTop: space.lg }}>
        <button disabled={busy} onClick={() => submit("approve")} style={{ ...btnPrimary, flex: 1, justifyContent: "center", background: colors.success }}>Approve</button>
        <button disabled={busy} onClick={() => submit("deny")} style={{ ...btnSecondary, flex: 1, justifyContent: "center", color: colors.danger, borderColor: colors.danger }}>Deny</button>
      </div>
    </div>
  );
}

function ModelObservationDetails({ modelId }: { modelId: string }) {
  const loader = useCallback(() => fetchModelObservations(modelId), [modelId]);
  const { data, loading } = useAsync(loader);
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

function PlaceholderDetails({ title, id }: { title: string; id: string }) {
  return <ObjectPanel data={{ type: title, id, note: "Detailed runtime data is loaded through the related task or trace." }} />;
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

function useAsync<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    loader()
      .then((value) => { if (active) setData(value); })
      .catch(() => { if (active) setData(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loader, revision]);

  return { data, loading, reload };
}
