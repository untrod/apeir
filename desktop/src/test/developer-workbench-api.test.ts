import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchWorkbenchFile,
  previewWorkbenchWrite,
  runWorkbenchProfile,
  setConfig,
  writeWorkbenchFile,
} from "../lib/api";

describe("developer workbench API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("encodes workspace paths and preserves compare-and-swap hashes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { path: "src/a b.py", content: "", sha256: "before" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    await fetchWorkbenchFile("src/a b.py");
    await previewWorkbenchWrite("src/a b.py", "print(1)\n", "before");
    await writeWorkbenchFile("src/a b.py", "print(1)\n", "before");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8770/api/v1/developer/workspace/file?path=src%2Fa%20b.py",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer session-token" }) }), // security-scan: fixture
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8770/api/v1/developer/workspace/write",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ path: "src/a b.py", content: "print(1)\n", expected_sha256: "before" }),
      }),
    );
  });

  it("sends a fixed profile rather than an arbitrary command", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { ok: true, run_id: "workbench-exec-1" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    await runWorkbenchProfile("pytest", "tests/unit", 120);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/developer/workspace/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ profile: "pytest", target: "tests/unit", timeout_seconds: 120 }),
      }),
    );
  });
});
