import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createDeveloperExperiment,
  evaluateDeveloperExperiment,
  fetchDeveloperOverview,
  setConfig,
} from "../lib/api";

describe("developer platform API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("uses stable v1 developer endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { workspace: "D:/workspace" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    await fetchDeveloperOverview();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/developer/overview",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer session-token" }) }), // security-scan: fixture
    );
  });

  it("sends experiment definitions and measured score arrays", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { experiment_id: "exp_1" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    await createDeveloperExperiment({ hypothesis: "h", baseline_name: "a", candidate_name: "b" });
    await evaluateDeveloperExperiment("exp_1", [1, 2, 3, 4, 5], [2, 3, 4, 5, 6]);

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8770/api/v1/developer/experiments/exp_1/evaluate",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ baseline_scores: [1, 2, 3, 4, 5], candidate_scores: [2, 3, 4, 5, 6] }),
      }),
    );
  });
});
