import { useEffect, useState } from "react";
import { btnSecondary, colors, radius, space, typo } from "../design";
import { fetchRunEvents, getConfig } from "../lib/api";
import { errorMessage } from "../lib/format";
import type { RuntimeEventEnvelope } from "../store";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const number = (value: unknown): string => typeof value === "number" && Number.isFinite(value) && value >= 0 ? String(value) : "UNKNOWN";
const hash = (value: unknown): string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : "UNKNOWN";

function Source({ value }: { value: unknown }) {
  const source = record(value);
  if (source.kind === "tool_result") return <>
    Tool result · {String(source.tool || "unknown")} · {source.ok === true ? "read/operation returned data" : "failed; no successful read claimed"}
    {source.tool === "read_file" && source.ok === true && <div>
      File: {String(source.path || "UNKNOWN")} · lines {number(source.start_line)}–{number(source.end_line)}
      <div>File SHA-256: {hash(source.file_sha256)}</div>
    </div>}
  </>;
  if (source.kind === "selected_context") return <>
    Selected context · {number(source.item_count)} sources · identifiers hashed
    <ul>{array(source.items).slice(0, 128).map((value, index) => {
      const item = record(value);
      return <li key={index}>{String(item.source_type || "unknown")} · {String(item.status || "UNKNOWN")} · {number(item.included_characters)}/{number(item.total_characters)} characters
        <div>Source reference SHA-256: {hash(item.source_ref_sha256)}</div>
      </li>;
    })}</ul>
    {source.items_truncated === true && <div>Source details truncated; omitted details are unknown.</div>}
  </>;
  return <>{source.kind === "instruction" ? "Runtime instruction" : source.kind === "conversation" ? "Conversation / current request" : "UNKNOWN source"}</>;
}

/** Read-only projection of canonical EventStream; never a model or authority call. */
export function ContextInspector({ runId, controller, onClose }: {
  runId: string; controller: string; onClose: () => void;
}) {
  const [events, setEvents] = useState<Partial<RuntimeEventEnvelope>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [partial, setPartial] = useState(false);
  const [selected, setSelected] = useState(0);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setEvents([]); setLoading(true); setError(""); setPartial(false); setSelected(0);
    void (async () => {
      try {
        let cursor = 0;
        const loaded: Partial<RuntimeEventEnvelope>[] = [];
        let truncated = true;
        for (let page = 0; page < 8; page++) {
          if (getConfig().url !== controller) throw new Error("Controller changed; original context cannot be queried here.");
          const response = await fetchRunEvents(runId, cursor);
          if (cancelled) return;
          if (getConfig().url !== controller || response.run_id !== runId) throw new Error("Context evidence does not match the requested Controller and Run.");
          loaded.push(...response.events);
          if (response.events.length < 200) { truncated = false; break; }
          if (response.next_after_sequence <= cursor) throw new Error("Context replay cursor did not advance.");
          cursor = response.next_after_sequence;
        }
        if (!cancelled) { setEvents(loaded); setPartial(truncated); }
      } catch (cause) { if (!cancelled) setError(errorMessage(cause, "Persisted context could not be loaded")); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [runId, controller, refresh]);

  const invocations = events.filter(event => event.event_type === "model.invocation.started");
  const invocation = invocations[selected];
  const payload = record(invocation?.payload);
  const manifest = record(payload.input_manifest);
  const valid = manifest.schema_version === 1 && manifest.scope === "admitted-gateway-input" && hash(manifest.input_sha256) !== "UNKNOWN"
    && Number.isInteger(manifest.message_count) && Number(manifest.message_count) >= 0
    && Number.isInteger(manifest.tool_count) && Number(manifest.tool_count) >= 0
    && Array.isArray(manifest.messages) && manifest.messages.length === Math.min(Number(manifest.message_count), 256)
    && Array.isArray(manifest.tools) && manifest.tools.length === Math.min(Number(manifest.tool_count), 64);
  const completion = events.find(event => (event.event_type === "model.invocation.completed" || event.event_type === "model.invocation.failed") && record(event.payload).iteration === payload.iteration);
  const completed = record(completion?.payload);
  const usage = record(completed.usage);

  return <section aria-label="Model Context Inspector" style={{ padding: space.md, border: `1px solid ${colors.border}`, borderRadius: radius.md, background: colors.surface, fontSize: typo.xs, overflowWrap: "anywhere", maxHeight: "50vh", overflowY: "auto" }}>
    <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
      <strong>Model Context Inspector</strong>
      <button onClick={() => setRefresh(value => value + 1)} disabled={loading} style={btnSecondary}>Reload evidence</button>
      <button onClick={onClose} style={btnSecondary}>Close context</button>
    </div>
    <p>Run {runId}. Recorded Gateway input; provider-specific formatting and provider receipt are not proven here. Tool declarations do not grant permission. Prompt and file contents are not copied into this manifest.</p>
    {loading ? <p role="status">Loading persisted model input…</p> : error ? <p role="alert">Context unavailable: {error}</p> : <>
      {partial && <p>Partial replay: the 1,600-event inspection bound was reached. Later input is UNKNOWN.</p>}
      {invocations.length === 0 ? <p>UNKNOWN — no recorded model input for this Run. This does not mean that the model saw no context.</p> : <>
        <label>Model invocation <select aria-label="Model invocation" value={selected} onChange={event => setSelected(Number(event.target.value))}>
          {invocations.map((event, index) => <option key={event.event_id || index} value={index}>Iteration {String(record(event.payload).iteration || index + 1)}</option>)}
        </select></label>
        {!valid ? <p>UNKNOWN — this invocation has no supported input manifest.</p> : <>
          <p>Input SHA-256: {hash(manifest.input_sha256)}</p>
          <p>Estimated input tokens: {number(manifest.estimated_input_tokens)} (heuristic, including tools). Recorded input tokens: {number(usage.input_tokens)}. Cached input tokens: {number(usage.cached_input_tokens)}.</p>
          <p>Usage and cost are normalized Runtime counters; zero does not establish a reported Provider measurement.</p>
          <p>Provider: {String(completed.provider_id || "UNKNOWN")} · model: {String(completed.model_id || "UNKNOWN")} · latency: {number(completed.latency_ms)} ms · cost: {number(completed.cost_usd)} USD</p>
          <p>Invocation outcome: {completion?.event_type === "model.invocation.completed" ? "response returned" : completion?.event_type === "model.invocation.failed" ? "failed" : "UNKNOWN / no terminal event"}. This is not effect verification.</p>
          <h3>Messages ({number(manifest.message_count)})</h3>
          {array(manifest.messages).slice(0, 256).map((value, index) => {
            const message = record(value);
            return <details key={index}><summary>#{number(message.index)} · {String(message.role || "unknown")} · {number(message.content_characters)} characters · ~{number(message.estimated_tokens)} tokens</summary>
              <Source value={message.source} /><div>Message SHA-256: {hash(message.sha256)}</div>
            </details>;
          })}
          {manifest.messages_truncated === true && <p>Message details truncated; counts and input digest cover the full Gateway request.</p>}
          <h3>Available tools ({number(manifest.tool_count)})</h3>
          <p>{array(manifest.tools).slice(0, 64).map(value => String(record(value).name || "unknown")).join(", ") || "None declared"}</p>
          {manifest.tools_truncated === true && <p>Tool details truncated.</p>}
        </>}
      </>}
    </>}
  </section>;
}
