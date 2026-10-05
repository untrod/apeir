import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsConsole, type OperationsSnapshot } from "../components/OperationsConsole";

const fixture: OperationsSnapshot = {
  agents: [], works: [{ work_id: "uncertain-effect-1", state: "UNKNOWN", execution_capability: "device.firmware.update" }], workflows: [], nodes: [{ node_id: "jetson-sim-1", state: "ONLINE" }], devices: [{ device_id: "actuator-sim-1", lifecycle: "AVAILABLE" }], approvals: [{ request_id: "approval-original-1", status: "PENDING" }], grants: [], credential_leases: [], artifacts: [], evidence: [{ work_id: "uncertain-effect-1", receipt: { status: "SUCCEEDED" }, effect_verification: { verdict: "UNKNOWN" } }], activity: [], incidents: [], health: { degraded: true, components: [] }, controls: { actions: ["approve_once", "deny", "interrupt", "reconcile"] },
};
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
describe("Operations Console", () => {
  it("shows real backend state and never treats uncertain effects as success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) }));
    render(<OperationsConsole />);
    expect(await screen.findByText("uncertain-effect-1")).toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByText("Interrupt")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "approvals" }));
    expect(screen.getByText("Approve Once")).toBeDisabled();
    expect(screen.getByText("Deny")).toBeDisabled();
    fireEvent.click(screen.getByText("approval-original-1"));
    expect(screen.getByLabelText("Evidence details")).toHaveTextContent("approval-original-1");
  });
  it("reports unavailable backend without inventing healthy data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Controller disconnected")));
    render(<OperationsConsole />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Controller disconnected"));
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.queryByText("HEALTHY")).not.toBeInTheDocument();
    expect(screen.getByText("Waiting for authoritative runtime data.")).toBeInTheDocument();
  });
});
