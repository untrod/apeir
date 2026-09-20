import React, { useCallback, useEffect, useState } from "react";

import { btnPrimary, btnSecondary, colors, radius, space, typo } from "../design";
import {
  ApiError,
  approvalAction,
  createResearchClaim,
  fetchResearchClaims,
  fetchResearchNetworkStatus,
  fetchResearchSources,
  fetchResearchUrl,
  searchResearchWeb,
  type ResearchFetchRequest,
  type ResearchFetchResult,
  type ResearchClaim,
  type ResearchClaimCreateRequest,
  type ResearchClaimDetail,
  type ResearchNetworkStatus,
  type ResearchSearchRequest,
  type ResearchSearchResult,
  type ResearchSource,
} from "../lib/api";
import { errorMessage } from "../lib/format";

const panel: React.CSSProperties = {
  background: colors.surface,
  border: "1px solid " + colors.border,
  borderRadius: radius.lg,
  padding: space.lg,
};

const input: React.CSSProperties = {
  border: "1px solid " + colors.border,
  borderRadius: radius.md,
  padding: space.sm + " " + space.md,
  background: colors.surface,
  color: colors.text,
  fontFamily: typo.font,
  fontSize: typo.sm,
  boxSizing: "border-box",
};

function newRequestId(prefix = "desktop"): string {
  const value = globalThis.crypto?.randomUUID?.() || Date.now() + "-" + Math.random().toString(16).slice(2);
  return prefix + "-" + value;
}

type PendingOperation = {
  kind: "fetch";
  request: ResearchFetchRequest;
  approvalRequestId: string;
  runId: string;
} | {
  kind: "search";
  request: ResearchSearchRequest;
  approvalRequestId: string;
  runId: string;
} | {
  kind: "claim";
  request: ResearchClaimCreateRequest;
  approvalRequestId: string;
  runId: string;
};

export function ResearchEvidence() {
  const [status, setStatus] = useState<ResearchNetworkStatus | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [claims, setClaims] = useState<ResearchClaim[]>([]);
  const [claimStatement, setClaimStatement] = useState("");
  const [claimSourceId, setClaimSourceId] = useState("");
  const [claimResult, setClaimResult] = useState<ResearchClaimDetail | null>(null);
  const [query, setQuery] = useState("");
  const [searchResult, setSearchResult] = useState<ResearchSearchResult | null>(null);
  const [url, setUrl] = useState("https://example.com/");
  const [method, setMethod] = useState<ResearchFetchRequest["method"]>("GET");
  const [body, setBody] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [maxBytes, setMaxBytes] = useState(1_048_576);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ResearchFetchResult | null>(null);
  const [pending, setPending] = useState<PendingOperation | null>(null);

  const refresh = useCallback(async () => {
    const [statusResult, sourcesResult, claimsResult] = await Promise.allSettled([
      fetchResearchNetworkStatus(),
      fetchResearchSources(),
      fetchResearchClaims(),
    ]);
    if (statusResult.status === "fulfilled") setStatus(statusResult.value);
    if (sourcesResult.status === "fulfilled") setSources(sourcesResult.value.sources);
    if (claimsResult.status === "fulfilled") setClaims(claimsResult.value.claims);
    const failure = [statusResult, sourcesResult, claimsResult].find((item) => item.status === "rejected");
    if (failure?.status === "rejected") {
      setError(errorMessage(failure.reason, "Research evidence is unavailable."));
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const captureApproval = (
    cause: unknown,
    operation: PendingOperation["kind"],
    request: ResearchFetchRequest | ResearchSearchRequest | ResearchClaimCreateRequest,
  ) => {
    if (!(cause instanceof ApiError) || cause.code !== "NOUS_APPROVAL_REQUIRED") return false;
    const approvalRequestId = String(cause.details?.approval_request_id || "");
    const runId = String(cause.details?.run_id || "");
    if (!approvalRequestId) return false;
    if (operation === "fetch") {
      setPending({ kind: "fetch", request: request as ResearchFetchRequest, approvalRequestId, runId });
    } else if (operation === "search") {
      setPending({ kind: "search", request: request as ResearchSearchRequest, approvalRequestId, runId });
    } else {
      setPending({ kind: "claim", request: request as ResearchClaimCreateRequest, approvalRequestId, runId });
    }
    setError("");
    return true;
  };

  const executeFetch = async (request: ResearchFetchRequest) => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const fetched = await fetchResearchUrl(request);
      setResult(fetched);
      setClaimSourceId(fetched.source_id);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, "fetch", request)) {
        setError(errorMessage(cause, "Governed network fetch failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeSearch = async (request: ResearchSearchRequest) => {
    setBusy(true);
    setError("");
    setSearchResult(null);
    try {
      const searched = await searchResearchWeb(request);
      setSearchResult(searched);
      setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, "search", request)) {
        setError(errorMessage(cause, "Governed web search failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const executeClaim = async (request: ResearchClaimCreateRequest) => {
    setBusy(true);
    setError("");
    setClaimResult(null);
    try {
      const created = await createResearchClaim(request);
      setClaimResult(created);
      setPending(null);
      setClaimStatement("");
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, "claim", request)) {
        setError(errorMessage(cause, "Evidence-backed claim creation failed."));
      }
    } finally {
      setBusy(false);
    }
  };

  const makeFetchRequest = (targetUrl: string): ResearchFetchRequest => ({
    request_id: newRequestId("desktop-fetch"),
    method,
    url: targetUrl.trim(),
    ...(method === "POST" && body ? { body } : {}),
    ...(credentialRef.trim() ? { credential_ref: credentialRef.trim() } : {}),
    network_scope: "public_internet",
    max_response_bytes: Math.max(1, Math.min(maxBytes || 1_048_576, 5_242_880)),
    timeout_seconds: 30,
  });

  const submitFetch = () => {
    if (!url.trim() || busy) return;
    setPending(null);
    void executeFetch(makeFetchRequest(url));
  };

  const submitSearch = () => {
    if (!query.trim() || busy) return;
    const request: ResearchSearchRequest = {
      request_id: newRequestId("desktop-search"),
      query: query.trim(),
      max_results: 10,
      network_scope: "public_internet",
      max_response_bytes: Math.max(1, Math.min(maxBytes || 1_048_576, 5_242_880)),
      timeout_seconds: 30,
    };
    setPending(null);
    void executeSearch(request);
  };

  const submitClaim = () => {
    if (!claimStatement.trim() || !claimSourceId || busy) return;
    const request: ResearchClaimCreateRequest = {
      statement: claimStatement.trim(),
      source_refs: [claimSourceId],
      confidence: 0.5,
      created_by: "desktop.research",
    };
    setPending(null);
    void executeClaim(request);
  };
  const fetchSelectedResult = (selectedUrl: string) => {
    setUrl(selectedUrl);
    setMethod("GET");
    setPending(null);
    const request = makeFetchRequest(selectedUrl);
    request.method = "GET";
    delete request.body;
    void executeFetch(request);
  };

  const approveAndContinue = async () => {
    if (!pending || busy) return;
    const reviewed = pending;
    setBusy(true);
    setError("");
    try {
      await approvalAction(reviewed.approvalRequestId, "approve");
      setBusy(false);
      if (reviewed.kind === "search") await executeSearch(reviewed.request);
      else if (reviewed.kind === "fetch") await executeFetch(reviewed.request);
      else await executeClaim(reviewed.request);
    } catch (cause) {
      setError(errorMessage(cause, "Approval could not be applied."));
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: space.md }}>
      <section style={{ ...panel, padding: space.md, display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
        <div>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>Governed Research Evidence</div>
          <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: 3 }}>
            Search → select → fetch → immutable evidence → structured citation
          </div>
        </div>
        <div style={{ color: status?.available ? colors.success : colors.warning, fontSize: typo.sm }}>
          {status ? status.gateway + " · " + status.evidence_level + " · " + status.source_count + " sources" : "Checking gateway…"}
        </div>
      </section>

      <section style={panel}>
        <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.sm }}>1. Governed web search</div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 1fr) 160px", gap: space.sm }}>
          <input aria-label="Research search query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search public sources" style={{ ...input, width: "100%" }} />
          <button onClick={submitSearch} disabled={busy || !query.trim()} style={{ ...btnPrimary, justifyContent: "center", opacity: busy || !query.trim() ? 0.55 : 1 }}>
            {busy ? "Working…" : "Search web"}
          </button>
        </div>
        <div style={{ color: colors.textTertiary, fontSize: typo.xs, marginTop: space.sm }}>
          Search terms use an approval-gated search request; audit URLs redact the query value.
        </div>
      </section>

      {searchResult && (
        <section style={panel}>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>2. Select a result to capture</div>
          <div style={{ display: "grid", gap: space.sm, marginTop: space.md }}>
            {searchResult.results.length === 0 && <div style={{ color: colors.textTertiary }}>No structured results were returned.</div>}
            {searchResult.results.map((item) => (
              <div key={item.url} style={{ padding: space.md, borderRadius: radius.md, background: colors.bg }}>
                <div style={{ color: colors.text, fontWeight: typo.medium }}>{item.rank}. {item.title}</div>
                <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: space.xs }}>{item.snippet}</div>
                <div style={{ color: colors.textTertiary, fontSize: typo.xs, overflowWrap: "anywhere", marginTop: space.xs }}>{item.url}</div>
                <button onClick={() => fetchSelectedResult(item.url)} disabled={busy} style={{ ...btnSecondary, marginTop: space.sm }}>Fetch this evidence</button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section style={panel}>
        <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.sm }}>Direct evidence fetch</div>
        <div style={{ display: "grid", gridTemplateColumns: "110px minmax(260px, 1fr) 160px", gap: space.sm }}>
          <select aria-label="Research method" value={method} onChange={(event) => setMethod(event.target.value as ResearchFetchRequest["method"])} style={input}>
            <option value="GET">GET</option><option value="HEAD">HEAD</option><option value="POST">POST</option>
          </select>
          <input aria-label="Research URL" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://public.example/resource" style={{ ...input, width: "100%", fontFamily: typo.mono }} />
          <button onClick={submitFetch} disabled={busy || !url.trim()} style={{ ...btnPrimary, justifyContent: "center", opacity: busy || !url.trim() ? 0.55 : 1 }}>
            {busy ? "Working…" : "Fetch evidence"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) 180px", gap: space.sm, marginTop: space.sm }}>
          <input aria-label="Credential reference" value={credentialRef} onChange={(event) => setCredentialRef(event.target.value)} placeholder="Optional: env:RESEARCH_API_KEY" style={{ ...input, width: "100%", fontFamily: typo.mono }} />
          <input aria-label="Maximum response bytes" type="number" min={1} max={5_242_880} value={maxBytes} onChange={(event) => setMaxBytes(Number(event.target.value))} style={{ ...input, width: "100%" }} />
        </div>
        {method === "POST" && <textarea aria-label="Research request body" value={body} onChange={(event) => setBody(event.target.value)} placeholder="POST body (only its SHA-256 is audited)" style={{ ...input, width: "100%", minHeight: 110, resize: "vertical", marginTop: space.sm, fontFamily: typo.mono }} />}
      </section>

      {pending && (
        <section style={{ ...panel, background: colors.warningSoft, borderColor: colors.warning }}>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>Explicit approval required</div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: space.xs }}>
            Review {pending.kind === "search" ? "web search" : pending.kind === "claim" ? "evidence-backed claim" : pending.request.method + " " + pending.request.url} · run <code style={{ fontFamily: typo.mono }}>{pending.runId || "local mutation"}</code>
          </div>
          <div style={{ display: "flex", gap: space.sm, marginTop: space.md }}>
            <button onClick={() => void approveAndContinue()} disabled={busy} style={btnPrimary}>{pending.kind === "search" ? "Approve once and search" : pending.kind === "claim" ? "Approve once and create claim" : "Approve once and fetch"}</button>
            <button onClick={() => setPending(null)} disabled={busy} style={btnSecondary}>Cancel</button>
          </div>
        </section>
      )}

      {error && <section style={{ ...panel, color: colors.danger, background: colors.dangerSoft }}>{error}</section>}

      {result && (
        <section style={panel}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
            <div>
              <div style={{ color: colors.text, fontWeight: typo.semibold }}>{result.final_url}</div>
              <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: 3 }}>HTTP {result.status_code} · {result.content_type} · {result.size_bytes.toLocaleString()} bytes</div>
            </div>
            <span style={{ color: result.injection_scan_result?.safe === false ? colors.warning : colors.success, fontSize: typo.sm }}>injection risk {result.injection_scan_result?.risk_level || "low"}</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: space.sm, marginTop: space.md, color: colors.textSecondary, fontSize: typo.xs }}>
            <span>Source <code style={{ fontFamily: typo.mono }}>{result.source_id}</code></span>
            <span>Snapshot <code style={{ fontFamily: typo.mono }}>{result.snapshot_id}</code></span>
            <span>Artifact <code style={{ fontFamily: typo.mono }}>{result.snapshot_artifact_id}</code></span>
          </div>
          <div style={{ color: colors.textTertiary, fontSize: typo.xs, overflowWrap: "anywhere", marginTop: space.sm }}>SHA-256 {result.content_hash} · run {result.run_id}</div>
          {result.citation && <div style={{ marginTop: space.md, padding: space.md, borderRadius: radius.md, background: colors.bg, color: colors.textSecondary, fontSize: typo.sm }}><strong style={{ color: colors.text }}>Citation</strong><div style={{ marginTop: space.xs }}>{result.citation.formatted}</div><div style={{ marginTop: space.xs, color: colors.textTertiary, fontFamily: typo.mono, fontSize: typo.xs }}>{result.citation.source_id} · {result.citation.snapshot_artifact_id}</div></div>}
          {result.content && <pre style={{ maxHeight: 340, overflow: "auto", whiteSpace: "pre-wrap", margin: space.md + " 0 0", padding: space.md, borderRadius: radius.md, background: colors.bg, color: colors.textSecondary, fontFamily: typo.mono, fontSize: typo.xs }}>{result.content}</pre>}
        </section>
      )}

      <section style={panel}>
        <div style={{ color: colors.text, fontWeight: typo.semibold }}>3. Evidence → Claim</div>
        <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: 3 }}>
          Associate a professional statement with a persisted Source, Snapshot and Artifact.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) 180px", gap: space.sm, marginTop: space.md }}>
          <select
            aria-label="Claim evidence source"
            value={claimSourceId}
            onChange={(event) => setClaimSourceId(event.target.value)}
            style={input}
          >
            <option value="">Select persisted evidence</option>
            {sources.map((source) => (
              <option key={source.source_id} value={source.source_id}>
                {source.title || source.url}
              </option>
            ))}
          </select>
          <button
            onClick={submitClaim}
            disabled={busy || !claimStatement.trim() || !claimSourceId}
            style={{ ...btnPrimary, justifyContent: "center", opacity: busy || !claimStatement.trim() || !claimSourceId ? 0.55 : 1 }}
          >
            Create governed claim
          </button>
        </div>
        <textarea
          aria-label="Claim statement"
          value={claimStatement}
          onChange={(event) => setClaimStatement(event.target.value)}
          placeholder="State the conclusion supported by the selected evidence"
          style={{ ...input, width: "100%", minHeight: 100, resize: "vertical", marginTop: space.sm }}
        />
        {claimResult && (
          <div style={{ marginTop: space.md, padding: space.md, borderRadius: radius.md, background: colors.successSoft }}>
            <div style={{ color: colors.text, fontWeight: typo.semibold }}>{claimResult.claim.statement}</div>
            <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: space.xs }}>
              {claimResult.claim.verification_state} · {claimResult.claim.claim_id} · {claimResult.trace_complete ? "trace complete" : "trace incomplete"}
            </div>
          </div>
        )}
        <div style={{ display: "grid", gap: space.sm, marginTop: space.md }}>
          {claims.length === 0 && <div style={{ color: colors.textTertiary, fontSize: typo.sm }}>No claims have been recorded.</div>}
          {claims.map((claim) => (
            <div key={claim.claim_id} style={{ padding: space.md, borderRadius: radius.md, background: colors.bg }}>
              <div style={{ color: colors.text }}>{claim.statement}</div>
              <div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: space.xs }}>
                {claim.verification_state} · confidence {claim.confidence.toFixed(2)} · {claim.evidence_refs.length} evidence
              </div>
              <div style={{ color: colors.textTertiary, fontFamily: typo.mono, fontSize: typo.xs, marginTop: 3 }}>
                {claim.claim_id} · trace {claim.trace_id}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: space.md }}><div style={{ color: colors.text, fontWeight: typo.semibold }}>Persisted sources</div><button onClick={() => void refresh()} disabled={busy} style={btnSecondary}>Refresh</button></div>
        <div style={{ display: "grid", gap: space.sm, marginTop: space.md }}>
          {sources.length === 0 && <div style={{ color: colors.textTertiary, fontSize: typo.sm }}>No verified web snapshots have been recorded.</div>}
          {sources.map((source) => <div key={source.source_id} style={{ padding: space.md, borderRadius: radius.md, background: colors.bg }}><div style={{ display: "flex", justifyContent: "space-between", gap: space.md }}><div style={{ minWidth: 0 }}><div style={{ color: colors.text, fontWeight: typo.medium }}>{source.title || source.url}</div><div style={{ color: colors.textTertiary, fontSize: typo.xs, overflowWrap: "anywhere", marginTop: 3 }}>{source.url}</div></div><span style={{ color: colors.textSecondary, fontSize: typo.xs }}>{source.trust_tier}</span></div><div style={{ color: colors.textSecondary, fontSize: typo.xs, marginTop: space.sm }}>{source.mime_type} · {source.source_id} · artifact {source.snapshot_artifact_id || "pending"}</div></div>)}
        </div>
      </section>
    </div>
  );
}