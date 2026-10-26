import { lazy, Suspense } from "react";
const StudioWorkflow = lazy(() => import("./StudioWorkflow").then(module => ({ default: module.StudioWorkflow })));
import { StudioChat } from "./StudioChat";
import { DeveloperWorkbench, type WorkbenchDraft } from "../DeveloperWorkbench";
import { DeveloperPlatform } from "../DeveloperPlatform";
import { EnvironmentInspector } from "../EnvironmentInspector";
import { DocumentWorkbench } from "../DocumentWorkbench";
import { SimulationWorkbench } from "../SimulationWorkbench";
import { TaskCenter } from "../TaskCenter";
import { OperationsConsole, type OperationsSnapshot } from "../OperationsConsole";
import { useStudioSnapshot } from "./StudioData";
export { StudioSnapshot } from "./StudioData";
import { StudioExtensionView } from "./StudioExtensionView";
import { StudioExtensions } from "./StudioExtensions";
import { availableContributions } from "../../lib/studioExtensions";
import { StudioDashboard, StudioUsage } from "./StudioDashboard";
import { ErrorBoundary } from "../ErrorBoundary";
import type { DrawerView } from "../DetailDrawer";

export type PanelContribution = {
  type: string; en: string; zh: string; owner: string;
  render: (props: PanelProps) => React.ReactNode;
};
export type PanelProps = { config?: unknown; updateConfig: (config: unknown) => void; saveLayout: () => void; isVisible: () => boolean; locale: "en" | "zh"; onDraftChange: (dirty: boolean) => void; onDraftSnapshot: (drafts: WorkbenchDraft[]) => void; open: (type: string) => void; inspect: (view: DrawerView) => void };
function Projection({ collection }: { collection: keyof OperationsSnapshot | "runtime" }) {
  const { data, loading, error, refresh } = useStudioSnapshot();
  const value = collection === "runtime" ? data?.health : data?.[collection];
  return <section className="studio-projection" aria-label={`${collection} Runtime records`}>
    <header><strong>{collection}</strong><button onClick={() => refresh(["operations"])}>Refresh / 刷新</button></header>
    {loading ? <p role="status">LOADING · Runtime</p> : error ? <p role="alert">UNAVAILABLE · {error}</p> : value === undefined ? <p role="status">UNKNOWN · No source reported.</p> : Array.isArray(value) ? value.length ? value.slice(0, 200).map((row, i) => <details key={i}><summary>{String((row as Record<string, unknown>).node_id ?? (row as Record<string, unknown>).device_id ?? (row as Record<string, unknown>).work_id ?? (row as Record<string, unknown>).digest ?? (row as Record<string, unknown>).sequence ?? `Record ${i + 1}`)}</summary><pre>{JSON.stringify(row, null, 2)}</pre></details>) : <p>No records reported / 暂无记录</p> : <pre>{JSON.stringify(value, null, 2)}</pre>}
    <details className="studio-card-details"><summary>Source / 来源</summary>Runtime projection · Receipt ≠ Observation · UNKNOWN remains unknown.</details>
  </section>;
}

// This registry owns presentation only. Contributions cannot create Capability grants.
export const STUDIO_PANELS: readonly PanelContribution[] = [
  { type: "extensions", en: "UI Extensions", zh: "界面扩展", owner: "ExtensionRegistry / Governance", render: props => <StudioExtensions {...props} /> },
  { type: "dashboard", en: "Dashboard", zh: "仪表盘", owner: "Existing Runtime projections / read-only", render: props => <StudioDashboard {...props} /> },
  { type: "chat", en: "Chat", zh: "对话", owner: "Conversation / Model Gateway", render: p => <StudioChat {...p} /> },
  { type: "files", en: "Project Files", zh: "项目文件", owner: "Workspace API / Governance", render: p => <DeveloperWorkbench embeddedConversation={false} onDraftChange={p.onDraftChange} onDraftSnapshot={p.onDraftSnapshot} onOpenEnvironments={() => p.open("environment")} /> },
  { type: "editor", en: "Workspace Editor", zh: "工作区编辑", owner: "Workspace API / Governance", render: p => <DeveloperWorkbench onDraftChange={p.onDraftChange} onDraftSnapshot={p.onDraftSnapshot} onOpenEnvironments={() => p.open("environment")} /> },
  { type: "tasks", en: "Tasks", zh: "任务", owner: "EntityStore / Task", render: p => <TaskCenter onTaskClick={taskId => p.inspect({ kind: "task", taskId })} onTraceClick={traceId => p.inspect({ kind: "trace", traceId })} /> },
  { type: "models", en: "Models", zh: "模型", owner: "Model Center / Gateway", render: () => <DeveloperPlatform modelsOnly /> },
  { type: "nodes", en: "Nodes", zh: "计算节点", owner: "Controller projection", render: () => <Projection collection="nodes" /> },
  { type: "devices", en: "Devices", zh: "设备", owner: "Reality DeviceRegistry projection", render: () => <Projection collection="devices" /> },
  { type: "workflow", en: "Workflow Builder", zh: "工作流编辑", owner: "WorkflowRuntime / Store / Governance", render: p => <Suspense fallback={<p role="status">LOADING · Workflow</p>}><StudioWorkflow {...p} /></Suspense> },
  { type: "environment", en: "Environment", zh: "环境", owner: "EnvironmentRuntime", render: () => <EnvironmentInspector /> },
  { type: "inspector", en: "Inspector", zh: "检查器", owner: "Existing Operations Console", render: () => <OperationsConsole /> },
  { type: "evidence", en: "Evidence Metadata", zh: "证据元数据", owner: "DistributedWork receipt / verification metadata", render: () => <Projection collection="evidence" /> },
  { type: "terminal", en: "Controlled Commands", zh: "受控命令", owner: "Existing Workbench / ProcessSession; not PTY", render: p => <DeveloperWorkbench embeddedConversation={false} onDraftChange={p.onDraftChange} onDraftSnapshot={p.onDraftSnapshot} /> },
  { type: "diagnostics", en: "Diagnostics", zh: "诊断", owner: "Runtime health projection", render: () => <Projection collection="runtime" /> },
  { type: "documents", en: "Documents", zh: "文档", owner: "DocumentRuntime", render: () => <DocumentWorkbench /> },
  { type: "simulation", en: "Simulation", zh: "仿真", owner: "SimulationRuntime", render: () => <SimulationWorkbench /> },
  { type: "usage", en: "Model Usage", zh: "模型用量", owner: "CostController / Usage accounting", render: p => <StudioUsage isVisible={p.isVisible} locale={p.locale} /> },
  { type: "activity", en: "Governance Activity", zh: "治理活动", owner: "GovernanceStore audit projection", render: () => <Projection collection="activity" /> },
  { type: "operations", en: "Operations Console", zh: "操作控制台", owner: "Existing Console / Governance", render: () => <OperationsConsole /> },
];

export function useStudioPanels(): readonly PanelContribution[] {
  const { extensions } = useStudioSnapshot();
  return [...STUDIO_PANELS, ...availableContributions(extensions.data, "panel").map(({ record, contribution }) => ({ type: contribution.type, en: contribution.title, zh: contribution.title, owner: `${record.extension_id} · UNVERIFIED`, render: (props: PanelProps) => <StudioExtensionView type={contribution.type} isVisible={props.isVisible} locale={props.locale} /> }))];
}
export function StudioPanel({ type, ...props }: PanelProps & { type: string }) {
  const definition = useStudioPanels().find(panel => panel.type === type);
  if (type.startsWith("ui:")) return <ErrorBoundary><StudioExtensionView type={type} isVisible={props.isVisible} locale={props.locale} /></ErrorBoundary>;
  return <ErrorBoundary>{definition ? definition.render(props) : <section role="status" className="studio-projection"><h2>Missing Component / 缺失组件</h2><p>{type}</p><p>No code was loaded. Install a reviewed compatible extension before using this panel.</p></section>}</ErrorBoundary>;
}
