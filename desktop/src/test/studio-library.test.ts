import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createStudioLayout } from "../lib/studioLayout";
import { changeStudioLibrary, layoutForScope, parseStudioLibrary, readStudioLibrary, STUDIO_LIBRARY_KEY, visibleLayouts, workspaceLayoutScope } from "../lib/studioLibrary";
const document = () => layoutForScope(createStudioLayout(), "global", "First");
const entry = (id = "example") => ({ id, scope: { kind: "global" as const }, document: document() });
beforeEach(() => { localStorage.clear(); vi.stubGlobal("crypto", webcrypto); Object.defineProperty(navigator, "locks", { configurable: true, value: { request: vi.fn(async (_key, callback) => callback()) } }); });
afterEach(() => vi.unstubAllGlobals());
describe("Studio layout library uses only the original presentation schema", () => {
  it("saves, duplicates, renames and removes immutable presentation snapshots", async () => {
    const first = await changeStudioLibrary(localStorage, 0, entries => [...entries, entry()]);
    const duplicate = await changeStudioLibrary(localStorage, first.revision, entries => [...entries, { ...entries[0], id: "copy", document: { ...entries[0].document, name: "Copied" } }]);
    const renamed = await changeStudioLibrary(localStorage, duplicate.revision, entries => entries.map(item => item.id === "copy" ? { ...item, document: { ...item.document, name: "Renamed" } } : item));
    expect(renamed.entries[0].document.name).toBe("First"); expect(readStudioLibrary(localStorage).entries[1].document.name).toBe("Renamed");
    const removed = await changeStudioLibrary(localStorage, renamed.revision, entries => entries.filter(item => item.id !== "copy"));
    expect(removed.entries).toHaveLength(1);
    expect(JSON.stringify(removed)).not.toMatch(/token|credential|grant|permissions|work_id/);
  });
  it("rejects stale revisions and preserves previous bytes on validation or quota failure", async () => {
    await changeStudioLibrary(localStorage, 0, () => [entry()]); const original = localStorage.getItem(STUDIO_LIBRARY_KEY);
    await expect(changeStudioLibrary(localStorage, 0, () => [])).rejects.toThrow(/another window/);
    await expect(changeStudioLibrary(localStorage, 1, entries => [...entries, entry()])).rejects.toThrow(/duplicate/);
    expect(localStorage.getItem(STUDIO_LIBRARY_KEY)).toBe(original);
    const storage: Storage = { ...localStorage, length: 1, key: () => STUDIO_LIBRARY_KEY, clear: vi.fn(), removeItem: vi.fn(), getItem: () => original, setItem: () => { throw new Error("quota"); } };
    await expect(changeStudioLibrary(storage, 1, () => [])).rejects.toThrow(/quota/); expect(localStorage.getItem(STUDIO_LIBRARY_KEY)).toBe(original);
  });
  it("requires a supported cross-window writer lock instead of silently racing", async () => {
    Object.defineProperty(navigator, "locks", { configurable: true, value: undefined });
    await expect(changeStudioLibrary(localStorage, 0, () => [entry()])).rejects.toThrow(/BLOCKED/); expect(localStorage.getItem(STUDIO_LIBRARY_KEY)).toBeNull();
  });
  it("binds Workspace namespaces to endpoint and actual directory without storing either", async () => {
    const a = await workspaceLayoutScope("http://controller-a.invalid", "/authorized/project-a");
    const otherController = await workspaceLayoutScope("http://controller-b.invalid", "/authorized/project-a");
    const otherDirectory = await workspaceLayoutScope("http://controller-a.invalid", "/authorized/project-b");
    expect(a).toMatch(/^[a-f0-9]{64}$/); expect(a).not.toBe(otherController); expect(a).not.toBe(otherDirectory);
    const saved = { ...entry("workspace"), scope: { kind: "workspace" as const, workspace: a }, document: layoutForScope(createStudioLayout(), "workspace", "Private layout") };
    const library = parseStudioLibrary(JSON.stringify({ schemaVersion: 1, revision: 0, entries: [entry(), saved] }));
    expect(visibleLayouts(library, null)).toHaveLength(1); expect(visibleLayouts(library, otherController)).toHaveLength(1); expect(visibleLayouts(library, a)).toHaveLength(2);
    expect(JSON.stringify(library)).not.toMatch(/controller-a|authorized|project-a/);
  });
  it.each(["token", "credential", "permission", "__proto__"])("rejects sensitive library %s fields", key => {
    expect(() => parseStudioLibrary(`{"schemaVersion":1,"revision":0,"entries":[],"${key}":"untrusted"}`)).toThrow(/sensitive/);
  });
  it("revalidates nested layouts and size/count/scope limits rather than trusting names", () => {
    const malicious = entry(); Object.assign(malicious.document, { grant: "untrusted" });
    expect(() => parseStudioLibrary(JSON.stringify({ schemaVersion: 1, revision: 0, entries: [malicious] }))).toThrow(/sensitive/);
    expect(() => parseStudioLibrary(JSON.stringify({ schemaVersion: 1, revision: 0, entries: Array.from({ length: 17 }, (_, i) => entry(String(i))) }))).toThrow(/count/);
    expect(() => parseStudioLibrary(" ".repeat(1024 * 1024 + 1))).toThrow(/MiB/);
    expect(() => parseStudioLibrary(JSON.stringify({ schemaVersion: 1, revision: 0, entries: [{ ...entry(), scope: { kind: "workspace", workspace: "raw-private-path" } }] }))).toThrow();
  });
  it("Dashboard scopes contain only dashboard panels and do not copy editor drafts or Runtime records", () => {
    const source = createStudioLayout("network");
    const dashboard = layoutForScope(source, "dashboard", "Network dashboard");
    expect(JSON.stringify(dashboard)).toContain('"component":"dashboard"'); expect(JSON.stringify(dashboard)).not.toContain('"component":"chat"');
    expect(() => layoutForScope(createStudioLayout("software"), "dashboard", "No dashboard")).toThrow(/Add a Dashboard/);
  });
});
