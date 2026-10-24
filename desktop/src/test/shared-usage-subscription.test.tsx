import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { setConfig } from "../lib/api";
import { useCostSummary } from "../store/hooks";
import { usageFixture } from "./usage-fixture";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });
const reply = () => ({ ok: true, json: async () => ({ ok: true, data: usageFixture() }) });

it("shares one usage request and one poll across independent widgets and retires the last reader", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-shared-usage" });
  const request = vi.fn().mockImplementation(async () => reply()); vi.stubGlobal("fetch", request);
  const a = renderHook(() => useCostSummary()); const b = renderHook(() => useCostSummary());
  await act(async () => { await Promise.resolve(); });
  expect(request).toHaveBeenCalledTimes(1);
  expect(a.result.current.status).toBe("ready"); expect(b.result.current.status).toBe("ready");
  a.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(request).toHaveBeenCalledTimes(2);
  b.unmount();
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(request).toHaveBeenCalledTimes(2);
});

it("pauses hidden readers without losing the original accounting provenance", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-shared-paused" });
  const request = vi.fn().mockImplementation(async () => reply()); vi.stubGlobal("fetch", request);
  let active = true;
  const view = renderHook(() => useCostSummary(() => active));
  await act(async () => { await Promise.resolve(); }); expect(request).toHaveBeenCalledTimes(1);
  active = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); }); expect(request).toHaveBeenCalledTimes(1);
  expect(view.result.current.summary?.receipts[0].receipt_id).toBe("receipt-original");
  active = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(request).toHaveBeenCalledTimes(2);
  view.unmount();
});
