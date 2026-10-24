import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchModelLab, fetchUsageSummary, setConfig } from "../lib/api";
import { usageFixture } from "./usage-fixture";

const serviceToken = "test-usage-service";
beforeEach(() => setConfig({ url: "http://localhost:8770", token: serviceToken }));
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

describe("canonical usage accounting API", () => {
  it("reads the existing authenticated usage endpoint and preserves unknown values", async () => {
    const summary = usageFixture({ input_tokens: null, total_cost_usd: null, cost_measurement: "unknown", unknown_cost_requests: 1 });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: summary }) });
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchUsageSummary("2026-10-12")).toEqual(summary);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8770/api/v1/usage?day=2026-10-12", expect.objectContaining({
      credentials: "include", headers: expect.objectContaining({ Authorization: `Bearer ${serviceToken}` }),
    }));
  });

  it("rejects unsupported legacy zero summaries rather than asserting free usage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { total_cost_usd: 0, requests: 0, items: [] } }) }));
    await expect(fetchUsageSummary()).rejects.toThrow("unsupported or incomplete");
  });

  it.each([
    { input_tokens: -1 },
    { output_tokens: 1.5 },
    { estimated_cost_usd: Number.NaN },
    { receipts: [{ ...usageFixture().receipts[0], usage: { input_tokens: 0 } }] },
    { policy: { ...usageFixture().policy, pricing: { loaded: true } } },
  ])("rejects incomplete or invalid accounting evidence (%j)", async invalid => {
    const summary = { ...usageFixture(), ...invalid };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: summary }) }));
    await expect(fetchUsageSummary()).rejects.toThrow("unsupported or incomplete");
  });

  it.each([fetchUsageSummary, fetchModelLab])("rejects responses from an earlier Controller connection", async (read) => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
      setConfig({ url: "http://other-controller:8770", token: "fake.other.service" });
      setConfig({ url: "http://localhost:8770", token: serviceToken });
      return { ok: true, json: async () => ({ ok: true, data: usageFixture() }) };
    }));
    await expect(read()).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  });

  it("invalidates a pending usage response when credentials change on the same Controller", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
      setConfig({ url: "http://localhost:8770", token: "fake.changed.service" });
      return { ok: true, json: async () => ({ ok: true, data: usageFixture() }) };
    }));
    await expect(fetchUsageSummary()).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  });
});
