import { describe, expect, it } from "vitest";
import { errorMessage, finiteNumber, fixedNumber } from "../lib/format";

describe("defensive number formatting", () => {
  it("does not crash on incomplete cached runtime entities", () => {
    expect(finiteNumber(undefined)).toBe(0);
    expect(fixedNumber(undefined, 2)).toBe("0.00");
    expect(fixedNumber("12.5", 1)).toBe("12.5");
  });

  it("preserves command failures returned as strings", () => {
    expect(errorMessage("Runtime child failed", "fallback")).toBe("Runtime child failed");
    expect(errorMessage(new Error("typed failure"), "fallback")).toBe("typed failure");
    expect(errorMessage(undefined, "fallback")).toBe("fallback");
  });
});
