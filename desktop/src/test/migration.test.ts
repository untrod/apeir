import { beforeEach, describe, expect, it } from "vitest";
import { migrateOldState, resetUIState, UI_STATE_SCHEMA_VERSION } from "../lib/migration";

describe("desktop UI state migration", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("invalidates only the legacy session token and preserves user references", () => {
    localStorage.setItem("nous_server_token", "legacy-secret");
    localStorage.setItem("nous_workspace_path", "D:/Workspace");
    localStorage.setItem("unrelated_product_data", "keep");

    const report = migrateOldState();

    expect(localStorage.getItem("nous_server_token")).toBeNull();
    expect(localStorage.getItem("nous_workspace_path")).toBe("D:/Workspace");
    expect(localStorage.getItem("unrelated_product_data")).toBe("keep");
    expect(localStorage.getItem("nous_ui_schema_version")).toBe(String(UI_STATE_SCHEMA_VERSION));
    expect(report.reset).toContain("nous_server_token");
  });

  it("resets disposable UI state without clearing workspace or provider references", () => {
    localStorage.setItem("nous_onboarding_completed", "1");
    localStorage.setItem("nous_workspace_path", "D:/Workspace");
    localStorage.setItem("nous_provider_id", "deepseek");
    sessionStorage.setItem("nous_server_token", "session-secret");

    resetUIState();

    expect(localStorage.getItem("nous_onboarding_completed")).toBeNull();
    expect(localStorage.getItem("nous_workspace_path")).toBe("D:/Workspace");
    expect(localStorage.getItem("nous_provider_id")).toBe("deepseek");
    expect(sessionStorage.getItem("nous_server_token")).toBeNull();
    expect(localStorage.getItem("nous_ui_state_backup")).not.toBeNull();
  });
});