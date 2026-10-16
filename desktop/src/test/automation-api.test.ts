import { afterEach, describe, expect, it, vi } from "vitest";
import { addAutomation, approvalAction, automationAction, fetchAutomationHistory, fetchAutomations, getConfig, setConfig } from "../lib/api";

const response = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); setConfig({ url: "http://localhost:8770", token: "" }); });
describe("Automation current human API", () => {
  it("nonce-binds exact structured create and original trigger/run bodies and reads bounded original history", async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => response(url.endsWith("/nonce") ? { nonce: "bound-nonce" } : {}));
    vi.stubGlobal("fetch", fetcher);
    const request = { adapter: "simulated-reality" as const, name: "simulation", trigger: "schedule" as const, due_at: "2026-10-13T01:00:00Z", firmware_version: "2.0.0" };
    await addAutomation(request);
    await automationAction("trigger", "auto/original", { trigger_key: "due:2026-10-13T01:00:00Z" });
    for (const action of ["resume", "reconcile", "cancel"]) await automationAction(action, "auto/original", { run_id: "run-original" });
    await approvalAction("approval/original", "deny");
    for (let n = 0; n < 12; n += 2) {
      const nonceOptions = fetcher.mock.calls[n][1];
      const mutationOptions = fetcher.mock.calls[n + 1][1];
      const nonceBody = JSON.parse(nonceOptions.body);
      expect(JSON.parse(mutationOptions.body)).toEqual(nonceBody.body);
      expect(fetcher.mock.calls[n + 1][0]).toBe(getConfig().url + nonceBody.path);
      expect(mutationOptions.headers["X-Control-Nonce"]).toBe("bound-nonce");
      expect(mutationOptions.credentials).toBe("include");
    }
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({ action: "trigger", automation_id: "auto/original", trigger_key: "due:2026-10-13T01:00:00Z" });
    expect(JSON.parse(fetcher.mock.calls[9][1].body)).toEqual({ action: "cancel", automation_id: "auto/original", run_id: "run-original" });
    expect(fetcher.mock.calls[11][0]).toContain("/approvals/approval%2Foriginal/deny");
    fetcher.mockResolvedValueOnce(response({ automation_id: "auto/original", history: [], total: 0 }));
    await fetchAutomationHistory("auto/original");
    expect(fetcher.mock.calls[12][0]).toContain("/automations/auto%2Foriginal/history?limit=50");
  });
  it("does not dispatch when the nonce is missing or the human session changes", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({})); vi.stubGlobal("fetch", fetcher);
    await expect(automationAction("resume", "auto", { run_id: "original" })).rejects.toThrow("nonce is unavailable");
    expect(fetcher).toHaveBeenCalledTimes(1);
    let current = true;
    fetcher.mockImplementation(async () => { current = false; return response({ nonce: "stale" }); });
    await expect(automationAction("cancel", "auto", { run_id: "original" }, () => { if (!current) throw new Error("Human session changed"); })).rejects.toThrow("Human session changed");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it.each(["url", "token", "ABA"])("blocks stale %s between nonce and approval/mutation", async change => {
    setConfig({ url: "https://controller.example.test", token: "fake-original" });
    const original = getConfig();
    const fetcher = vi.fn().mockImplementation(async () => {
      setConfig({ url: change === "token" ? original.url : "https://other.example.test", token: "fake-changed" });
      if (change === "ABA") setConfig(original);
      return response({ nonce: "stale" });
    }); vi.stubGlobal("fetch", fetcher);
    await expect(approvalAction("original", "approve")).rejects.toThrow("Controller changed");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("rejects a response from a changed connection and never retries a lost trigger response", async () => {
    const fetcher = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/nonce")) return response({ nonce: "bound" });
      throw new Error("response lost");
    }); vi.stubGlobal("fetch", fetcher);
    await expect(automationAction("trigger", "auto-original", { trigger_key: "manual:original" })).rejects.toThrow("response lost");
    expect(fetcher).toHaveBeenCalledTimes(2);
    fetcher.mockImplementation(async () => { setConfig({ url: "https://next.example.test", token: "" }); return response({ automations: [], total: 0 }); });
    await expect(fetchAutomations()).rejects.toThrow("Controller changed");
    expect(fetcher).toHaveBeenCalledTimes(3);
  });
  it("rejects mismatched persisted history instead of offering actions on another Automation", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ automation_id: "another", history: [], total: 0 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(fetchAutomationHistory("original")).rejects.toThrow("history binding");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("preserves legacy config-only input under the same exact current-human nonce contract", async () => {
    const legacy = { name: "Legacy config", trigger: "schedule", schedule: "0 * * * *", action: "free-text intent" };
    const fetcher = vi.fn().mockImplementation(async (url: string) => response(url.endsWith("/nonce") ? { nonce: "legacy-bound" } : { ...legacy, qualification: "UNQUALIFIED", execution_qualified: false }));
    vi.stubGlobal("fetch", fetcher);
    const result = await addAutomation(legacy);
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ method: "POST", path: "/api/v1/automations/add", body: legacy });
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual(legacy);
    expect(fetcher.mock.calls[1][1].headers["X-Control-Nonce"]).toBe("legacy-bound");
    expect(result.qualification).toBe("UNQUALIFIED");
    expect(fetcher.mock.calls.some(([url]) => url.endsWith("/action"))).toBe(false);
  });

});
