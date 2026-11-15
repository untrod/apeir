/** Read-only rendering of original Runtime outputs. Provider text is never executable markup. */
export function WorkflowOutputs({ outputs, states, locale }: { outputs: Record<string, unknown>; states: Record<string, string>; locale: "en" | "zh" }) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const entries = Object.entries(outputs || {});
  if (!entries.length) return <p>{t("No step output yet.", "暂无节点输出。")}</p>;
  return <section aria-label={t("Step outputs", "节点输出")} className="workflow-outputs">{entries.map(([id, value]) => {
    const record = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
    const display = record && (typeof record.content === "string" ? record.content : Object.prototype.hasOwnProperty.call(record, "value") ? record.value : record.structured_output ?? value);
    const text = typeof display === "string" ? display : JSON.stringify(display ?? value, null, 2) ?? "UNKNOWN";
    return <article key={id}><header><strong>{id}</strong><span>{states[id] || "UNKNOWN"}</span></header><div className="workflow-output-text">{text.slice(0, 8192)}</div>{text.length > 8192 && <small>{t("Preview shortened. The full result is in the original record.", "预览已截断，完整结果可在原始记录中查看。")}</small>}{record && typeof record.model_id === "string" && <small>{typeof record.provider_id === "string" ? record.provider_id : "UNKNOWN"} · {record.model_id}</small>}</article>;
  })}</section>;
}
