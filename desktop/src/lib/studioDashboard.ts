/** Bounded presentation configuration. Never serialises Runtime data or permission. */
export const WIDGET_TYPES = ["runtime", "kernel", "nodes", "devices", "resources", "usage", "cache", "progress", "quick-actions", "works", "evidence", "activity", "diagnostics", "events", "gpu", "network", "sensors", "topology"] as const;
export type WidgetType = typeof WIDGET_TYPES[number];
export const OVERVIEW_MODES = ["simple", "standard", "professional"] as const;
export const WIDGET_ACCENTS = ["neutral", "accent", "info"] as const;
export const WIDGET_ICONS = ["default", "dashboard", "model", "node", "tasks", "history", "evidence"] as const;
export const USAGE_FIELDS = ["cost", "requests", "tokens", "pending", "unknown_cost"] as const;
export type WidgetPresentation = {
  day?: string;
  fields?: typeof USAGE_FIELDS[number][];
  density?: "compact" | "comfortable";
  accent?: typeof WIDGET_ACCENTS[number];
  icon?: typeof WIDGET_ICONS[number];
  style?: "card" | "plain";
  sort?: "source" | "name" | "state";
};
export type DashboardWidget = { id: string; type: string; title: string; x: number; y: number; w: number; h: number; paused: boolean; presentation?: WidgetPresentation };
export type DashboardConfig = { schemaVersion: 1; widgets: DashboardWidget[] } | { schemaVersion: 2; mode: typeof OVERVIEW_MODES[number]; widgets: DashboardWidget[] };
export const dashboardMode = (value: DashboardConfig) => value.schemaVersion === 2 ? value.mode : "standard";
export const upgradeDashboard = (value: DashboardConfig, mode = dashboardMode(value)): DashboardConfig =>
  validateDashboard({ schemaVersion: 2, mode, widgets: value.widgets });
const id = /^[a-zA-Z0-9_.:-]{1,80}$/;
export function validateDashboard(input: unknown): DashboardConfig {
  const object = (value: unknown): Record<string, unknown> => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid dashboard object.");
    return value as Record<string, unknown>;
  };
  const exact = (value: Record<string, unknown>, keys: string[]) => {
    if (Object.keys(value).some(key => !keys.includes(key))) throw new Error("Unsupported or sensitive dashboard field.");
  };
  const root = object(input); exact(root, root.schemaVersion === 2 ? ["schemaVersion", "mode", "widgets"] : ["schemaVersion", "widgets"]);
  if ((root.schemaVersion !== 1 && root.schemaVersion !== 2) || !Array.isArray(root.widgets) || root.widgets.length > 32) throw new Error("Unsupported dashboard schema or widget limit (32).");
  if (root.schemaVersion === 2 && !OVERVIEW_MODES.includes(root.mode as typeof OVERVIEW_MODES[number])) throw new Error("Unsupported Overview mode.");
  const ids = new Set<string>();
  const widgets = root.widgets.map(value => {
    const item = object(value); exact(item, ["id", "type", "title", "x", "y", "w", "h", "paused", ...(root.schemaVersion === 2 ? ["presentation"] : [])]);
    if (typeof item.id !== "string" || !id.test(item.id) || ids.has(item.id)) throw new Error("Invalid or duplicate widget identity.");
    ids.add(item.id);
    if (typeof item.type !== "string" || !id.test(item.type) || typeof item.title !== "string" || item.title.length > 64 || typeof item.paused !== "boolean") throw new Error("Invalid widget presentation.");
    const integer = (key: string, min: number, max: number) => {
      const number = item[key];
      if (typeof number !== "number" || !Number.isSafeInteger(number) || number < min || number > max) throw new Error("Invalid widget position or size.");
      return number;
    };
    const x = integer("x", 0, 11), y = integer("y", 0, 198), w = integer("w", 2, 12), h = integer("h", 2, 30);
    if (x + w > 12 || y + h > 200) throw new Error("Widget exceeds grid bounds.");
    let presentation: WidgetPresentation | undefined;
    if (item.presentation !== undefined) {
      const source = object(item.presentation); exact(source, ["density", "accent", "icon", "style", "sort", "day", "fields"]);
      const choices = { density: ["compact", "comfortable"], accent: WIDGET_ACCENTS, icon: WIDGET_ICONS, style: ["card", "plain"], sort: ["source", "name", "state"] };
      for (const [key, values] of Object.entries(choices)) if (source[key] !== undefined && !(values as readonly unknown[]).includes(source[key])) throw new Error("Invalid widget presentation value.");
      if (source.day !== undefined) {
        if (!["usage", "cache"].includes(item.type) || typeof source.day !== "string" || source.day !== "today" && (!/^\d{4}-\d{2}-\d{2}$/.test(source.day) || !Number.isFinite(Date.parse(source.day + "T00:00:00Z")) || new Date(source.day + "T00:00:00Z").toISOString().slice(0, 10) !== source.day || source.day < "1970-01-01" || source.day > new Date().toISOString().slice(0, 10))) throw new Error("Select a valid UTC usage date up to today.");
      }
      if (source.fields !== undefined && (item.type !== "usage" || !Array.isArray(source.fields) || !source.fields.length || source.fields.length > USAGE_FIELDS.length || new Set(source.fields).size !== source.fields.length || !source.fields.every(field => USAGE_FIELDS.includes(field as typeof USAGE_FIELDS[number])))) throw new Error("Select supported usage fields.");
      if (source.sort !== undefined && !["nodes", "devices", "resources", "works", "evidence", "activity", "diagnostics"].includes(item.type)) throw new Error("Widget source does not support sorting.");
      presentation = { ...source, ...(Array.isArray(source.fields) ? { fields: [...source.fields] } : {}) } as WidgetPresentation;
    }
    return { id: item.id, type: item.type, title: item.title, x, y, w, h, paused: item.paused, ...(presentation ? { presentation } : {}) };
  });
  for (let i = 0; i < widgets.length; i++) for (let j = i + 1; j < widgets.length; j++) {
    const a = widgets[i], b = widgets[j];
    if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) throw new Error("Widgets overlap; choose an empty grid position.");
  }
  return root.schemaVersion === 2 ? { schemaVersion: 2, mode: root.mode as typeof OVERVIEW_MODES[number], widgets } : { schemaVersion: 1, widgets };
}
export const defaultDashboard = (): DashboardConfig => ({ schemaVersion: 1, widgets: ["runtime", "kernel", "nodes", "works", "usage", "evidence"].map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: (i % 3) * 4, y: Math.floor(i / 3) * 6, w: 4, h: 6, paused: false })) });

/** New layouts are denser; config-less version-1 layouts retain their original geometry. */
export const compactDashboard = (types: readonly WidgetType[] = ["runtime", "kernel", "nodes", "works", "usage", "evidence"]): DashboardConfig => ({ schemaVersion: 1, widgets: types.map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: (i % 3) * 4, y: Math.floor(i / 3) * 4, w: 4, h: 4, paused: false })) });

/** Keyboard changes use the same bounds/collision admission as pointer changes. */
export function moveDashboardWidget(value: DashboardConfig, widgetId: string, key: string, resize = false): DashboardConfig {
  const delta = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[key];
  if (!delta) return value;
  return validateDashboard({ ...value, widgets: value.widgets.map(widget => widget.id !== widgetId ? widget : {
    ...widget, ...(resize ? { w: widget.w + delta[0], h: widget.h + delta[1] } : { x: widget.x + delta[0], y: widget.y + delta[1] }),
  }) });
}
