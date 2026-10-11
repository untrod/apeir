import { afterEach, describe, expect, it, vi } from "vitest";

import {
  approvalAction,
  createEnvironment,
  getConfig,
  destroyEnvironment,
  runEnvironment,
  setConfig,
  startEnvironment,
  stopEnvironment,
  type EnvironmentCreateRequest,
} from "../lib/api";

describe("environment inspector API", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

  it("uses typed governed environment lifecycle endpoints", async () => {
    const request: EnvironmentCreateRequest = {
      environment_type: "oci_container",
      provider: "oci",
      image: "ubuntu:24.04",
      cpu_limit: 1,
      memory_limit_mb: 512,
      gpu_policy: "none",
      network_policy: { mode: "none", allowed_hosts: [] },
      filesystem_policy: { read_only_root: true, temporary_filesystem_mb: 64 },
      device_policy: { gpu: "none", devices: [] },
      workspace_mounts: [],
      lifetime_seconds: 3600,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: {} }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "token" });

    await createEnvironment(request);
    await startEnvironment("env_1");
    await runEnvironment("env_1", { argv: ["python", "-V"] });
    await stopEnvironment("env_1");
    await destroyEnvironment("env_1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/api/v1/environments", expect.objectContaining({ credentials: "omit", method: "POST", body: JSON.stringify(request), headers: expect.objectContaining({ Authorization: `Bearer ${getConfig().token}` }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/api/v1/environments/env_1/start", expect.objectContaining({ credentials: "omit", method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://127.0.0.1:8770/api/v1/environments/env_1/run", expect.objectContaining({ credentials: "omit", method: "POST", body: JSON.stringify({ argv: ["python", "-V"] }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://127.0.0.1:8770/api/v1/environments/env_1/stop", expect.objectContaining({ credentials: "omit", method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://127.0.0.1:8770/api/v1/environments/env_1", expect.objectContaining({ credentials: "omit", method: "DELETE" }));
  });
  it("does not send an approval when the human nonce is absent", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: {} }) });
    vi.stubGlobal("fetch", fetcher);
    await expect(approvalAction("apr_original", "approve")).rejects.toThrow("Trusted human approval nonce");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it("binds a human nonce and refuses a Controller change before decision", async () => {
    setConfig({ url: "http://127.0.0.1:8770", token: "fake-service" });
    const fetcher = vi.fn().mockImplementation(async () => {
      setConfig({ url: "https://other.example.test", token: "other-fake-service" });
      return { ok: true, json: async () => ({ ok: true, data: { nonce: "original-human-nonce" } }) };
    });
    vi.stubGlobal("fetch", fetcher);
    await expect(approvalAction("apr_original", "approve")).rejects.toThrow("Controller changed");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

});
