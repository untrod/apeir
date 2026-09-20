import { afterEach, describe, expect, it, vi } from "vitest";
import { setConfig, testModel } from "../lib/api";

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
