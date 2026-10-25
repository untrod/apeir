/** Public data-only Studio host contract. These declarations grant no authority. */
export const STUDIO_UI_SCHEMA = "apeir.studio-ui/v1";
// 64 installed packages, each with at most 64 KiB of presentation metadata,
// plus stable component identities and verified record envelopes.
export const MAX_STUDIO_UI_PROJECTION_BYTES = 5 * 1024 * 1024;
export const STUDIO_UI_FIELDS = ["running", "version", "providers", "capabilities", "devices", "events", "jobs_pending", "kernel_state", "kernel_ready"] as const;
export type StudioField = typeof STUDIO_UI_FIELDS[number];
export type StudioView =
  | { kind: "text"; label?: string; text: string }
  | { kind: "metric" | "status" | "chart"; label?: string; source: "runtime.status"; field: StudioField }
  | { kind: "table"; label?: string; source: "runtime.status"; fields: { field: StudioField; label: string }[] }
  | { kind: "stack"; label?: string; children: StudioView[] }
  | { kind: "action"; label: string; action: "workflow.run"; params: { workflow_id: string; version: string; inputs?: Record<string, unknown> } };
export type StudioUIContribution = { id: string; type: string; kind: "panel" | "widget"; title: string; description?: string; subscriptions?: string[]; events?: string[]; view: StudioView };
export type StudioUIExtension = { extension_id: string; version: string; digest: string; enabled: boolean; state: string; authority: string; publisher_trust: string; signature_status: string; contributions: StudioUIContribution[] };
export type StudioUIView = { extensions: StudioUIExtension[]; diagnostics: { extension_id: string; state: string; reason: string }[]; status: Partial<Record<StudioField, string | number | boolean | null>> | null; received_at: string; executable_ui: "BLOCKED"; execution_scope: "runtime-service" };
export type StudioUIReview = { extension_id: string; version: string; digest: string; previous_digest: string; manifest: Record<string, unknown> };
const component = /^ui:[0-9a-f]{32}:[a-z][a-z0-9-]{0,31}$/;
const digest = /^sha256:[0-9a-f]{64}$/;
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Studio host response");
  return value as Record<string, unknown>;
};
const boundedText = (value: unknown, max = 2048) => typeof value === "string" && value.length <= max;
function validateView(value: unknown, depth = 0): value is StudioView {
  if (depth > 2) return false;
  const view = object(value);
  if (view.label !== undefined && !boundedText(view.label, 64)) return false;
  const common = ["kind", "label"];
  const exact = (keys: string[]) => Object.keys(view).every(key => [...common, ...keys].includes(key));
  if (view.kind === "text") return exact(["text"]) && boundedText(view.text);
  if (view.kind === "stack") return exact(["children"]) && Array.isArray(view.children) && view.children.length >= 1 && view.children.length <= 12 && view.children.every(child => validateView(child, depth + 1));
  if (view.kind === "action") {
    const params = object(view.params);
    return exact(["action", "params"]) && boundedText(view.label, 64) && view.action === "workflow.run" && [params.workflow_id, params.version].every(value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value)) && Object.keys(params).every(key => ["workflow_id", "version", "inputs"].includes(key)) && (params.inputs === undefined || !!object(params.inputs));
  }
  if (view.source !== "runtime.status") return false;
  const field = (value: unknown) => STUDIO_UI_FIELDS.includes(value as StudioField);
  if (view.kind === "table") return exact(["source", "fields"]) && Array.isArray(view.fields) && view.fields.length >= 1 && view.fields.length <= 12 && view.fields.every(item => { const row = object(item); return Object.keys(row).every(key => ["field", "label"].includes(key)) && field(row.field) && boundedText(row.label, 64); });
  return ["metric", "status", "chart"].includes(String(view.kind)) && exact(["source", "field"]) && field(view.field);
}
export function parseStudioUIView(input: unknown): StudioUIView {
  const value = object(input);
  if (new TextEncoder().encode(JSON.stringify(input)).byteLength > MAX_STUDIO_UI_PROJECTION_BYTES || !Array.isArray(value.extensions) || value.extensions.length > 64 || value.execution_scope !== "runtime-service" || value.executable_ui !== "BLOCKED" || !boundedText(value.received_at, 64)) throw new Error("Unsupported Studio host response");
  const types = new Set<string>();
  for (const item of value.extensions) {
    const record = object(item);
    if (!boundedText(record.extension_id, 256) || !boundedText(record.version, 128) || typeof record.digest !== "string" || !digest.test(record.digest) || typeof record.enabled !== "boolean" || ![record.state, record.authority, record.publisher_trust, record.signature_status].every(field => boundedText(field, 256)) || !Array.isArray(record.contributions) || record.contributions.length > 16) throw new Error("Invalid Studio extension identity");
    for (const raw of record.contributions) {
      const contribution = object(raw);
      if (typeof contribution.type !== "string" || !component.test(contribution.type) || types.has(contribution.type) || !["panel", "widget"].includes(String(contribution.kind)) || !boundedText(contribution.title, 64) || !validateView(contribution.view)) throw new Error("Unsupported Studio contribution");
      types.add(contribution.type);
      for (const key of ["subscriptions", "events"]) if (contribution[key] !== undefined && (!Array.isArray(contribution[key]) || !(contribution[key] as unknown[]).every(item => typeof item === "string" && ["runtime.status", "runtime.lifecycle", "runtime.started", "runtime.stopped"].includes(item)))) throw new Error("Unsupported Studio subscription");
    }
  }
  if (value.status !== null) for (const [key, field] of Object.entries(object(value.status))) if (!STUDIO_UI_FIELDS.includes(key as StudioField) || !(field === null || typeof field === "string" || typeof field === "boolean" || typeof field === "number" && Number.isFinite(field))) throw new Error("Invalid sanitized Studio status");
  if (!Array.isArray(value.diagnostics) || value.diagnostics.length > 512 || value.diagnostics.some(row => { const item = object(row); return ![item.extension_id, item.state, item.reason].every(field => boundedText(field, 256)); })) throw new Error("Invalid Studio diagnostics");
  return input as StudioUIView;
}
export function availableContributions(view: StudioUIView | null, kind: "panel" | "widget") {
  return (view?.extensions || []).filter(record => record.enabled).flatMap(record => record.contributions.filter(item => item.kind === kind).map(contribution => ({ record, contribution })));
}
