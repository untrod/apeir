import { parseStudioLayout, type LayoutKind, type StudioLayout } from "./studioLayout";

/** A library of existing presentation documents; no Runtime state or authority. */
export const STUDIO_LIBRARY_KEY = "apeir.studio.library.v1";
export type LayoutScope = { kind: LayoutKind; workspace?: string };
export type SavedLayout = { id: string; scope: LayoutScope; document: StudioLayout };
export type StudioLibrary = { schemaVersion: 1; revision: number; entries: SavedLayout[] };
const MAX_BYTES = 1024 * 1024;
const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid layout library object.");
  return value as Record<string, unknown>;
};
const fields = (value: Record<string, unknown>, allowed: string[]) => {
  if (Object.keys(value).some(key => !allowed.includes(key))) throw new Error("Unsupported or sensitive library field.");
};
export function parseStudioLibrary(input: string): StudioLibrary {
  if (new TextEncoder().encode(input).length > MAX_BYTES) throw new Error("Layout library exceeds 1 MiB.");
  const value = object(JSON.parse(input)); fields(value, ["schemaVersion", "revision", "entries"]);
  if (value.schemaVersion !== 1 || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !Array.isArray(value.entries) || value.entries.length > 16) throw new Error("Invalid library version, revision or entry count (16).");
  const ids = new Set<string>();
  const entries = value.entries.map(item => {
    const entry = object(item); fields(entry, ["id", "scope", "document"]);
    if (typeof entry.id !== "string" || !/^[a-zA-Z0-9_.:-]{1,80}$/.test(entry.id) || ids.has(entry.id)) throw new Error("Invalid or duplicate library identity.");
    ids.add(entry.id);
    const scope = object(entry.scope); fields(scope, ["kind", "workspace"]);
    const document = parseStudioLayout(JSON.stringify(entry.document));
    if (scope.kind !== document.kind) throw new Error("Library scope and document kind differ.");
    if (scope.kind === "workspace" ? typeof scope.workspace !== "string" || !/^[a-f0-9]{64}$/.test(scope.workspace) : scope.workspace !== undefined) throw new Error("Invalid workspace presentation scope.");
    return { id: entry.id, scope: scope as LayoutScope, document };
  });
  return { schemaVersion: 1, revision: Number(value.revision), entries };
}
export function readStudioLibrary(storage: Storage): StudioLibrary {
  const source = storage.getItem(STUDIO_LIBRARY_KEY);
  return source ? parseStudioLibrary(source) : { schemaVersion: 1, revision: 0, entries: [] };
}
export function visibleLayouts(library: StudioLibrary, workspace: string | null): SavedLayout[] {
  return library.entries.filter(entry => entry.scope.kind !== "workspace" || entry.scope.workspace === workspace);
}
/** Only an opaque presentation namespace is retained; no path, bearer or grant. */
export async function workspaceLayoutScope(endpoint: string, path: string): Promise<string> {
  if (!path || path.length > 4096 || !crypto.subtle) throw new Error("Workspace identity or browser SHA-256 is unavailable.");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(["apeir.workspace.presentation.v1", endpoint, path])));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}
/** Use the browser's cross-window configuration lock, plus optimistic revision. */
export async function changeStudioLibrary(storage: Storage, revision: number, edit: (entries: SavedLayout[]) => SavedLayout[]): Promise<StudioLibrary> {
  if (!navigator.locks) throw new Error("BLOCKED · Browser configuration locks unavailable. Export layouts instead.");
  return navigator.locks.request(STUDIO_LIBRARY_KEY, () => {
    const current = readStudioLibrary(storage);
    if (current.revision !== revision) throw new Error("Library changed in another window. Reload before editing.");
    const next = parseStudioLibrary(JSON.stringify({ ...current, revision: revision + 1, entries: edit(current.entries) }));
    // Web Storage replacement is atomic. A quota/write error retains prior bytes.
    storage.setItem(STUDIO_LIBRARY_KEY, JSON.stringify(next)); return next;
  });
}
export function layoutForScope(source: StudioLayout, kind: LayoutKind, name: string): StudioLayout {
  const value = { ...source, kind, name };
  if (kind === "dashboard") {
    const panels: Record<string, unknown>[] = [];
    const collect = (input: unknown) => {
      const node = object(input);
      if (node.type === "tab" && node.component === "dashboard") panels.push(node);
      if (Array.isArray(node.children)) node.children.forEach(collect);
    };
    collect(source.layout);
    if (!panels.length) throw new Error("Add a Dashboard panel before saving a Dashboard layout.");
    value.layout = { type: "row", id: "library-root", children: [{ type: "tabset", id: "library-group", children: panels }] } as StudioLayout["layout"];
  }
  return parseStudioLayout(JSON.stringify(value));
}
