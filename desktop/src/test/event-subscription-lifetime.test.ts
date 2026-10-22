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
