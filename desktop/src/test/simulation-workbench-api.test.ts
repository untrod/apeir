import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelSimulation,
  createSimulation,
  replaySimulation,
  runSimulation,
  setConfig,
  type SimulationCreateRequest,
} from "../lib/api";

describe("simulation workbench API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("uses typed governed simulation lifecycle endpoints", async () => {
    const request: SimulationCreateRequest = {
      model_ref: "spacecraft-thermal/v1",
      environment_type: "local_sandbox",
      provider: "local-sandbox",
      initial_state: { initial_temperature: 290 },
      boundary_conditions: { external_temperature: 3 },
      parameters: {
        solar_flux: 1361,
        surface_area: 2,
        emissivity: 0.8,
        thermal_capacity: 10000,
      },
      solver: "explicit-euler",
      time_step: 1,
      duration: 60,
      seed: 42,
      resource_budget: {
        cpu_limit: 1,
        memory_limit_mb: 512,
        wall_time_seconds: 300,
        max_cases: 8,
        max_retries: 0,
        max_output_bytes: 20000000,
      },
      network_policy: { mode: "none" },
      metric_schema: ["peak_temperature"],
      output_schema: ["json", "csv", "svg"],
      parameter_space: {},
      numerical_tolerance: { absolute: 1e-9, relative: 1e-9 },
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "token" });

    await createSimulation(request);
    await runSimulation("sim_1");
    await replaySimulation("simrun_1");
    await cancelSimulation("sim_1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8770/api/v1/simulations",
      expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8770/api/v1/simulations/sim_1/run",
      expect.objectContaining({ method: "POST", body: "{}" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8770/api/v1/simulations/runs/simrun_1/replay",
      expect.objectContaining({ method: "POST", body: "{}" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8770/api/v1/simulations/sim_1/cancel",
      expect.objectContaining({ method: "POST", body: "{}" }),
    );
  });
});
