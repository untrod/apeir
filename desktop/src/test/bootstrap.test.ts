import { describe, expect, it } from "vitest";
import {
  canTransitionBootstrap,
  createInitialStatus,
  selectDesktopSurface,
  transitionBootstrap,
} from "../lib/bootstrap";

describe("desktop bootstrap state machine", () => {
  it("accepts the normal startup sequence", () => {
    let status = createInitialStatus();
    for (const state of [
      "loading_configuration",
      "checking_environment",
      "checking_runtime",
      "establishing_session",
      "checking_workspace",
      "checking_provider",
      "checking_model_route",
      "ready",
    ] as const) {
      status = transitionBootstrap(status, state);
    }
    expect(status.state).toBe("ready");
    expect(status.progress).toBe(100);
  });

  it("rejects a lifecycle jump that would hide a startup defect", () => {
    expect(canTransitionBootstrap("shell_starting", "ready")).toBe(false);
    expect(() => transitionBootstrap(createInitialStatus(), "ready")).toThrow(
      "shell_starting -> ready",
    );
  });

  it("treats zero-provider onboarding and diagnostics as explicit surfaces", () => {
    const onboarding = {
      ...createInitialStatus(),
      state: "onboarding_required" as const,
      provider: { configured: false, count: 0 },
    };
    expect(selectDesktopSurface(onboarding, { fatal: false, onboarding: false, connected: true })).toBe("onboarding");
    expect(selectDesktopSurface(onboarding, { fatal: true, onboarding: false, connected: true })).toBe("diagnostics");
  });
});