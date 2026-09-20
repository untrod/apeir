/**
 * RuntimeCard — Unified card for Task, Approval, Artifact, Verification.
 *
 * Every card is driven by RuntimeEvent payloads, not mock data.
 * Variants: task, approval, artifact, verification, trace, node, model.
 */

import React, { useState } from "react";
import { colors, typo, radius, shadow, space, card, statusColor, slideUp } from "../design";
import type { RuntimeEventEnvelope, TaskView, TraceSpanView } from "../lib/api";


// Props


export interface PlanStage {
  name: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  description?: string;
  depends_on?: string[];
}

export interface RuntimeCardProps {
  /** Card variant determines the visual treatment */
  variant: "task" | "approval" | "artifact" | "verification" | "trace" | "node" | "model" | "event" | "plan";
  /** Runtime event that spawned this card */
  event?: RuntimeEventEnvelope;
  /** Optional task data (for task cards) */
  task?: TaskView;
  /** Optional trace span data */
  span?: TraceSpanView;
  /** Optional title override */
  title?: string;
  /** Optional status override */
  status?: string;
  /** Optional subtitle */
  subtitle?: string;
  /** Optional detail payload */
  detail?: Record<string, unknown>;
  /** Click handler */
  onClick?: () => void;
  /** Whether to show a progress bar */
  progress?: number; // 0-100
  /** Plan stages (for plan variant) */
  planStages?: PlanStage[];
  /** Child content for expanded cards */
  children?: React.ReactNode;
  /** Compact mode (inline in chat) */
  compact?: boolean;
}


// Variant configuration


const variantConfig: Record<string, { icon: string; label: string; color: string }> = {
  task: { icon: "T", label: "Task", color: colors.accent },
  approval: { icon: "A", label: "Approval", color: colors.warning },
  artifact: { icon: "F", label: "Artifact", color: colors.teal },
  verification: { icon: "V", label: "Verification", color: colors.purple },
  trace: { icon: "R", label: "Trace", color: colors.info },
  node: { icon: "N", label: "Node", color: colors.success },
  model: { icon: "M", label: "Model", color: colors.accent },
  event: { icon: "E", label: "Event", color: colors.textSecondary },
  plan: { icon: "P", label: "Plan", color: colors.warning },
};


// Sub-components


function CardHeader({
  variant, icon, label, color, title, status, subtitle, compact,
}: {
  variant: string; icon: string; label: string; color: string;
  title?: string; status?: string; subtitle?: string; compact?: boolean;
}) {
  const st = statusColor(status || "pending");

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: compact ? space.sm : space.md,
      marginBottom: compact ? space.xs : space.sm,
    }}>
      {/* Variant icon pill */}
      <div style={{
        width: compact ? 26 : 32, height: compact ? 26 : 32,
        borderRadius: radius.md,
        background: color + "18",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: compact ? typo.sm : typo.md,
        flexShrink: 0,
      }}>
        {icon}
      </div>

      {/* Title + subtitle */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: space.sm,
          flexWrap: "wrap",
        }}>
          <span style={{
            fontSize: compact ? typo.xs : typo.xs,
            fontWeight: typo.semibold,
            color: colors.textTertiary,
            textTransform: "uppercase",
            letterSpacing: "0.5px",
          }}>
            {label}
          </span>
          {status && (
            <span style={{
              padding: "1px 8px",
              borderRadius: radius.full,
              fontSize: typo.xs,
              fontWeight: typo.medium,
              background: st.bg,
              color: st.text,
            }}>
              {status}
            </span>
          )}
        </div>
        {title && (
          <div style={{
            fontSize: compact ? typo.sm : typo.base,
            fontWeight: typo.semibold,
            color: colors.text,
            marginTop: 2,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {title}
          </div>
        )}
        {subtitle && (
          <div style={{
            fontSize: typo.xs, color: colors.textSecondary, marginTop: 1,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {subtitle}
          </div>
        )}
      </div>

      {/* Status dot */}
      {status && (
        <div style={{
          width: 8, height: 8, borderRadius: "50%",
          background: st.dot, flexShrink: 0,
        }} />
      )}
    </div>
  );
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div style={{
      marginTop: space.sm,
      height: 3,
      background: colors.borderLight,
      borderRadius: radius.full,
      overflow: "hidden",
    }}>
      <div style={{
        height: "100%",
        width: `${Math.min(100, Math.max(0, value))}%`,
        background: colors.accent,
        borderRadius: radius.full,
        transition: "width 0.4s ease-out",
      }} />
    </div>
  );
}


// Plan Stages


const stageStatusConfig: Record<string, { bg: string; text: string; dot: string; icon: string }> = {
  completed: { bg: colors.successSoft, text: colors.success, dot: colors.success, icon: "✓" },
  running:   { bg: colors.accentSoft,  text: colors.accent,  dot: colors.accent,  icon: "◎" },
  pending:   { bg: colors.borderLight, text: colors.textTertiary, dot: colors.textTertiary, icon: "○" },
  failed:    { bg: colors.dangerSoft,  text: colors.danger,  dot: colors.danger,  icon: "X" },
  skipped:   { bg: colors.borderLight, text: colors.textTertiary, dot: colors.textTertiary, icon: "—" },
};

function PlanStages({ stages, compact }: { stages: PlanStage[]; compact?: boolean }) {
  if (!stages || stages.length === 0) return null;

  const completedCount = stages.filter((s) => s.status === "completed").length;
  const progressPct = stages.length > 0 ? Math.round((completedCount / stages.length) * 100) : 0;

  return (
    <div style={{ marginTop: space.sm }}>
      {/* Overall progress bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: space.sm, marginBottom: space.sm,
      }}>
        <div style={{
          flex: 1, height: 4, background: colors.borderLight,
          borderRadius: radius.full, overflow: "hidden",
        }}>
          <div style={{
            height: "100%", width: `${progressPct}%`,
            background: colors.accent,
            borderRadius: radius.full,
            transition: "width 0.4s ease-out",
          }} />
        </div>
        <span style={{ fontSize: typo.xs, color: colors.textTertiary, whiteSpace: "nowrap" }}>
          {completedCount}/{stages.length}
        </span>
      </div>

      {/* Stage list */}
      <div style={{
        borderLeft: `2px solid ${colors.border}`,
        marginLeft: 6, paddingLeft: space.md,
      }}>
        {stages.slice(0, compact ? 4 : stages.length).map((stage, i) => {
          const sc = stageStatusConfig[stage.status] || stageStatusConfig.pending;
          return (
            <div key={i} style={{
              display: "flex", alignItems: "flex-start", gap: space.sm,
              padding: `${space.xs} 0`,
              position: "relative",
            }}>
              {/* Status dot on the timeline */}
              <div style={{
                width: 12, height: 12, borderRadius: "50%",
                background: sc.dot,
                border: `2px solid ${sc.dot}`,
                flexShrink: 0,
                marginTop: 2,
                marginLeft: -6 - 6, // align with border left
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 8, color: colors.textInverse, fontWeight: typo.bold,
              }}>
                {stage.status === "completed" ? "✓" : stage.status === "running" ? "" : ""}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: typo.sm, fontWeight: typo.medium, color: colors.text,
                }}>
                  {stage.name}
                </div>
                {stage.description && (
                  <div style={{ fontSize: typo.xs, color: colors.textSecondary, marginTop: 1 }}>
                    {stage.description}
                  </div>
                )}
                {stage.depends_on && stage.depends_on.length > 0 && (
                  <div style={{ fontSize: typo.xs, color: colors.textTertiary, marginTop: 1 }}>
                    depends on: {stage.depends_on.join(", ")}
                  </div>
                )}
              </div>
              <span style={{
                fontSize: typo.xs,
                padding: `1px ${space.sm}`,
                borderRadius: radius.full,
                background: sc.bg,
                color: sc.text,
                flexShrink: 0,
              }}>
                {stage.status}
              </span>
            </div>
          );
        })}
        {compact && stages.length > 4 && (
          <div style={{ fontSize: typo.xs, color: colors.textTertiary, padding: `${space.xs} 0` }}>
            +{stages.length - 4} more stages
          </div>
        )}
      </div>
    </div>
  );
}


// Main Component


export function RuntimeCard({
  variant, event, task, span, title, status, subtitle, detail,
  onClick, progress, planStages, children, compact,
}: RuntimeCardProps) {
  const [expanded, setExpanded] = useState(false);
  const vc = variantConfig[variant] || variantConfig.event;
  const derivedStatus = status || task?.status || span?.status || "";
  const derivedTitle = title || task?.task_id || span?.span_name || event?.event_type || "";
  const derivedSubtitle = subtitle || (
    event
      ? `${event.source} · ${new Date(event.timestamp).toLocaleTimeString()}`
      : ""
  );

  const containerStyle: React.CSSProperties = {
    ...card,
    padding: compact ? space.md : space.lg,
    marginBottom: compact ? space.sm : space.md,
    cursor: onClick || children ? "pointer" : "default",
    transition: "box-shadow 0.15s, transform 0.1s",
    ...(onClick || children ? {} : {}),
    ...slideUp,
  };

  return (
    <div
      style={containerStyle}
      onClick={() => {
        if (children) setExpanded(!expanded);
        if (onClick) onClick();
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = shadow.md;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = shadow.card;
      }}
    >
      <CardHeader
        variant={variant}
        icon={vc.icon}
        label={vc.label}
        color={vc.color}
        title={derivedTitle}
        status={derivedStatus}
        subtitle={derivedSubtitle}
        compact={compact}
      />

      {progress !== undefined && <ProgressBar value={progress} />}

      {/* Plan stages */}
      {variant === "plan" && planStages && <PlanStages stages={planStages} compact={compact} />}

      {/* Detail fields */}
      {detail && Object.keys(detail).length > 0 && (
        <div style={{
          marginTop: space.sm,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))",
          gap: space.sm,
        }}>
          {Object.entries(detail).slice(0, compact ? 2 : 6).map(([key, val]) => (
            <div key={key}>
              <div style={{ fontSize: typo.xs, color: colors.textTertiary, textTransform: "uppercase" }}>
                {key.replace(/_/g, " ")}
              </div>
              <div style={{ fontSize: typo.sm, color: colors.text, fontWeight: typo.medium }}>
                {typeof val === "object" ? JSON.stringify(val).slice(0, 40) : String(val).slice(0, 40)}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Expanded content */}
      {expanded && children && (
        <div style={{
          marginTop: space.md,
          paddingTop: space.md,
          borderTop: `1px solid ${colors.borderLight}`,
          ...slideUp,
        }}>
          {children}
        </div>
      )}

      {/* Expand indicator */}
      {children && (
        <div style={{
          textAlign: "center", marginTop: space.xs,
          fontSize: typo.xs, color: colors.textTertiary,
        }}>
          {expanded ? "▲" : "▼"}
        </div>
      )}
    </div>
  );
}


// Convenience constructors


export function TaskCard(props: Omit<RuntimeCardProps, "variant">) {
  return <RuntimeCard variant="task" {...props} />;
}

export function ApprovalCard(props: Omit<RuntimeCardProps, "variant">) {
  return <RuntimeCard variant="approval" {...props} />;
}

export function ArtifactCard(props: Omit<RuntimeCardProps, "variant">) {
  return <RuntimeCard variant="artifact" {...props} />;
}

export function VerificationCard(props: Omit<RuntimeCardProps, "variant">) {
  return <RuntimeCard variant="verification" {...props} />;
}

export function PlanCard(props: Omit<RuntimeCardProps, "variant">) {
  return <RuntimeCard variant="plan" {...props} />;
}
