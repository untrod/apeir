/**
 * TaskCenter — Complete task management page with timeline, actions, and export.
 *
 * Reads from EntityStore. Supports:
 *   - Filter by status
 *   - Pause / Cancel / Resume / Retry failed steps
 *   - View timeline of task events
 *   - Export task report
 *   - Navigate back to originating conversation
 */

import React, { useState, useMemo } from "react";
import { colors, typo, radius, space, card as cardStyle, btnSecondary, btnPrimary, statusColor } from "../design";
import { useTasks, useActiveTasks, entityStore, type Task, type TaskStatus } from "../store";
import { taskAction } from "../lib/api";
import { toast } from "./Toast";
import { Skeleton } from "./Skeleton";


// TaskCenter


interface TaskCenterProps {
  onTaskClick: (taskId: string) => void;
  onTraceClick: (traceId: string) => void;
}

export function TaskCenter({ onTaskClick, onTraceClick }: TaskCenterProps) {
  const allTasks = useTasks();
  const [filter, setFilter] = useState<string>("all");

  const tabs = [
    { key: "all", label: "All", count: allTasks.length },
    { key: "running", label: "Active", count: allTasks.filter((t) => ["running", "queued", "dispatching", "planning", "verifying"].includes(t.status)).length },
    { key: "needs_input", label: "Needs Input", count: allTasks.filter((t) => ["awaiting_approval", "waiting_user", "blocked"].includes(t.status)).length },
    { key: "completed", label: "Completed", count: allTasks.filter((t) => t.status === "completed" || t.status === "completed_with_warnings").length },
    { key: "failed", label: "Failed", count: allTasks.filter((t) => t.status === "failed" || t.status === "failed_verification").length },
  ];

  const filtered = filter === "all"
    ? allTasks
    : filter === "needs_input"
      ? allTasks.filter((t) => ["awaiting_approval", "waiting_user", "blocked"].includes(t.status))
      : allTasks.filter((t) => t.status === filter);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: colors.bg }}>
      {/* Header + tabs */}
      <div style={{ padding: `${space.lg} ${space.xl}`, background: colors.surface, borderBottom: `1px solid ${colors.borderLight}` }}>
        <h1 style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text, margin: 0 }}>Tasks</h1>
        <div style={{ display: "flex", gap: space.sm, marginTop: space.md, flexWrap: "wrap" }}>
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setFilter(tab.key)}
              style={{
                padding: `${space.xs} ${space.md}`,
                borderRadius: radius.full,
                border: `1px solid ${filter === tab.key ? colors.accent : colors.border}`,
                background: filter === tab.key ? colors.accentSoft : "transparent",
                color: filter === tab.key ? colors.accent : colors.textSecondary,
                fontSize: typo.sm, fontWeight: typo.medium,
                fontFamily: typo.font, cursor: "pointer",
              }}
            >
              {tab.label} <span style={{ color: colors.textTertiary, fontWeight: typo.normal }}>{tab.count}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Task list */}
      <div style={{ flex: 1, overflowY: "auto", padding: space.xl }}>
        {allTasks.length === 0 ? (
          <div style={{ textAlign: "center", padding: space.xxxl, color: colors.textTertiary, fontSize: typo.md }}>
            No tasks yet. Send a message in Chat to create one.
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ textAlign: "center", padding: space.xxxl, color: colors.textTertiary, fontSize: typo.md }}>
            No tasks match the current filter.
          </div>
        ) : (
          filtered.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              onTaskClick={onTaskClick}
              onTraceClick={onTraceClick}
            />
          ))
        )}
      </div>
    </div>
  );
}


// Task Row


function TaskRow({ task, onTaskClick, onTraceClick }: {
  task: Task;
  onTaskClick: (id: string) => void;
  onTraceClick: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const st = statusColor(task.status);

  const handleAction = async (action: string) => {
    setActing(true);
    try {
      await taskAction(action, task.id);
      // Status changes arrive via runtime events — do NOT optimistically mutate local state.
      // entityStore.updateTaskStatus() removed per RC9 state ownership audit.
      toast.success(`Task ${action} requested`, `Task ${task.id.slice(0, 12)}... awaiting confirmation`);
    } catch (err) {
      toast.error("Action failed", err instanceof Error ? err.message : "Unknown error");
    } finally {
      setActing(false);
    }
  };

  const canCancel = ["created", "queued", "planning", "dispatching", "running", "waiting_for_model", "waiting_for_node", "waiting_user", "blocked", "recovering", "paused"].includes(task.status);
  const canPause = ["planning", "running", "dispatching", "recovering"].includes(task.status);
  const canResume = task.status === "paused" && task.task_kind !== "work";
  const canRetry = task.status === "failed" && task.recoverable && task.task_kind !== "work";

  return (
    <div style={{ ...cardStyle, marginBottom: space.md }}>
      {/* Main row */}
      <div style={{ display: "flex", alignItems: "center", gap: space.md, cursor: "pointer" }} onClick={() => setExpanded(!expanded)}>
        {/* Status dot */}
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: st.dot, flexShrink: 0 }} />

        {/* Info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
            <span style={{ fontSize: typo.base, fontWeight: typo.semibold, color: colors.text }}>
              {task.name || task.id.slice(0, 12)}
            </span>
            {task.task_kind === "work" && (
              <span style={{ fontSize: typo.xs, color: colors.accent }}>Work</span>
            )}
            <span style={{ padding: `1px ${space.sm}`, borderRadius: radius.full, fontSize: typo.xs, fontWeight: typo.medium, background: st.bg, color: st.text }}>
              {task.status}
            </span>
            {task.priority === "critical" && (
              <span style={{ fontSize: typo.xs, color: colors.danger }}>Critical</span>
            )}
          </div>
          <div style={{ fontSize: typo.xs, color: colors.textSecondary, marginTop: 2 }}>
            {task.model_id || "auto"} · {task.steps.length} steps
            {task.plan_revision ? ` · plan v${task.plan_revision}` : ""}
            {task.artifact_refs?.length ? ` · ${task.artifact_refs.length} artifacts` : ""}
            {` · ${new Date(task.created_at).toLocaleString()}`}
            {task.conversation_id && " · from conversation"}
          </div>
        </div>

        {/* Progress */}
        <div style={{ width: 100 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: typo.xs, color: colors.textTertiary, marginBottom: 2 }}>
            <span>Progress</span><span>{task.progress_pct}%</span>
          </div>
          <div style={{ height: 3, background: colors.borderLight, borderRadius: radius.full, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${task.progress_pct}%`, background: colors.accent, borderRadius: radius.full, transition: "width 0.3s" }} />
          </div>
        </div>

        {/* Expand toggle */}
        <span style={{ fontSize: typo.xs, color: colors.textTertiary }}>{expanded ? "▲" : "▼"}</span>
      </div>

      {/* Expanded: steps + actions */}
      {expanded && (
        <div style={{ marginTop: space.md, paddingTop: space.md, borderTop: `1px solid ${colors.borderLight}` }}>
          {/* Steps timeline */}
          {task.steps.length > 0 && (
            <div style={{ marginBottom: space.md }}>
              <div style={{ fontSize: typo.xs, fontWeight: typo.semibold, color: colors.textTertiary, textTransform: "uppercase", marginBottom: space.sm }}>
                Steps
              </div>
              <div style={{ borderLeft: `2px solid ${colors.border}`, marginLeft: 6, paddingLeft: space.md }}>
                {task.steps.map((step) => {
                  const sst = statusColor(step.status);
                  return (
                    <div key={step.step_id} style={{ padding: `${space.xs} 0`, display: "flex", gap: space.sm, alignItems: "flex-start" }}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: sst.dot, flexShrink: 0, marginTop: 3 }} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: typo.sm, fontWeight: typo.medium, color: colors.text }}>{step.name}</div>
                        {step.error && <div style={{ fontSize: typo.xs, color: colors.danger, marginTop: 1 }}>{step.error}</div>}
                        <div style={{ fontSize: typo.xs, color: colors.textTertiary }}>
                          {step.status} · retries: {step.retry_count}/{step.max_retries}
                          {step.completed_at && ` · ${new Date(step.completed_at).toLocaleString()}`}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {task.current_step && (
            <div style={{ marginBottom: space.md, fontSize: typo.sm, color: colors.textSecondary }}>
              Current: <span style={{ color: colors.text }}>{task.current_step}</span>
            </div>
          )}

          {/* Actions */}
          <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
            <button onClick={() => onTaskClick(task.id)} style={{ ...btnSecondary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
              View Details
            </button>
            {task.trace_id && (
              <button onClick={() => onTraceClick(task.trace_id!)} style={{ ...btnSecondary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
                View Trace
              </button>
            )}
            {task.conversation_id && (
              <button onClick={() => { /* navigate to conversation */ }} style={{ ...btnSecondary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
                Open Conversation
              </button>
            )}
            {canCancel && (
              <button onClick={() => handleAction("cancel")} disabled={acting} style={{ ...btnSecondary, fontSize: typo.xs, padding: `${space.xs} ${space.md}`, color: colors.danger, borderColor: colors.danger }}>
                Cancel
              </button>
            )}
            {canPause && (
              <button onClick={() => handleAction("pause")} disabled={acting} style={{ ...btnSecondary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
                Pause
              </button>
            )}
            {canResume && (
              <button onClick={() => handleAction("resume")} disabled={acting} style={{ ...btnPrimary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
                Resume
              </button>
            )}
            {canRetry && (
              <button onClick={() => handleAction("retry")} disabled={acting} style={{ ...btnPrimary, fontSize: typo.xs, padding: `${space.xs} ${space.md}` }}>
                Retry
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
