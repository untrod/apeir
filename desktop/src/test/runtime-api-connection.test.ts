import { afterEach, describe, expect, it, vi } from "vitest";
import { api, setConfig } from "../lib/api";

afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

describe("shared Runtime API response binding", () => {
  it.each(["token", "ABA"] as const)("rejects %s changes before publishing a response and never retries", async change => {
    setConfig({ url: "http://localhost:8770", token: "api.fake.original" });
    let finish!: (value: unknown) => void;
    const cancel = vi.fn().mockResolvedValue(undefined);
    const json = vi.fn().mockResolvedValue({ ok: true, data: { private: "old-context" } });
    const fetcher = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const result = api("/api/v1/conversations");
    const check = expect(result).rejects.toThrow("Controller changed");
    if (change === "token") setConfig({ url: "http://localhost:8770", token: "api.fake.changed" });
    else {
      setConfig({ url: "https://temporary.example.test", token: "api.fake.temporary" });
      setConfig({ url: "http://localhost:8770", token: "api.fake.original" });
    }
    finish({ ok: true, json, body: { cancel }, bodyUsed: false });
    await check;
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(json).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("rechecks the original connection after a delayed JSON body", async () => {
    setConfig({ url: "http://localhost:8770", token: "api.fake.original" });
    let finish!: (value: unknown) => void;
    const json = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json, bodyUsed: true }));
    const result = api("/api/v1/conversations");
    const check = expect(result).rejects.toThrow("Controller changed");
    await vi.waitFor(() => expect(json).toHaveBeenCalledTimes(1));
    setConfig({ url: "http://localhost:8770", token: "api.fake.changed" });
    finish({ ok: true, data: { private: "old-context" } });
    await check;
  });
});
