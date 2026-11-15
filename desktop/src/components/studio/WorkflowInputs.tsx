import type { WorkflowDefinition } from "../../lib/studioWorkflow";

/** Plain fields for simple schemas; complex/imported contracts retain their JSON editor. */
export function WorkflowInputs({ definition, value, onChange, locale }: { definition: WorkflowDefinition; value: string; onChange: (value: string) => void; locale: "en" | "zh" }) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const schema = definition.inputs_schema;
  const properties = schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return null;
  const entries = Object.entries(properties);
  if (!entries.length || entries.length > 12 || entries.some(([key, config]) => key.startsWith("_") || ["constructor", "prototype"].includes(key) || !config || typeof config !== "object" || Array.isArray(config) || !["string", "number", "integer", "boolean"].includes(String((config as Record<string, unknown>).type)))) return null;
  let inputs: Record<string, unknown>;
  try { const parsed = JSON.parse(value); if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null; inputs = parsed; } catch { return null; }
  return <fieldset className="workflow-input-form" aria-label={t("Run input form", "运行输入表单")}><legend>{t("Task inputs", "任务输入")}</legend>{entries.map(([name, raw]) => {
    const config = raw as Record<string, unknown>;
    const title = typeof config.title === "string" ? config.title.slice(0, 100) : name;
    const maxLength = typeof config.maxLength === "number" && Number.isInteger(config.maxLength) && config.maxLength >= 0 ? Math.min(32768, config.maxLength) : 32768;
    const update = (entry: unknown) => onChange(JSON.stringify({ ...inputs, [name]: entry }, null, 2));
    return <label key={name}>{title}{config.type === "boolean" ? <input aria-label={name} type="checkbox" checked={inputs[name] === true} onChange={e => update(e.target.checked)} /> : config.type === "string" ? <textarea aria-label={name} maxLength={maxLength} value={typeof inputs[name] === "string" ? inputs[name] : ""} onChange={e => update(e.target.value)} /> : <input aria-label={name} type="number" step={config.type === "integer" ? "1" : "any"} value={typeof inputs[name] === "number" ? inputs[name] : ""} onChange={e => { if (e.target.value === "") { const next = { ...inputs }; delete next[name]; onChange(JSON.stringify(next, null, 2)); } else if (Number.isFinite(e.target.valueAsNumber)) update(e.target.valueAsNumber); }} />}</label>;
  })}</fieldset>;
}
