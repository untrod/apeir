import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { GridLayout, useContainerWidth, type Layout } from "react-grid-layout";
import { noOverlapCompactor } from "react-grid-layout/core";
import { compactDashboard, defaultDashboard, validateDashboard, WIDGET_TYPES, type DashboardWidget } from "../../lib/studioDashboard";
import { captureStudioLayout, parseStudioLayout, MAX_LAYOUT_BYTES, type StudioLayout } from "../../lib/studioLayout";
import { createStudioLayout } from "../../lib/studioLayout";
import { useStudioSnapshot } from "./StudioData";
import { useCostSummary } from "../../store/hooks";
import { eventClient } from "../../store/eventClient";
import { usageNumber, usageTotal } from "../../lib/usageAccounting";
import { StudioIcon } from "./StudioIcon";
import { useStudioPresentation } from "./StudioPresentation";
import { UsageAccounting } from "../UsageAccounting";
import type { PanelProps } from "./StudioPanels";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import "./StudioDashboard.css";

const titles: Record<string, [string, string]> = {
  topology: ["Device Topology", "设备拓扑"], runtime: ["Runtime", "运行时"], kernel: ["Kernel", "内核"], nodes: ["Nodes", "节点"], devices: ["Device Status", "设备状态"], resources: ["Node CPU / RAM", "节点 CPU / 内存"], usage: ["Model Usage", "模型用量"], works: ["Work Timeline", "任务时间线"], evidence: ["Evidence", "证据"], activity: ["Governance Audit", "治理审计"], diagnostics: ["Error Diagnostics", "错误诊断"], events: ["EventStream", "事件流"], gpu: ["GPU Metrics", "GPU 指标"], network: ["Network Throughput", "网络吞吐"], sensors: ["Device Sensors", "设备传感器"],
};
const text = (value: unknown) => value === undefined || value === null || value === "" ? "UNKNOWN" : String(value);
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
type Locale = "en" | "zh";
const translate = (locale: Locale) => (en: string, zh: string) => locale === "zh" ? zh : en;
function Status({ state }: { state: string }) {
  const tone = ["READY", "ONLINE", "CONNECTED", "MATCH", "VERIFIED"].includes(state) ? "success" : ["ERROR", "FAILED", "MISMATCH", "REVOKED"].includes(state) ? "danger" : ["BLOCKED", "UNCONFIGURED", "WAITING_APPROVAL"].includes(state) ? "warning" : state === "RUNNING" ? "info" : "neutral";
  return <span className={`studio-status studio-status-${tone}`} data-state={state}><span aria-hidden="true" />{state}</span>;
}
function Empty({ children, state = "UNKNOWN" }: { children: React.ReactNode; state?: string }) {
  return <div className="studio-empty" role="status"><Status state={state} /><span>{children}</span></div>;
}
function UsageWidget({ active, locale }: { active: () => boolean; locale: Locale }) {
  const value = useCostSummary(active), t = translate(locale);
  if (value.status !== "ready" || !value.summary) return <Empty state={value.status === "loading" ? "LOADING" : "UNKNOWN"}>{value.error || t("Usage unavailable", "暂无用量数据")}</Empty>;
  const summary = value.summary, empty = summary.requests === 0 && summary.pending_requests === 0;
  return <><div className="studio-metric-value">{empty ? "—" : usageTotal(summary)}</div><div className="studio-metric-caption">{empty ? t("No model requests yet", "尚无模型请求") : t("Accounted cost · USD", "已记账费用 · USD")}</div>
    <dl className="studio-metric-pairs studio-usage-pairs"><div><dt>{t("Requests", "请求")}</dt><dd>{usageNumber(summary.requests)}</dd></div><div><dt>Token</dt><dd>{empty ? "UNKNOWN" : usageNumber(summary.total_tokens)}</dd></div><div><dt>{t("Pending", "待核算")}</dt><dd>{usageNumber(summary.pending_requests)}</dd></div><div><dt>{t("Unknown cost", "费用未知")}</dt><dd>{usageNumber(summary.unknown_cost_requests)}</dd></div></dl>
    <details className="studio-card-details"><summary>{t("Usage details", "用量详情")}</summary><UsageAccounting summary={summary} /></details></>;
}
function EventWidget({ active, locale }: { active: () => boolean; locale: Locale }) {
  const t = translate(locale);
  const snapshot = useSyncExternalStore(useCallback(listener => eventClient.subscribe(() => { if (active()) listener(); }), [active]), eventClient.getSnapshot);
  useEffect(() => eventClient.acquirePresentationReader(), []);
  return <><Status state={snapshot.status.toUpperCase()} />{!snapshot.events.length && <Empty>{t("No events yet", "暂无事件")}</Empty>}{snapshot.events.slice(-40).reverse().map(event => <div className="studio-widget-row" key={event.event_id}><strong>{event.event_type}</strong><small><time>{event.timestamp}</time></small><details className="studio-card-details"><summary>{t("Event ID", "事件 ID")}</summary>{event.event_id}</details></div>)}</>;
}
export function ResourceRow({ row, locale }: { row: Record<string, unknown>; locale: Locale }) {
  const t = translate(locale);
  const available = row.connected === true && row.trust_status === "TRUSTED" && row.resource_report_current === true && row.resource_report_fresh === true;
  const resources = available ? record(row.resources) : {};
  const total = resources.memory_total_bytes, free = resources.memory_available_bytes;
  const valid = typeof total === "number" && Number.isFinite(total) && total > 0 && typeof free === "number" && Number.isFinite(free) && free >= 0 && free <= total;
  const cpu = resources.cpu_logical;
  const used = valid ? Math.round((total - free) / total * 100) : null;
  return <div className="studio-resource"><div className="studio-row-heading"><strong>{text(row.node_name || row.node_id)}</strong><Status state={available ? "CURRENT" : "UNKNOWN"} /></div>
    <dl className="studio-metric-pairs"><div><dt>{t("CPU capacity", "CPU 容量")}</dt><dd>{typeof cpu === "number" && Number.isSafeInteger(cpu) && cpu > 0 ? `${cpu} ${t("logical", "逻辑核")}` : "UNKNOWN"}</dd></div><div><dt>{t("Memory used", "内存已用")}</dt><dd>{used === null ? "UNKNOWN" : `${used}%`}</dd></div></dl>
    {valid && <><meter className="studio-meter" aria-label={t("Memory used", "内存已用")} min={0} max={total} value={total - free} /><small>{((total - free) / 1073741824).toFixed(1)} / {(total / 1073741824).toFixed(1)} GiB</small></>}
    <details className="studio-card-details"><summary>{t("Report details", "报告详情")}</summary><p>{t("Observed", "观测时间")}: {text(row.resource_observed_at)}</p><p>{t("CPU utilization", "CPU 使用率")}: UNSUPPORTED</p>{!available && <p>{t("Current trusted resource report required", "需要当前可信资源报告")}</p>}</details></div>;
}
export function DeviceTopology({ nodes, devices, locale }: { nodes: Record<string, unknown>[]; devices: Record<string, unknown>[]; locale: Locale }) {
  const t = translate(locale);
  const known = new Set(nodes.map(node => node.node_id).filter(id => typeof id === "string" && id));
  const unbound = devices.filter(device => !known.has(device.node_id));
  const item = (device: Record<string, unknown>, i: number) => <li key={String(device.device_id ?? i)}><span className="studio-topology-symbol" aria-hidden="true">◇</span><span>{text(device.name || device.device_id)}</span><Status state={text(device.lifecycle)} /></li>;
  if (!nodes.length && !devices.length) return <Empty>{t("No nodes or devices", "暂无节点或设备")}</Empty>;
  return <div className="studio-topology" aria-label={t("Device topology", "设备拓扑")}>{nodes.slice(0, 40).map((node, i) => <div key={String(node.node_id ?? i)}><div className="studio-row-heading"><strong>▣ {text(node.node_name || node.node_id)}</strong><Status state={node.connected === true ? "CONNECTED" : node.connected === false ? "OFFLINE" : "UNKNOWN"} /></div><small>{t("Trust", "信任")}: {text(node.trust_status)}</small><ul>{devices.filter(device => typeof node.node_id === "string" && node.node_id && device.node_id === node.node_id).slice(0, 40).map(item)}</ul></div>)}{unbound.length > 0 && <div><small>{t("Node binding", "节点绑定")}: UNKNOWN</small><ul>{unbound.slice(0, 40).map(item)}</ul></div>}</div>;
}
function DataWidget({ type, active, inspect, open, locale }: { type: string; active: () => boolean; inspect: PanelProps["inspect"]; open: PanelProps["open"]; locale: Locale }) {
  const { data, loading, error, health } = useStudioSnapshot(), t = translate(locale);
  if (type === "usage") return <UsageWidget active={active} locale={locale} />;
  if (type === "events") return <EventWidget active={active} locale={locale} />;
  if (["gpu", "network", "sensors"].includes(type)) return <Empty state="UNSUPPORTED">{t("No metric source", "暂无指标来源")}</Empty>;
  if (!WIDGET_TYPES.includes(type as typeof WIDGET_TYPES[number])) return <Empty>{t("Missing Component", "缺失组件")} · {type}</Empty>;
  if (["runtime", "kernel"].includes(type)) {
    if (health.loading) return <Empty state="LOADING">{t("Checking service", "正在检查服务")}</Empty>;
    if (health.error || !health.data) return <Empty state="UNAVAILABLE">{health.error || t("No health reported", "暂无健康报告")}</Empty>;
    const kernel = health.data.kernel;
    const state = type === "runtime" ? health.data.running === true ? "ONLINE" : "UNKNOWN" : kernel?.configured === false ? "UNCONFIGURED" : kernel?.ready === true && kernel?.connected === true ? "READY" : "BLOCKED";
    return <><div className="studio-service-state"><Status state={state} /></div><div className="studio-metric-caption studio-platform">{text(health.data.platform)} · {text(health.data.architecture)}</div><div className="studio-card-bottom"><button onClick={() => open("diagnostics")}>{t("Diagnostics", "诊断")} <StudioIcon name="arrow" /></button>{type === "kernel" && kernel?.state && kernel.state !== state && <span>{text(kernel.state)}</span>}</div></>;
  }
  if (loading) return <Empty state="LOADING">{t("Loading records", "正在加载")}</Empty>;
  if (error || !data) return <Empty state="UNAVAILABLE">{error || t("No records reported", "暂无记录")}</Empty>;
  if (type === "topology") return <DeviceTopology nodes={Array.isArray(data.nodes) ? data.nodes : []} devices={Array.isArray(data.devices) ? data.devices : []} locale={locale} />;
  const collection = type === "resources" ? "nodes" : type === "diagnostics" ? "incidents" : type;
  const rows = data[collection as keyof typeof data];
  if (!Array.isArray(rows)) return <Empty>{t("No supported source", "暂无受支持的数据源")}</Empty>;
  if (!rows.length) return <Empty>{t("No records reported", "暂无记录")}</Empty>;
  return <>{type === "nodes" && <div className="studio-node-count"><strong>{rows.filter(row => row.connected === true).length}</strong><span>{t("connected", "已连接")} / {rows.length}</span></div>}{rows.slice(0, 40).map((row, i) => <div key={String(row.node_id ?? row.device_id ?? row.work_id ?? row.sequence ?? i)} className="studio-widget-row">
    {type === "resources" ? <ResourceRow row={row} locale={locale} /> : <><div className="studio-row-heading"><strong>{text(row.node_name ?? row.node_id ?? row.device_id ?? row.work_id ?? row.event_type ?? row.action ?? row.incident_id ?? `Record ${i + 1}`)}</strong><Status state={type === "nodes" ? row.connected === true ? "CONNECTED" : row.connected === false ? "OFFLINE" : "UNKNOWN" : text(row.state ?? row.status ?? row.lifecycle ?? row.verdict ?? row.event_type)} /></div>
      {type === "nodes" ? <div className="studio-card-bottom"><small>{t("Trust", "信任")}: {text(row.trust_status)}</small><button onClick={() => typeof row.node_id === "string" && inspect({ kind: "node", nodeId: row.node_id })}>{t("Inspect", "检查")} <StudioIcon name="arrow" /></button></div> : <button className="studio-detail-link" onClick={() => open(type === "diagnostics" ? "operations" : type === "works" ? "tasks" : type)}>{t("Details", "详情")} <StudioIcon name="arrow" /></button>}
    </>}
  </div>)}{["evidence", "activity"].includes(type) && <details className="studio-card-details"><summary>{t("Source", "来源")}</summary>{type === "evidence" ? t("Distributed Work receipt / verification metadata. Receipt is not independent Observation or physical verification.", "分布式任务回执与验证元数据。回执不代表独立观测或物理验证。") : t("GovernanceStore audit", "GovernanceStore 审计")}</details>}</>;
}
function Widget({ widget, isVisible, inspect, open, locale }: { widget: DashboardWidget; locale: Locale; isVisible: () => boolean; inspect: PanelProps["inspect"]; open: PanelProps["open"] }) {
  const { subscribeLive } = useStudioSnapshot();
  const active = useCallback(() => !widget.paused && isVisible() && document.visibilityState !== "hidden", [widget.paused, isVisible]);
  useEffect(() => {
    if (["usage", "events", "gpu", "network", "sensors"].includes(widget.type)) return;
    return subscribeLive(active, [widget.type === "kernel" || widget.type === "runtime" ? "health" : "operations"]);
  }, [active, subscribeLive, widget.type]);
  return widget.paused ? <Empty state="PAUSED">{translate(locale)("Updates paused", "已暂停刷新")}</Empty> : <DataWidget type={widget.type} active={active} inspect={inspect} open={open} locale={locale} />;
}
function download(value: StudioLayout) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "apeir-dashboard.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function StudioDashboard({ config, updateConfig, isVisible, locale, inspect, open, saveLayout }: PanelProps) {
  const { editing } = useStudioPresentation();
  const dashboard = config === undefined ? defaultDashboard() : validateDashboard(config);
  const { width, mounted, containerRef } = useContainerWidth();
  const { refresh } = useStudioSnapshot();
  const [type, setType] = useState("nodes"), [selected, setSelected] = useState<string | null>(null), [message, setMessage] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") { setSelected(null); if (menu.current?.open) { menu.current.open = false; menu.current.querySelector("summary")?.focus(); } } };
    const outside = (event: PointerEvent) => { if (menu.current?.open && event.target instanceof Node && !menu.current.contains(event.target)) menu.current.open = false; };
    window.addEventListener("keydown", key); window.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("keydown", key); window.removeEventListener("pointerdown", outside); };
  }, []);
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const title = (widget: DashboardWidget) => widget.title || titles[widget.type]?.[locale === "zh" ? 1 : 0] || widget.type;
  const change = (widgets: DashboardWidget[]) => { try { updateConfig(validateDashboard({ schemaVersion: 1, widgets })); setMessage(""); } catch (error) { setMessage(String(error)); } };
  const add = (source?: DashboardWidget) => {
    if (dashboard.widgets.length >= 32) { setMessage("Widget limit reached (32)."); return; }
    const y = Math.max(0, ...dashboard.widgets.map(widget => widget.y + widget.h));
    change([...dashboard.widgets, { ...(source || { type, title: "", x: 0, y, w: 4, h: 4, paused: false }), id: `widget-${crypto.randomUUID()}`, y }]);
  };
  const positions = (layout: Layout) => {
    if (!editing) return;
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
  return <section className={`studio-dashboard ${editing ? "dashboard-editing" : "dashboard-browsing"}`} aria-label="Dashboard builder">
    <header className="studio-dashboard-toolbar"><strong>{t("Overview", "概览")}</strong><span className="studio-dashboard-mode">{editing ? t("Editing layout", "正在编辑布局") : ""}</span><button onClick={() => refresh()} title={t("Refresh shared Runtime data", "刷新 Runtime 数据")}>{t("Refresh data", "刷新数据")} <StudioIcon name="refresh" /></button>
    {editing && <><label><select aria-label="Widget type" value={type} onChange={event => setType(event.target.value)}>{WIDGET_TYPES.map(type => <option key={type} value={type}>{titles[type][locale === "zh" ? 1 : 0]}</option>)}</select></label><button onClick={() => add()}><StudioIcon name="add" />{t("Add widget", "添加组件")}</button><details className="studio-menu studio-dashboard-menu" ref={menu}><summary aria-label={t("Dashboard options", "仪表盘选项")}>···</summary><div className="studio-menu-content"><button onClick={saveLayout}>{t("Save dashboard", "保存仪表盘")}</button><button onClick={exportLayout}>{t("Export dashboard", "导出仪表盘")}</button><button onClick={() => input.current?.click()}>{t("Import dashboard", "导入仪表盘")}</button><button onClick={() => change(compactDashboard().widgets)}>{t("Reset dashboard", "重置仪表盘")}</button></div></details></>}
    </header>
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
    {editing && settings && <form className="studio-widget-settings" aria-label="Widget settings" onSubmit={event => event.preventDefault()}><strong>{t("Widget settings", "组件设置")} · {settings.type}</strong><label>{t("Title", "标题")}<input aria-label="Widget title" maxLength={64} value={settings.title} onChange={event => update({ title: event.target.value })} /></label>{(["x", "y", "w", "h"] as const).map(key => <label key={key}>{key}<input aria-label={`Widget ${key}`} type="number" value={settings[key]} onChange={event => update({ [key]: Number(event.target.value) })} /></label>)}<label><input type="checkbox" checked={settings.paused} onChange={event => update({ paused: event.target.checked })} />{t("Pause display", "暂停显示")}</label><button onClick={() => setSelected(null)}>{t("Close settings", "关闭设置")}</button></form>}
    <div className="studio-dashboard-grid" ref={containerRef as React.RefObject<HTMLDivElement>}>{mounted && <GridLayout width={width} gridConfig={{ cols: 12, rowHeight: 40, margin: [8, 8], maxRows: 200 }} compactor={noOverlapCompactor} resizeConfig={{ enabled: editing }} dragConfig={{ enabled: editing, handle: ".studio-widget-grip", allowMobileScroll: true }} layout={dashboard.widgets.map(widget => ({ i: widget.id, x: widget.x, y: widget.y, w: widget.w, h: widget.h, minW: 2, minH: 2, maxH: 30 }))} onLayoutChange={positions}>
      {dashboard.widgets.map(widget => <div key={widget.id} className={`studio-widget ${selected === widget.id && editing ? "studio-widget-selected" : ""}`} data-widget-id={widget.id}><header>{editing ? <><button className="studio-widget-grip" aria-label={`${t("Move", "移动")} ${title(widget)}`} title={t("Drag to move", "拖动以移动")}>{title(widget)}</button><button aria-label={`${t("Settings", "设置")} ${title(widget)}`} aria-pressed={selected === widget.id} onClick={() => setSelected(widget.id)}><StudioIcon name="settings" /></button><button aria-label={`${t("Duplicate", "复制")} ${title(widget)}`} onClick={() => add(widget)}><StudioIcon name="copy" /></button><button aria-label={`${t("Remove", "移除")} ${title(widget)}`} onClick={() => { change(dashboard.widgets.filter(item => item.id !== widget.id)); if (selected === widget.id) setSelected(null); }}><StudioIcon name="close" /></button></> : <h3>{title(widget)}</h3>}</header><div className="studio-widget-body"><Widget widget={widget} locale={locale} isVisible={isVisible} inspect={inspect} open={open} /></div></div>)}
    </GridLayout>}</div>
  </section>;
}

export function StudioUsage({ isVisible, locale }: Pick<PanelProps, "isVisible" | "locale">) {
  const active = useCallback(() => isVisible() && document.visibilityState !== "hidden", [isVisible]);
  return <section className="studio-projection" aria-label={translate(locale)("Model Usage", "模型用量")}><UsageWidget active={active} locale={locale} /></section>;
}
