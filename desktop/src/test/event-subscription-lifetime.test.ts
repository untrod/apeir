import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setConfig, subscribeRunEvents, subscribeRuntimeEvents } from "../lib/api";

const event = (id: string, sequence: number) => ({ event_id: id, sequence, event_type: "work.updated", source: "runtime" });
const response = (events = [event("original", 7)]) => ({ ok: true, json: async () => ({ ok: true, data: { events, next_after_sequence: 7 } }) });
const subscriptions = [
  { name: "run", open: (receive: () => void) => { const sub = subscribeRunEvents("original-run", receive, { intervalMs: 500 }); return { ...sub, position: () => sub.cursor() }; } },
  { name: "runtime", open: (receive: () => void) => { const sub = subscribeRuntimeEvents(receive, { intervalMs: 500 }); return { ...sub, position: () => sub.lastEventId() }; } },
];
beforeEach(() => { vi.useFakeTimers(); setConfig({ url: "http://localhost:8770", token: "events.fake.original" }); });
afterEach(() => { vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });

describe.each(subscriptions)("$name subscription lifetime", ({ open }) => {
  it("discards an in-flight page after close without advancing its cursor", async () => {
    let finish!: (value: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(resolve => { finish = resolve; })));
    const receive = vi.fn(), sub = open(receive), original = sub.position();
    sub.close(); finish(response());
    await vi.advanceTimersByTimeAsync(0);
    expect(receive).not.toHaveBeenCalled(); expect(sub.position()).toBe(original);
    expect(vi.getTimerCount()).toBe(0);
  });
  it.each(["token", "ABA"] as const)("does not poll another connection after %s change", async change => {
    const fetcher = vi.fn().mockResolvedValue(response()); vi.stubGlobal("fetch", fetcher);
    const receive = vi.fn(), sub = open(receive);
    await vi.advanceTimersByTimeAsync(0);
    expect(receive).toHaveBeenCalledTimes(1);
    const original = sub.position();
    if (change === "token") setConfig({ url: "http://localhost:8770", token: "events.fake.changed" });
    else { setConfig({ url: "https://other.example.test", token: "events.fake.other" }); setConfig({ url: "http://localhost:8770", token: "events.fake.original" }); }
    await vi.advanceTimersByTimeAsync(1500);
    expect(fetcher).toHaveBeenCalledTimes(1); expect(receive).toHaveBeenCalledTimes(1);
    expect(sub.position()).toBe(original); expect(vi.getTimerCount()).toBe(0); sub.close();
  });
  it("stops within a batch when its first callback closes the subscription", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([event("first", 1), event("second", 2)])));
    let sub!: ReturnType<typeof open>;
    const receive = vi.fn(() => sub.close()); sub = open(receive);
    await vi.advanceTimersByTimeAsync(0);
    expect(receive).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0);
  });
  it("clears its scheduled timer immediately on close", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response()));
    const sub = open(vi.fn()); await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1); sub.close(); expect(vi.getTimerCount()).toBe(0);
  });
  it("continues a transient read failure only on the original connection", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("Transient read failure")).mockResolvedValue(response()); vi.stubGlobal("fetch", fetcher);
    const receive = vi.fn(), sub = open(receive);
    await vi.advanceTimersByTimeAsync(500);
    expect(fetcher).toHaveBeenCalledTimes(2); expect(receive).toHaveBeenCalledTimes(1); sub.close();
  });
});

describe("global event history integrity", () => {
  it.each(["duplicate IDs", "changed last ID", "unavailable cursor"] as const)("stops and reports %s before publication", async failure => {
    const rows = failure === "duplicate IDs" ? [event("same", 0), event("same", 0)] : [event("original", 0)];
    const fetcher = vi.fn().mockResolvedValue({ ok: failure !== "unavailable cursor", status: 409, json: async () => failure === "unavailable cursor"
      ? { ok: false, error: { code: "NOUS_EVENT_CURSOR_UNAVAILABLE", message: "Reload current state" } }
      : { ok: true, data: { events: rows, latest_event_id: failure === "changed last ID" ? "other" : "same" } } });
    vi.stubGlobal("fetch", fetcher);
    const receive = vi.fn(), onError = vi.fn();
    const sub = subscribeRuntimeEvents(receive, { intervalMs: 500, onError });
    await vi.advanceTimersByTimeAsync(1500);
    expect(receive).not.toHaveBeenCalled(); expect(onError).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledTimes(1); expect(sub.lastEventId()).toBe("");
    expect(vi.getTimerCount()).toBe(0); sub.close();
  });
});

describe("run event connection feedback", () => {
  it("reports a failed read and recovery without submitting any task", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error("private transport detail")).mockResolvedValue(response());
    vi.stubGlobal("fetch", fetcher);
    const onStatus = vi.fn(), receive = vi.fn();
    const sub = subscribeRunEvents("original-run", receive, { intervalMs: 500, onStatus });
    await vi.advanceTimersByTimeAsync(0);
    expect(onStatus.mock.calls).toEqual([["reconnecting"]]);
    await vi.advanceTimersByTimeAsync(500);
    expect(onStatus.mock.calls).toEqual([["reconnecting"], ["live"]]);
    expect(receive).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls.every(([url]) => String(url).includes("/original-run/events?"))).toBe(true);
    sub.close();
  });
  it("never reports a late failure for a retired Controller", async () => {
    let reject!: (reason: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((_resolve, fail) => { reject = fail; })));
    const onStatus = vi.fn();
    const sub = subscribeRunEvents("original-run", vi.fn(), { intervalMs: 500, onStatus });
    setConfig({ url: "https://other.example.test", token: "events.fake.other" });
    reject(new Error("old Controller"));
    await vi.advanceTimersByTimeAsync(1000);
    expect(onStatus).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    sub.close();
  });
});
