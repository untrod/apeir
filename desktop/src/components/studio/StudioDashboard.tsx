import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { GridLayout, useContainerWidth, type Layout } from "react-grid-layout";
import { noOverlapCompactor } from "react-grid-layout/core";
import { defaultDashboard, validateDashboard, WIDGET_TYPES, type DashboardWidget } from "../../lib/studioDashboard";
import { captureStudioLayout, parseStudioLayout, MAX_LAYOUT_BYTES, type StudioLayout } from "../../lib/studioLayout";
import { createStudioLayout } from "../../lib/studioLayout";
import { useStudioSnapshot } from "./StudioData";
import { useCostSummary } from "../../store/hooks";
import { eventClient } from "../../store/eventClient";
import { UsageAccounting } from "../UsageAccounting";
import type { PanelProps } from "./StudioPanels";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import "./StudioDashboard.css";

const titles: Record<string, [string, string]> = {
  runtime: ["Runtime Status", "运行时状态"], kernel: ["Kernel Status", "内核状态"], nodes: ["Node Status", "节点状态"], devices: ["Device Status", "设备状态"], resources: ["Node CPU / RAM", "节点 CPU / 内存"], usage: ["Model Usage", "模型用量"], works: ["Work Timeline", "任务时间线"], evidence: ["Evidence Metadata", "证据元数据"], activity: ["Governance Audit", "治理审计"], diagnostics: ["Error Diagnostics", "错误诊断"], events: ["EventStream", "事件流"], gpu: ["GPU Metrics", "GPU 指标"], network: ["Network Throughput", "网络吞吐"], sensors: ["Device Sensors", "设备传感器"],
};
const text = (value: unknown) => value === undefined || value === null || value === "" ? "UNKNOWN" : String(value);
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
function UsageWidget({ active }: { active: () => boolean }) {
  const value = useCostSummary(active);
  return value.status === "ready" && value.summary ? <UsageAccounting summary={value.summary} compact /> : <p role="status">{value.status === "loading" ? "LOADING" : "UNKNOWN"} · Usage / cost · {value.error}</p>;
}
function EventWidget({ active }: { active: () => boolean }) {
  const snapshot = useSyncExternalStore(useCallback(listener => eventClient.subscribe(() => { if (active()) listener(); }), [active]), eventClient.getSnapshot);
  useEffect(() => eventClient.acquirePresentationReader(), []);
  return <><p>{snapshot.status.toUpperCase()} · RuntimeEventBus · recent 200, memory only</p>{!snapshot.events.length && <p>No events reported / 暂无事件</p>}{snapshot.events.slice(-40).reverse().map(event => <div key={event.event_id}><time>{event.timestamp}</time> · {event.event_type}<small>{event.event_id}</small></div>)}</>;
}
function ResourceRow({ row }: { row: Record<string, unknown> }) {
  const available = row.connected === true && row.trust_status === "TRUSTED" && row.resource_report_current === true && row.resource_report_fresh === true;
  const resources = available ? record(row.resources) : {};
  const number = (key: string, suffix: string) => typeof resources[key] === "number" && Number.isFinite(resources[key]) ? `${resources[key]} ${suffix}` : "UNKNOWN";
  return <p><strong>{text(row.node_name || row.node_id)}</strong> · {available ? "CURRENT REPORT" : "UNKNOWN · stale, offline or unavailable"}<br />CPU capacity: {number("cpu_logical", "logical")}<br />RAM available / total: {number("memory_available_bytes", "bytes")} / {number("memory_total_bytes", "bytes")}<small>CPU utilization: UNSUPPORTED · Report observed: {text(row.resource_observed_at)}</small></p>;
}
function DataWidget({ type, active, inspect, open }: { type: string; active: () => boolean; inspect: PanelProps["inspect"]; open: PanelProps["open"] }) {
  const { data, loading, error, health } = useStudioSnapshot();
  if (type === "usage") return <UsageWidget active={active} />;
  if (type === "events") return <EventWidget active={active} />;
  if (["gpu", "network", "sensors"].includes(type)) return <p role="status">UNSUPPORTED · No qualified Runtime metric source / 暂无已验收的数据源</p>;
  if (!WIDGET_TYPES.includes(type as typeof WIDGET_TYPES[number])) return <p role="status">Missing Component · {type}. No extension code was loaded.</p>;
  if (["runtime", "kernel"].includes(type)) {
    if (health.loading) return <p role="status">LOADING · Detailed health</p>;
    if (health.error || !health.data) return <p role="status">UNAVAILABLE · {health.error || "No health reported"}</p>;
    const kernel = health.data.kernel;
    return <><p>{type === "runtime" ? health.data.running === true ? "ONLINE · Runtime API" : "UNKNOWN · Runtime" : kernel?.configured === false ? "UNCONFIGURED · Kernel" : kernel?.ready === true ? "READY · Kernel" : `BLOCKED · Kernel · ${text(kernel?.state)}`}</p><p>{text(health.data.platform)} · {text(health.data.architecture)}</p><button onClick={() => open("diagnostics")}>Details / 详情</button><small>API online does not prove model or effect verification.</small></>;
  }
  if (loading) return <p role="status">LOADING · Runtime projection</p>;
  if (error || !data) return <p role="status">UNAVAILABLE · {error || "No records reported"}</p>;
  const collection = type === "resources" ? "nodes" : type === "diagnostics" ? "incidents" : type;
  const rows = (data[collection as keyof typeof data]);
  if (!Array.isArray(rows)) return <p role="status">UNKNOWN · No supported source reported.</p>;
  if (!rows.length) return <p role="status">No records reported / 暂无记录</p>;
  return <>{rows.slice(0, 40).map((row, i) => <div key={String(row.node_id ?? row.device_id ?? row.work_id ?? row.sequence ?? i)} className="studio-widget-row">
    {type === "resources" ? <ResourceRow row={row} /> : <><strong>{text(row.node_name ?? row.node_id ?? row.device_id ?? row.work_id ?? row.event_type ?? row.action ?? row.incident_id ?? `Record ${i + 1}`)}</strong><p>{text(row.connectivity_state ?? row.state ?? row.status ?? row.verdict ?? row.event_type)}</p>
      {type === "nodes" && <><small>Trust: {text(row.trust_status)} · Connection: {row.connected === true ? "CONNECTED" : "OFFLINE"}</small><button onClick={() => typeof row.node_id === "string" && inspect({ kind: "node", nodeId: row.node_id })}>Inspect node / 检查节点</button></>}
      {type !== "nodes" && <button onClick={() => open(type === "diagnostics" ? "operations" : type === "works" ? "tasks" : type)}>Details / 详情</button>}
    </>}
  </div>)}{type === "evidence" && <small>Receipt ≠ Observation. Metadata is not independent artifact-byte or physical verification.</small>}{type === "activity" && <small>GovernanceStore audit, not RuntimeEventBus.</small>}</>;
}
function Widget({ widget, isVisible, inspect, open }: { widget: DashboardWidget; isVisible: () => boolean; inspect: PanelProps["inspect"]; open: PanelProps["open"] }) {
  const { subscribeLive } = useStudioSnapshot();
  const active = useCallback(() => !widget.paused && isVisible() && document.visibilityState !== "hidden", [widget.paused, isVisible]);
  useEffect(() => {
    if (["usage", "events", "gpu", "network", "sensors"].includes(widget.type)) return;
    return subscribeLive(active, [widget.type === "kernel" || widget.type === "runtime" ? "health" : "operations"]);
  }, [active, subscribeLive, widget.type]);
  return widget.paused ? <p role="status">PAUSED · Display subscription stopped / 显示订阅已暂停</p> : <DataWidget type={widget.type} active={active} inspect={inspect} open={open} />;
}
function download(value: StudioLayout) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "apeir-dashboard.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function StudioDashboard({ config, updateConfig, isVisible, locale, inspect, open, saveLayout }: PanelProps) {
  const dashboard = config === undefined ? defaultDashboard() : validateDashboard(config);
  const { width, mounted, containerRef } = useContainerWidth();
  const { refresh } = useStudioSnapshot();
  const [type, setType] = useState("nodes"), [selected, setSelected] = useState<string | null>(null), [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const title = (widget: DashboardWidget) => widget.title || titles[widget.type]?.[locale === "zh" ? 1 : 0] || widget.type;
  const change = (widgets: DashboardWidget[]) => { try { updateConfig(validateDashboard({ schemaVersion: 1, widgets })); setMessage(""); } catch (error) { setMessage(String(error)); } };
  const add = (source?: DashboardWidget) => {
    if (dashboard.widgets.length >= 32) { setMessage("Widget limit reached (32)."); return; }
    const y = Math.max(0, ...dashboard.widgets.map(widget => widget.y + widget.h));
    change([...dashboard.widgets, { ...(source || { type, title: "", x: 0, y, w: 4, h: 6, paused: false }), id: `widget-${crypto.randomUUID()}`, y }]);
  };
  const positions = (layout: Layout) => {
    const widgets = dashboard.widgets.map(widget => { const item = layout.find(item => item.i === widget.id); return item ? { ...widget, x: item.x, y: item.y, w: item.w, h: item.h } : widget; });
    if (JSON.stringify(widgets) !== JSON.stringify(dashboard.widgets)) change(widgets);
  };
  const settings = dashboard.widgets.find(widget => widget.id === selected);
  const update = (fields: Partial<DashboardWidget>) => change(dashboard.widgets.map(widget => widget.id === selected ? { ...widget, ...fields } : widget));
  const exportLayout = () => {
    const base = createStudioLayout("blank", locale); base.kind = "dashboard"; base.name = "Dashboard";
    base.layout.children = [{ type: "tabset", id: "dashboard-group", children: [{ type: "tab", id: "dashboard-panel", component: "dashboard", name: "Dashboard", config: dashboard }] }];
    download(captureStudioLayout({ layout: base.layout }, base));
  };
  return <section className="studio-dashboard" aria-label="Dashboard builder">
    <header className="studio-dashboard-toolbar"><label>{t("Widget", "组件")}<select aria-label="Widget type" value={type} onChange={event => setType(event.target.value)}>{WIDGET_TYPES.map(type => <option key={type} value={type}>{titles[type][locale === "zh" ? 1 : 0]}</option>)}</select></label><button onClick={() => add()}>{t("Add widget", "添加组件")}</button><button onClick={saveLayout}>{t("Save dashboard", "保存仪表盘")}</button><button onClick={exportLayout}>{t("Export dashboard", "导出仪表盘")}</button><button onClick={() => input.current?.click()}>{t("Import dashboard", "导入仪表盘")}</button><button onClick={() => change(defaultDashboard().widgets)}>{t("Reset dashboard", "重置仪表盘")}</button><button onClick={() => refresh()}>{t("Refresh data", "刷新数据")}</button></header>
    <p className="studio-note">{t("Read-only Runtime data. Drag headers or resize corners; Settings also supports keyboard position and size. Save uses the Studio layout; import does not execute Work.", "只读 Runtime 数据。拖动标题或调整角落；也可用设置键盘调整位置与尺寸。保存使用 Studio 布局，导入不执行任务。")}</p>
    {message && <p role="alert">{message}</p>}
    <input hidden ref={input} type="file" aria-label="Import dashboard" accept="application/json,.json" onChange={async event => {
      const file = event.target.files?.[0]; event.target.value = ""; if (!file) return;
      try {
        if (file.size > MAX_LAYOUT_BYTES) throw new Error("Layout exceeds 96 KiB.");
        const layout = parseStudioLayout(await file.text());
        if (layout.kind !== "dashboard") throw new Error("Select an exported Dashboard layout.");
        const panels: Record<string, unknown>[] = [];
        const visit = (node: unknown) => { const row = record(node); if (row.type === "tab") panels.push(row); if (Array.isArray(row.children)) row.children.forEach(visit); }; visit(layout.layout);
        if (panels.length !== 1 || panels[0].component !== "dashboard") throw new Error("Dashboard import must contain exactly one Dashboard panel.");
        updateConfig(validateDashboard(panels[0].config)); setSelected(null); setMessage("Dashboard imported. No Runtime operation was executed.");
      } catch (error) { setMessage(String(error)); }
    }} />
    {settings && <form className="studio-widget-settings" aria-label="Widget settings" onSubmit={event => event.preventDefault()}><strong>{t("Widget settings", "组件设置")} · {settings.type}</strong><label>{t("Title", "标题")}<input aria-label="Widget title" maxLength={64} value={settings.title} onChange={event => update({ title: event.target.value })} /></label>{(["x", "y", "w", "h"] as const).map(key => <label key={key}>{key}<input aria-label={`Widget ${key}`} type="number" value={settings[key]} onChange={event => update({ [key]: Number(event.target.value) })} /></label>)}<label><input type="checkbox" checked={settings.paused} onChange={event => update({ paused: event.target.checked })} />{t("Pause display", "暂停显示")}</label><button onClick={() => setSelected(null)}>{t("Close settings", "关闭设置")}</button></form>}
    <div className="studio-dashboard-grid" ref={containerRef as React.RefObject<HTMLDivElement>}>{mounted && <GridLayout width={width} gridConfig={{ cols: 12, rowHeight: 40, margin: [8, 8], maxRows: 200 }} compactor={noOverlapCompactor} dragConfig={{ handle: ".studio-widget-grip", allowMobileScroll: true }} layout={dashboard.widgets.map(widget => ({ i: widget.id, x: widget.x, y: widget.y, w: widget.w, h: widget.h, minW: 2, minH: 2, maxH: 30 }))} onLayoutChange={positions}>
      {dashboard.widgets.map(widget => <div key={widget.id} className="studio-widget" data-widget-id={widget.id}><header><button className="studio-widget-grip" aria-label={`Move ${title(widget)}`}>{title(widget)}</button><button aria-label={`Settings ${title(widget)}`} onClick={() => setSelected(widget.id)}>⚙</button><button aria-label={`Duplicate ${title(widget)}`} onClick={() => add(widget)}>⧉</button><button aria-label={`Remove ${title(widget)}`} onClick={() => { change(dashboard.widgets.filter(item => item.id !== widget.id)); if (selected === widget.id) setSelected(null); }}>×</button></header><div className="studio-widget-body"><Widget widget={widget} isVisible={isVisible} inspect={inspect} open={open} /></div></div>)}
    </GridLayout>}</div>
  </section>;
}
