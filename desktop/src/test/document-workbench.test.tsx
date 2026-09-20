import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentWorkbench } from "../components/DocumentWorkbench";
import { ApiError, approvalAction, createDocument, fetchDocuments, fetchDocumentStatus, renderDocument } from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return { ...actual, approvalAction: vi.fn(), createDocument: vi.fn(), fetchDocuments: vi.fn(), fetchDocumentStatus: vi.fn(), renderDocument: vi.fn() };
});

describe("professional document workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchDocumentStatus).mockResolvedValue({
      schema_version: "nous.document-runtime/v1", workspace: "C:/workspace", documents: 0,
      dependencies: { docx: true, reportlab: true, pypdf: true }, formats: { docx: true, pdf: true },
      limits: { blocks: 500, content_characters: 500000, output_bytes: 52428800 },
      event_authority: "EventStream", artifact_authority: "ArtifactRegistry",
    });
    vi.mocked(fetchDocuments).mockResolvedValue({ documents: [], total: 0 });
    vi.mocked(approvalAction).mockResolvedValue({});
  });

  it("requires explicit approval then retries the identical create request", async () => {
    vi.mocked(createDocument)
      .mockRejectedValueOnce(new ApiError("NOUS_APPROVAL_REQUIRED", "Approval required", { approval_request_id: "apr_document" }))
      .mockResolvedValueOnce({
        title: "Nous Professional Brief", subtitle: "Governed, traceable and render-verified", author: "Nous Desktop", language: "zh-CN",
        preset: "standard_business_brief", blocks: [{ kind: "paragraph", text: "content" }],
        schema_version: "nous.document-ir/v1", document_id: "doc_created", created_at: "2026-08-31T00:00:00Z",
        sha256: "a".repeat(64), artifact_id: "artifact_ir", run_id: "document-create-ui",
      });

    render(<DocumentWorkbench />);
    expect(await screen.findByText(/DOCX ready · PDF ready/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create governed document" }));

    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    expect(approvalAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and create" }));

    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_document", "approve"));
    await waitFor(() => expect(createDocument).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createDocument).mock.calls[1][0]).toBe(vi.mocked(createDocument).mock.calls[0][0]);
    expect(await screen.findByText(/artifact_ir/)).toBeInTheDocument();
  });

  it("renders both formats and exposes verified Artifact evidence", async () => {
    vi.mocked(fetchDocuments).mockResolvedValue({ documents: [{
      document_id: "doc_existing", title: "Existing brief", subtitle: "", preset: "standard_business_brief",
      created_at: "2026-08-31T00:00:00Z", block_count: 2, sha256: "b".repeat(64),
    }], total: 1 });
    vi.mocked(renderDocument).mockResolvedValue({
      document_id: "doc_existing", ir_sha256: "b".repeat(64), run_id: "render-ui", verified: true,
      outputs: [{ ok: true, format: "docx", location: "artifacts/documents/existing.docx", size_bytes: 1234, sha256: "c".repeat(64), artifact_id: "artifact_docx", checks: ["parser_reopen"] },
        { ok: true, format: "pdf", location: "artifacts/documents/existing.pdf", size_bytes: 2345, sha256: "d".repeat(64), artifact_id: "artifact_pdf", checks: ["parser_reopen"], page_count: 1 }],
    });

    render(<DocumentWorkbench />);
    await screen.findByRole("option", { name: "Existing brief" });
    fireEvent.click(screen.getByRole("button", { name: "Render and verify DOCX + PDF" }));

    expect(await screen.findByText(/artifact_docx/)).toBeInTheDocument();
    expect(screen.getByText(/artifact_pdf/)).toBeInTheDocument();
    expect(renderDocument).toHaveBeenCalledWith("doc_existing", ["docx", "pdf"]);
  });
});