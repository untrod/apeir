import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsConsole, type OperationsSnapshot } from "../components/OperationsConsole";
import { setConfig, type ModelLabSnapshot } from "../lib/api";
import { usageFixture } from "./usage-fixture";

vi.mock("../components/DeveloperWorkbench", () => ({
  DeveloperWorkbench: ({ onDraftChange }: { onDraftChange: (draft: boolean) => void }) =>
    <input aria-label="Workspace draft fixture" defaultValue="" onChange={() => onDraftChange(true)} />,
}));

const snapshot: OperationsSnapshot = {
  agents: [], works: [], workflows: [], nodes: [], devices: [], approvals: [], grants: [],
  credential_leases: [], artifacts: [], evidence: [], activity: [], incidents: [],
  health: { degraded: false, components: [] }, controls: { actions: [] },
};
const modelLab = (): ModelLabSnapshot => ({
  models: [], summary: { total: 0, enabled: 0, healthy: 0, recoverable_operations: 0 },
  rankings: [], recent_observations: [], costs: [], evidence_status: "awaiting_observations",
  usage_accounting: usageFixture(), usage_accounting_status: "available",
});
const envelope = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });
const serviceToken = "test-console-usage-service";

beforeEach(() => setConfig({ url: "http://localhost:8770", token: serviceToken }));
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); });

describe("public Operations Console model usage entry", () => {
  it("opens the authenticated read-only Model Lab with bilingual navigation and no mutation views", async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => envelope(url.endsWith("/model-lab") ? modelLab() : snapshot));
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    fireEvent.click(screen.getByRole("button", { name: "Model Lab / Usage" }));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("Receipt: receipt-original · request: request-original");
    expect(screen.getByRole("tab", { name: "Model Lab / Usage" })).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("button", { name: /Create project|Create experiment|Save atomically|Run in sandbox/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Search records" })).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith("http://localhost:8770/api/v1/developer/model-lab", expect.objectContaining({
      credentials: "include", headers: expect.objectContaining({ Authorization: `Bearer ${serviceToken}` }),
    }));
    expect(fetcher.mock.calls.every(([, options]) => !options.method || options.method === "GET")).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => /developer\/(projects|runs|experiments|overview)|\/chat/.test(url))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Change language" }));
    expect(screen.getByRole("button", { name: "模型实验室 / 用量" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "模型实验室 / 用量" })).toHaveAttribute("aria-selected", "true");
    expect(localStorage.getItem("apeir.operations.layout.v1")).not.toContain("receipt-original");
  });

  it("preserves the existing unsaved workspace draft while inspecting usage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => envelope(url.endsWith("/model-lab") ? modelLab() : snapshot)));
    render(<OperationsConsole />);
    fireEvent.click(screen.getByRole("button", { name: "workspace" }));
    fireEvent.change(screen.getByLabelText("Workspace draft fixture"), { target: { value: "Private unsaved draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Model Lab / Usage" }));
    await screen.findByLabelText("Usage accounting");
    expect(screen.getByRole("button", { name: "Close workspace view" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "workspace" }));
    expect(screen.getByLabelText("Workspace draft fixture")).toHaveValue("Private unsaved draft");
    expect(localStorage.getItem("apeir.operations.layout.v1")).not.toContain("Private unsaved draft");
  });

  it("clears previously loaded billing when the Controller credentials change and the read fails", async () => {
    let modelReads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (!url.endsWith("/model-lab")) return envelope(snapshot);
      if (modelReads++ === 0) return envelope(modelLab());
      throw new Error("PRIVATE_ACCOUNTING_FAILURE");
    }));
    render(<OperationsConsole />);
    fireEvent.click(screen.getByRole("button", { name: "Model Lab / Usage" }));
    await screen.findByLabelText("Usage accounting");
    act(() => setConfig({ url: "http://localhost:8770", token: "fake.changed.console.service" }));
    await waitFor(() => expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument());
    expect(await screen.findByRole("alert")).toHaveTextContent("Spend UNKNOWN");
    expect(screen.queryByText(/PRIVATE_ACCOUNTING_FAILURE/)).not.toBeInTheDocument();
  });
});
