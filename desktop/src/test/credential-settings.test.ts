import { describe, expect, it } from "vitest";
import {
  credentialNameError,
  credentialSecretError,
} from "../components/CredentialSettings";

describe("credential settings validation", () => {
  it("accepts stable environment references", () => {
    expect(credentialNameError("DEEPSEEK_API_KEY")).toBe("");
    expect(credentialNameError("9INVALID")).not.toBe("");
    expect(credentialNameError("provider_key")).not.toBe("");
  });

  it("rejects missing or short credentials", () => {
    expect(credentialSecretError("provider-secret-value")).toBe("");
    expect(credentialSecretError("short")).not.toBe("");
  });
});
