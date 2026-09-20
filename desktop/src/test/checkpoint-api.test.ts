import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchInspectorCheckpoints, setConfig } from "../lib/api";

describe("checkpoint inspector API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("uses the stable v1 checkpoint diagnostics endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: { status: "empty", latest: [] },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({
      url: "http://127.0.0.1:8770",
      token: "session-token",
    });

    await fetchInspectorCheckpoints(5, 12);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/inspector/checkpoints?limit=5&keep_latest_per_task=12",
      expect.objectContaining({
        headers: expect.objectContaining({
        Authorization: "Bearer session-token", // security-scan: fixture
        }),
      }),
    );
  });
});
