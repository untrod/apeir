import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchModels, setConfig, testModel } from "../lib/api";
import { entityStore } from "../store/entityStore";
import type { Model } from "../store/types";
import { act, renderHook } from "@testing-library/react";
import { useModels } from "../store/hooks";
import { createElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { Composer } from "../components/Composer";
import { ModelsPage, ResourceDock } from "../App";
import { StatusBar } from "../components/StatusBar";

// ModelCenterModel's public registry projection; model_id remains supported
// when reading a Controller that predates the additive entity id alias.
const centerModel = (model_id: string) => ({ model_id, display_name: model_id, provider_id: "fake", endpoint_type: "local_service", state: "enabled", health: "unknown", capabilities: ["reasoning"], capability_scores: {}, evaluation: null, location: "", recoverable: false });
const reply = (models: unknown[]) => ({ ok: true, json: async () => ({ ok: true, data: { models, summary: { total: models.length } } }) });

describe("Model Center snapshot reaches the real Desktop store", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it.each([false, true])("preserves distinct public model identities and notifies subscribed views (entity alias: %s)", async entityAlias => {
    entityStore.clearStore();
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const models = [centerModel("fake/one"), centerModel("fake/two")].map(model => entityAlias ? { ...model, id: model.model_id } : model);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(models)));
    const view = renderHook(() => useModels());
    const result = await fetchModels();
    act(() => entityStore.upsertModels(result.models as unknown as Model[]));
    expect(view.result.current.map(model => model.id)).toEqual(["fake/one", "fake/two"]);
    expect(entityStore.getState().models["fake/one"].health).toBe("unknown");
    expect(result.models[0].model_id).toBe("fake/one");
    expect(result.models[0].avg_latency_ms).toBeUndefined();
    expect(result.models[0].cost_per_1k_tokens_usd).toBeUndefined();
  });
  it("replaces complete snapshot membership including an empty current list", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const fetch = vi.fn().mockResolvedValue(reply([{ ...centerModel("former"), id: "former" }]));
    vi.stubGlobal("fetch", fetch);
    entityStore.upsertModels((await fetchModels()).models as unknown as Model[]);
    expect(entityStore.getState().models.former).toBeDefined();
    fetch.mockResolvedValue(reply([]));
    entityStore.upsertModels((await fetchModels()).models as unknown as Model[]);
    expect(entityStore.getState().models).toEqual({});
  });
  it("rejects inconsistent entity and public model identities", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ ...centerModel("original"), id: "different" }])));
    await expect(fetchModels()).rejects.toThrow(/identity/);
  });
  it("rejects a pending snapshot after the Controller configuration changes", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    let release!: (response: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(resolve => { release = resolve; })));
    const pending = fetchModels();
    setConfig({ url: "http://127.0.0.1:8771", token: "fake-model-center-replacement" });
    release(reply([centerModel("former")]));
    await expect(pending).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  });
  it("loads every bounded public HTTP page before replacing model membership", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const page = (index: number, model: string) => ({ ok: true, json: async () => ({ ok: true, data: {
      models: [centerModel(model)], total_count: 2, available_count: 1,
      pagination: { page: index, page_size: 1, total: 2, total_pages: 2, has_next: index === 1, has_prev: index === 2 },
    } }) });
    const fetch = vi.fn().mockResolvedValueOnce(page(1, "first")).mockResolvedValueOnce(page(2, "second"));
    vi.stubGlobal("fetch", fetch);
    const snapshot = await fetchModels();
    entityStore.upsertModels(snapshot.models as unknown as Model[]);
    expect(Object.keys(entityStore.getState().models)).toEqual(["first", "second"]);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain("page=2&page_size=1");
  });
  it.each(["repeat", "duplicate", "limit", "changed"])("rejects %s pagination without publishing a partial snapshot", async fault => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const payload = (index: number) => ({ ok: true, json: async () => ({ ok: true, data: {
      models: [centerModel(index === 1 || fault === "duplicate" ? "first" : "second")],
      pagination: { page: fault === "repeat" ? 1 : index, page_size: 1, total: fault === "limit" ? 10001 : fault === "changed" && index === 2 ? 3 : 2,
        total_pages: fault === "limit" ? 10001 : fault === "changed" && index === 2 ? 3 : 2, has_next: index === 1 },
    } }) });
    const fetch = vi.fn().mockResolvedValueOnce(payload(1)).mockResolvedValueOnce(payload(2));
    vi.stubGlobal("fetch", fetch);
    await expect(fetchModels()).rejects.toMatchObject({ code: "MODEL_SNAPSHOT_INVALID" });
    expect(fetch.mock.calls.length).toBeLessThanOrEqual(2);
  });
  it.each(["composer", "dock", "status"])("offers only canonical enabled models in the %s", async surface => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const states = ["enabled", "registered", "broken", "removed", "disabled"];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(states.map(state => ({ ...centerModel(`fake-${state}`), state })))));
    const result = await fetchModels();
    const models = result.models as unknown as Model[];
    entityStore.upsertModels(models);
    if (surface === "composer") {
      render(createElement(Composer, { onSend: vi.fn(), onStop: vi.fn(), disabled: false, streaming: false, models, nodes: [] }));
      fireEvent.click(screen.getByTitle("Constraints"));
      expect(screen.getByRole("option", { name: "fake-enabled" })).toHaveValue("fake-enabled");
    } else if (surface === "dock") {
      render(createElement(ResourceDock));
      expect(screen.getByText("fake-enabled")).toBeInTheDocument();
    } else {
      render(createElement(StatusBar));
      expect(screen.getByText("Models").parentElement).toHaveTextContent("Models1");
      fireEvent.click(screen.getByText("Models"));
      expect(screen.getByText(/fake-enabled/)).toBeInTheDocument();
    }
    for (const state of states.filter(state => state !== "enabled")) {
      expect(screen.queryByText(`fake-${state}`)).not.toBeInTheDocument();
    }
  });
  it.each([null, 0])("renders actual model metric evidence without converting %s into a measurement", async measurement => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    const model = { ...centerModel("fake-measured"), id: "fake-measured", avg_latency_ms: measurement, cost_per_1k_tokens_usd: measurement };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([model])));
    entityStore.upsertModels((await fetchModels()).models as unknown as Model[]);
    render(createElement(ModelsPage, { onModelClick: vi.fn() }));
    expect(screen.getByText("fake · unknown")).toBeInTheDocument();
    if (measurement === null) {
      expect(screen.getByText("latency").parentElement).toHaveTextContent("UNKNOWN");
      expect(screen.getByText("cost").parentElement).toHaveTextContent("UNKNOWN");
      expect(screen.queryByText("0ms")).not.toBeInTheDocument();
    } else {
      expect(screen.getByText("0ms")).toBeInTheDocument();
      expect(screen.getByText(/^\$0(?:\.0+)?\/1k$/)).toBeInTheDocument();
    }
  });
  it("keeps an unmeasured model latency UNKNOWN in the actual status consumer", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-model-center-service" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply([{ ...centerModel("fake-unmeasured"), avg_latency_ms: null }])));
    entityStore.upsertModels((await fetchModels()).models as unknown as Model[]);
    render(createElement(StatusBar));
    fireEvent.click(screen.getByText("Models"));
    expect(screen.getByText(/fake-unmeasured/)).toHaveTextContent("UNKNOWN");
    expect(screen.queryByText(/fake-unmeasured · 0ms/)).not.toBeInTheDocument();
  });
});

describe("model diagnostics API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("uses the body-safe model test endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          model_id: "deepseek/deepseek-reasoner",
          selected_model_id: "deepseek/deepseek-reasoner",
          healthy: true,
          request_id: "modelreq_test",
          response_id: "modelresp_test",
          instance_id: "deepseek-test",
          latency_ms: 10,
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    const result = await testModel("deepseek/deepseek-reasoner");

    expect(result.healthy).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/models/test",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model_id: "deepseek/deepseek-reasoner" }),
      }),
    );
  });
});
