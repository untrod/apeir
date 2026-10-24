import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createHash, webcrypto } from "node:crypto";
import { entityStore } from "../store/entityStore";
import { fetchNodes, setConfig } from "../lib/api";

const a = { url: "http://127.0.0.1:8770", token: "fake-cache-scope-a" };
async function seed() {
  setConfig(a); entityStore.clearStore();
  const node = { node_id: "private-node-a", node_name: "Private A", platform: "Linux", arch: "arm64", capabilities: [], online: false, last_seen: "", status: "offline", trust_status: "UNKNOWN", connected: false, connectivity_state: "OFFLINE", connectivity_lease_valid: false, resource_report_fresh: false, source: "node_runtime.controller-status" };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: [node] }) }));
  entityStore.upsertNodes(await fetchNodes());
  return structuredClone(entityStore.getState());
}
function request<T>(result: T) {
  const value = { result, onsuccess: null as null | (() => void) };
  queueMicrotask(() => value.onsuccess?.()); return value;
}
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); });

it("retires all in-memory entities immediately on Controller or credential replacement", async () => {
  await seed();
  expect(entityStore.getState().nodes["private-node-a"]).toBeDefined();
  setConfig({ ...a, token: "fake-cache-scope-b" });
  expect(entityStore.getState().nodes).toEqual({});
});

it("never hydrates legacy records without a proven Controller/session scope", async () => {
  const cached = await seed(); entityStore.clearStore();
  vi.stubGlobal("indexedDB", { open: () => request({ close: () => {}, transaction: () => ({ objectStore: () => ({ get: () => request(cached), put: () => {} }) }) }) });
  await entityStore.hydrate();
  expect(entityStore.getState().hydrated).toBe(true);
  expect(entityStore.getState().nodes).toEqual({});
});

it("refuses a valid cached envelope belonging to a different credential scope", async () => {
  const state = await seed(); entityStore.clearStore();
  const scope = createHash("sha256").update(JSON.stringify(["apeir.entity.cache.v2", a.url, a.token])).digest("hex");
  vi.stubGlobal("indexedDB", { open: () => request({ close: () => {}, transaction: () => ({ objectStore: () => ({ get: () => request({ cache_schema: 2, scope, state }), put: () => {} }) }) }) });
  setConfig({ ...a, token: "fake-other-credential" });
  await entityStore.hydrate();
  expect(entityStore.getState().nodes).toEqual({});
});

it("rejects an in-flight hydration when the Controller changes before the database resolves", async () => {
  await seed(); entityStore.clearStore();
  let release: (() => void) | undefined;
  vi.stubGlobal("indexedDB", { open: () => {
    const value = { result: { close: () => {}, transaction: () => ({ objectStore: () => ({ get: () => request(null) }) }) }, onsuccess: null as null | (() => void) };
    release = () => value.onsuccess?.(); return value;
  } });
  const pending = entityStore.hydrate();
  const rejected = expect(pending).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  await vi.waitFor(() => expect(release).toBeDefined());
  setConfig({ ...a, url: "http://127.0.0.1:9770" }); release!();
  await rejected;
  expect(entityStore.getState().nodes).toEqual({});
});
