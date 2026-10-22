import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchNodes, setConfig } from "../lib/api";
import { entityStore } from "../store/entityStore";

const row = (node_id: string) => ({ node_id, node_name: node_id, platform: "Linux", arch: "arm64", capabilities: ["system.echo"], online: true, last_seen: "", status: "online", trust_status: "TRUSTED", connected: true, connectivity_state: "ONLINE", connectivity_lease_valid: true, resource_report_fresh: true, source: "node_runtime.controller-status" });
const reply = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });

describe("canonical Node facts in the existing desktop store", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it("keeps two Node identities instead of collapsing under undefined", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([row("node-one"), row("node-two")])));
    entityStore.upsertNodes(await fetchNodes() as never[]);
    expect(Object.keys(entityStore.getState().nodes).sort()).toEqual(["node-one", "node-two"]);
    expect(entityStore.getState().nodes["node-one"].name).toBe("node-one");
    expect(entityStore.getState().nodes["node-one"].active_task_count).toBeNull();
  });
  it("does not infer readiness or permission from an online flag", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ ...row("node-one"), trust_status: "REVOKED" }])));
    const [node] = await fetchNodes();
    expect(node.online).toBe(false);
    expect(node.status).toBe("revoked");
    expect(node.capabilities).toEqual([{ name: "system.echo", version: "", status: "unknown" }]);
  });
  it("accepts current revoked facts over a cached event timestamp", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    const fetch = vi.fn().mockResolvedValue(reply([row("node-one")])); vi.stubGlobal("fetch", fetch);
    const first = await fetchNodes();
    entityStore.upsertNodes(first.map(n => ({ ...n, updated_at: "2099-01-01T00:00:00Z" })) as never[]);
    fetch.mockResolvedValue(reply([{ ...row("node-one"), trust_status: "REVOKED" }]));
    entityStore.upsertNodes(await fetchNodes() as never[]);
    expect(entityStore.getState().nodes["node-one"].online).toBe(false);
    expect(entityStore.getState().nodes["node-one"].trust_status).toBe("REVOKED");
  });
  it("rejects pending reads after a Controller or credential change", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    let release!: (value: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(resolve => { release = resolve; })));
    const read = fetchNodes();
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-replacement" });
    release(reply([row("node-one")]));
    await expect(read).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  });
});

describe("Node activity cannot grant current connectivity", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it.each([false, true])("preserves incomplete or revoked readiness: %s", async revoked => {
    entityStore.clearStore();
    if (revoked) {
      setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ ...row("node-one"), trust_status: "REVOKED" }])));
      entityStore.upsertNodes(await fetchNodes() as never[]);
    }
    entityStore.ingestEvent({ event_id: "owned-event", sequence: 0, event_type: "node.online", domain: "node", source: "recorded-runtime", timestamp: "2099-01-01T00:00:00Z", payload: { node_id: "node-one" }, metadata: {}, dedup_key: "owned-event" });
    const node = entityStore.getState().nodes["node-one"];
    expect(node.online).toBe(false);
    expect(node.name).toBe("node-one");
    expect(node.capabilities).toBeDefined();
    if (revoked) expect(node.trust_status).toBe("REVOKED");
    else expect(node.status).toBe("unknown");
  });
});

describe("Node REST snapshots actually reach subscribed views", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it("notifies a real useNodes subscriber after REST publication", async () => {
    const { act, renderHook } = await import("@testing-library/react");
    const { useNodes } = await import("../store/hooks");
    entityStore.clearStore();
    const view = renderHook(() => useNodes());
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([row("node-subscribed")])));
    const nodes = await fetchNodes();
    act(() => entityStore.upsertNodes(nodes));
    expect(view.result.current.map(n => n.id)).toContain("node-subscribed");
  });
  it("clears prior Node records rather than reusing mutable default maps", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([row("node-before-reset")])));
    entityStore.upsertNodes(await fetchNodes());
    expect(entityStore.getState().nodes["node-before-reset"]).toBeDefined();
    entityStore.clearStore();
    expect(entityStore.getState().nodes).toEqual({});
  });
});

describe("persisted Node cache is historical evidence", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it.each(["TRUSTED", "REVOKED"])("cannot restore current readiness from %s cache", async trust => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ ...row("node-cached"), trust_status: trust }])));
    entityStore.upsertNodes(await fetchNodes());
    const cached = structuredClone(entityStore.getState());
    entityStore.clearStore();
    function request<T>(result: T) {
      const req = { result, onsuccess: null as null | (() => void) };
      queueMicrotask(() => req.onsuccess?.());
      return req;
    }
    vi.stubGlobal("indexedDB", { open: () => request({ close: () => {}, transaction: () => ({ objectStore: () => ({ get: () => request(cached), put: () => {} }) }) }) });
    await entityStore.hydrate();
    const node = entityStore.getState().nodes["node-cached"];
    expect(node.name).toBe("node-cached");
    expect(node.online).toBe(false);
    expect(node.connectivity_state).toBe("UNKNOWN");
    expect(node.trust_status).toBe(trust === "REVOKED" ? "REVOKED" : "UNKNOWN");
  });
});

describe("current Controller snapshot membership", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it("removes former Nodes when the complete current snapshot is empty", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-fact-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([row("node-former-controller")])));
    entityStore.upsertNodes(await fetchNodes());
    expect(entityStore.getState().nodes["node-former-controller"]).toBeDefined();
    entityStore.upsertNodes([]);
    expect(entityStore.getState().nodes).toEqual({});
  });
});
