import React, { useCallback, useEffect, useState } from "react";

import { btnPrimary, btnSecondary, card, colors, input, radius, space, typo } from "../design";
import {
  ApiError, approvalAction, createDocument, fetchDocuments, fetchDocumentStatus, renderDocument,
  type DocumentCreateRequest, type DocumentCreateResult, type DocumentRenderResult,
  type DocumentRuntimeStatus, type DocumentSummary,
} from "../lib/api";
import { errorMessage } from "../lib/format";

type Pending =
  | { kind: "create"; approvalId: string; request: DocumentCreateRequest }
  | { kind: "render"; approvalId: string; documentId: string; formats: Array<"docx" | "pdf"> };

export function DocumentWorkbench() {
  const [status, setStatus] = useState<DocumentRuntimeStatus | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [title, setTitle] = useState("Nous Professional Brief");
  const [subtitle, setSubtitle] = useState("Governed, traceable and render-verified");
  const [body, setBody] = useState("Executive summary\n\nNous turns typed Document IR into safe DOCX and PDF artifacts.\n\nCapabilities\n- Bounded structured input\n- Explicit approval before local writes\n- Structural verification and Artifact evidence");
  const [preset, setPreset] = useState<DocumentCreateRequest["preset"]>("standard_business_brief");
  const [selected, setSelected] = useState("");
  const [created, setCreated] = useState<DocumentCreateResult | null>(null);
  const [rendered, setRendered] = useState<DocumentRenderResult | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [nextStatus, nextDocuments] = await Promise.all([fetchDocumentStatus(), fetchDocuments()]);
    setStatus(nextStatus);
    setDocuments(nextDocuments.documents);
    if (!selected && nextDocuments.documents[0]?.document_id) setSelected(nextDocuments.documents[0].document_id);
  }, [selected]);

  useEffect(() => { void refresh().catch((cause) => setError(errorMessage(cause, "Document Runtime is unavailable."))); }, [refresh]);

  const requestFromEditor = (): DocumentCreateRequest => {
    const lines = body.split(/\r?\n/);
    const blocks: DocumentCreateRequest["blocks"] = [];
    let list: string[] = [];
    const flushList = () => { if (list.length) { blocks.push({ kind: "bullet_list", items: list }); list = []; } };
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) { flushList(); continue; }
      if (line.startsWith("- ")) { list.push(line.slice(2).trim()); continue; }
      flushList();
      if (/^(Executive summary|Capabilities|Summary|Overview|摘要|能力|概述)$/i.test(line)) blocks.push({ kind: "heading", level: 1, text: line });
      else blocks.push({ kind: "paragraph", text: line });
    }
    flushList();
    return { title: title.trim(), subtitle: subtitle.trim(), author: "Nous Desktop", language: "zh-CN", preset, blocks };
  };

  const captureApproval = (cause: unknown, value: Pending): boolean => {
    if (!(cause instanceof ApiError) || cause.code !== "NOUS_APPROVAL_REQUIRED") return false;
    const approvalId = String(cause.details?.approval_request_id || "");
    if (!approvalId) return false;
    setPending({ ...value, approvalId } as Pending);
    return true;
  };

  const executeCreate = async (request: DocumentCreateRequest) => {
    setBusy(true); setError(""); setRendered(null);
    try {
      const result = await createDocument(request);
      setCreated(result); setSelected(result.document_id); setPending(null);
      await refresh();
    } catch (cause) {
      if (!captureApproval(cause, { kind: "create", approvalId: "", request })) setError(errorMessage(cause, "Document creation failed."));
    } finally { setBusy(false); }
  };

  const executeRender = async (documentId: string, formats: Array<"docx" | "pdf">) => {
    setBusy(true); setError(""); setRendered(null);
    try {
      setRendered(await renderDocument(documentId, formats)); setPending(null);
    } catch (cause) {
      if (!captureApproval(cause, { kind: "render", approvalId: "", documentId, formats })) setError(errorMessage(cause, "Document rendering failed."));
    } finally { setBusy(false); }
  };

  const approveAndContinue = async () => {
    if (!pending || busy) return;
    const reviewed = pending;
    setBusy(true); setError("");
    try {
      await approvalAction(reviewed.approvalId, "approve");
      setBusy(false);
      if (reviewed.kind === "create") await executeCreate(reviewed.request);
      else await executeRender(reviewed.documentId, reviewed.formats);
    } catch (cause) { setError(errorMessage(cause, "Approval could not be applied.")); setBusy(false); }
  };

  return <div style={{ height: "100%", overflowY: "auto", background: colors.bg, padding: space.xl }}>
    <div style={{ maxWidth: 1120, margin: "0 auto", display: "grid", gap: space.lg }}>
      <section style={{ ...card, display: "flex", justifyContent: "space-between", gap: space.md, flexWrap: "wrap" }}>
        <div><div style={{ fontSize: typo.lg, fontWeight: typo.semibold, color: colors.text }}>Professional Documents</div>
          <div style={{ color: colors.textSecondary, fontSize: typo.sm, marginTop: space.xs }}>Document IR → approval → DOCX/PDF → structural verification → Artifact evidence</div></div>
        <div style={{ color: status?.formats.docx && status?.formats.pdf ? colors.success : colors.warning, fontSize: typo.sm }}>
          {status ? `${status.documents} documents · DOCX ${status.formats.docx ? "ready" : "missing"} · PDF ${status.formats.pdf ? "ready" : "missing"}` : "Checking…"}
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.6fr) minmax(280px, 0.8fr)", gap: space.lg }}>
        <section style={card}>
          <div style={{ color: colors.text, fontWeight: typo.semibold, marginBottom: space.md }}>Compose from bounded IR</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm }}>
            <input aria-label="Document title" value={title} onChange={(event) => setTitle(event.target.value)} style={input} />
            <select aria-label="Document preset" value={preset} onChange={(event) => setPreset(event.target.value as DocumentCreateRequest["preset"])} style={input}>
              <option value="standard_business_brief">Business brief</option><option value="compact_reference_guide">Reference guide</option><option value="narrative_proposal">Narrative proposal</option>
            </select>
          </div>
          <input aria-label="Document subtitle" value={subtitle} onChange={(event) => setSubtitle(event.target.value)} style={{ ...input, marginTop: space.sm }} />
          <textarea aria-label="Document body" value={body} onChange={(event) => setBody(event.target.value)} rows={15} style={{ ...input, marginTop: space.sm, resize: "vertical", fontFamily: typo.font, lineHeight: typo.body }} />
          <button onClick={() => void executeCreate(requestFromEditor())} disabled={busy || !title.trim() || !body.trim()} style={{ ...btnPrimary, marginTop: space.md, opacity: busy ? 0.55 : 1 }}>
            {busy ? "Working…" : "Create governed document"}
          </button>
          {created && <div style={{ marginTop: space.md, color: colors.success, fontSize: typo.sm }}>Created {created.document_id} · Artifact {created.artifact_id}</div>}
        </section>

        <section style={card}>
          <div style={{ color: colors.text, fontWeight: typo.semibold }}>Library and verified export</div>
          <select aria-label="Document library" value={selected} onChange={(event) => setSelected(event.target.value)} style={{ ...input, marginTop: space.md }}>
            <option value="">Select a document</option>{documents.filter((item) => !item.status).map((item) => <option key={item.document_id} value={item.document_id}>{item.title}</option>)}
          </select>
          <div style={{ display: "grid", gap: space.sm, marginTop: space.md }}>
            <button onClick={() => void executeRender(selected, ["docx", "pdf"])} disabled={busy || !selected} style={{ ...btnPrimary, opacity: busy || !selected ? 0.55 : 1 }}>Render and verify DOCX + PDF</button>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.sm }}>
              <button onClick={() => void executeRender(selected, ["docx"])} disabled={busy || !selected} style={btnSecondary}>DOCX only</button>
              <button onClick={() => void executeRender(selected, ["pdf"])} disabled={busy || !selected} style={btnSecondary}>PDF only</button>
            </div>
          </div>
          {rendered && <div style={{ marginTop: space.md, display: "grid", gap: space.sm }}>{rendered.outputs.map((output) =>
            <div key={output.artifact_id} style={{ padding: space.sm, border: `1px solid ${colors.borderLight}`, borderRadius: radius.md, color: colors.text, fontSize: typo.sm }}>
              <strong>{output.format.toUpperCase()}</strong> · verified · {output.size_bytes.toLocaleString()} bytes<br/><span style={{ color: colors.textTertiary }}>{output.location}</span><br/>Artifact {output.artifact_id}
            </div>)}</div>}
        </section>
      </div>

      {pending && <section style={{ ...card, borderColor: colors.warning, background: colors.warningSoft }}>
        <div style={{ color: colors.text, fontWeight: typo.semibold }}>Explicit approval required</div>
        <div style={{ color: colors.textSecondary, fontSize: typo.sm, margin: `${space.sm} 0` }}>Review the local document write. Approval is one-use; Nous retries the identical request.</div>
        <button onClick={() => void approveAndContinue()} disabled={busy} style={btnPrimary}>Approve once and {pending.kind === "create" ? "create" : "render"}</button>
      </section>}
      {error && <section style={{ ...card, color: colors.danger, borderColor: colors.danger }}>{error}</section>}
    </div>
  </div>;
}