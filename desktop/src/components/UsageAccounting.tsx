import { colors, space, typo } from "../design";
import { measuredUsage, usageCounters, usageMoney, usageNumber, usageTotal } from "../lib/usageAccounting";
import type { UsageAccountingSummary } from "../store/types";

/** A read-only view of CostController's summary, never a local cost calculation. */
export function UsageAccounting({ summary, compact = false }: {
  summary: UsageAccountingSummary; compact?: boolean;
}) {
  const empty = summary.requests === 0 && summary.pending_requests === 0;
  const policy = summary.policy;
  const pricing = policy.pricing;
  return <div aria-label="Usage accounting" style={{ fontSize: typo.sm, color: colors.textSecondary, overflowWrap: "anywhere" }}>
    <div style={{ fontSize: compact ? typo.lg : typo.xl, color: colors.text, fontWeight: typo.semibold }}>
      {usageTotal(summary)}
    </div>
    <p>{summary.day} UTC · {usageNumber(summary.requests)} usage receipts · {usageNumber(summary.pending_requests)} pending requests</p>
    {empty ? <p>No cost measurement has been recorded yet.</p> : <>
      <div>Provider reported: {summary.reported_cost_requests > 0 ? usageMoney(summary.reported_cost_usd) : "No reported-cost receipts"} ({usageNumber(summary.reported_cost_requests)} receipts)</div>
      <div>Estimated cost: {summary.estimated_cost_requests > 0 ? usageMoney(summary.estimated_cost_usd) : "No estimated-cost receipts"} ({usageNumber(summary.estimated_cost_requests)} receipts)</div>
      <div>Derived cost: {summary.derived_cost_requests > 0 ? usageMoney(summary.derived_cost_usd) : "No derived-cost receipts"} ({usageNumber(summary.derived_cost_requests)} receipts)</div>
      <p>Unknown cost: {usageNumber(summary.unknown_cost_requests)} receipts · uncertain calls: {usageNumber(summary.uncertain_calls)}. Known subtotals exclude unknown costs.</p>
    </>}
    <p>Provider reported values are telemetry, not independently verified invoices.</p>
    <div>Reserved estimates: {summary.reservations.length === 0 ? "No outstanding reservations" : <>{usageNumber(summary.reserved_tokens)} tokens · {usageMoney(summary.reserved_cost_usd)}</>}</div>
    <div>Remaining token budget: {usageNumber(summary.remaining.tokens)}</div>
    <div>Remaining USD budget: {policy.max_daily_cost_usd === null ? "Disabled by the configured policy" : usageMoney(summary.remaining.cost_usd)}</div>
    {!compact && <>
      <details style={{ marginTop: space.md }} open>
        <summary>Token usage</summary>
        <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse", marginTop: space.sm }}>
          <thead><tr><th>Counter</th><th>Total</th><th>Known subtotal</th><th>Estimated subtotal</th><th>Unknown receipts</th></tr></thead>
          <tbody>{usageCounters.map(([key, label]) => <tr key={key}>
            <th style={{ padding: "6px 0", fontWeight: typo.normal }}>{label}</th>
            <td>{empty ? "No receipts" : usageNumber(summary[key])}</td>
            <td>{empty ? "No receipts" : usageNumber(summary.known_totals[key])}</td>
            <td>{empty ? "No receipts" : usageNumber(summary.estimated_totals[key])}</td>
            <td>{usageNumber(summary.unknown_counters[key])}</td>
          </tr>)}</tbody>
        </table>
        <p>Known subtotals include reported and derived counters. Estimates and unknown counters cannot establish a complete reported total.</p>
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>Usage by Provider, model and task ({summary.items.length})</summary>
        {summary.items.length === 0 ? <p>No recorded usage groups for this day.</p> : <>
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse", marginTop: space.sm }}>
            <thead><tr><th>Provider / model</th><th>Task</th><th>Receipts</th><th>Accounted cost</th><th>Unknown cost receipts</th><th>Total tokens</th></tr></thead>
            <tbody>{summary.items.map((item, index) => <tr key={`${item.provider_id}/${item.model_id}/${item.task_id}/${index}`}>
              <td style={{ padding: "6px 0" }}>{item.provider_id} / {item.model_id}</td><td>{item.task_id || "UNKNOWN"}</td>
              <td>{usageNumber(item.requests)}</td><td>{usageMoney(item.cost_usd)}</td>
              <td>{usageNumber(item.unknown_cost_requests)}</td><td>{usageNumber(item.total_tokens)}</td>
            </tr>)}</tbody>
          </table>
          <p>Accounted costs include available reported, derived and estimated values. Inspect receipts for each measurement's source. Unknown costs are excluded from known subtotals.</p>
        </>}
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>Budget and pricing configuration</summary>
        <p>{policy.max_daily_cost_usd === null && policy.max_retry_cost_usd === null ? "Token-only policy" : "USD and token limits"} · maximum attempts: {usageNumber(policy.max_attempts)}</p>
        <p>Input limit: {usageNumber(policy.max_input_tokens)} · output limit: {usageNumber(policy.max_output_tokens)} · per-request limit: {usageNumber(policy.max_request_tokens)} · daily limit: {usageNumber(policy.max_daily_tokens)} · retry limit: {usageNumber(policy.max_retry_tokens)} tokens</p>
        <p>Daily USD limit: {policy.max_daily_cost_usd === null ? "Disabled" : usageMoney(policy.max_daily_cost_usd)} · retry USD limit: {policy.max_retry_cost_usd === null ? "Disabled" : usageMoney(policy.max_retry_cost_usd)}</p>
        <p>Pricing: {pricing ? pricing.status : "UNKNOWN readiness"}{pricing && <> · {pricing.loaded ? "loaded" : "not loaded"} · {usageNumber(pricing.priced_models)} entries with input/output estimate rates</>}</p>
        <p>The Controller's existing APEIR_MODEL_PRICING_FILE configuration supplies price estimates. Loaded entries do not establish pricing for every selected model or verify a Provider invoice.</p>
        <p>Explicit token-only configuration requires both existing APEIR_MAX_DAILY_COST_USD and APEIR_MAX_RETRY_COST_USD values to be none. This view does not change the policy.</p>
      </details>
      <details style={{ marginTop: space.md }}>
        <summary>Usage receipts ({summary.receipts.length}{summary.receipts_truncated ? " · partial list" : ""})</summary>
        {summary.receipts_truncated && <p>The most recent 256 receipts are shown. Aggregate totals cover the selected day.</p>}
        {summary.receipts.length === 0 && <p>No usage receipts for this day.</p>}
        {summary.receipts.slice().reverse().map((receipt, index) => <details key={`${receipt.receipt_id}-${index}`} style={{ padding: "6px 0" }}>
          <summary>{receipt.provider_id || "UNKNOWN provider"} · {receipt.model_id || "UNKNOWN model"} · {receipt.status} · {measuredUsage(receipt.cost_usd, receipt.cost_measurement, true)}</summary>
          <p>Receipt: {receipt.receipt_id} · request: {receipt.request_id || "UNKNOWN"} · attempt: {usageNumber(receipt.attempt)} · task: {receipt.task_id || "UNKNOWN"}</p>
          <p>Reservation: {receipt.reservation_id || "UNKNOWN"} · recorded: {receipt.created_at || "UNKNOWN"}</p>
          {usageCounters.map(([key, label]) => <div key={key}>{label}: {measuredUsage(receipt.usage?.[key], receipt.usage?.counter_measurements?.[key])}</div>)}
        </details>)}
      </details>
      {summary.reservations.length > 0 && <details style={{ marginTop: space.md }}>
        <summary>Outstanding reservations ({summary.reservations.length})</summary>
        {summary.reservations.map((reservation, index) => <div key={`${reservation.reservation_id}-${index}`} style={{ padding: "6px 0" }}>
          {reservation.provider_id} · {reservation.model_id} · {reservation.status}
          <div>Request: {reservation.request_id} · attempt: {usageNumber(reservation.attempt)} · reservation: {reservation.reservation_id}</div>
          <div>Reserved estimate: {usageNumber(reservation.estimated_tokens)} tokens · {usageMoney(reservation.estimated_cost_usd)} · {reservation.receipt_recorded ? "receipt recorded; uncertainty retained" : "awaiting receipt"}</div>
        </div>)}
      </details>}
    </>}
  </div>;
}
