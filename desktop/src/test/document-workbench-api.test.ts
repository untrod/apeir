import { afterEach, describe, expect, it, vi } from "vitest";

import { createDocument, renderDocument, setConfig, type DocumentCreateRequest } from "../lib/api";

describe("document workbench API", () => {
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); });

  it("posts the exact typed IR and bounded render formats", async () => {
    const request: DocumentCreateRequest = {
      title: "Nous Brief", preset: "standard_business_brief",
      blocks: [{ kind: "paragraph", text: "Verified content" }],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ok: true, data: { document_id: "doc_1", outputs: [] } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    setConfig({ url: "http://127.0.0.1:8770", token: "token" });

    await createDocument(request);
    await renderDocument("doc_1", ["docx", "pdf"]);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://127.0.0.1:8770/api/v1/documents", expect.objectContaining({ method: "POST", body: JSON.stringify(request) }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://127.0.0.1:8770/api/v1/documents/doc_1/render", expect.objectContaining({ method: "POST", body: JSON.stringify({ formats: ["docx", "pdf"] }) }));
  });
});