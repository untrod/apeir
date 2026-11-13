import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeveloperPlatform } from "../components/DeveloperPlatform";
import {
  fetchDeveloperExperiments, fetchDeveloperOverview, fetchDeveloperProjects, fetchDeveloperRuns,
  api, fetchModelLab, setConfig, type ModelLabSnapshot,
} from "../lib/api";
import { usageFixture } from "./usage-fixture";

vi.mock("../lib/api", async original => ({
  ...await original<typeof import("../lib/api")>(),
  fetchDeveloperOverview: vi.fn(), fetchDeveloperProjects: vi.fn(), fetchDeveloperRuns: vi.fn(),
  fetchDeveloperExperiments: vi.fn(), fetchModelLab: vi.fn(), api: vi.fn(),
}));
vi.mock("../components/DeveloperWorkbench", () => ({ DeveloperWorkbench: () => <div>Workbench fixture</div> }));
vi.mock("../components/ResearchEvidence", () => ({ ResearchEvidence: () => <div>Research fixture</div> }));
function modelLab(cost = 0.25, day = "2026-10-12"): ModelLabSnapshot {
  const accounting = usageFixture({ total_cost_usd: cost, reported_cost_usd: cost, day });
  accounting.receipts[0] = { ...accounting.receipts[0], cost_usd: cost };
  return {
    models: [], summary: { total: 0, enabled: 0, healthy: 0, recoverable_operations: 0 }, rankings: [],
    recent_observations: [], costs: [], evidence_status: "awaiting_observations",
    usage_accounting: accounting, usage_accounting_status: "available",
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  setConfig({ url: "http://localhost:8770", token: "fake.model.lab.service" });
  vi.mocked(fetchDeveloperOverview).mockResolvedValue({
    workspace: "fixture", projects: { total: 0, active: 0 }, runs: { total: 0, active: 0 },
    experiments: { total: 0, benchmarked: 0, production: 0 }, models: { total: 0, enabled: 0, healthy: 0, recoverable_operations: 0 },
  });
  vi.mocked(fetchDeveloperProjects).mockResolvedValue({ projects: [], total: 0 });
  vi.mocked(fetchDeveloperRuns).mockResolvedValue({ runs: [], total: 0 });
  vi.mocked(fetchDeveloperExperiments).mockResolvedValue({ experiments: [], results: [], summary: { total: 0, benchmarked: 0, production: 0 } });
  vi.mocked(fetchModelLab).mockResolvedValue(modelLab());
  vi.mocked(api).mockResolvedValue([]);
});

describe("Model Lab accounting read workflow", () => {
  it("separates model configuration, usage and records without losing edits or adding reads", async () => {
    const protection = vi.fn();
    const props = { modelsOnly: true, manageProviders: true, onDraftChange: protection };
    const view = render(<StrictMode><DeveloperPlatform {...props} /></StrictMode>);
    await waitFor(() => expect(fetchModelLab).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "Add Provider" }));
    fireEvent.change(screen.getByLabelText("Vendor model ID"), { target: { value: "unsaved-model" } });
    fireEvent.click(screen.getByRole("tab", { name: "Usage" }));
    expect(await screen.findByLabelText("Usage accounting")).toBeVisible();
    expect(screen.getByLabelText("Vendor model ID")).not.toBeVisible();
    expect(protection).toHaveBeenLastCalledWith(true);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Usage" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "Run records" })).toHaveFocus();
    fireEvent.click(screen.getByRole("tab", { name: "Connections" }));
    expect(screen.getByLabelText("Vendor model ID")).toHaveValue("unsaved-model");
    view.rerender(<StrictMode><DeveloperPlatform {...props} locale="zh" /></StrictMode>);
    expect(screen.getByRole("tab", { name: "连接配置" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("厂商模型 ID")).toHaveValue("unsaved-model");
    expect(fetchModelLab).toHaveBeenCalledOnce();
    expect(api).toHaveBeenCalledOnce();
  });
  it("loads a selected usage day from the existing API and returns to the current day", async () => {
    render(<DeveloperPlatform />);
    fireEvent.click(screen.getByRole("button", { name: /Model Lab/ }));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("$0.250000");
    vi.mocked(fetchModelLab).mockResolvedValueOnce(modelLab(0.5, "2026-10-11"));
    fireEvent.change(screen.getByLabelText("Usage day (UTC)"), { target: { value: "2026-10-11" } });
    await waitFor(() => expect(fetchModelLab).toHaveBeenLastCalledWith("2026-10-11"));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("2026-10-11");
    fireEvent.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(fetchModelLab).toHaveBeenLastCalledWith(undefined));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("2026-10-12");
  });

  it("clears prior billing if a new read fails", async () => {
    render(<DeveloperPlatform />);
    fireEvent.click(screen.getByRole("button", { name: /Model Lab/ }));
    await screen.findByLabelText("Usage accounting");
    vi.mocked(fetchModelLab).mockRejectedValueOnce(new Error("Usage read unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Spend UNKNOWN");
    expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument();
  });

  it("ignores an older refresh that completes after a newer one", async () => {
    let resolveOld!: (value: ModelLabSnapshot) => void;
    vi.mocked(fetchModelLab).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    render(<DeveloperPlatform />);
    fireEvent.click(screen.getByRole("button", { name: /Model Lab/ }));
    await waitFor(() => expect(fetchModelLab).toHaveBeenCalledOnce());
    vi.mocked(fetchModelLab).mockResolvedValueOnce(modelLab(0.5));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("$0.500000");
    await act(async () => { resolveOld(modelLab(0.25)); });
    expect(screen.getByLabelText("Usage accounting")).not.toHaveTextContent("$0.250000");
  });

  it("clears old evidence and rejects a late read after a Controller change", async () => {
    let resolveOld!: (value: ModelLabSnapshot) => void;
    vi.mocked(fetchModelLab).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    render(<DeveloperPlatform />);
    fireEvent.click(screen.getByRole("button", { name: /Model Lab/ }));
    await waitFor(() => expect(fetchModelLab).toHaveBeenCalledOnce());
    vi.mocked(fetchModelLab).mockResolvedValueOnce(modelLab(0.5));
    act(() => setConfig({ url: "http://other-controller:8770", token: "fake.other.service" }));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("$0.500000");
    await act(async () => { resolveOld(modelLab(0.25)); });
    expect(screen.getByLabelText("Usage accounting")).not.toHaveTextContent("$0.250000");
  });

  it("clears loaded usage during a credential change on the same Controller", async () => {
    render(<DeveloperPlatform />);
    fireEvent.click(screen.getByRole("button", { name: /Model Lab/ }));
    await screen.findByLabelText("Usage accounting");
    let resolveNew!: (value: ModelLabSnapshot) => void;
    vi.mocked(fetchModelLab).mockReturnValueOnce(new Promise(resolve => { resolveNew = resolve; }));
    act(() => setConfig({ url: "http://localhost:8770", token: "fake.new.service" }));
    expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading model evidence and usage accounting");
    await act(async () => { resolveNew(modelLab(0.5)); });
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("$0.500000");
  });
});
