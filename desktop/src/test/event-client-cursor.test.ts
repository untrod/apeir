import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { eventClient } from "../store/eventClient";
import { entityStore } from "../store/entityStore";
import { ApiError, fetchEventStream, setConfig } from "../lib/api";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), fetchEventStream: vi.fn() }));
const event = (id: string) => ({ event_id: id, sequence: 0, event_type: "task.updated", domain: "task", source: "runtime", timestamp: "2026-10-23T00:00:00Z", payload: {}, metadata: {}, dedup_key: id });
const page = (events: ReturnType<typeof event>[] = []) => ({ events, count: events.length, domain: "", latest_event_id: events.at(-1)?.event_id || "" });
let connection = 0;
beforeEach(() => { vi.useFakeTimers(); vi.resetAllMocks(); entityStore.clearStore(); setConfig({ url: "http://localhost:8770", token: `cursor.fake.${++connection}` }); });
afterEach(() => { eventClient.stop(); entityStore.clearStore(); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe("existing EventClient uses the global Bus event-ID contract", () => {
  it("does not send a per-Run numeric sequence and advances with actual event IDs", async () => {
    entityStore.ingestEvent({ ...event("run-seed"), sequence: 123 });
    vi.mocked(fetchEventStream).mockResolvedValue(page())
      .mockResolvedValueOnce(page(Array.from({ length: 200 }, (_, i) => event(`bus-${i}`))))
      .mockResolvedValueOnce(page([event("bus-tail")]));
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(fetchEventStream).mock.calls.map(c => c[1])).toEqual(["", "bus-199", "bus-tail"]);
  });
  it("resumes the same connection cursor after stop/start and resets on another identity", async () => {
    vi.mocked(fetchEventStream).mockResolvedValue(page()).mockResolvedValueOnce(page([event("bus-original")]));
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    eventClient.stop(); eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(fetchEventStream).mock.calls[2][1]).toBe("bus-original");
    setConfig({ url: "http://localhost:8770", token: "cursor.fake.changed" });
    eventClient.start({ mode: "polling" }); await vi.advanceTimersByTimeAsync(0);
    expect(vi.mocked(fetchEventStream).mock.calls[4][1]).toBe("");
  });
  it("surfaces an unavailable original cursor and stops rather than guessing a snapshot", async () => {
    const onError = vi.fn();
    vi.mocked(fetchEventStream).mockRejectedValue(new ApiError("NOUS_EVENT_CURSOR_UNAVAILABLE", "Reload current state"));
    eventClient.start({ mode: "polling", onError }); await vi.advanceTimersByTimeAsync(6000);
    expect(fetchEventStream).toHaveBeenCalledTimes(1); expect(onError).toHaveBeenCalledTimes(1);
  });
  it("rejects a repeated full page instead of spinning or ingesting it again", async () => {
    const onError = vi.fn(), ingest = vi.spyOn(entityStore, "ingestEvent");
    const full = page(Array.from({ length: 200 }, (_, i) => event(`bus-${i}`)));
    let requests = 0;
    vi.mocked(fetchEventStream).mockImplementation(async () => { if (++requests > 4) throw new Error("Fixture safety bound"); return full; });
    eventClient.start({ mode: "polling", onError }); await vi.advanceTimersByTimeAsync(0);
    expect(requests).toBe(2); expect(ingest).toHaveBeenCalledTimes(200); expect(onError).toHaveBeenCalledTimes(1);
  });
});
