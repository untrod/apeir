import { colors, space, typo } from "../design";
import { measuredUsage, usageCounters, usageMoney, usageNumber, usageTotal } from "../lib/usageAccounting";
import type { UsageAccountingSummary } from "../store/types";

/** A read-only view of CostController's summary, never a local cost calculation. */
export function UsageAccounting({ summary, compact = false, locale = "en" }: {
  summary: UsageAccountingSummary; compact?: boolean; locale?: "en" | "zh";
}) {
  const t = (en: string, zh: string) => locale === "zh" ? zh : en;
  const counterLabels: Record<string, string> = { input_tokens: "输入 Token", output_tokens: "输出 Token", cached_input_tokens: "缓存命中 Token", cache_miss_input_tokens: "缓存未命中 Token", reasoning_tokens: "推理 Token", total_tokens: "Token 总量", cache_creation_input_tokens: "缓存写入 Token" };
  const empty = summary.requests === 0 && summary.pending_requests === 0;
  const policy = summary.policy;
  const pricing = policy.pricing;
  return <div aria-label="Usage accounting" style={{ fontSize: typo.sm, color: colors.textSecondary, overflowWrap: "anywhere" }}>
    <div style={{ fontSize: compact ? typo.lg : typo.xl, color: colors.text, fontWeight: typo.semibold }}>
      {empty ? t("No usage receipts", "暂无用量记录") : usageTotal(summary)}
    </div>
    <p>{summary.day} UTC · {usageNumber(summary.requests)} {t("usage receipts", "用量记录")} · {usageNumber(summary.pending_requests)} {t("pending requests", "待确认请求")}</p>
    {empty ? <p>{t("No cost measurement has been recorded yet.", "尚无费用记录。")}</p> : <>
      <div>{t("Provider reported:", "服务商上报：")} {summary.reported_cost_requests > 0 ? usageMoney(summary.reported_cost_usd) : t("No reported-cost receipts", "暂无上报费用记录")} ({usageNumber(summary.reported_cost_requests)} {t("receipts", "条记录")})</div>
      <div>{t("Estimated cost:", "估算费用：")} {summary.estimated_cost_requests > 0 ? usageMoney(summary.estimated_cost_usd) : t("No estimated-cost receipts", "暂无估算费用记录")} ({usageNumber(summary.estimated_cost_requests)} {t("receipts", "条记录")})</div>
      <div>{t("Derived cost:", "推算费用：")} {summary.derived_cost_requests > 0 ? usageMoney(summary.derived_cost_usd) : t("No derived-cost receipts", "暂无推算费用记录")} ({usageNumber(summary.derived_cost_requests)} {t("receipts", "条记录")})</div>
      <p>{t("Unknown cost:", "未知费用：")} {usageNumber(summary.unknown_cost_requests)} {t("receipts", "条记录")} · {t("uncertain calls:", "结果未确认的调用：")} {usageNumber(summary.uncertain_calls)}. {t("Known subtotals exclude unknown costs.", "已知小计不包含未知费用。")}</p>
    </>}
    <p>{t("Provider reported values are telemetry, not independently verified invoices.", "服务商上报值为用量数据，不代表独立核验的账单。")}</p>
    <div>{t("Reserved estimates:", "预留估算：")} {summary.reservations.length === 0 ? t("No outstanding reservations", "无待完成的预留") : <>{usageNumber(summary.reserved_tokens)} tokens · {usageMoney(summary.reserved_cost_usd)}</>}</div>
    <div>{t("Remaining token budget:", "剩余 Token 预算：")} {usageNumber(summary.remaining.tokens)}</div>
    <div>{t("Remaining USD budget:", "剩余美元预算：")} {policy.max_daily_cost_usd === null ? t("Disabled by the configured policy", "当前策略未启用") : usageMoney(summary.remaining.cost_usd)}</div>
    {!compact && <>
      <details style={{ marginTop: space.md }} open>
        <summary>{t("Token usage", "Token 用量")}</summary>
        <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse", marginTop: space.sm }}>
          <thead><tr><th>{t("Counter", "计数项")}</th><th>{t("Total", "合计")}</th><th>{t("Known subtotal", "已知小计")}</th><th>{t("Estimated subtotal", "估算小计")}</th><th>{t("Unknown receipts", "未知记录")}</th></tr></thead>
          <tbody>{usageCounters.map(([key, label]) => <tr key={key}>
            <th style={{ padding: "6px 0", fontWeight: typo.normal }}>{t(label, counterLabels[key])}</th>
            <td>{empty ? t("No receipts", "暂无记录") : usageNumber(summary[key])}</td>
            <td>{empty ? t("No receipts", "暂无记录") : usageNumber(summary.known_totals[key])}</td>
            <td>{empty ? t("No receipts", "暂无记录") : usageNumber(summary.estimated_totals[key])}</td>
            <td>{usageNumber(summary.unknown_counters[key])}</td>
          </tr>)}</tbody>
        </table>
        <p>{t("Known subtotals include reported and derived counters. Estimates and unknown counters cannot establish a complete reported total.", "已知小计包括上报及推算值；估算或未知记录不能证明上报总量完整。")}</p>
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>{t("Usage by Provider, model and task", "按服务商、模型和任务查看用量")} ({summary.items.length})</summary>
        {summary.items.length === 0 ? <p>{t("No recorded usage groups for this day.", "此日期暂无分组用量。")}</p> : <>
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse", marginTop: space.sm }}>
            <thead><tr><th>{t("Provider / model", "服务商 / 模型")}</th><th>{t("Task", "任务")}</th><th>{t("Receipts", "记录")}</th><th>{t("Accounted cost", "已核算费用")}</th><th>{t("Unknown cost receipts", "费用未知的记录")}</th><th>{t("Total tokens", "Token 总量")}</th></tr></thead>
            <tbody>{summary.items.map((item, index) => <tr key={`${item.provider_id}/${item.model_id}/${item.task_id}/${index}`}>
              <td style={{ padding: "6px 0" }}>{item.provider_id} / {item.model_id}</td><td>{item.task_id || "UNKNOWN"}</td>
              <td>{usageNumber(item.requests)}</td><td>{usageMoney(item.cost_usd)}</td>
              <td>{usageNumber(item.unknown_cost_requests)}</td><td>{usageNumber(item.total_tokens)}</td>
            </tr>)}</tbody>
          </table>
          <p>{t("Accounted cost", "已核算费用")}s include available reported, derived and estimated values. Inspect receipts for each measurement's source. Unknown costs are excluded from known subtotals.</p>
        </>}
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>{t("Budget and pricing configuration", "预算与定价设置")}</summary>
        <p>{policy.max_daily_cost_usd === null && policy.max_retry_cost_usd === null ? t("Token-only policy", "仅 Token 预算") : t("USD and token limits", "美元与 Token 预算")} · {t("maximum attempts:", "最多尝试次数：")} {usageNumber(policy.max_attempts)}</p>
        <p>{t("Input limit:", "输入上限：")} {usageNumber(policy.max_input_tokens)} · {t("output limit:", "输出上限：")} {usageNumber(policy.max_output_tokens)} · {t("per-request limit:", "单次请求上限：")} {usageNumber(policy.max_request_tokens)} · {t("daily limit:", "每日上限：")} {usageNumber(policy.max_daily_tokens)} · {t("retry limit:", "重试上限：")} {usageNumber(policy.max_retry_tokens)} tokens</p>
        <p>{t("Daily USD limit:", "每日美元上限：")} {policy.max_daily_cost_usd === null ? t("Disabled", "未启用") : usageMoney(policy.max_daily_cost_usd)} · {t("retry USD limit:", "重试美元上限：")} {policy.max_retry_cost_usd === null ? t("Disabled", "未启用") : usageMoney(policy.max_retry_cost_usd)}</p>
        <p>{t("Pricing:", "定价：")} {pricing ? pricing.status : "UNKNOWN readiness"}{pricing && <> · {pricing.loaded ? t("loaded", "已加载") : t("not loaded", "未加载")} · {usageNumber(pricing.priced_models)} {t("entries with input/output estimate rates", "项输入 / 输出估算费率")}</>}</p>
        <p>{t("The Controller's existing APEIR_MODEL_PRICING_FILE configuration supplies price estimates. Loaded entries do not establish pricing for every selected model or verify a Provider invoice.", "Controller 使用 APEIR_MODEL_PRICING_FILE 提供价格估算。加载配置不代表每个模型都有定价，也不等于核验服务商账单。")}</p>
        <p>{t("Explicit token-only configuration requires both existing APEIR_MAX_DAILY_COST_USD and APEIR_MAX_RETRY_COST_USD values to be none. This view does not change the policy.", "仅按 Token 预算需将 APEIR_MAX_DAILY_COST_USD 和 APEIR_MAX_RETRY_COST_USD 均设为 none。此页面不修改预算策略。")}</p>
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>{t("Usage receipts", "用量记录")} ({summary.receipts.length}{summary.receipts_truncated ? t(" · partial list", " · 部分记录") : ""})</summary>
        {summary.receipts_truncated && <p>{t("The most recent 256 receipts are shown. Aggregate totals cover the selected day.", "显示最近 256 条记录；汇总覆盖所选日期。")}</p>}
        {summary.receipts.length === 0 && <p>{t("No usage receipts for this day.", "此日期暂无用量记录。")}</p>}
        {summary.receipts.slice().reverse().map((receipt, index) => <details key={`${receipt.receipt_id}-${index}`} style={{ padding: "6px 0" }}>
          <summary>{receipt.provider_id || "UNKNOWN provider"} · {receipt.model_id || "UNKNOWN model"} · {receipt.status} · {measuredUsage(receipt.cost_usd, receipt.cost_measurement, true)}</summary>
          <p>{t("Receipt:", "记录：")} {receipt.receipt_id} · {t("request:", "请求：")} {receipt.request_id || "UNKNOWN"} · {t("attempt:", "尝试次数：")} {usageNumber(receipt.attempt)} · {t("task:", "任务：")} {receipt.task_id || "UNKNOWN"}</p>
          <p>{t("Reservation:", "预留：")} {receipt.reservation_id || "UNKNOWN"} · {t("recorded:", "记录时间：")} {receipt.created_at || "UNKNOWN"}</p>
          {usageCounters.map(([key, label]) => <div key={key}>{t(label, counterLabels[key])}: {measuredUsage(receipt.usage?.[key], receipt.usage?.counter_measurements?.[key])}</div>)}
        </details>)}
      </details>
      {summary.reservations.length > 0 && <details style={{ marginTop: space.md }}>
        <summary>{t("Outstanding reservations", "待完成的预留")} ({summary.reservations.length})</summary>
        {summary.reservations.map((reservation, index) => <div key={`${reservation.reservation_id}-${index}`} style={{ padding: "6px 0" }}>
          {reservation.provider_id} · {reservation.model_id} · {reservation.status}
          <div>{t("Request:", "请求：")} {reservation.request_id} · {t("attempt:", "尝试次数：")} {usageNumber(reservation.attempt)} · {t("reservation:", "预留：")} {reservation.reservation_id}</div>
          <div>{t("Reserved estimate:", "预留估算：")} {usageNumber(reservation.estimated_tokens)} tokens · {usageMoney(reservation.estimated_cost_usd)} · {reservation.receipt_recorded ? t("receipt recorded; uncertainty retained", "记录已保存；结果仍未确认") : t("awaiting receipt", "等待记录")}</div>
        </div>)}
      </details>}
    </>}
  </div>;
}
