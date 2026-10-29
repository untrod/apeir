import { afterEach, expect, it, vi } from "vitest";
import { governedStudioMutation, humanMutation, setConfig } from "../lib/api";
const response = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });
const forbidden = () => ({ ok: true, json: async () => ({ ok: false, error: { code: "NOUS_FORBIDDEN", message: "No human session" } }) });
afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });
it("probes identity without a mutation, uses a service request or exact human nonce", async () => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_STUDIO_GOV" });
  const fetcher = vi.fn().mockResolvedValueOnce(forbidden()).mockResolvedValueOnce(response({ saved: true })); vi.stubGlobal("fetch", fetcher);
  await governedStudioMutation("/api/v1/studio/extensions/configure", { enabled: false });
  expect(fetcher).toHaveBeenCalledTimes(2); expect(fetcher.mock.calls[0][1].method).toBeUndefined();
  expect(fetcher.mock.calls[1][1].headers["X-Control-Nonce"]).toBeUndefined();
  fetcher.mockClear(); fetcher.mockResolvedValueOnce(response({ subject_id: "human-owner", session_id: "original" })).mockResolvedValueOnce(response({ nonce: "original-body" })).mockResolvedValueOnce(response({ saved: true }));
  await governedStudioMutation("/api/v1/studio/extensions/configure", { enabled: false });
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(fetcher.mock.calls[2][1].headers["X-Control-Nonce"]).toBe("original-body");
  expect(JSON.parse(fetcher.mock.calls[1][1].body).body).toEqual(JSON.parse(fetcher.mock.calls[2][1].body));
});
it("never dispatches after a Controller switch during the read probe and never retries a lost effect response", async () => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_STUDIO_OLD" });
  const fetcher = vi.fn().mockImplementation(async () => { setConfig({ url: "http://localhost:8771", token: "APEIR_FAKE_ONLY_STUDIO_NEW" }); return forbidden(); }); vi.stubGlobal("fetch", fetcher);
  await expect(governedStudioMutation("/api/v1/studio/extensions/install", {})).rejects.toThrow("Controller changed");
  expect(fetcher).toHaveBeenCalledTimes(1);
  fetcher.mockClear(); fetcher.mockResolvedValueOnce(forbidden()).mockRejectedValueOnce(new Error("Response lost after request"));
  await expect(governedStudioMutation("/api/v1/studio/extensions/install", {})).rejects.toThrow("Response lost"); expect(fetcher).toHaveBeenCalledTimes(2);
});

it.each(["PATCH", "DELETE"] as const)("binds the original %s method and exact body to its human nonce", async method => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_METHOD_BINDING" });
  const fetcher = vi.fn().mockResolvedValueOnce(response({ subject_id: "owner" })).mockResolvedValueOnce(response({ nonce: "bound-original-method" })).mockResolvedValueOnce(response({ saved: true }));
  vi.stubGlobal("fetch", fetcher);
  const body = method === "PATCH" ? { model: "selected-version" } : {};
  await governedStudioMutation("/api/v1/providers/example", body, () => {}, method);
  const nonce = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(nonce).toEqual({ method, path: "/api/v1/providers/example", body });
  expect(fetcher.mock.calls[2][1]).toMatchObject({ method, body: JSON.stringify(body), headers: { "X-Control-Nonce": "bound-original-method" } });
});

it.each(["PATCH", "DELETE"] as const)("does not send %s after a Controller switch while issuing its nonce", async method => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_ORIGINAL_OWNER" });
  const fetcher = vi.fn().mockImplementation(async () => { setConfig({ url: "http://other:8770", token: "APEIR_FAKE_ONLY_REPLACEMENT" }); return response({ nonce: "obsolete" }); });
  vi.stubGlobal("fetch", fetcher);
  await expect(humanMutation("/api/v1/providers/example", {}, () => {}, method)).rejects.toMatchObject({ code: "NOUS_CONTROLLER_CHANGED" });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
