import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperationsConsole, type OperationsSnapshot } from "../components/OperationsConsole";

const fixture: OperationsSnapshot = {
  agents: [], works: [{ work_id: "uncertain-effect-1", state: "UNKNOWN", execution_capability: "device.firmware.update" }], workflows: [], nodes: [{ node_id: "jetson-sim-1", state: "ONLINE" }], devices: [{ device_id: "actuator-sim-1", lifecycle: "AVAILABLE" }], approvals: [{ request_id: "approval-original-1", status: "PENDING" }], grants: [], credential_leases: [], artifacts: [], evidence: [{ work_id: "uncertain-effect-1", receipt: { status: "SUCCEEDED" }, effect_verification: { verdict: "UNKNOWN" } }], activity: [], incidents: [], health: { degraded: true, components: [] }, controls: { actions: ["approve_once", "deny", "interrupt", "reconcile"] },
};
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); window.history.replaceState({}, "", "/"); });
describe("Operations Console", () => {
  it("opens the existing Environment API view without model requests or duplicated state", async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => ({ ok: true, data: url.endsWith("/environments/status") ? { environments: 0, providers: [] } : url.endsWith("/environments") ? { environments: [], total: 0 } : fixture }) }));
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    await screen.findByRole("button", { name: "uncertain-effect-1" });
    fireEvent.click(screen.getByRole("button", { name: "environments" }));
    expect(await screen.findByText("Create environment")).toBeInTheDocument();
    await screen.findByText(/0 environments/);
    expect(screen.getByRole("tab", { name: "environments" })).toHaveAttribute("aria-selected", "true");
    const calls = fetcher.mock.calls.map(([url]) => url);
    expect(calls.some(url => url.endsWith("/environments/status"))).toBe(true);
    expect(calls.some(url => url.endsWith("/environments"))).toBe(true);
    expect(calls.some(url => /model|completion|chat/.test(url))).toBe(false);
    expect(localStorage.getItem("apeir.operations.layout.v1")).not.toContain("environment_id");
  });
  it("restores bounded layout without persisting identity or Runtime evidence", async () => {
    const data = { ...fixture, activity: [{ sequence: 1, event_type: "work.reconciled", work_id: "uncertain-effect-1" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data }) }));
    const first = render(<OperationsConsole />);
    fireEvent.click(await screen.findByRole("button", { name: "uncertain-effect-1" }));
    fireEvent.change(screen.getByLabelText("Resize evidence inspector"), { target: { value: "520" } });
    fireEvent.click(screen.getByRole("button", { name: "Show activity · 1" }));
    fireEvent.click(screen.getByRole("button", { name: /^nodes/ }));
    const saved = JSON.parse(localStorage.getItem("apeir.operations.layout.v1") || "{}");
    expect(saved).toEqual({ tabs: ["works", "nodes"], active: "nodes", inspectorWidth: 520, activityOpen: true, locale: "en" });
    expect(JSON.stringify(saved)).not.toContain("uncertain-effect-1");
    first.unmount();
    render(<OperationsConsole />);
    expect(screen.getByRole("tab", { name: "nodes" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: "jetson-sim-1" })).toBeInTheDocument();
    expect(screen.getByLabelText("Activity panel")).toHaveTextContent("work.reconciled");
    expect(screen.queryByLabelText("Evidence details")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "jetson-sim-1" }));
    expect(screen.getByLabelText("Resize evidence inspector")).toHaveValue("520");
  });
  it("searches real records, navigates tabs by keyboard and localizes navigation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) }));
    render(<OperationsConsole />);
    await screen.findByRole("button", { name: "uncertain-effect-1" });
    fireEvent.keyDown(window, { ctrlKey: true, key: "f" });
    expect(screen.getByRole("textbox", { name: "Search records" })).toHaveFocus();
    fireEvent.change(screen.getByRole("textbox", { name: "Search records" }), { target: { value: "absent-node" } });
    expect(screen.getByText("No matching records.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^nodes/ }));
    expect(screen.getByRole("textbox", { name: "Search records" })).toHaveValue("");
    fireEvent.keyDown(screen.getByRole("tab", { name: "nodes" }), { key: "ArrowLeft" });
    expect(screen.getByRole("tab", { name: "works" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "uncertain-effect-1" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change language" }));
    expect(screen.getByRole("main")).toHaveAttribute("lang", "zh-CN");
    expect(screen.getByRole("heading", { name: "执行与现实" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "节点" })).toBeInTheDocument();
  });
  it("keeps Node trust independent of reported connectivity", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { ...fixture, nodes: [{ node_id: "candidate", connectivity_state: "ONLINE", trust_status: "REVOKED" }] } }) }));
    render(<OperationsConsole />);
    await screen.findByRole("button", { name: "uncertain-effect-1" });
    fireEvent.click(screen.getByRole("button", { name: /^nodes/ }));
    const row = screen.getByRole("button", { name: "candidate" }).closest("article")!;
    expect(within(row).getByText("Trust").nextElementSibling).toHaveTextContent("REVOKED");
    expect(within(row).getByText("Connection").nextElementSibling).toHaveTextContent("ONLINE");
  });
  it("refreshes or removes the selected evidence instead of retaining a stale record", async () => {
    let data = fixture;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => ({ ok: true, json: async () => ({ ok: true, data }) })));
    render(<OperationsConsole />);
    fireEvent.click(await screen.findByRole("button", { name: "uncertain-effect-1" }));
    data = { ...fixture, works: [{ ...fixture.works[0], state: "VERIFIED", effect_verification: { verdict: "MISMATCH" } }] };
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByLabelText("Work execution chain")).toHaveTextContent("MISMATCH"));
    data = { ...fixture, works: [] };
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.queryByLabelText("Evidence details")).not.toBeInTheDocument());
  });
  it("rejects unsafe Controller addresses without leaking credentials or making a request", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    await screen.findByRole("button", { name: "uncertain-effect-1" });
    const count = fetcher.mock.calls.length;
    for (const address of ["http://remote.example", "https://user:fake@remote.example", "https://remote.example?credential=fake", "https://remote.example#token"]) {
      fireEvent.change(screen.getByRole("textbox", { name: "API URL" }), { target: { value: address } });
      fireEvent.submit(screen.getByRole("textbox", { name: "API URL" }).closest("form")!);
      expect(screen.getByRole("alert")).toHaveTextContent("Controller requires HTTPS");
      expect(fetcher.mock.calls.length).toBe(count);
      expect(screen.getByRole("alert")).not.toHaveTextContent(address);
    }
  });
  it("ignores an earlier successful snapshot after a later refresh failure", async () => {
    let complete: (value: unknown) => void = () => {};
    const earlier = new Promise(resolve => { complete = resolve; });
    let count = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      if (url.endsWith("/human/session")) return Promise.reject(new Error("No human session"));
      return ++count === 1 ? earlier : Promise.reject(new Error("Latest refresh disconnected"));
    }));
    render(<OperationsConsole />);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Latest refresh disconnected");
    await act(async () => { complete({ ok: true, json: async () => ({ ok: true, data: { ...fixture, health: { degraded: false, components: [] } } }) }); });
    expect(screen.queryByText("HEALTHY")).not.toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });
  it("clears stale healthy state after a refresh disconnect", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: { ...fixture, health: { degraded: false, components: [] } } }) });
    vi.stubGlobal("fetch", fetcher);
    render(<OperationsConsole />);
    expect(await screen.findByText("HEALTHY")).toBeInTheDocument();
    fetcher.mockRejectedValue(new Error("Controller disconnected after snapshot"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Controller disconnected after snapshot");
    expect(screen.queryByText("HEALTHY")).not.toBeInTheDocument();
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "uncertain-effect-1" })).not.toBeInTheDocument();
  });
  it("separates actual receipt, observations and UNKNOWN verification in the Work inspector", async () => {
    const data = { ...fixture, devices: [{ device_id: "sim-device", metadata: { simulation: true } }], works: [{
      work_id: "original-work", state: "VERIFIED", intent: "Update simulated firmware", target_resource_id: "sim-device", assigned_node: "original-node",
      provenance: { agent_session_id: "original-session", plan_id: "original-plan", workflow_run_id: "original-workflow", operation_id: "original-work" },
      execution_arguments: { authorization_id: "original-authorization" },
      result_summary: { remote_execution_receipt: { operation_id: "original-work", status: "SUCCEEDED" } },
      effect_verification: { verdict: "UNKNOWN", observation_ids: ["independent-observation"] }, evidence_refs: ["artifact://sha256/evidence"],
    }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data }) }));
    render(<OperationsConsole />);
    expect(await screen.findByText("SIMULATED")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "original-work" }));
    const chain = within(screen.getByLabelText("Work execution chain"));
    expect(chain.getByText("original-authorization")).toBeInTheDocument();
    expect(chain.getByText("original-plan")).toBeInTheDocument();
    expect(chain.getByText("independent-observation")).toBeInTheDocument();
    expect(chain.getByText("Effect verification").nextElementSibling).toHaveTextContent("UNKNOWN");
    expect(chain.queryByText("COMMITTED")).not.toBeInTheDocument();
    expect(screen.getByText("Reconcile")).toBeDisabled();
  });
  it("keeps missing evidence unknown and provides instructions without fabricated demo records", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: fixture }) }));
    render(<OperationsConsole />);
    fireEvent.click(await screen.findByRole("button", { name: "uncertain-effect-1" }));
    const chain = screen.getByLabelText("Work execution chain");
    expect(chain).toHaveTextContent("UNKNOWN");
    expect(chain).toHaveTextContent("Not recorded");
    expect(chain).not.toHaveTextContent("MATCH");
    expect(screen.getByText("Execution scope not recorded")).toBeInTheDocument();
    expect(screen.getByText("Run the verified simulated demo")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview-firmware-update" })).not.toBeInTheDocument();
  });
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

describe("Secure Node onboarding", () => {
  beforeEach(() => { vi.stubGlobal("EventSource", class { addEventListener() {} close() {} }); });
  const publicKey = "ab".repeat(32);
  const pending = { request_id: "pair-1", status: "PENDING", node_id: "node-new", public_key: publicKey };
  const data = { ...fixture, controller_public_key: "cd".repeat(32), pairings: [pending] };
  it("keeps pairing observe-only without human authentication", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data }) }));
    render(<OperationsConsole />);
    await screen.findByRole("button", { name: "uncertain-effect-1" });
    fireEvent.click(screen.getByRole("button", { name: "pairings" }));
    expect(screen.getByRole("button", { name: "Trust this Node once" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Deny" })).toBeDisabled();
    expect(screen.getByText(/Node: node-new/)).toHaveTextContent(publicKey);
  });
  it("binds the human nonce and decision to the exact backend Node key", async () => {
    const requests: { url: string; body?: Record<string, unknown> }[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string, options: RequestInit = {}) => {
      const body = options.body ? JSON.parse(String(options.body)) : undefined;
      requests.push({ url, body });
      const response = url.endsWith("/human/session") ? { subject_id: "verified-human", expires_at: Math.floor(Date.now() / 1000) + 600 } : url.endsWith("/human/nonce") ? { nonce: "bound-nonce" } : data;
      return { ok: true, json: async () => ({ ok: true, data: response }) };
    }));
    render(<OperationsConsole />);
    await screen.findByText("Human: verified-human");
    fireEvent.click(screen.getByRole("button", { name: "pairings" }));
    fireEvent.click(screen.getByRole("button", { name: "Trust this Node once" }));
    await waitFor(() => expect(requests.some(request => request.url.endsWith("/operations/actions"))).toBe(true));
    const mutation = requests.find(request => request.url.endsWith("/operations/actions"))!;
    expect(mutation.body).toEqual({ kind: "pairings", action: "approve_once", target_id: "pair-1", node_id: "node-new", public_key: publicKey });
    const nonce = requests.find(request => request.url.endsWith("/human/nonce"))!;
    expect(nonce.body?.body).toEqual(mutation.body);
    expect(JSON.stringify(localStorage)).not.toContain(publicKey);
  });
  it("requires Controller confirmation and keeps the invitation code out of storage", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      const response = url.endsWith("/human/session") ? { subject_id: "verified-human", expires_at: Math.floor(Date.now() / 1000) + 600 } : url.endsWith("/human/nonce") ? { nonce: "bound-nonce" } : url.endsWith("/operations/actions") ? { request_id: "pair-issued", pairing_code: "ABCD2345", expires_at: Math.floor(Date.now() / 1000) + 300, relay_url: "wss://controller.example:9770", controller_public_key: data.controller_public_key } : data;
      return { ok: true, json: async () => ({ ok: true, data: response }) };
    }));
    render(<OperationsConsole />);
    await screen.findByText("Human: verified-human");
    fireEvent.click(screen.getByRole("button", { name: "Add Node" }));
    const create = screen.getByRole("button", { name: "Create one-time invitation" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Relay URL"), { target: { value: "wss://controller.example:9770" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Confirm Controller identity" }));
    fireEvent.click(create);
    await screen.findByText("ABCD2345");
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain("ABCD2345");
    fireEvent.click(screen.getByRole("button", { name: "Hide code and inspect pairing" }));
    expect(screen.queryByText("ABCD2345")).not.toBeInTheDocument();
  });
});

describe("Controlled Skill Center", () => {
  const entry = { skill_key: "catalog:review-skill:source", skill_id: "review-skill", name: "Review Skill", description: "Inspect bounded evidence", version: "1.0.0", digest: "sha256:" + "a".repeat(64), provider: "catalog", source: "/reviewed/catalog/review-skill", catalog_source: "/reviewed/catalog", package_source: "/reviewed/catalog/review-skill", risk: "high", trust: "unverified", requested_capabilities: ["device.state.read"], dependencies: [], compatibility: "linux", installable: true, enabled: true, installed: false, artifact_ref: "" };
  beforeEach(() => { vi.stubGlobal("EventSource", class { close() {} addEventListener() {} }); });
  it("shows canonical identity conflicts and blocks alias management", async () => {
    const conflicting = { ...entry, provider: "installed", skill_key: "installed:review-skill:import", installed: true, identity_status: "AMBIGUOUS" };
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      requests.push(url);
      const data = url.endsWith("/human/session") ? { subject_id: "fake-human", expires_at: Date.now() / 1000 + 300 } : { ...fixture, skills: [conflicting] };
      return { ok: true, json: async () => ({ ok: true, data }) };
    }));
    render(<OperationsConsole />);
    await screen.findByText("Human: fake-human");
    fireEvent.click(screen.getByRole("button", { name: /^skills/ }));
    fireEvent.click(screen.getByRole("button", { name: conflicting.skill_key }));
    expect(screen.getByRole("status")).toHaveTextContent("Conflicting installed Skill identities");
    for (const name of ["Load instructions", "Disable", "Uninstall"]) expect(screen.getByRole("button", { name })).toBeDisabled();
    expect(requests.some(url => url.endsWith("/operations/actions") || url.endsWith("/human/nonce"))).toBe(false);
  });
  it("requires exact-package review and submits existing human nonce actions", async () => {
    let skills = [entry];
    const requests: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string, options?: RequestInit) => {
      let data: unknown = { ...fixture, skills };
      if (url.endsWith("/human/session")) data = { subject_id: "fake-oidc-human", expires_at: Date.now() / 1000 + 300 };
      if (url.endsWith("/human/nonce")) data = { nonce: "existing-human-nonce" };
      if (url.endsWith("/operations/actions")) {
        const body = JSON.parse(String(options?.body)); requests.push(body);
        expect(options?.headers).toMatchObject({ "X-Control-Nonce": "existing-human-nonce" });
        if (body.action === "install") skills = [entry, { ...entry, skill_key: "installed:review-skill", provider: "installed", installed: true, artifact_ref: "sha256:" + "b".repeat(64) }];
        if (body.action === "disable") skills = skills.map(row => row.provider === "installed" ? { ...row, enabled: false } : row);
        data = body.action === "load" ? { skill: { ok: true, skill: { ...entry, instructions: "Inspect original evidence, never self-approve." } }, execution_performed: false } : { authority: "none", execution_performed: false };
      }
      return { ok: true, json: async () => ({ ok: true, data }) };
    }));
    render(<OperationsConsole />);
    await screen.findByText("Human: fake-oidc-human");
    fireEvent.click(screen.getByRole("button", { name: /^skills/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review package" }));
    const install = screen.getByRole("button", { name: "Install reviewed package" });
    expect(install).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed this exact/ }));
    fireEvent.click(install);
    await screen.findByRole("button", { name: "installed:review-skill" });
    expect(requests[0]).toEqual({ kind: "skills", action: "install", target_id: entry.skill_key, version: entry.version, digest: entry.digest, catalog_source: entry.catalog_source, package_source: entry.package_source });
    fireEvent.click(screen.getByRole("button", { name: "installed:review-skill" }));
    fireEvent.click(screen.getByRole("button", { name: "Load instructions" }));
    expect(await screen.findByLabelText("Loaded Skill instructions")).toHaveTextContent("never self-approve");
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Load instructions" })).toBeDisabled());
    expect(screen.queryByLabelText("Loaded Skill instructions")).not.toBeInTheDocument();
    expect(localStorage.getItem("apeir.operations.layout.v1")).not.toContain("never self-approve");
  });
  it("shows backend denial without claiming installation or executing instructions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => url.endsWith("/operations/actions") ? { ok: false, error: { code: "NOUS_FORBIDDEN", message: "Catalog digest changed; review again" } } : { ok: true, data: url.endsWith("/human/session") ? { subject_id: "fake-human", expires_at: Date.now() / 1000 + 300 } : url.endsWith("/human/nonce") ? { nonce: "fake-nonce" } : { ...fixture, skills: [entry] } } })));
    render(<OperationsConsole />);
    await screen.findByText("Human: fake-human");
    fireEvent.click(screen.getByRole("button", { name: /^skills/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review package" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed this exact/ }));
    fireEvent.click(screen.getByRole("button", { name: "Install reviewed package" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Catalog digest changed");
    expect(screen.queryByRole("button", { name: "installed:review-skill" })).not.toBeInTheDocument();
  });
  it("adds, refreshes and removes exact catalogs through the original nonce body", async () => {
    const source = "https://catalog.example.test/catalog.json";
    const requests: { url: string; body?: Record<string, unknown> }[] = [];
    let catalogs: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string, options: RequestInit = {}) => {
      const body = options.body ? JSON.parse(String(options.body)) : undefined;
      requests.push({ url, body });
      if (url.endsWith("/operations/actions")) {
        catalogs = body.action === "catalog_remove" ? [] : [{ source, remote: true }];
      }
      const data = url.endsWith("/human/session") ? { subject_id: "fake-human", expires_at: Date.now() / 1000 + 300 } : url.endsWith("/human/nonce") ? { nonce: "catalog-body-nonce" } : { ...fixture, skills: [], skill_catalogs: catalogs };
      return { ok: true, json: async () => ({ ok: true, data }) };
    }));
    render(<OperationsConsole />);
    await screen.findByText("Human: fake-human");
    fireEvent.click(screen.getByRole("button", { name: /^skills/ }));
    const add = screen.getByRole("button", { name: "Add catalog" });
    fireEvent.change(screen.getByRole("textbox", { name: "Catalog HTTPS URL" }), { target: { value: source } });
    expect(add).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "I confirm this exact catalog URL." }));
    fireEvent.click(add);
    await screen.findByRole("button", { name: "Refresh catalog" });
    fireEvent.click(screen.getByRole("button", { name: "Refresh catalog" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Remove catalog" })).not.toBeDisabled());
    fireEvent.click(screen.getByRole("button", { name: "Remove catalog" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Refresh catalog" })).not.toBeInTheDocument());
    const actions = requests.filter(request => request.url.endsWith("/operations/actions"));
    expect(actions.map(request => request.body?.action)).toEqual(["catalog_add", "catalog_refresh", "catalog_remove"]);
    const nonces = requests.filter(request => request.url.endsWith("/human/nonce"));
    actions.forEach((request, index) => {
      expect(request.body).toEqual({ kind: "skills", action: request.body?.action, target_id: source, catalog_source: source });
      expect(nonces[index].body?.body).toEqual(request.body);
    });
    expect(requests.every(request => !request.url.startsWith(source))).toBe(true);
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain(source);
  });
  it("clears the package review when the backend package URL changes with the same digest", async () => {
    let skill = { ...entry, source: "https://packages.example.test/old.zip", package_source: "https://packages.example.test/old.zip", catalog_source: "https://catalog.example.test/catalog.json" };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({ ok: true, json: async () => ({ ok: true, data: url.endsWith("/human/session") ? { subject_id: "fake-human", expires_at: Date.now() / 1000 + 300 } : { ...fixture, skills: [skill] } }) })));
    render(<OperationsConsole />);
    await screen.findByText("Human: fake-human");
    fireEvent.click(screen.getByRole("button", { name: /^skills/ }));
    fireEvent.click(screen.getByRole("button", { name: "Review package" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /I reviewed this exact/ }));
    expect(screen.getByRole("button", { name: "Install reviewed package" })).not.toBeDisabled();
    skill = { ...skill, source: "https://packages.example.test/new.zip", package_source: "https://packages.example.test/new.zip" };
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Install reviewed package" })).toBeDisabled());
    expect(screen.getByRole("checkbox", { name: /I reviewed this exact/ })).not.toBeChecked();
  });

});
