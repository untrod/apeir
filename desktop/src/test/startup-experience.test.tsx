import { fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";
import { BootstrapScreen } from "../components/BootstrapScreen";
import { StudioEntrance } from "../components/StudioEntrance";
import { createInitialStatus } from "../lib/bootstrap";

describe("quiet startup and workspace entry", () => {
  it("keeps recovery controls out of the loading surface and exposes original diagnostics on demand", () => {
    const reset = vi.fn();
    const status = { ...createInitialStatus(), progressMessage: "Checking Runtime API..." };
    const actions = { onRetry: vi.fn(), onStartRuntime: vi.fn(), onResetSession: vi.fn(), onCreateWorkspace: vi.fn(), onOpenLogs: vi.fn(), onResetUI: reset, onProceedToOnboarding: vi.fn(), onProceedToDashboard: vi.fn() };
    const view = render(<BootstrapScreen status={status} {...actions} />);
    expect(screen.getByRole("status")).toHaveTextContent("Opening your workspace");
    expect(screen.getByText("Checking Runtime API...")).not.toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    view.rerender(<BootstrapScreen status={{ ...status, state: "recoverable_error", errorCode: "RUNTIME_START_FAILED", errorMessage: "Original startup failure" }} {...actions} />);
    expect(screen.getByRole("alert")).toHaveTextContent("could not be opened");
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open logs" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reset interface settings" })).not.toBeVisible();
    fireEvent.click(screen.getByText("Connection details"));
    expect(screen.getByText("Original startup failure")).toBeVisible();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    try {
      fireEvent.click(screen.getByRole("button", { name: "Reset interface settings" }));
      expect(reset).not.toHaveBeenCalled();
      confirm.mockReturnValue(true);
      fireEvent.click(screen.getByRole("button", { name: "Reset interface settings" }));
      expect(reset).toHaveBeenCalledTimes(1);
    } finally { confirm.mockRestore(); }
  });

  it("keeps the workspace mounted and editable while its entry presentation changes", () => {
    const mounted = vi.fn();
    const entered = vi.fn();
    function Workspace() {
      useEffect(() => { mounted(); }, []);
      return <input aria-label="Project draft" defaultValue="original" />;
    }
    const view = render(<StudioEntrance animate onEntered={entered}><Workspace /></StudioEntrance>);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "unsaved" } });
    view.rerender(<StudioEntrance animate={false} onEntered={entered}><Workspace /></StudioEntrance>);
    expect(screen.getByRole("textbox")).toHaveValue("unsaved");
    expect(mounted).toHaveBeenCalledTimes(1);
    expect(entered).toHaveBeenCalledTimes(1);
  });
});
