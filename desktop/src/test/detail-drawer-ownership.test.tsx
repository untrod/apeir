import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DetailDrawer } from "../components/DetailDrawer";
import { approvalAction, fetchApprovals, fetchModelObservations, setConfig, testModel } from "../lib/api";
import { toast } from "../components/Toast";

vi.mock("../lib/api", async importOriginal => ({
  ...await importOriginal<typeof import("../lib/api")>(),
  fetchApprovals: vi.fn(), fetchModelObservations: vi.fn(),
  approvalAction: vi.fn(), testModel: vi.fn(),
}));
vi.mock("../components/Toast", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  setConfig({ url: "http://127.0.0.1:8770", token: "drawer.fake.a" });
  vi.mocked(fetchModelObservations).mockResolvedValue({ observations: [{ trace_id: "FAKE_HISTORY_A" }], count: 1, statistics: {} });
  vi.mocked(fetchApprovals).mockResolvedValue({ approvals: [{ request_id: "shared-request", summary: "FAKE_APPROVAL_A" }] } as Awaited<ReturnType<typeof fetchApprovals>>);
});
afterEach(() => { cleanup(); sessionStorage.clear(); });

describe("Inspector selection ownership", () => {
  it.each(["controller", "ABA"] as const)("retires history on %s change and permits an explicit fresh selection", async change => {
    const close = vi.fn();
    const selected = { kind: "model-observations" as const, modelId: "shared-model" };
    const view = render(<DetailDrawer view={selected} onClose={close} />);
    await screen.findByText(/FAKE_HISTORY_A/);
    act(() => {
      setConfig({ url: "http://127.0.0.1:8771", token: "drawer.fake.b" });
      if (change === "ABA") setConfig({ url: "http://127.0.0.1:8770", token: "drawer.fake.a" });
    });
    expect(screen.queryByText(/FAKE_HISTORY_A/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Test Connection" })).toBeNull();
    expect(close).toHaveBeenCalled();
    vi.mocked(fetchModelObservations).mockResolvedValue({ observations: [{ trace_id: "FAKE_HISTORY_B" }], count: 1, statistics: {} });
    view.rerender(<DetailDrawer view={{ ...selected }} onClose={close} />);
    await screen.findByText(/FAKE_HISTORY_B/);
    expect(screen.queryByText(/FAKE_HISTORY_A/)).toBeNull();
    expect(fetchModelObservations).toHaveBeenCalledTimes(2);
  });

  it("does not admit an old approval after its Controller changes", async () => {
    render(<DetailDrawer view={{ kind: "approval", requestId: "shared-request" }} onClose={vi.fn()} />);
    const approve = await screen.findByRole("button", { name: "Approve Once" });
    await waitFor(() => expect(approve).not.toBeDisabled());
    act(() => {
      setConfig({ url: "http://127.0.0.1:8771", token: "drawer.fake.b" });
      fireEvent.click(approve);
    });
    expect(approvalAction).not.toHaveBeenCalled();
  });

  it("keeps an admitted approval on its original Controller without a new-context toast or retry", async () => {
    const pending = deferred<Awaited<ReturnType<typeof approvalAction>>>();
    vi.mocked(approvalAction).mockReturnValueOnce(pending.promise);
    render(<DetailDrawer view={{ kind: "approval", requestId: "shared-request" }} onClose={vi.fn()} />);
    const approve = await screen.findByRole("button", { name: "Approve Once" });
    await waitFor(() => expect(approve).not.toBeDisabled());
    fireEvent.click(approve);
    expect(approvalAction).toHaveBeenCalledTimes(1);
    act(() => setConfig({ url: "http://127.0.0.1:8771", token: "drawer.fake.b" }));
    await act(async () => { pending.resolve({}); await pending.promise; });
    expect(approvalAction).toHaveBeenCalledTimes(1);
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("ignores a model test result from a retired selection", async () => {
    const pending = deferred<Awaited<ReturnType<typeof testModel>>>();
    vi.mocked(testModel).mockReturnValueOnce(pending.promise);
    render(<DetailDrawer view={{ kind: "model-observations", modelId: "shared-model" }} onClose={vi.fn()} />);
    const test = await screen.findByRole("button", { name: "Test Connection" });
    fireEvent.click(test);
    expect(testModel).toHaveBeenCalledTimes(1);
    act(() => setConfig({ url: "http://127.0.0.1:8771", token: "drawer.fake.b" }));
    await act(async () => {
      pending.resolve({ healthy: true, latency_ms: 1, model_id: "shared-model", selected_model_id: "shared-model", instance_id: "fake-instance-a", request_id: "fake-request-a", response_id: "fake-response-a" });
      await pending.promise;
    });
    expect(screen.queryByRole("button", { name: "Test Connection" })).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(testModel).toHaveBeenCalledTimes(1);
  });
});
