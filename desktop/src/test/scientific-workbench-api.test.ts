import { afterEach, describe, expect, it, vi } from "vitest";

import {
  analyzeSimulationRun,
  fetchScientificAnalyses,
  fetchScientificStatus,
  setConfig,
} from "../lib/api";

describe("scientific workbench API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("uses authenticated scientific status, list, and governed analysis endpoints", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "token" });

    await fetchScientificStatus();
    await fetchScientificAnalyses();
    await analyzeSimulationRun("simrun_1", 0.05);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8770/api/v1/scientific/status",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer token" }), // security-scan: fixture
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8770/api/v1/scientific/analyses",
      expect.anything(),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8770/api/v1/scientific/analyses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          simulation_run_id: "simrun_1",
          analysis_type: "spacecraft-thermal-analysis/v1",
          reference_solver: "scipy.solve_ivp",
          reference_tolerance_kelvin: 0.05,
          report_formats: ["docx", "pdf"],
        }),
      }),
    );
  });
});
