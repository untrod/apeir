import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OperationsConsole, type OperationsSnapshot } from "../components/OperationsConsole";

const fixture: OperationsSnapshot = {
  agents: [], works: [{ work_id: "uncertain-effect-1", state: "UNKNOWN", execution_capability: "device.firmware.update" }], workflows: [], nodes: [{ node_id: "jetson-sim-1", state: "ONLINE" }], devices: [{ device_id: "actuator-sim-1", lifecycle: "AVAILABLE" }], approvals: [{ request_id: "approval-original-1", status: "PENDING" }], grants: [], credential_leases: [], artifacts: [], evidence: [{ work_id: "uncertain-effect-1", receipt: { status: "SUCCEEDED" }, effect_verification: { verdict: "UNKNOWN" } }], activity: [], incidents: [], health: { degraded: true, components: [] }, controls: { actions: ["approve_once", "deny", "interrupt", "reconcile"] },
};
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); window.history.replaceState({}, "", "/"); });
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
  it("restores a cookie session and signs out using the exact bound nonce", async () => {
    vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
    const fetcher = vi.fn().mockImplementation(async (url: string, options: RequestInit) => {
      const data = url.endsWith("/human/session") ? { subject_id: "oidc:enrolled:alice", expires_at: Math.floor(Date.now() / 1000) + 600 }
        : url.endsWith("/human/nonce") ? { nonce: "m35q.fake.single.use.nonce" }
        : url.endsWith("/human/logout") ? { revoked: true } : fixture;
      expect(options.credentials).toBe("include");
      return { ok: true, json: async () => ({ ok: true, data }) };
    });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    expect(await screen.findByText("Human: oidc:enrolled:alice")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "approvals" }));
    expect(screen.getByText("Approve Once")).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByText("Approve Once")).toBeDisabled());
    const nonce = fetcher.mock.calls.find(([url]) => url.endsWith("/human/nonce"));
    expect(JSON.parse(nonce?.[1].body)).toEqual({ method: "POST", path: "/api/v1/control/human/logout", body: {} });
    const logout = fetcher.mock.calls.find(([url]) => url.endsWith("/human/logout"));
    expect(logout?.[1].headers["X-Control-Nonce"]).toBe("m35q.fake.single.use.nonce");
    expect(sessionStorage.getItem("apeir.human.pkce")).toBeNull();
  });
  it("rejects mismatched callback state without submitting the code", async () => {
    window.history.replaceState({}, "", "/?code=m35q.fake.code&state=wrong-state");
    sessionStorage.setItem("apeir.human.pkce", JSON.stringify({ state: "expected-state", verifier: "m35q.fake.verifier", endpoint: "http://127.0.0.1:8770" }));
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Authentication state mismatch");
    expect(fetcher.mock.calls.some(([url]) => url.endsWith("/human/session"))).toBe(false);
    expect(sessionStorage.getItem("apeir.human.pkce")).toBeNull();
    expect(window.location.search).toBe("");
  });
  it("keeps controls disabled for expired restored sessions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => ({ ok: true, data: url.endsWith("/human/session") ? { subject_id: "oidc:enrolled:alice", expires_at: 1 } : fixture }) })));
    render(<OperationsConsole />);
    expect(await screen.findByText("uncertain-effect-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "approvals" }));
    expect(screen.getByText("Approve Once")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
  it("discards a denied IdP callback without exchanging a proof", async () => {
    window.history.replaceState({}, "", "/?error=access_denied&state=old-state");
    sessionStorage.setItem("apeir.human.pkce", "m35q.fake.pending.proof");
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Human authentication was rejected");
    expect(fetcher.mock.calls.some(([url]) => url.endsWith("/human/session"))).toBe(false);
    expect(sessionStorage.getItem("apeir.human.pkce")).toBeNull();
    expect(window.location.search).toBe("");
  });
});
