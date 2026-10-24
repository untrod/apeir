/** Bounded presentation configuration. Never serialises Runtime data or permission. */
export const WIDGET_TYPES = ["runtime", "kernel", "nodes", "devices", "resources", "usage", "works", "evidence", "activity", "diagnostics", "events", "gpu", "network", "sensors", "topology"] as const;
export type WidgetType = typeof WIDGET_TYPES[number];
export type DashboardWidget = { id: string; type: string; title: string; x: number; y: number; w: number; h: number; paused: boolean };
export type DashboardConfig = { schemaVersion: 1; widgets: DashboardWidget[] };
const id = /^[a-zA-Z0-9_.:-]{1,80}$/;
export function validateDashboard(input: unknown): DashboardConfig {
  const object = (value: unknown): Record<string, unknown> => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid dashboard object.");
    return value as Record<string, unknown>;
  };
  const exact = (value: Record<string, unknown>, keys: string[]) => {
    if (Object.keys(value).some(key => !keys.includes(key))) throw new Error("Unsupported or sensitive dashboard field.");
  };
  const root = object(input); exact(root, ["schemaVersion", "widgets"]);
  if (root.schemaVersion !== 1 || !Array.isArray(root.widgets) || root.widgets.length > 32) throw new Error("Unsupported dashboard schema or widget limit (32).");
  const ids = new Set<string>();
  const widgets = root.widgets.map(value => {
    const item = object(value); exact(item, ["id", "type", "title", "x", "y", "w", "h", "paused"]);
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
    return { id: item.id, type: item.type, title: item.title, x, y, w, h, paused: item.paused };
  });
  for (let i = 0; i < widgets.length; i++) for (let j = i + 1; j < widgets.length; j++) {
    const a = widgets[i], b = widgets[j];
    if (a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y) throw new Error("Widgets overlap; choose an empty grid position.");
  }
  return { schemaVersion: 1, widgets };
}
export const defaultDashboard = (): DashboardConfig => ({ schemaVersion: 1, widgets: ["runtime", "kernel", "nodes", "works", "usage", "evidence"].map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: (i % 3) * 4, y: Math.floor(i / 3) * 6, w: 4, h: 6, paused: false })) });

/** New layouts are denser; config-less version-1 layouts retain their original geometry. */
export const compactDashboard = (types: readonly WidgetType[] = ["runtime", "kernel", "nodes", "works", "usage", "evidence"]): DashboardConfig => ({ schemaVersion: 1, widgets: types.map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: (i % 3) * 4, y: Math.floor(i / 3) * 4, w: 4, h: 4, paused: false })) });
