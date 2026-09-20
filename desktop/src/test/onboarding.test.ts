import { describe, expect, it } from "vitest";

import { credentialEnvironmentError, credentialValueError } from "../components/OnboardingWizard";

describe("onboarding credential references", () => {
  it("accepts a conventional environment-variable name", () => {
    expect(credentialEnvironmentError("DEEPSEEK_API_KEY")).toBe("");
  });

  it("rejects a value that resembles a pasted secret", () => {
    expect(credentialEnvironmentError("A1B2C3D4E5F60718293A4B5C6D7E8F90")).toBe("secret");
  });

  it("rejects malformed or empty names", () => {
    expect(credentialEnvironmentError("")).toBe("required");
    expect(credentialEnvironmentError("9INVALID_NAME")).toBe("invalid");
  });

  it("accepts a provider key in secure credential mode", () => {
    expect(credentialValueError("sk-example-provider-key")).toBe("");
    expect(credentialValueError("short")).toBe("required");
  });
});
