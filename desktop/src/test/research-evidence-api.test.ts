import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  approvalAction,
  fetchResearchSources,
  fetchResearchUrl,
  searchResearchWeb,
  setConfig,
  type ResearchFetchRequest,
  type ResearchSearchRequest,
} from "../lib/api";

describe("research evidence API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("preserves the reviewed request across approval and retry", async () => {
    const request: ResearchFetchRequest = {
      request_id: "desktop-fixed-request",
      method: "GET",
      url: "https://example.com/proof",
      network_scope: "public_internet",
      max_response_bytes: 4096,
      timeout_seconds: 30,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({
          ok: false,
          error: {
            code: "NOUS_APPROVAL_REQUIRED",
            message: "Approval required",
            details: { approval_request_id: "apr_research", run_id: "network-fetch-1" },
          },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, data: { action: "approve" } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ ok: true, data: { ok: true, source_id: "src_1" } }),
      });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    let approvalId = "";
    try {
      await fetchResearchUrl(request);
    } catch (cause) {
      expect(cause).toBeInstanceOf(ApiError);
      approvalId = String((cause as ApiError).details?.approval_request_id || "");
    }
    await approvalAction(approvalId, "approve");
    await fetchResearchUrl(request);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8770/api/v1/research/fetch",
      expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8770/api/v1/approvals/apr_research/approve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8770/api/v1/research/fetch",
      expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
    );
  });

  it("uses bounded source listing endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: { sources: [], total: 0 } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "" });

    await fetchResearchSources(25);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/research/sources?limit=25",
      expect.any(Object),
    );
  });
  it("posts the exact governed search contract", async () => {
    const request: ResearchSearchRequest = {
      request_id: "desktop-fixed-search",
      query: "governed evidence",
      max_results: 10,
      network_scope: "public_internet",
      max_response_bytes: 4096,
      timeout_seconds: 30,
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data: { ok: true, results: [] } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "session-token" });

    await searchResearchWeb(request);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8770/api/v1/research/search",
      expect.objectContaining({ method: "POST", body: JSON.stringify(request) }),
    );
  });
});