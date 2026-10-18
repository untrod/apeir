import React, { useState } from "react";
import { colors, typo, shadow, space } from "../design";
import { usageNumber } from "../lib/usageAccounting";
import { useOnlineNodes, useModels, usePendingApprovals, useCostSummary } from "../store";
import { useEffect } from "react";
import { fetchStatus, getConfig, getRuntimeConfigVersion, type RuntimeStatus } from "../lib/api";
import { useRuntimeConfigVersion } from "../store";
import { UsageAccounting } from "./UsageAccounting";

export function StatusBar({ onSearch }: { onSearch?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const onlineNodes = useOnlineNodes();
  const models = useModels();
  const pendingApprovals = usePendingApprovals();
  const cost = useCostSummary();
  const configurationVersion = useRuntimeConfigVersion();

  const enabledModels = models.filter((model) => model.state === "enabled");
  const healthyModels = enabledModels.filter((model) => model.health === "healthy");

  useEffect(() => {
    let active = true;
    const controller = getConfig().url;
    setRuntimeStatus(null);
    const refresh = () => void fetchStatus()
      .then((status) => { if (active && getRuntimeConfigVersion() === configurationVersion && getConfig().url === controller) setRuntimeStatus(status); })
      .catch(() => { if (active && getRuntimeConfigVersion() === configurationVersion) setRuntimeStatus(null); });
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [configurationVersion]);

  const kernel = runtimeStatus?.kernel;

  const indicators = [
    { label: "Runtime API", value: runtimeStatus?.running ? "Online" : "Offline", ok: !!runtimeStatus?.running },
    { label: "Rust Kernel", value: kernel?.ready ? "Ready" : kernel?.configured ? kernel.state : "Not configured", ok: !!kernel?.ready },
    { label: "Nodes", value: String(onlineNodes.length), ok: onlineNodes.length > 0 },
    { label: "Models", value: String(enabledModels.length), ok: healthyModels.length > 0 },
    { label: "Tasks", value: pendingApprovals.length > 0 ? `${pendingApprovals.length} approvals` : "Ready", ok: pendingApprovals.length === 0, warn: pendingApprovals.length > 0 },
  ];

  return (
    <>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          height: 44,
          background: colors.surface,
          borderBottom: `1px solid ${colors.borderLight}`,
          display: "flex",
          alignItems: "center",
          padding: `0 ${space.xl}`,
          gap: space.xl,
          fontSize: typo.xs,
          color: colors.textTertiary,
          cursor: "pointer",
          userSelect: "none",
          flexShrink: 0,
        }}
      >
        {indicators.map((indicator) => (
          <div key={indicator.label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span
              style={{
                width: 7,
                height: 7,
                borderRadius: "50%",
                background: indicator.warn ? colors.warning : indicator.ok ? colors.success : colors.danger,
              }}
            />
            <span style={{ color: colors.textSecondary }}>{indicator.label}</span>
            {indicator.value && <span style={{ color: indicator.warn ? colors.warning : colors.text }}>{indicator.value}</span>}
          </div>
        ))}
        <div style={{ flex: 1 }} />
        <button
          type="button"
          aria-label="Search APEIR"
          onClick={(event) => {
            event.stopPropagation();
            onSearch?.();
          }}
          style={{
            minWidth: 220,
            height: 30,
            borderRadius: 15,
            background: colors.bg,
            border: `1px solid ${colors.borderLight}`,
            display: "flex",
            alignItems: "center",
            padding: `0 ${space.md}`,
            color: colors.textTertiary,
            fontFamily: typo.font,
            cursor: "text",
          }}
        >
          Search (Ctrl K)
        </button>
        <span style={{ fontSize: typo.sm, color: colors.textSecondary }}>N</span>
      </div>

      {expanded && (
        <>
          <div onClick={() => setExpanded(false)} style={{ position: "fixed", inset: 0, zIndex: 99 }} />
          <div
            style={{
              position: "fixed",
              top: 44,
              left: 0,
              right: 0,
              zIndex: 100,
              background: colors.surface,
              borderBottom: `1px solid ${colors.border}`,
              boxShadow: shadow.lg,
              padding: space.lg,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: space.lg,
              fontSize: typo.sm,
            }}
          >
            <StatusGroup title="Nodes">
              {onlineNodes.length === 0 ? (
                <span style={{ color: colors.textTertiary }}>No nodes online</span>
              ) : (
                onlineNodes.slice(0, 5).map((node) => (
                  <div key={node.id} style={{ color: colors.textSecondary, padding: "2px 0" }}>
                    <span style={{ color: colors.success }}>●</span> {node.name} · {node.platform}
                  </div>
                ))
              )}
            </StatusGroup>
            <StatusGroup title="Models">
              {enabledModels.slice(0, 5).map((model) => (
                <div key={model.id} style={{ color: colors.textSecondary, padding: "2px 0", fontSize: typo.xs }}>
                  <span style={{ color: model.health === "healthy" ? colors.success : colors.warning }}>●</span>{" "}
                  {model.display_name} · {usageNumber(model.avg_latency_ms) === "UNKNOWN" ? "UNKNOWN" : `${usageNumber(model.avg_latency_ms)}ms`}
                </div>
              ))}
            </StatusGroup>
            <StatusGroup title="Approvals">
              {pendingApprovals.length === 0 ? (
                <span style={{ color: colors.textTertiary }}>No pending approvals</span>
              ) : (
                pendingApprovals.slice(0, 5).map((approval) => (
                  <div key={approval.id} style={{ color: colors.warning, padding: "2px 0" }}>
                    {approval.capability_id} · {approval.risk_level} risk
                  </div>
                ))
              )}
            </StatusGroup>
            <StatusGroup title="Cost Today">
              {cost.status === "ready" && cost.summary ? <UsageAccounting summary={cost.summary} compact />
                : <div role={cost.status === "unavailable" ? "alert" : "status"}>
                  {cost.status === "unavailable" ? cost.error : "Loading usage accounting… Spend UNKNOWN."}
                </div>}
            </StatusGroup>
          </div>
        </>
      )}
    </>
  );
}

function StatusGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontWeight: typo.semibold, color: colors.text, marginBottom: space.sm }}>{title}</div>
      {children}
    </div>
  );
}
