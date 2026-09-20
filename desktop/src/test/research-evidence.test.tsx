import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResearchEvidence } from "../components/ResearchEvidence";
import {
  ApiError,
  approvalAction,
  createResearchClaim,
  fetchResearchClaims,
  fetchResearchNetworkStatus,
  fetchResearchSources,
  fetchResearchUrl,
  searchResearchWeb,
} from "../lib/api";

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    approvalAction: vi.fn(),
    createResearchClaim: vi.fn(),
    fetchResearchClaims: vi.fn(),
    fetchResearchNetworkStatus: vi.fn(),
    fetchResearchSources: vi.fn(),
    fetchResearchUrl: vi.fn(),
    searchResearchWeb: vi.fn(),
  };
});

describe("research evidence workbench", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchResearchNetworkStatus).mockResolvedValue({
      gateway: "governed",
      available: true,
      network_scope: "public_internet",
      methods: ["GET", "HEAD", "POST"],
      max_response_bytes: 5_242_880,
      max_request_body_bytes: 1_048_576,
      credential_boundary: "reference_only",
      redirect_revalidation: true,
      dns_pinning: true,
      compressed_responses: "blocked",
      source_count: 0,
      snapshot_count: 0,
      artifact_count: 0,
      claim_count: 0,
      claim_evidence_count: 0,
      claim_contract: "1.0",
      claim_event_authority: "EventStream",
      evidence_level: "integrated-host",
    });
    vi.mocked(fetchResearchSources).mockResolvedValue({ sources: [], total: 0 });
    vi.mocked(fetchResearchClaims).mockResolvedValue({ claims: [], total: 0, summary: {} });
    vi.mocked(approvalAction).mockResolvedValue({});
  });

  it("requires an explicit click and retries the identical reviewed request", async () => {
    vi.mocked(fetchResearchUrl)
      .mockRejectedValueOnce(new ApiError(
        "NOUS_APPROVAL_REQUIRED",
        "Approval required",
        { approval_request_id: "apr_ui", run_id: "network-fetch-ui" },
      ))
      .mockResolvedValueOnce({
        ok: true,
        url: "https://example.com/",
        final_url: "https://example.com/",
        status_code: 200,
        content: "verified",
        content_hash: "a".repeat(64),
        content_type: "text/plain",
        size_bytes: 8,
        snapshot_id: "snap_ui",
        snapshot_artifact_id: "artifact_ui",
        source_id: "src_ui",
        retrieved_at: "2026-08-30T00:00:00Z",
        redirect_chain: [],
        run_id: "network-fetch-ui",
        request_id: "desktop-ui",
        injection_scan_result: {
          safe: true,
          risk_level: "low",
          detected_patterns: [],
          blocked: false,
          reason: "",
        },
      });

    render(<ResearchEvidence />);

    expect(await screen.findByText(/governed · integrated-host/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fetch evidence" }));

    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    expect(approvalAction).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Approve once and fetch" }));

    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_ui", "approve"));
    await waitFor(() => expect(fetchResearchUrl).toHaveBeenCalledTimes(2));
    expect(vi.mocked(fetchResearchUrl).mock.calls[1][0]).toBe(
      vi.mocked(fetchResearchUrl).mock.calls[0][0],
    );
    expect(await screen.findByText("verified")).toBeInTheDocument();
    expect(screen.getByText(/artifact_ui/)).toBeInTheDocument();
  });
  it("gates search, retries the identical query, then offers manual result capture", async () => {
    vi.mocked(searchResearchWeb)
      .mockRejectedValueOnce(new ApiError(
        "NOUS_APPROVAL_REQUIRED",
        "Approval required",
        { approval_request_id: "apr_search_ui", run_id: "network-search-ui" },
      ))
      .mockResolvedValueOnce({
        ok: true,
        query: "Nous evidence",
        results: [{
          rank: 1,
          title: "Evidence source",
          url: "https://example.com/evidence",
          snippet: "A governed result.",
        }],
        search_evidence: {
          ok: true,
          url: "https://www.bing.com/search?q=%3Credacted%3E",
          final_url: "https://www.bing.com/search?q=%3Credacted%3E",
          status_code: 200,
          content: "search results",
          content_hash: "b".repeat(64),
          content_type: "text/html",
          size_bytes: 14,
          snapshot_id: "snap_search_ui",
          snapshot_artifact_id: "artifact_search_ui",
          source_id: "src_search_ui",
          retrieved_at: "2026-08-30T00:00:00Z",
          redirect_chain: [],
          run_id: "network-search-ui",
          request_id: "desktop-search-ui",
        },
        request_id: "desktop-search-ui",
        run_id: "network-search-ui",
      });

    render(<ResearchEvidence />);
    fireEvent.change(screen.getByLabelText("Research search query"), {
      target: { value: "Nous evidence" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search web" }));

    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    expect(approvalAction).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and search" }));

    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_search_ui", "approve"));
    await waitFor(() => expect(searchResearchWeb).toHaveBeenCalledTimes(2));
    expect(vi.mocked(searchResearchWeb).mock.calls[1][0]).toBe(
      vi.mocked(searchResearchWeb).mock.calls[0][0],
    );
    expect(await screen.findByText(/Evidence source/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fetch this evidence" })).toBeInTheDocument();
    expect(fetchResearchUrl).not.toHaveBeenCalled();
  });

  it("creates a source-backed claim only after explicit approval", async () => {
    const source = {
      source_id: "src_claim_ui",
      url: "https://example.com/claim-proof",
      title: "Claim proof",
      publisher: "Example",
      retrieved_at: "2026-08-30T00:00:00Z",
      retrieval_time: "2026-08-30T00:00:00Z",
      content_hash: "c".repeat(64),
      mime_type: "text/plain",
      source_type: "web_page",
      trust_tier: "unknown",
      snapshot_location: "snapshot",
      snapshot_artifact_id: "artifact_claim_ui",
      injection_risk: "low",
    };
    const claim = {
      claim_id: "claim_ui",
      statement: "The captured evidence supports this conclusion.",
      task_id: "research.claim:claim_ui",
      run_id: "claim-ui",
      trace_id: "trace-ui",
      evidence_refs: ["ev_ui"],
      source_refs: [source.source_id],
      snapshot_refs: ["snap_ui"],
      confidence: 0.5,
      created_by: "desktop.research",
      created_at: "2026-08-30T00:00:00Z",
      verification_state: "supported" as const,
      provenance: {},
    };
    vi.mocked(fetchResearchSources).mockResolvedValue({ sources: [source], total: 1 });
    vi.mocked(createResearchClaim)
      .mockRejectedValueOnce(new ApiError(
        "NOUS_APPROVAL_REQUIRED",
        "Approval required",
        { approval_request_id: "apr_claim_ui" },
      ))
      .mockResolvedValueOnce({
        claim,
        evidence: [{
          evidence_id: "ev_ui",
          claim_id: claim.claim_id,
          source_id: source.source_id,
          relation: "supports",
          strength: 0.5,
          description: "",
          snapshot_ref: "snap_ui",
          artifact_ref: "artifact_claim_ui",
          created_at: "2026-08-30T00:00:00Z",
          provenance: {},
        }],
        source_refs: [source.source_id],
        snapshot_refs: ["snap_ui"],
        artifact_refs: ["artifact_claim_ui"],
        sources: [{ ...source, citation: {
          source_id: source.source_id,
          title: source.title,
          url: source.url,
          publisher: source.publisher,
          author: "",
          publication_time: "",
          retrieved_at: source.retrieved_at,
          content_hash: source.content_hash,
          snapshot_artifact_id: source.snapshot_artifact_id,
          formatted: "Claim proof.",
        } }],
        snapshots: [],
        artifacts: [],
        trace_complete: true,
      });

    render(<ResearchEvidence />);
    await screen.findByRole("option", { name: "Claim proof" });
    fireEvent.change(screen.getByLabelText("Claim evidence source"), {
      target: { value: source.source_id },
    });
    fireEvent.change(screen.getByLabelText("Claim statement"), {
      target: { value: claim.statement },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create governed claim" }));

    expect(await screen.findByText("Explicit approval required")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve once and create claim" }));

    await waitFor(() => expect(approvalAction).toHaveBeenCalledWith("apr_claim_ui", "approve"));
    await waitFor(() => expect(createResearchClaim).toHaveBeenCalledTimes(2));
    expect(vi.mocked(createResearchClaim).mock.calls[1][0]).toBe(
      vi.mocked(createResearchClaim).mock.calls[0][0],
    );
    expect(await screen.findByText(/trace complete/)).toBeInTheDocument();
  });
});