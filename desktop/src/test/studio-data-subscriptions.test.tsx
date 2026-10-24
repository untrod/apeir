import { act, render, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { StudioSnapshot, useStudioSnapshot } from "../components/studio/StudioData";
import { api, setConfig } from "../lib/api";
vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), api: vi.fn() }));
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
it("deduplicates independent widget reads, pauses hidden polling and retires owned requests", async () => {
  setConfig({ url: "http://localhost:8770", token: "dashboard.fake.shared" });
  const responses = { health: {}, nodes: [], works: [], devices: [], evidence: [], activity: [] };
  vi.mocked(api).mockResolvedValue(responses);
  let shared!: ReturnType<typeof useStudioSnapshot>;
  function Reader() { shared = useStudioSnapshot(); return <p>{shared.loading ? "loading" : "ready"}</p>; }
  vi.useFakeTimers();
  const view = render(<StudioSnapshot><Reader /></StudioSnapshot>);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(shared.loading).toBe(false);
  expect(api).toHaveBeenCalledTimes(1);
  let visible = true;
  const stopA = shared.subscribeLive(() => visible, ["operations"]), stopB = shared.subscribeLive(() => visible, ["operations"]);
  await act(async () => { await vi.advanceTimersByTimeAsync(30); }); expect(api).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(api).toHaveBeenCalledTimes(2);
  visible = false; await act(async () => { await vi.advanceTimersByTimeAsync(10000); }); expect(api).toHaveBeenCalledTimes(2);
  visible = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(api).toHaveBeenCalledTimes(3);
  stopA(); stopB(); view.unmount(); await vi.advanceTimersByTimeAsync(5000); expect(api).toHaveBeenCalledTimes(3);
});
it("never publishes a retired Controller response into the new scoped provider", async () => {
  setConfig({ url: "http://localhost:8770", token: "dashboard.fake.a" });
  let resolveA!: (value: unknown) => void;
  vi.mocked(api).mockReturnValueOnce(new Promise(resolve => { resolveA = resolve; })).mockResolvedValue({ nodes: [{ node_id: "B" }] });
  function Reader() { const snapshot = useStudioSnapshot(); return <p>{JSON.stringify(snapshot.data)}</p>; }
  const view = render(<StudioSnapshot key="a"><Reader /></StudioSnapshot>);
  const signalA = vi.mocked(api).mock.calls.at(-1)?.[1]?.signal;
  setConfig({ url: "http://localhost:8771", token: "dashboard.fake.b" });
  view.rerender(<StudioSnapshot key="b"><Reader /></StudioSnapshot>);
  await waitFor(() => expect(view.getByText('{"nodes":[{"node_id":"B"}]}')).toBeVisible());
  expect(signalA?.aborted).toBe(true);
  await act(async () => { resolveA({ nodes: [{ node_id: "PRIVATE_A" }] }); });
  expect(view.container.textContent).not.toContain("PRIVATE_A");
});
