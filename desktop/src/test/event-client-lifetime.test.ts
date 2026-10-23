import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eventClient } from "../store/eventClient";
import { entityStore } from "../store/entityStore";
import { fetchEventStream, setConfig } from "../lib/api";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), fetchEventStream: vi.fn() }));
const page = (events: ReturnType<typeof event>[]) => ({ events, count: events.length, domain: "runtime", latest_event_id: events.at(-1)?.event_id || "" });
const event = (id: string) => ({ event_id: id, sequence: 1, event_type: "qualification.event", domain: "runtime", source: "runtime", timestamp: "2026-10-22T00:00:00Z", payload: {}, metadata: {}, dedup_key: id });
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); entityStore.clearStore(); setConfig({ url: "http://localhost:8770", token: "events.fake.original" }); });
afterEach(() => { eventClient.stop(); entityStore.clearStore(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); });

describe("existing EventClient consumer lifetime", () => {
  it("does not publish an old page or create a second loop after stop/start", async () => {
    let finish!: (value: Awaited<ReturnType<typeof fetchEventStream>>) => void;
    vi.mocked(fetchEventStream).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue(page([]));
    const ingest = vi.spyOn(entityStore, "ingestEvent");
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    eventClient.stop(); eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);
    const calls = vi.mocked(fetchEventStream).mock.calls.length;
    finish(page([event("retired-page")])); await vi.advanceTimersByTimeAsync(0);
    expect(ingest).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchEventStream).toHaveBeenCalledTimes(calls + 1);
  });
  it("rejects a pending mocked transport page after credential replacement", async () => {
    let finish!: (value: Awaited<ReturnType<typeof fetchEventStream>>) => void;
    vi.mocked(fetchEventStream).mockResolvedValue(page([])).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const ingest = vi.spyOn(entityStore, "ingestEvent");
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    setConfig({ url: "http://localhost:8770", token: "events.fake.changed" });
    finish(page([event("other-identity-page")])); await vi.advanceTimersByTimeAsync(2000);
    expect(ingest).not.toHaveBeenCalled(); expect(fetchEventStream).toHaveBeenCalledTimes(1);
  });
  it("does not continue a retired multi-page backfill", async () => {
    entityStore.ingestEvent(event("seed"));
    let finish!: (value: Awaited<ReturnType<typeof fetchEventStream>>) => void;
    vi.mocked(fetchEventStream).mockResolvedValue(page([])).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const ingest = vi.spyOn(entityStore, "ingestEvent");
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    eventClient.stop();
    finish(page(Array.from({ length: 200 }, (_, n) => ({ ...event(`retired-${n}`), sequence: n + 2 }))));
    await vi.advanceTimersByTimeAsync(0);
    expect(ingest).not.toHaveBeenCalled(); expect(fetchEventStream).toHaveBeenCalledTimes(1);
  });
  it("drains the current original backfill and leaves one polling loop", async () => {
    entityStore.ingestEvent(event("seed"));
    vi.mocked(fetchEventStream).mockResolvedValue(page([]))
      .mockResolvedValueOnce(page(Array.from({ length: 200 }, (_, n) => ({ ...event(`current-${n}`), sequence: n + 2 }))))
      .mockResolvedValueOnce(page([{ ...event("current-tail"), sequence: 202 }]));
    const ingest = vi.spyOn(entityStore, "ingestEvent");
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    expect(ingest).toHaveBeenCalledTimes(201); expect(fetchEventStream).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetchEventStream).mock.calls[1][1]).toBe("current-199");
    const calls = vi.mocked(fetchEventStream).mock.calls.length;
    await vi.advanceTimersByTimeAsync(2000); expect(fetchEventStream).toHaveBeenCalledTimes(calls + 1);
  });
  it("ignores retired WebSocket callbacks while retaining the new socket", () => {
    const sockets: FakeSocket[] = [];
    class FakeSocket {
      onopen?: () => void; onclose?: () => void; onerror?: () => void; onmessage?: (value: { data: string }) => void;
      close = vi.fn();
      constructor() { sockets.push(this); }
    }
    vi.stubGlobal("WebSocket", FakeSocket);
    const ingest = vi.spyOn(entityStore, "ingestEvent");
    eventClient.start({ mode: "websocket" }); eventClient.start({ mode: "websocket" });
    expect(sockets[0].close).toHaveBeenCalledTimes(1);
    sockets[0].onmessage?.({ data: JSON.stringify(event("retired-socket")) }); sockets[0].onclose?.();
    expect(ingest).not.toHaveBeenCalled();
    sockets[1].onmessage?.({ data: JSON.stringify(event("current-socket")) });
    expect(ingest).toHaveBeenCalledTimes(1); eventClient.stop();
    expect(sockets[1].close).toHaveBeenCalledTimes(1);
  });

});
