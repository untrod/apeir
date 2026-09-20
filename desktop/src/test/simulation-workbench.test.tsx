import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SimulationWorkbench } from "../components/SimulationWorkbench";
import {
  ApiError,
  approvalAction,
  analyzeSimulationRun,
  cancelSimulation,
  createSimulation,
  fetchScientificAnalyses,
  fetchScientificStatus,
  fetchSimulationRuns,
  fetchSimulations,
  fetchSimulationStatus,
  replaySimulation,
  runSimulation,
  type SimulationRecord,
  type SimulationRunRecord,
} from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    approvalAction: vi.fn(),
    analyzeSimulationRun: vi.fn(),
    cancelSimulation: vi.fn(),
    createSimulation: vi.fn(),
    fetchScientificAnalyses: vi.fn(),
    fetchScientificStatus: vi.fn(),
    fetchSimulationRuns: vi.fn(),
    fetchSimulations: vi.fn(),
    fetchSimulationStatus: vi.fn(),
    replaySimulation: vi.fn(),
    runSimulation: vi.fn(),
  };
});

const simulation: SimulationRecord = {
  schema_version: "nous.simulation/v1",
  simulation_id: "sim_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
  metric_schema: ["peak_temperature", "final_temperature", "safety_margin"],
  output_schema: ["json", "csv", "svg"],
  parameter_space: { solar_flux: [900, 1361] },
  numerical_tolerance: { absolute: 1e-9, relative: 1e-9 },
  created_at: "2026-09-01T00:00:00Z",
  state: "created",
  last_error: "",
  sha256: "a".repeat(64),
};

const run: SimulationRunRecord = {
  schema_version: "nous.simulation-run/v1",
  simulation_id: simulation.simulation_id,
  simulation_run_id: "simrun_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  event_run_id: "simulation-run-1",
  state: "completed",
  replay_of: "",
  started_at: "2026-09-01T00:00:00Z",
  completed_at: "2026-09-01T00:00:01Z",
  model_ref: simulation.model_ref,
  solver: simulation.solver,
  environment_id: "env_cccccccccccccccccccccccccccccccc",
  execution_attempts: [
    {
      attempt: 1,
      ok: true,
      exit_code: 0,
      timed_out: false,
      operation_run_id: "environment-run-1",
      artifact_id: "artifact-execution",
    },
  ],
  spec_sha256: simulation.sha256,
  case_count: 1,
  cases: [
    {
      case_id: 0,
      parameters: simulation.parameters,
      metrics: {
        peak_temperature: 301.5,
        final_temperature: 301.5,
        safety_margin: 71.65,
      },
      last_temperature_rate: 0.1,
    },
  ],
  result_digest: "d".repeat(64),
  artifacts: [
    {
      name: "series.csv",
      location: "artifacts/simulations/series.csv",
      size_bytes: 100,
      sha256: "e".repeat(64),
      artifact_id: "artifact-series",
    },
  ],
  manifest_artifact_id: "artifact-manifest",
  reproducibility: { seed: 42, code_hash: "f".repeat(64) },
  replay: {
    verified: true,
    matching_contract: true,
    within_tolerance: true,
    maximum_absolute_error: 0,
    absolute_tolerance: 1e-9,
    relative_tolerance: 1e-9,
  },
  sha256: "9".repeat(64),
};

describe("simulation workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchScientificStatus).mockResolvedValue({
      schema_version: "nous.scientific-runtime/v1",
      analysis_contract: "nous.scientific-analysis/v1",
      result_contract: "nous.scientific-result/v1",
      workspace: "C:/workspace",
      analyses: 0,
      completed: 0,
      failed: 0,
      providers: {
        numpy: { available: true, version: "2.4.5", capabilities: ["array"], error: "" },
        scipy: { available: true, version: "1.17.1", capabilities: ["ode-reference"], error: "" },
        pandas: { available: true, version: "3.0.3", capabilities: ["csv"], error: "" },
        sympy: { available: true, version: "1.14.0", capabilities: ["symbolic-equation"], error: "" },
        matplotlib: { available: true, version: "3.10.9", capabilities: ["png-visualization"], error: "" },
      },
      reference_tasks: [],
      event_authority: "EventStream",
      artifact_authority: "ArtifactRegistry",
      claim_authority: "ClaimEvidenceGraph",
      document_authority: "DocumentRuntime",
      defaults: {},
      evidence_level: "integrated-host",
    });
    vi.mocked(fetchScientificAnalyses).mockResolvedValue({ analyses: [], total: 0 });
    vi.mocked(fetchSimulationStatus).mockResolvedValue({
      schema_version: "nous.simulation-runtime/v1",
      simulation_contract: "nous.simulation/v1",
      simulation_run_contract: "nous.simulation-run/v1",
      environment_contract: "nous.environment/v1",
      workspace: "C:/workspace",
      simulations: 1,
      runs: 1,
      completed: 1,
      failed: 0,
      active: 0,
      built_in_models: [
        {
          model_ref: "spacecraft-thermal/v1",
          solver: "explicit-euler",
          deterministic: true,
          evidence_level: "integrated-host",
        },
      ],
      scientific_providers: { numpy: "2.0" },
      defaults: { network: "none" },
      limitations: [],
      event_authority: "EventStream",
      artifact_authority: "ArtifactRegistry",
      execution_authority: "EnvironmentRuntime",
    });
    vi.mocked(fetchSimulations).mockResolvedValue({
      simulations: [simulation],
      total: 1,
    });
    vi.mocked(fetchSimulationRuns).mockResolvedValue({ runs: [run], total: 1 });
    vi.mocked(analyzeSimulationRun).mockResolvedValue({} as never);
    vi.mocked(approvalAction).mockResolvedValue({});
  });

  it("shows reproducibility evidence and replay verification", async () => {
    vi.mocked(replaySimulation).mockResolvedValue(run);
    render(<SimulationWorkbench />);

    expect(await screen.findByText(/integrated-host on Windows 10/)).toBeInTheDocument();
    expect(await screen.findByText(/Replay verified/)).toBeInTheDocument();
    expect(screen.getByText("series.csv - artifacts/simulations/series.csv - eeeeeeeeeeee")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Replay and verify tolerance" }));
    await waitFor(() =>
      expect(replaySimulation).toHaveBeenCalledWith(run.simulation_run_id),
    );
  });

  it("retries the identical create request after one-use approval", async () => {
    vi.mocked(createSimulation)
      .mockRejectedValueOnce(
        new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", {
          approval_request_id: "apr_simulation",
        }),
      )
      .mockResolvedValueOnce(simulation);

    render(<SimulationWorkbench />);
    await screen.findByRole("option", { name: /spacecraft-thermal/ });
    fireEvent.click(
      screen.getByRole("button", { name: "Create reproducible simulation" }),
    );
    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and create" }));

    await waitFor(() =>
      expect(approvalAction).toHaveBeenCalledWith("apr_simulation", "approve"),
    );
    await waitFor(() => expect(createSimulation).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createSimulation).mock.calls[1][0]).toBe(
      vi.mocked(createSimulation).mock.calls[0][0],
    );
  });
});
