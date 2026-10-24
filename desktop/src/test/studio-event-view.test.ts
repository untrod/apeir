import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { eventClient } from "../store/eventClient";
import { fetchEventStream, setConfig } from "../lib/api";
vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), fetchEventStream: vi.fn() }));
const event = (id: string) => ({ event_id: id, sequence: 1, event_type: "qualification.event", domain: "runtime", source: "runtime", timestamp: "2026-10-24T00:00:00Z", payload: {}, metadata: {}, dedup_key: id });
const page = (events: ReturnType<typeof event>[]) => ({ events, count: events.length, domain: "runtime", latest_event_id: events.at(-1)?.event_id || "" });
let identity = 0;
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); setConfig({ url: "http://localhost:8770", token: `events.fake.studio.${++identity}` }); });
afterEach(() => { eventClient.stop(); vi.clearAllTimers(); vi.useRealTimers(); });
it("shares one existing transport, bounds its read-only view and releases only its own loop", async () => {
  vi.mocked(fetchEventStream).mockResolvedValue(page([])).mockResolvedValueOnce(page(Array.from({ length: 200 }, (_, i) => event(`original-${i}`)))).mockResolvedValueOnce(page([event("tail")]));
  const releaseA = eventClient.acquirePresentationReader(), releaseB = eventClient.acquirePresentationReader();
  await vi.advanceTimersByTimeAsync(0);
  expect(fetchEventStream).toHaveBeenCalledTimes(3);
  expect(eventClient.getSnapshot().events).toHaveLength(200);
  expect(eventClient.getSnapshot().events[0].event_id).toBe("original-1");
  releaseA(); await vi.advanceTimersByTimeAsync(2000); expect(fetchEventStream).toHaveBeenCalledTimes(4);
  releaseB(); await vi.advanceTimersByTimeAsync(6000); expect(fetchEventStream).toHaveBeenCalledTimes(4);
  expect(eventClient.getSnapshot().status).toBe("paused");
});
it("does not stop another existing consumer or leak events across Controller identities", async () => {
  vi.mocked(fetchEventStream).mockResolvedValue(page([])).mockResolvedValueOnce(page([event("controller-a")]));
  eventClient.start({ mode: "polling" }); const release = eventClient.acquirePresentationReader();
  await vi.advanceTimersByTimeAsync(0); expect(eventClient.getSnapshot().events).toHaveLength(1);
  release(); const before = vi.mocked(fetchEventStream).mock.calls.length;
  await vi.advanceTimersByTimeAsync(2000); expect(fetchEventStream).toHaveBeenCalledTimes(before + 1);
  const seen: string[][] = [];
  const unsubscribe = eventClient.subscribe(() => seen.push(eventClient.getSnapshot().events.map(item => item.event_id)));
  setConfig({ url: "http://localhost:8771", token: "events.fake.other" });
  expect(eventClient.getSnapshot().events).toEqual([]); expect(seen.every(ids => ids.length === 0)).toBe(true); unsubscribe();
});
it("keeps the shared cursor progressing if a read-only display observer fails", async () => {
  vi.mocked(fetchEventStream).mockResolvedValue(page([])).mockResolvedValueOnce(page([event("observer-original")]));
  const unsubscribe = eventClient.subscribe(() => { throw new Error("Failed presentation only"); });
  const release = eventClient.acquirePresentationReader(); await vi.advanceTimersByTimeAsync(0);
  expect(eventClient.getSnapshot().events.at(-1)?.event_id).toBe("observer-original");
  expect(vi.mocked(fetchEventStream).mock.calls[1][1]).toBe("observer-original");
  unsubscribe(); release();
});
