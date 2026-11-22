import { useEffect, useState } from "react";
import { btnSecondary, colors, radius, space, typo } from "../design";
import { fetchRunEvents, getConfig, getRuntimeConfigVersion } from "../lib/api";
import { errorMessage } from "../lib/format";
import { useRuntimeConfigVersion, type RuntimeEventEnvelope } from "../store";
import { measuredUsage, usageCounters } from "../lib/usageAccounting";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): RecordValue => value !== null && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const number = (value: unknown): string => typeof value === "number" && Number.isFinite(value) && value >= 0 ? String(value) : "UNKNOWN";
const hash = (value: unknown): string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value) ? value : "UNKNOWN";

function Source({ value, locale }: { value: unknown; locale: "en" | "zh" }) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const source = record(value);
  if (source.kind === "conversation_summary") return <>{t("Archived conversation excerpt · incomplete history · not authorization", "历史对话摘录 · 非完整记忆 · 不授予权限")}</>;
  if (source.kind === "tool_result") return <>
    {t("Tool result", "工具结果")} · {String(source.tool || "unknown")} · {source.ok === true ? t("read/operation returned data", "读取或操作已返回数据") : t("failed; no successful read claimed", "失败；未声明读取成功")}
    {source.tool === "read_file" && source.ok === true && <div>
      {t("File:", "文件：")} {String(source.path || "UNKNOWN")} · {t("lines", "行")} {number(source.start_line)}–{number(source.end_line)}
      <div>{t("File SHA-256:", "文件 SHA-256：")} {hash(source.file_sha256)}</div>
    </div>}
  </>;
  if (source.kind === "selected_context") return <>
    {t("Selected context", "已选上下文")} · {number(source.item_count)} {t("sources · identifiers hashed", "个来源 · 标识符已哈希") }
    <ul>{array(source.items).slice(0, 128).map((value, index) => {
      const item = record(value);
      return <li key={index}>{String(item.source_type || "unknown")} · {String(item.status || "UNKNOWN")} · {number(item.included_characters)}/{number(item.total_characters)} {t("characters", "字符")}
        <div>{t("Source reference SHA-256:", "来源引用 SHA-256：")} {hash(item.source_ref_sha256)}</div>
      </li>;
    })}</ul>
    {source.items_truncated === true && <div>{t("Source details truncated; omitted details are unknown.", "来源详情已截断，省略部分为未知。")}</div>}
  </>;
  return <>{source.kind === "instruction" ? t("Runtime instruction", "运行时指令") : source.kind === "conversation" ? t("Conversation / current request", "对话／当前请求") : source.kind === "work_checkpoint" ? t("Original Work checkpoint · history may be incomplete", "原始任务检查点 · 历史可能不完整") : t("UNKNOWN source", "UNKNOWN 来源")}</>;
}

/** Read-only projection of canonical EventStream; never a model or authority call. */
export function ContextInspector({ runId, controller, onClose, locale = "en" }: {
  locale?: "en" | "zh"; runId: string; controller: string; onClose: () => void;
}) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const usageText = (value: unknown, measurement: unknown, money = false) => {
    const text = measuredUsage(value, measurement, money);
    return locale === "zh" ? text.replace("Provider reported", "服务商报告").replace("Estimated", "估算").replace("Derived", "推导") : text;
  };
  const [events, setEvents] = useState<Partial<RuntimeEventEnvelope>[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [partial, setPartial] = useState(false);
  const [selected, setSelected] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const configurationVersion = useRuntimeConfigVersion();
  const [evidenceBinding, setEvidenceBinding] = useState<{ runId: string; controller: string; version: number } | null>(null);
  useEffect(() => {
    let cancelled = false;
    setEvidenceBinding({ runId, controller, version: configurationVersion });
    setEvents([]); setLoading(true); setError(""); setPartial(false); setSelected(0);
    void (async () => {
      try {
        let cursor = 0;
        const loaded: Partial<RuntimeEventEnvelope>[] = [];
        let truncated = true;
        for (let page = 0; page < 8; page++) {
          if (getConfig().url !== controller || getRuntimeConfigVersion() !== configurationVersion) throw new Error("Controller changed; original context cannot be queried here.");
          const response = await fetchRunEvents(runId, cursor);
          if (cancelled) return;
          if (getConfig().url !== controller || getRuntimeConfigVersion() !== configurationVersion || response.run_id !== runId) throw new Error("Context evidence does not match the requested Controller and Run.");
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
  }, [runId, controller, refresh, configurationVersion]);

  const currentEvidence = evidenceBinding?.runId === runId && evidenceBinding.controller === controller && evidenceBinding.version === configurationVersion;
  const visibleEvents = currentEvidence ? events : [];
  const invocations = visibleEvents.filter(event => event.event_type === "model.invocation.started");
  const invocation = invocations[selected];
  const payload = record(invocation?.payload);
  const manifest = record(payload.input_manifest);
  const valid = manifest.schema_version === 1 && ["admitted-gateway-input", "prepared-work-gateway-input"].includes(String(manifest.scope)) && hash(manifest.input_sha256) !== "UNKNOWN"
    && Number.isInteger(manifest.message_count) && Number(manifest.message_count) >= 0
    && Number.isInteger(manifest.tool_count) && Number(manifest.tool_count) >= 0
    && Array.isArray(manifest.messages) && manifest.messages.length === Math.min(Number(manifest.message_count), 256)
    && Array.isArray(manifest.tools) && manifest.tools.length === Math.min(Number(manifest.tool_count), 64);
  const completion = visibleEvents.find(event => (event.event_type === "model.invocation.completed" || event.event_type === "model.invocation.failed") && (payload.invocation_id ? record(event.payload).invocation_id === payload.invocation_id : record(event.payload).iteration === payload.iteration));
  const completed = record(completion?.payload);
  const usage = record(completed.usage);
  const measurements = record(usage.counter_measurements);
  const selectedInputEvents = visibleEvents.filter(event => event.event_type?.startsWith("context.input.") && (record(event.payload).input_sha256 === manifest.input_sha256 || record(event.payload).input_sha256 === undefined));
  const selectedInput = array(record(selectedInputEvents.at(-1)?.payload).sources);

  return <section aria-label={t("Model Context Inspector", "模型上下文")} style={{ padding: space.md, border: `1px solid ${colors.border}`, borderRadius: radius.md, background: colors.surface, fontSize: typo.xs, overflowWrap: "anywhere", maxHeight: "50vh", overflowY: "auto" }}>
    <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
      <strong>{t("Model Context Inspector", "模型上下文")}</strong>
      <button onClick={() => setRefresh(value => value + 1)} disabled={loading} style={btnSecondary}>{t("Reload evidence", "刷新记录")}</button>
      <button onClick={onClose} style={btnSecondary}>{t("Close context", "关闭上下文")}</button>
    </div>
    <details><summary>{t("Technical details", "技术详情")}</summary><p>{t("Run", "运行")} {runId}</p></details>
    <p>{t("Recorded input and usage; prompts and file contents are not copied here. Tool declarations do not grant permission.", "查看输入来源与用量；此处不复制提示词或文件正文。工具声明不授予权限。")}</p>
    {loading || !currentEvidence ? <p role="status">{t("Loading persisted model input\u2026", "正在加载输入记录…")}</p> : error ? <p role="alert">{t("Context unavailable:", "上下文不可用：")} {error}</p> : <>
      {partial && <p>{t("Partial replay: the 1,600-event inspection bound was reached. Later input is UNKNOWN.", "已达到 1,600 条事件查看上限，后续输入状态为 UNKNOWN。")}</p>}
      {selectedInput.length > 0 && <section aria-label={t("Saved file input provenance", "文件输入来源")}><h3>{t("Selected saved files", "已选文件")}</h3><p>{t("Sent means the Gateway dispatched to its provider boundary; provider receipt is not confirmed.", "“已发送”表示网关已发出请求，不代表服务商确认接收。")}</p><ul>{selectedInput.slice(0, 8).map((value, index) => { const source = record(value); const status = ["selected", "read", "sent", "rejected", "budget_limited"].includes(String(source.status)) ? String(source.status) : "UNKNOWN"; return <li key={index}>{status} · read: {source.was_read === true ? "yes" : source.was_read === false ? "no" : "UNKNOWN"}<div>{t("Source:", "来源：")} {typeof source.source_id === "string" && /^workspace-file:[a-f0-9]{64}$/.test(source.source_id) ? source.source_id : "UNKNOWN"}</div><div>{t("Saved SHA-256:", "文件 SHA-256：")} {hash(source.source_version)}</div></li>; })}</ul></section>}
      {invocations.length === 0 ? <p>{t("UNKNOWN — no recorded model input for this Run. This does not mean that the model saw no context.", "UNKNOWN：没有可用输入记录，不代表模型未收到上下文。")}</p> : <>
        <label>{t("Model invocation", "模型调用")} <select aria-label={t("Model invocation", "模型调用")} value={selected} onChange={event => setSelected(Number(event.target.value))}>
          {invocations.map((event, index) => <option key={event.event_id || index} value={index}>{t("Iteration", "迭代")} {String(record(event.payload).iteration || index + 1)}</option>)}
        </select></label>
        {manifest.scope === "prepared-work-gateway-input" && <p>{t("Prepared Work input; execution admission and Provider receipt are separate.", "已准备的任务输入；执行授权与服务商接收状态需分别确认。")}</p>}
        {!valid ? <p>{t("UNKNOWN — this invocation has no supported input manifest.", "UNKNOWN：本次调用没有受支持的输入清单。")}</p> : <>
          <details><summary>{t("Input integrity", "输入完整性")}</summary><p>{t("Input SHA-256:", "输入 SHA-256：")} {hash(manifest.input_sha256)}</p></details>
          <p>{t("Estimated input tokens:", "估算输入 Token：")} {number(manifest.estimated_input_tokens)} {t("(heuristic, including tools). Recorded input tokens:", "（包含工具声明的估算值）。记录输入 Token：")} {usageText(usage.input_tokens, measurements.input_tokens)}{t(". Cached input tokens:", "。缓存输入 Token：")} {usageText(usage.cached_input_tokens, measurements.cached_input_tokens)}.</p>
          <p>{t("Provider reported values are telemetry, not independently verified invoices. Missing measurements and unclassified legacy values remain UNKNOWN.", "服务商报告值不是独立核验的账单；缺失或无法识别的计量保持 UNKNOWN。")}</p>
          <p>{t("Provider:", "服务商：")} {String(completed.provider_id || "UNKNOWN")} · {t("model:", "模型：")} {String(completed.model_id || "UNKNOWN")} · {t("latency:", "耗时：")} {number(completed.latency_ms)} ms · {t("cost:", "费用：")} {usageText(completed.cost_usd, completed.cost_measurement, true)}</p>
          <details><summary>{t("Usage receipt", "用量回执")}</summary><p>{t("Usage receipt:", "用量回执：")} {String(completed.usage_receipt_ref || "UNKNOWN")} · {t("request:", "请求：")} {String(completed.usage_request_id || "UNKNOWN")} · {t("attempt:", "尝试：")} {number(completed.usage_attempt)}</p></details>
          {usageCounters.filter(([key]) => key !== "input_tokens" && key !== "cached_input_tokens").map(([key, label]) =>
            <div key={key}>{locale === "zh" ? ({ output_tokens: "输出 Token", total_tokens: "总 Token", reasoning_tokens: "推理 Token", cache_miss_input_tokens: "未命中缓存 Token", cache_creation_input_tokens: "缓存写入 Token" } as Record<string, string>)[key] || label : label}: {usageText(usage[key], measurements[key])}</div>)}
          <p>{t("Invocation outcome:", "调用结果：")} {completion?.event_type === "model.invocation.completed" ? t("response returned", "响应已返回") : completion?.event_type === "model.invocation.failed" ? t("failed", "失败") : t("UNKNOWN / no terminal event", "UNKNOWN／无结束事件")}{t(". This is not effect verification.", "。这不代表实际效果已验证。")}</p>
          <h3>{t("Messages", "消息")} ({number(manifest.message_count)})</h3>
          {array(manifest.messages).slice(0, 256).map((value, index) => {
            const message = record(value);
            return <details key={index}><summary>#{number(message.index)} · {String(message.role || "unknown")} · {number(message.content_characters)} characters · ~{number(message.estimated_tokens)} tokens</summary>
              <Source value={message.source} locale={locale} /><div>{t("Message SHA-256:", "消息 SHA-256：")} {hash(message.sha256)}</div>
            </details>;
          })}
          {manifest.messages_truncated === true && <p>{t("Message details truncated; counts and input digest cover the full Gateway request.", "消息详情已截断，计数与摘要覆盖完整网关请求。")}</p>}
          <h3>{t("Available tools", "可用工具")} ({number(manifest.tool_count)})</h3>
          <p>{array(manifest.tools).slice(0, 64).map(value => String(record(value).name || "unknown")).join(", ") || t("None declared", "未声明工具")}</p>
          {manifest.tools_truncated === true && <p>{t("Tool details truncated.", "工具详情已截断。")}</p>}
        </>}
      </>}
    </>}
  </section>;
}
