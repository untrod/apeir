/**
 * Inspector — Runtime internals panel.
 * Shows live event stream, system health, memory usage, trace statistics.
 * Accessible via a toggle in the main view — not a primary navigation target.
 */

import React, { useState, useEffect, useCallback } from "react";
import { colors, typo, radius, shadow, space, card, btnSecondary, fadeIn } from "../design";
import { fixedNumber } from "../lib/format";
import {
  fetchStatus, fetchMemory, fetchInspectorRuntime, subscribeRuntimeEvents,
  fetchTraceTimeline, fetchModelRankings, fetchInspectorCheckpoints,
  type CheckpointDiagnostics, type RuntimeEventEnvelope, type RuntimeStatus,
} from "../lib/api";


// Live Event Stream


function LiveEventStream() {
  const [events, setEvents] = useState<RuntimeEventEnvelope[]>([]);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const sub = subscribeRuntimeEvents((event) => {
      setEvents((prev) => [event, ...prev].slice(0, 200));
    }, { intervalMs: 1500 });
    return () => sub.close();
  }, [paused]);

  return (
    <Section title="Live Events" action={
      <button onClick={() => setPaused(!paused)} style={{
        ...btnSecondary, fontSize: typo.xs, padding: `2px ${space.sm}`,
      }}>
        {paused ? "▶ Resume" : "⏸ Pause"}
      </button>
    }>
      <div style={{
        maxHeight: 300, overflowY: "auto",
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: typo.xs,
      }}>
        {events.slice(0, 50).map((evt) => (
          <div key={evt.event_id} style={{
            padding: `${space.xs} 0`,
            borderBottom: `1px solid ${colors.borderLight}`,
            display: "flex", gap: space.sm, alignItems: "baseline",
          }}>
            <span style={{
              color: colors.textTertiary, flexShrink: 0,
              width: 72, overflow: "hidden", textOverflow: "ellipsis",
            }}>
              {new Date(evt.timestamp).toLocaleTimeString()}
            </span>
            <span style={{
              color: evt.event_type.startsWith("error") ? colors.danger :
                     evt.event_type.startsWith("approval") ? colors.warning :
                     evt.event_type.startsWith("task.completed") ? colors.success :
                     colors.accent,
              flexShrink: 0, minWidth: 140,
            }}>
              {evt.event_type}
            </span>
            <span style={{ color: colors.textSecondary, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {evt.source}
            </span>
          </div>
        ))}
        {events.length === 0 && (
          <div style={{ color: colors.textTertiary, padding: space.md }}>
            Waiting for events...
          </div>
        )}
      </div>
    </Section>
  );
}


// System Status


function SystemStatus() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [memory, setMemory] = useState<{ used_pct: number; rss_mb: number; total_gb: number } | null>(null);

  useEffect(() => {
    const load = () => {
      fetchStatus().then(setStatus).catch(() => {});
      fetchMemory().then(setMemory).catch(() => {});
    };
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Section title="Runtime Status">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm }}>
        <MiniStat label="Version" value={status?.version || "—"} />
        <MiniStat label="Uptime" value={status?.running ? "Running" : "Stopped"} />
        <MiniStat label="Providers" value={status?.providers ?? "—"} />
        <MiniStat label="Capabilities" value={status?.capabilities ?? "—"} />
        <MiniStat label="Devices" value={status?.devices ?? "—"} />
        <MiniStat label="Jobs Pending" value={status?.jobs_pending ?? "—"} />
      </div>
      {memory && (
        <div style={{ marginTop: space.sm }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: typo.xs, color: colors.textTertiary }}>
            <span>Memory</span>
            <span>{memory.rss_mb}MB / {memory.total_gb}GB</span>
          </div>
          <div style={{
            height: 3, background: colors.borderLight, borderRadius: radius.full,
            marginTop: 4, overflow: "hidden",
          }}>
            <div style={{
              height: "100%",
              width: `${Math.min(100, memory.used_pct)}%`,
              background: memory.used_pct > 80 ? colors.danger : colors.accent,
              borderRadius: radius.full,
              transition: "width 0.5s",
            }} />
          </div>
        </div>
      )}
    </Section>
  );
}


// Agent Checkpoints


export function CheckpointHealth() {
  const [report, setReport] = useState<CheckpointDiagnostics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => {
      fetchInspectorCheckpoints()
        .then((data) => {
          setReport(data);
          setError("");
        })
        .catch(() => setError("Checkpoint diagnostics unavailable"));
    };
    load();
    const timer = setInterval(load, 10000);
    return () => clearInterval(timer);
  }, []);

  const statusColor = report?.status === "healthy" ? colors.success :
    report?.status === "degraded" ? colors.danger :
    report?.status === "empty" ? colors.textTertiary :
    colors.warning;
  const statusLabel = report
    ? report.status.charAt(0).toUpperCase() + report.status.slice(1)
    : "Loading";

  return (
    <Section title="Agent Checkpoints">
      <div style={{
        display: "flex", alignItems: "center", gap: space.xs,
        marginBottom: space.sm, fontSize: typo.xs,
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: radius.full,
          background: error ? colors.danger : statusColor,
        }} />
        <span style={{ color: error ? colors.danger : statusColor }}>
          {error || statusLabel}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm }}>
        <MiniStat label="Stored" value={report?.integrity.total ?? "--"} />
        <MiniStat label="Valid" value={report?.integrity.valid ?? "--"} />
        <MiniStat label="Invalid" value={report?.integrity.invalid ?? "--"} />
        <MiniStat label="Tasks" value={report?.tasks ?? "--"} />
      </div>
      {report && (
        <>
          <div style={{
            marginTop: space.sm, padding: space.sm, background: colors.bg,
            borderRadius: radius.md, fontSize: typo.xs, color: colors.textSecondary,
          }}>
            Retention preview: keep {report.retention.keep_latest_per_task} per task
            {"  /  "}{report.retention.candidate_count} removable
            {report.retention.invalid_excluded > 0 &&
              `  /  ${report.retention.invalid_excluded} invalid excluded`}
          </div>
          {report.latest.length > 0 && (
            <div style={{ marginTop: space.sm, fontSize: typo.xs }}>
              {report.latest.slice(0, 5).map((checkpoint) => (
                <div key={checkpoint.checkpoint_id} style={{
                  padding: `${space.xs} 0`,
                  borderBottom: `1px solid ${colors.borderLight}`,
                }}>
                  <div style={{
                    color: colors.text, overflow: "hidden",
                    textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {checkpoint.task_id}
                  </div>
                  <div style={{ color: colors.textTertiary }}>
                    {checkpoint.kind || "checkpoint"}  /  {
                      new Date(checkpoint.timestamp).toLocaleString()
                    }
                  </div>
                </div>
              ))}
            </div>
          )}
          <div style={{ marginTop: space.sm, fontSize: typo.xs, color: colors.textTertiary }}>
            Cleanup requires a matching preview digest and governed API approval.
          </div>
        </>
      )}
    </Section>
  );
}


// Model Rankings


function ModelRankings() {
  const [rankings, setRankings] = useState<{ model_id: string; provider_id: string; sample_count: number; success_rate: number; avg_latency_ms: number; avg_cost_usd: number }[]>([]);

  useEffect(() => {
    fetchModelRankings().then((d) => {
      if (d?.rankings) setRankings(d.rankings);
    }).catch(() => {});
  }, []);

  if (rankings.length === 0) return null;

  return (
    <Section title="Model Rankings">
      <div style={{ fontSize: typo.xs }}>
        {rankings.slice(0, 8).map((r) => (
          <div key={r.model_id} style={{
            display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: `${space.xs} 0`,
            borderBottom: `1px solid ${colors.borderLight}`,
          }}>
            <span style={{ color: colors.text, fontWeight: typo.medium }}>
              {r.model_id}
            </span>
            <div style={{ display: "flex", gap: space.sm, color: colors.textTertiary }}>
              <span>{fixedNumber(Number(r.success_rate || 0) * 100, 0)}%</span>
              <span>{fixedNumber(r.avg_latency_ms, 0)}ms</span>
              <span>${fixedNumber(r.avg_cost_usd, 4)}</span>
              <span style={{ color: colors.textTertiary }}>{r.sample_count}×</span>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}


// Shared


function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div style={{ ...card, marginBottom: space.lg }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: space.sm,
      }}>
        <h3 style={{
          fontSize: typo.sm, fontWeight: typo.semibold, color: colors.textTertiary,
          textTransform: "uppercase", letterSpacing: "0.5px", margin: 0,
        }}>
          {title}
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      padding: space.sm,
      background: colors.bg,
      borderRadius: radius.md,
    }}>
      <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>{label}</div>
      <div style={{ fontSize: typo.md, fontWeight: typo.semibold, color: colors.text }}>
        {value}
      </div>
    </div>
  );
}


// Main Inspector


export function Inspector({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  if (!visible) return null;

  return (
    <>
      <div onClick={onClose} style={{
        position: "fixed", inset: 0, zIndex: 98,
      }} />
      <div style={{
        position: "fixed",
        bottom: 0, left: 240, right: 0,
        height: "60vh",
        background: colors.bg,
        borderTop: `1px solid ${colors.border}`,
        boxShadow: shadow.xl,
        zIndex: 99,
        display: "flex", flexDirection: "column",
        ...fadeIn,
      }}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: `${space.md} ${space.xl}`,
          background: colors.surface,
          borderBottom: `1px solid ${colors.borderLight}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
            <h2 style={{ fontSize: typo.md, fontWeight: typo.semibold, margin: 0, color: colors.text }}>
              Inspector
            </h2>
            <span style={{
              fontSize: typo.xs, color: colors.textTertiary,
              background: colors.accentSoft, padding: `1px ${space.sm}`, borderRadius: radius.full,
            }}>
              Runtime Internals
            </span>
          </div>
          <button onClick={onClose} style={{
            ...btnSecondary, width: 28, height: 28,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: typo.lg, padding: 0,
          }}>
            ×
          </button>
        </div>

        {/* Content — 3 columns */}
        <div style={{
          flex: 1, overflowY: "auto",
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: space.lg,
          padding: space.xl,
        }}>
          <div>
            <SystemStatus />
            <CheckpointHealth />
            <ModelRankings />
          </div>
          <div style={{ gridColumn: "span 2" }}>
            <LiveEventStream />
          </div>
        </div>
      </div>
    </>
  );
}
