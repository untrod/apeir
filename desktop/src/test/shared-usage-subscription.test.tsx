import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { setConfig } from "../lib/api";
import { useCostSummary } from "../store/hooks";
import { usageFixture } from "./usage-fixture";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });
const reply = () => ({ ok: true, json: async () => ({ ok: true, data: usageFixture() }) });

it("shares the original usage read across development-mode subscription replay", async () => {
  setConfig({ url: "http://127.0.0.1:8770", token: "fake-strict-usage" });
  const request = vi.fn().mockImplementation(async () => reply()); vi.stubGlobal("fetch", request);
  const view = renderHook(() => useCostSummary(), { wrapper: StrictMode });
  await act(async () => { await Promise.resolve(); });
  expect(request).toHaveBeenCalledTimes(1);
  expect(view.result.current.summary?.receipts[0].receipt_id).toBe("receipt-original");
  view.unmount();
});

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

it("shares each historical day without replacing today's original accounting", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-history-dedup" });
  const request = vi.fn(async (url: string) => ({ ok: true, json: async () => ({ ok: true, data: usageFixture({ day: new URL(url).searchParams.get("day") || "2026-10-12" }) }) }));
  vi.stubGlobal("fetch", request);
  const today = renderHook(() => useCostSummary());
  const a = renderHook(() => useCostSummary(() => true, "2000-01-01"));
  const b = renderHook(() => useCostSummary(() => true, "2000-01-01"));
  await act(async () => { await Promise.resolve(); });
  expect(request).toHaveBeenCalledTimes(2);
  expect(today.result.current.summary?.day).toBe("2026-10-12");
  expect(a.result.current.summary?.day).toBe("2000-01-01"); expect(b.result.current.summary?.day).toBe("2000-01-01");
  a.unmount(); await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(request).toHaveBeenCalledTimes(4);
  today.unmount(); b.unmount();
});

it("refuses an incorrect history date instead of showing a different ledger", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-history-wrong-date" });
  vi.stubGlobal("fetch", vi.fn(async () => reply()));
  const view = renderHook(() => useCostSummary(() => true, "2000-01-01"));
  await act(async () => { await Promise.resolve(); });
  expect(view.result.current.status).toBe("unavailable"); expect(view.result.current.summary).toBeNull();
  expect(view.result.current.error).toContain("UNKNOWN"); view.unmount();
});

it("bounds simultaneous visible dates and admits a waiting date after another pauses", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-history-quota" });
  const request = vi.fn(async (url: string) => ({ ok: true, json: async () => ({ ok: true, data: usageFixture({ day: new URL(url).searchParams.get("day")! }) }) }));
  vi.stubGlobal("fetch", request); let firstActive = true;
  const readers = Array.from({ length: 9 }, (_, i) => renderHook(() => useCostSummary(() => i !== 0 || firstActive, `2000-01-0${i + 1}`)));
  await act(async () => { await Promise.resolve(); });
  expect(request).toHaveBeenCalledTimes(8);
  expect(readers[8].result.current.status).toBe("unavailable"); expect(readers[8].result.current.error).toContain("eight");
  firstActive = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(request).toHaveBeenCalledTimes(16); expect(readers[8].result.current.summary?.day).toBe("2000-01-09");
  readers.forEach(reader => reader.unmount());
});

it("a retired Controller's historical reply cannot restore private accounting", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-history-a" });
  let finish!: (value: unknown) => void;
  const request = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue({ ok: true, json: async () => ({ ok: true, data: usageFixture({ day: "2000-01-01", requests: 2 }) }) });
  vi.stubGlobal("fetch", request);
  const view = renderHook(() => useCostSummary(() => true, "2000-01-01"));
  await act(async () => { await Promise.resolve(); });
  expect(request).toHaveBeenCalledTimes(1);
  setConfig({ url: "http://127.0.0.1:8771", token: "fake-history-b" });
  await act(async () => { await Promise.resolve(); });
  expect(view.result.current.summary?.requests).toBe(2);
  await act(async () => { finish({ ok: true, json: async () => ({ ok: true, data: usageFixture({ day: "2000-01-01", requests: 99 }) }) }); });
  expect(view.result.current.summary?.requests).toBe(2); view.unmount();
});

it("an explicit current-date alias cannot display a Controller's different UTC day", async () => {
  vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-history-clock" });
  const selected = new Date().toISOString().slice(0, 10);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, data: usageFixture({ day: "1999-01-01" }) }) })));
  const view = renderHook(() => useCostSummary(() => true, selected));
  await act(async () => { await Promise.resolve(); });
  expect(view.result.current.status).toBe("unavailable"); expect(view.result.current.summary).toBeNull();
  expect(view.result.current.error).toContain("UTC date"); view.unmount();
});
