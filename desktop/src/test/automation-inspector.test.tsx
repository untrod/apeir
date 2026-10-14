import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AutomationInspector } from "../components/AutomationInspector";
import { OperationsConsole } from "../components/OperationsConsole";
import { setConfig, type AutomationRun, type AutomationView } from "../lib/api";
const human = { subject_id: "human-original", expires_at: Date.now() / 1000 + 300 };
const item: AutomationView = { id: "auto-original", name: "Firmware simulation", trigger: "manual", action: "device.firmware.update", enabled: true, created_at: "2026-10-13", adapter: "simulated-reality", qualification: "SIMULATED_TEMPLATE", simulated: true, execution_scope: "runtime-service", kernel_traversed: false, workflow_id: "workflow-original", definition_digest: "digest-original" };
const run: AutomationRun = { automation_id: item.id, run_id: "run-original", state: "waiting_approval", trigger_key: "manual:original", cancellation_requested: false, reconciliation_required: false, outputs: { mutate: { approval_request_id: "approval-original", work_id: "work-original" } }, works: [{ work_id: "work-original" }], simulated: true, execution_scope: "runtime-service", kernel_traversed: false };
const approvals = [{ request_id: "approval-original", status: "PENDING" }];
const ok = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); sessionStorage.clear(); setConfig({ url: "http://localhost:8770", token: "" }); });
function backend(initial: AutomationRun[] = [run]) {
  let history = initial;
  const fetcher = vi.fn().mockImplementation(async (url: string, options: RequestInit = {}) => {
    if (url.endsWith("/nonce")) return ok({ nonce: "bound-human-nonce" });
    if (url.endsWith("/automations")) return ok({ automations: [item, { ...item, id: "legacy", name: "Free text", qualification: "UNQUALIFIED", adapter: undefined }], total: 2 });
    if (url.includes("/history?")) return ok({ automation_id: item.id, history, total: history.length });
    if (url.endsWith("/action")) {
      const body = JSON.parse(String(options.body));
      if (body.action === "trigger") { history = [{ ...run, trigger_key: body.trigger_key }]; throw new Error("trigger response lost"); }
      if (body.action === "cancel") history = [{ ...run, state: "cancelled", cancellation_requested: true }];
      return ok(history[0]);
    }
    if (url.includes("/approvals/")) return ok({ request_id: "approval-original" });
    throw new Error(`Unexpected request ${url}`);
  });
  vi.stubGlobal("fetch", fetcher); return fetcher;
}
const mutations = (fetcher: ReturnType<typeof backend>) => fetcher.mock.calls.filter(([url]) => url.endsWith("/action") || url.includes("/approvals/")).map(([url, options]) => ({ url, body: JSON.parse(String(options.body)) }));
describe("Automation Desktop original-state consumer", () => {
  it("opens the real Console pane without reading private Automations while signed out", () => {
    const snapshot = { agents: [], works: [], workflows: [], nodes: [], devices: [], approvals: [], grants: [], credential_leases: [], artifacts: [], evidence: [], activity: [], incidents: [], health: { degraded: true, components: [] }, controls: { actions: [] } };
    const fetcher = vi.fn().mockImplementation(async (url: string) => { if (url.endsWith("/human/session")) throw new Error("signed out"); return ok(snapshot); });
    vi.stubGlobal("fetch", fetcher); render(<OperationsConsole />);
    fireEvent.click(screen.getByRole("button", { name: "automations" }));
    expect(screen.getByLabelText("Automation inspector")).toHaveTextContent("kernel_traversed=false");
    expect(screen.getByRole("button", { name: "Create simulated Automation" })).toBeDisabled();
    expect(fetcher.mock.calls.some(([url]) => url.includes("/automations"))).toBe(false);
  });
  it.each(["Approve Once", "Deny"])("%s decides exact approval then resumes only the original Automation/run", async decision => {
    const fetcher = backend(); render(<AutomationInspector human={human} approvals={approvals} />);
    fireEvent.click(await screen.findByRole("button", { name: decision }));
    await waitFor(() => expect(mutations(fetcher)).toHaveLength(2));
    expect(mutations(fetcher)).toEqual([
      { url: expect.stringContaining(`/approvals/approval-original/${decision === "Deny" ? "deny" : "approve"}`), body: {} },
      { url: expect.stringContaining("/automations/action"), body: { action: "resume", automation_id: item.id, run_id: run.run_id } },
    ]);
    expect(within(screen.getByText("Free text").closest("article")!).queryByRole("button")).not.toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.getItem("approval-original")).toBeNull();
  });
  it("recovers lost trigger response from persisted original key/run without another trigger", async () => {
    const fetcher = backend([]); render(<AutomationInspector human={human} approvals={approvals} />);
    const button = await screen.findByRole("button", { name: "Trigger manual run" });
    await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button);
    await screen.findByLabelText("Automation run run-original");
    expect(mutations(fetcher)).toHaveLength(1);
    const original = mutations(fetcher)[0].body.trigger_key;
    expect(original).toMatch(/^manual:/);
    expect(screen.getByText(`Original trigger: ${original}`)).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("trigger response lost");
    fireEvent.click(screen.getByRole("button", { name: "Refresh Automation history" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh Automation history" })).toBeEnabled());
    expect(mutations(fetcher)).toHaveLength(1);
  });
  it("cancels exact original run and disables further admission", async () => {
    const fetcher = backend(); render(<AutomationInspector human={human} approvals={approvals} />);
    fireEvent.click(await screen.findByRole("button", { name: "Cancel original run" }));
    await screen.findByText("run-original · cancelled");
    expect(mutations(fetcher)[0].body).toEqual({ action: "cancel", automation_id: item.id, run_id: run.run_id });
    expect(screen.getByRole("button", { name: "Resume original run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Approve Once" })).toBeDisabled();
  });
  it("reconciles UNKNOWN evidence and blocks resume of an uncertain effect", async () => {
    const fetcher = backend([{ ...run, state: "unknown", reconciliation_required: true }]); render(<AutomationInspector human={human} approvals={[]} />);
    const reconcile = await screen.findByRole("button", { name: "Reconcile original run" });
    expect(screen.getByRole("button", { name: "Resume original run" })).toBeDisabled(); fireEvent.click(reconcile);
    await waitFor(() => expect(mutations(fetcher)).toHaveLength(1));
    expect(mutations(fetcher)[0].body).toEqual({ action: "reconcile", automation_id: item.id, run_id: run.run_id });
  });
  it.each(["logout", "controller ABA"])("fails closed when %s occurs during approval nonce", async change => {
    const fetcher = backend(); const view = render(<AutomationInspector human={human} approvals={approvals} />);
    await screen.findByRole("button", { name: "Approve Once" });
    let release: (result: unknown) => void = () => {};
    const nonce = new Promise(resolve => { release = resolve; });
    fetcher.mockImplementation((url: string) => url.endsWith("/nonce") ? nonce : Promise.resolve(ok({ automations: [item], total: 1 })));
    fireEvent.click(screen.getByRole("button", { name: "Approve Once" }));
    if (change === "logout") view.rerender(<AutomationInspector human={null} approvals={[]} />);
    else { setConfig({ url: "https://other.example.test", token: "fake" }); setConfig({ url: "http://localhost:8770", token: "" }); }
    await act(async () => { release(ok({ nonce: "stale" })); });
    expect(mutations(fetcher)).toHaveLength(0);
    expect(screen.queryByLabelText("Automation run run-original")).not.toBeInTheDocument();
  });
  it("permission revocation clears private history without replacement work", async () => {
    const fetcher = backend(); render(<AutomationInspector human={human} approvals={approvals} />);
    await screen.findByRole("button", { name: "Resume original run" });
    fetcher.mockResolvedValue({ ok: false, json: async () => ({ ok: false, error: { code: "PERMISSION_DENIED", message: "Current permission revoked" } }) });
    fireEvent.click(screen.getByRole("button", { name: "Resume original run" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Outcome unconfirmed");
    expect(screen.queryByLabelText("Automation run run-original")).not.toBeInTheDocument();
    expect(mutations(fetcher)).toHaveLength(0);
  });
  it("creates the exact structured one-shot UTC intent and consumes only its original due key", async () => {
    const scheduled = { ...item, trigger: "schedule", due_at: "2026-01-01T00:00:00.000000+00:00" };
    let records: AutomationView[] = [];
    const fetcher = vi.fn().mockImplementation(async (url: string, options: RequestInit = {}) => {
      if (url.endsWith("/nonce")) return ok({ nonce: "bound" });
      if (url.endsWith("/automations")) return ok({ automations: records, total: records.length });
      if (url.includes("/history?")) return ok({ automation_id: item.id, history: [], total: 0 });
      if (url.endsWith("/add")) { records = [scheduled]; return ok(scheduled); }
      if (url.endsWith("/action")) return ok({ ...run, trigger_key: JSON.parse(String(options.body)).trigger_key });
      throw new Error("Unexpected route");
    });
    vi.stubGlobal("fetch", fetcher); render(<AutomationInspector human={human} approvals={[]} />);
    await screen.findByText("No authoritative Automations loaded.");
    fireEvent.change(screen.getByLabelText("Automation name"), { target: { value: "One-shot firmware" } });
    fireEvent.change(screen.getByLabelText("Automation trigger"), { target: { value: "schedule" } });
    fireEvent.change(screen.getByLabelText("UTC due timestamp"), { target: { value: scheduled.due_at } });
    fireEvent.click(screen.getByRole("button", { name: "Create simulated Automation" }));
    const due = await screen.findByRole("button", { name: "Consume original due trigger" });
    await waitFor(() => expect(due).toBeEnabled());
    const create = fetcher.mock.calls.find(([url]) => url.endsWith("/add"))!;
    expect(JSON.parse(String(create[1].body))).toEqual({ adapter: "simulated-reality", name: "One-shot firmware", firmware_version: "2.0.0", trigger: "schedule", due_at: scheduled.due_at });
    fireEvent.click(due);
    await waitFor(() => expect(mutations(fetcher)).toHaveLength(1));
    expect(mutations(fetcher)[0].body).toEqual({ action: "trigger", automation_id: item.id, trigger_key: `due:${scheduled.due_at}` });
  });
  it("retains a lost original trigger key and blocks replacement if no persisted run is visible yet", async () => {
    const fetcher = backend([]);
    const originalImplementation = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, options: RequestInit = {}) => {
      if (url.endsWith("/action")) throw new Error("response lost before history available");
      return originalImplementation(url, options);
    });
    render(<AutomationInspector human={human} approvals={[]} />);
    const button = await screen.findByRole("button", { name: "Trigger manual run" });
    fireEvent.click(button);
    const message = await screen.findByRole("status");
    expect(message).toHaveTextContent("Unconfirmed original trigger: manual:");
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh Automation history" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh Automation history" })).toBeEnabled());
    expect(mutations(fetcher)).toHaveLength(1);
    expect(button).toBeDisabled();
  });
  it("reads original history after approval response loss without automatically resuming or replacing Work", async () => {
    const fetcher = backend();
    const originalImplementation = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url: string, options: RequestInit = {}) => {
      if (url.includes("/approvals/")) throw new Error("approval response lost");
      return originalImplementation(url, options);
    });
    render(<AutomationInspector human={human} approvals={approvals} />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve Once" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("approval response lost");
    expect(mutations(fetcher)).toEqual([{ url: expect.stringContaining("/approvals/approval-original/approve"), body: {} }]);
    expect(screen.getByLabelText("Automation run run-original")).toBeInTheDocument();
  });

});
