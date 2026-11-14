import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ToastProvider, toast } from "../components/Toast";
import { setConfig } from "../lib/api";

beforeEach(() => { vi.useFakeTimers(); setConfig({ url: "http://127.0.0.1:9017", token: "fixture.notification.a" }); });
afterEach(() => vi.useRealTimers());

it("coalesces repeated transport failures without covering the workspace", () => {
  render(<ToastProvider><button>Keep working</button></ToastProvider>);
  act(() => { for (let i = 0; i < 20; i++) toast.error("Connection unavailable", "Inspect the original Runtime before retrying."); });
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  act(() => vi.advanceTimersByTime(8000));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  act(() => toast.error("Connection unavailable", "Inspect the original Runtime before retrying."));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Keep working" })).toBeEnabled();
});

it("limits the visible stack and lets users inspect distinct notices", () => {
  render(<ToastProvider><span>Workspace</span></ToastProvider>);
  act(() => { for (let i = 0; i < 6; i++) toast({ title: `Notice ${i}`, level: "warning", durationMs: 0 }); });
  expect(screen.getAllByRole("status")).toHaveLength(3);
  fireEvent.click(screen.getByRole("button", { name: "3 more notifications" }));
  expect(screen.getAllByRole("status")).toHaveLength(6);
  fireEvent.click(screen.getByRole("button", { name: "Dismiss notification: Notice 0" }));
  expect(screen.queryByText("Notice 0")).not.toBeInTheDocument();
});

it("retires old Controller notifications and actions when identity changes", () => {
  const oldAction = vi.fn();
  render(<ToastProvider><span>Workspace</span></ToastProvider>);
  act(() => toast({ title: "Original request", level: "warning", durationMs: 0, action: { label: "Inspect A", onClick: oldAction } }));
  const originalButton = screen.getByRole("button", { name: "Inspect A" });
  act(() => {
    setConfig({ url: "http://127.0.0.1:9018", token: "fixture.notification.b" });
    fireEvent.click(originalButton);
  });
  expect(screen.queryByRole("button", { name: "Inspect A" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Notifications" })).queryByText("Original request")).not.toBeInTheDocument();
  expect(oldAction).not.toHaveBeenCalled();
});

it("does not merge separate actionable requests and clears timers on unmount", () => {
  const schedule = vi.spyOn(globalThis, "setTimeout"), cancel = vi.spyOn(globalThis, "clearTimeout");
  const { unmount } = render(<ToastProvider><span>Workspace</span></ToastProvider>);
  act(() => {
    toast({ title: "Review request", level: "info", action: { label: "Inspect first", onClick: vi.fn() } });
    toast({ title: "Review request", level: "info", action: { label: "Inspect second", onClick: vi.fn() } });
  });
  expect(screen.getByRole("button", { name: "Inspect first" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Inspect second" })).toBeVisible();
  const expiryTimers = schedule.mock.calls.flatMap((args, index) => args[1] === 4000 ? [schedule.mock.results[index].value] : []);
  expect(expiryTimers).toHaveLength(2);
  unmount();
  for (const timer of expiryTimers) expect(cancel).toHaveBeenCalledWith(timer);
  schedule.mockRestore(); cancel.mockRestore();
});
