import type { IJsonModel, IJsonRowNode } from "flexlayout-react";
import { Actions, DockLocation, GroupAction, type Action, type Model, type TabNode, type TabSetNode } from "flexlayout-react";
import { compactDashboard, validateDashboard } from "./studioDashboard";

export function discardsProtectedPanel(action: Action, protectedIds: ReadonlySet<string>): boolean {
  if (action instanceof GroupAction) return action.actions.some(item => discardsProtectedPanel(item, protectedIds));
  return action.type === Actions.DELETE_TABSET ? protectedIds.size > 0 : action.type === Actions.DELETE_TAB && protectedIds.has(action.data.node);
}

/** Presentation only: no resource identity, content, session or authority is serialised. */
export type LayoutKind = "global" | "workspace" | "dashboard" | "template";
export type StudioLayout = {
  schemaVersion: 1; kind: LayoutKind; name: string; locale: "en" | "zh";
  layout: IJsonRowNode;
};
export const STUDIO_LAYOUT_KEY = "apeir.studio.layout.v1";
export const MAX_LAYOUT_BYTES = 96 * 1024;
const idPattern = /^[a-zA-Z0-9_.:-]{1,80}$/;
const nodeIdPattern = /^#?[a-zA-Z0-9_.:-]{1,80}$/;
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Expected a layout object.");
  return value as Record<string, unknown>;
};
function fields(value: Record<string, unknown>, allowed: string[]) {
  if (Object.keys(value).some(key => !allowed.includes(key))) throw new Error("Unsupported or sensitive layout field.");
}

export function parseStudioLayout(input: string): StudioLayout {
  if (new TextEncoder().encode(input).length > MAX_LAYOUT_BYTES) throw new Error("Layout exceeds 96 KiB.");
  const root = record(JSON.parse(input));
  fields(root, ["schemaVersion", "kind", "name", "locale", "layout"]);
  if (root.schemaVersion !== 1 || !["global", "workspace", "dashboard", "template"].includes(String(root.kind))) throw new Error("Unsupported layout schema.");
  if (typeof root.name !== "string" || !root.name.trim() || root.name.length > 64) throw new Error("Layout name must contain 1–64 characters.");
  if (root.locale !== "en" && root.locale !== "zh") throw new Error("Unsupported layout language.");
  const ids = new Set<string>(); let count = 0; let panels = 0;
  function node(input: unknown, parent: string, depth: number): Record<string, unknown> {
    if (++count > 100 || depth > 8) throw new Error("Layout structure exceeds limits.");
    const value = record(input);
    fields(value, ["type", "id", "weight", "children", "component", "name", "selected", "active", "maximized", "config"]);
    const { type, id } = value;
    if (typeof id !== "string" || !nodeIdPattern.test(id) || ids.has(id)) throw new Error("Invalid or duplicate layout identity.");
    ids.add(id);
    if (!((parent === "root" && type === "row") || (parent === "row" && ["row", "tabset"].includes(String(type))) || (parent === "tabset" && type === "tab"))) throw new Error("Invalid layout nesting.");
    if (value.weight !== undefined && (typeof value.weight !== "number" || !Number.isFinite(value.weight) || value.weight <= 0 || value.weight > 10000)) throw new Error("Invalid panel size.");
    if (type === "tab") {
      if (++panels > 24 || typeof value.component !== "string" || !idPattern.test(value.component)) throw new Error("Invalid panel type or panel count.");
      if (value.children !== undefined || value.selected !== undefined || value.active !== undefined || value.maximized !== undefined) throw new Error("Invalid panel configuration.");
      if (value.name !== undefined && (typeof value.name !== "string" || value.name.length > 80)) throw new Error("Invalid panel title.");
      if (value.config !== undefined) {
        if (value.component !== "dashboard") throw new Error("This panel does not accept layout configuration.");
        value.config = validateDashboard(value.config);
      }
    } else {
      if (value.config !== undefined) throw new Error("Invalid container configuration.");
      if (value.component !== undefined || value.name !== undefined || !Array.isArray(value.children)) throw new Error("Invalid layout container.");
      const children = value.children.map(item => node(item, String(type), depth + 1));
      value.children = children;
      if (value.selected !== undefined && (type !== "tabset" || !Number.isInteger(value.selected) || Number(value.selected) < -1 || Number(value.selected) >= children.length)) throw new Error("Invalid selected tab.");
      for (const key of ["active", "maximized"]) if (value[key] !== undefined && (type !== "tabset" || typeof value[key] !== "boolean")) throw new Error("Invalid tab group state.");
    }
    return value;
  }
  return { schemaVersion: 1, kind: root.kind as LayoutKind, name: root.name, locale: root.locale, layout: node(root.layout, "root", 0) as unknown as IJsonRowNode };
}

/** Trusted host constraints; imported layout JSON cannot override these values. */
export function studioPanelSize(type: string): { minWidth: number; minHeight: number } {
  if (type === "workflow") return { minWidth: 420, minHeight: 240 };
  if (["editor", "files", "terminal"].includes(type)) return { minWidth: 380, minHeight: 200 };
  if (type === "chat") return { minWidth: 320, minHeight: 200 };
  if (type === "dashboard") return { minWidth: 300, minHeight: 200 };
  return { minWidth: 280, minHeight: 180 };
}

export function studioModel(layout: StudioLayout): IJsonModel {
  const sized = (node: Record<string, unknown>): Record<string, unknown> => node.type === "tab"
    ? { ...node, ...studioPanelSize(String(node.component)) }
    : { ...node, children: (node.children as Record<string, unknown>[]).map(sized) };
  return { global: { tabEnablePopout: false, tabEnableFloat: false, tabEnableDrag: true, tabSetEnableDrag: true, tabEnableClose: true, enableEdgeDock: true, enableEdgeDockIndicators: true, tabSetEnableTabStrip: true, tabEnableRenderOnDemand: false, tabSetMinWidth: 280, tabSetMinHeight: 180 }, layout: sized(layout.layout as unknown as Record<string, unknown>) as unknown as IJsonRowNode };
}

export function studioMinimumSize(layout: IJsonRowNode, splitter = 8): { width: number; height: number } {
  function measure(node: Record<string, unknown>, vertical: boolean): { width: number; height: number } {
    const children = node.children as Record<string, unknown>[];
    if (node.type === "tabset") {
      const sizes = children.map(child => studioPanelSize(String(child.component)));
      return { width: Math.max(280, ...sizes.map(size => size.minWidth)), height: Math.max(180, ...sizes.map(size => size.minHeight)) + 36 };
    }
    const sizes = children.map(child => measure(child, !vertical));
    // FlexLayout includes the row's own one-pixel extent in its minimum.
    const gap = Math.max(0, sizes.length - 1) * splitter + 1;
    return { width: vertical ? Math.max(1, ...sizes.map(size => size.width)) : sizes.reduce((sum, size) => sum + size.width, gap), height: vertical ? sizes.reduce((sum, size) => sum + size.height, gap) : Math.max(1, ...sizes.map(size => size.height)) };
  }
  return measure(layout as unknown as Record<string, unknown>, false);
}

/** Legacy imports can have selected tabs without an explicitly active group. */
export function activeStudioTab(model: Model): TabNode | undefined {
  let selected = model.getMaximizedTabset()?.getSelectedNode() ?? model.getActiveTabset()?.getSelectedNode();
  if (!selected) model.visitNodes(node => { if (!selected && node.getType() === "tabset") selected = (node as TabSetNode).getSelectedNode(); });
  return selected;
}

/** Reveal the existing instance, including one hidden by a maximized sibling. */
export function focusStudioTab(model: Model, id: string): void {
  const node = model.getNodeById(id);
  if (node?.getType() !== "tab") return;
  const parent = node.getParent();
  const maximized = model.getMaximizedTabset();
  if (maximized && maximized !== parent) model.doAction(Actions.maximizeToggle(maximized.getId()));
  model.doAction(Actions.selectTab(id));
  if (parent?.getType() === "tabset") model.doAction(Actions.setActiveTabset(parent.getId()));
}

export function dockStudioTab(model: Model, id: string, side: "left" | "right" | "top" | "bottom"): void {
  if (model.getNodeById(id)?.getType() !== "tab") return;
  const maximized = model.getMaximizedTabset();
  if (maximized) model.doAction(Actions.maximizeToggle(maximized.getId()));
  const root = model.getRootRow();
  if (!root) return;
  const locations = { left: DockLocation.LEFT, right: DockLocation.RIGHT, top: DockLocation.TOP, bottom: DockLocation.BOTTOM };
  model.doAction(Actions.moveNode(id, root.getId(), locations[side], -1, true));
  focusStudioTab(model, id);
}

/** Drop library-only rendering metadata, then revalidate before saving. */
export function captureStudioLayout(model: IJsonModel, previous: StudioLayout, automaticFocus?: string): StudioLayout {
  function clean(input: unknown): unknown {
    const value = record(input); const result: Record<string, unknown> = {};
    for (const key of ["type", "id", "weight", "component", "name", "selected", "active", "maximized"]) if (value[key] !== undefined) result[key] = value[key];
    if (value.id === automaticFocus) delete result.maximized;
    if (value.config !== undefined && value.component === "dashboard") result.config = validateDashboard(value.config);
    if (Array.isArray(value.children)) result.children = value.children.map(clean);
    return result;
  }
  return parseStudioLayout(JSON.stringify({ ...previous, layout: clean(model.layout) }));
}

export const STUDIO_TEMPLATES: Record<string, { en: string; zh: string; panels: string[][] }> = {
  general: { en: "General", zh: "通用", panels: [["chat"], ["editor", "tasks", "evidence"]] },
  software: { en: "Software Development", zh: "软件开发", panels: [["editor"], ["chat", "tasks"], ["evidence", "activity"]] },
  agents: { en: "AI Agent Development", zh: "智能体开发", panels: [["chat"], ["models", "workflow"], ["tasks", "usage"]] },
  embedded: { en: "Embedded Engineering", zh: "嵌入式工程", panels: [["editor"], ["devices", "nodes"], ["environment", "evidence"]] },
  network: { en: "Network Operations", zh: "网络运维", panels: [["dashboard", "nodes", "devices"], ["diagnostics", "activity"], ["chat", "evidence"]] },
  scientific: { en: "Scientific Research", zh: "科学研究", panels: [["simulation", "documents"], ["chat", "environment"], ["evidence", "usage"]] },
  interactive: { en: "Interactive Agent Studio", zh: "交互智能体", panels: [["chat"], ["models", "diagnostics"]] },
  blank: { en: "Blank Workspace", zh: "空白工作区", panels: [[]] },
};
export function createStudioLayout(template = "general", locale: "en" | "zh" = "en"): StudioLayout {
  const preset = STUDIO_TEMPLATES[template];
  if (!preset) throw new Error("Unknown workspace template.");
  let sequence = 0;
  return parseStudioLayout(JSON.stringify({ schemaVersion: 1, kind: "workspace", name: preset.en, locale, layout: {
    type: "row", id: "studio-root", children: preset.panels.map((types, i) => ({ type: "tabset", id: `group-${i}`, weight: template === "software" ? [55, 27, 18][i] : template === "general" ? [65, 35][i] : 100 / preset.panels.length,
      children: types.map(type => ({ type: "tab", id: `panel-${++sequence}`, component: type, name: type, ...(type === "dashboard" ? { config: template === "network" ? compactDashboard(["runtime", "kernel", "nodes", "resources", "topology", "usage", "works", "evidence"]) : compactDashboard() } : {}) })) })),
  } }));
}

export function loadStudioLayout(storage: Storage, key = STUDIO_LAYOUT_KEY): StudioLayout {
  const saved = storage.getItem(key);
  if (saved) return parseStudioLayout(saved);
  // Legacy layouts and editor preferences are deliberately never overwritten.
  const previous = storage.getItem("apeir.operations.layout.v1");
  if (previous) {
    try {
      const old = record(JSON.parse(previous));
      return createStudioLayout(Array.isArray(old.tabs) && old.tabs.includes("workspace") ? "software" : "general", old.locale === "zh" ? "zh" : "en");
    } catch { /* Invalid legacy preferences do not become executable configuration. */ }
  }
  return createStudioLayout();
}
