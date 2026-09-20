import { describe, expect, it } from "vitest";

import { describeRuntimeFailure } from "../lib/api";

describe("runtime failure guidance", () => {
  it("turns Provider 401 failures into an actionable message", () => {
    expect(describeRuntimeFailure("HTTP 401: Unauthorized")).toBe(
      "Provider authentication failed. Update the Provider credential in Settings, then retry.",
    );
  });

  it("explains an unavailable model route", () => {
    expect(describeRuntimeFailure("no model route satisfies hard constraints")).toContain(
      "Enable a compatible model",
    );
  });

  it("turns Provider 402 failures into an actionable balance message", () => {
    expect(describeRuntimeFailure("HTTP 402: Payment Required")).toContain(
      "insufficient balance",
    );
    expect(describeRuntimeFailure("HTTP 402: Payment Required")).toContain(
      "different Provider",
    );
  });

  it("preserves an unknown Runtime failure", () => {
    expect(describeRuntimeFailure("Provider timed out")).toBe("Provider timed out");
  });
});
