import type { UsageAccountingSummary } from "../store/types";

export const usageCounters = [
  ["input_tokens", "Input tokens"],
  ["output_tokens", "Output tokens"],
  ["cached_input_tokens", "Cached input tokens"],
  ["cache_miss_input_tokens", "Cache miss input tokens"],
  ["reasoning_tokens", "Reasoning tokens"],
  ["total_tokens", "Total tokens"],
  ["cache_creation_input_tokens", "Cache creation input tokens"],
] as const;

const object = (value: unknown): Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value) && value >= 0;
const counter = (value: unknown): boolean => finite(value) && Number.isSafeInteger(value);
const nullable = (value: unknown): boolean => value === null || finite(value);
const counters = (value: unknown): boolean => usageCounters.every(([key]) => counter(object(value)[key]));
const nullableCounters = (value: unknown): boolean => usageCounters.every(([key]) => object(value)[key] === null || counter(object(value)[key]));
const measurement = (value: unknown): boolean => ["reported", "derived", "estimated", "unknown"].includes(String(value));
function validReceipt(value: unknown): boolean {
  const receipt = object(value);
  const usage = object(receipt.usage);
  const measurements = object(usage.counter_measurements);
  return typeof receipt.receipt_id === "string" && typeof receipt.status === "string"
    && nullable(receipt.cost_usd) && (measurement(receipt.cost_measurement) || receipt.cost_measurement === "legacy_unknown")
    && nullableCounters(usage) && usageCounters.every(([key]) => measurement(measurements[key]))
    && ["request_id", "reservation_id", "task_id", "provider_id", "model_id", "created_at"].every(key => receipt[key] === undefined || typeof receipt[key] === "string")
    && (receipt.attempt === undefined || counter(receipt.attempt));
}
function validItem(value: unknown): boolean {
  const item = object(value);
  return ["provider_id", "model_id", "task_id", "credential_ref_hash"].every(key => typeof item[key] === "string")
    && nullableCounters(item) && counter(item.requests) && counter(item.unknown_cost_requests)
    && finite(item.known_cost_usd) && nullable(item.cost_usd)
    && counters(item.known_totals) && counters(item.estimated_totals) && counters(item.unknown_counters);
}
function validReservation(value: unknown): boolean {
  const reservation = object(value);
  return ["reservation_id", "request_id", "task_id", "provider_id", "model_id", "status"].every(key => typeof reservation[key] === "string")
    && counter(reservation.attempt) && counter(reservation.estimated_tokens) && nullable(reservation.estimated_cost_usd)
    && typeof reservation.receipt_recorded === "boolean";
}
function validPricing(value: unknown): boolean {
  if (value === undefined) return true;
  const pricing = object(value);
  return typeof pricing.configured === "boolean" && typeof pricing.loaded === "boolean"
    && ["unconfigured", "missing", "unpriced", "configured"].includes(String(pricing.status))
    && counter(pricing.model_entries) && counter(pricing.priced_models)
    && ["host", "file", "unconfigured"].includes(String(pricing.source))
    && typeof pricing.environment_variable === "string";
}

/** Refuse an older or malformed summary instead of manufacturing zero totals. */
export function isUsageAccountingSummary(value: unknown): value is UsageAccountingSummary {
  const summary = object(value);
  const policy = object(summary.policy);
  const remaining = object(summary.remaining);
  return summary.schema_version === 1 && typeof summary.day === "string" && /^\d{4}-\d{2}-\d{2}$/.test(summary.day)
    && nullableCounters(summary)
    && counters(summary.known_totals) && counters(summary.estimated_totals) && counters(summary.unknown_counters)
    && ["requests", "reported_cost_requests", "estimated_cost_requests", "derived_cost_requests",
      "unknown_cost_requests", "uncertain_calls", "pending_requests"].every(key => counter(summary[key]))
    && ["reported_cost_usd", "estimated_cost_usd", "derived_cost_usd"].every(key => finite(summary[key]))
    && ["total_cost_usd", "reserved_tokens", "reserved_cost_usd"].every(key => nullable(summary[key]))
    && ["reported", "estimated", "derived", "unknown", "no_receipts"].includes(String(summary.cost_measurement))
    && nullable(remaining.tokens) && nullable(remaining.cost_usd)
    && ["max_input_tokens", "max_output_tokens", "max_request_tokens", "max_daily_tokens", "max_attempts", "max_retry_tokens"].every(key => counter(policy[key]))
    && nullable(policy.max_daily_cost_usd) && nullable(policy.max_retry_cost_usd)
    && validPricing(policy.pricing)
    && Array.isArray(summary.items) && summary.items.every(validItem)
    && Array.isArray(summary.reservations) && summary.reservations.every(validReservation)
    && Array.isArray(summary.receipts) && summary.receipts.length <= 256
    && summary.receipts.every(validReceipt)
    && typeof summary.receipts_truncated === "boolean";
}

export function usageNumber(value: unknown): string {
  return finite(value) ? value.toLocaleString("en-US") : "UNKNOWN";
}

export function usageMoney(value: unknown): string {
  return finite(value) ? value > 0 && value < 0.000001 ? `$${value.toPrecision(4)}` : `$${value.toFixed(6)}` : "UNKNOWN";
}

export function measuredUsage(value: unknown, measurement: unknown, money = false): string {
  if (!finite(value)) return "UNKNOWN";
  const formatted = money ? usageMoney(value) : usageNumber(value);
  if (measurement === "reported") return `${formatted} · Provider reported`;
  if (measurement === "estimated") return `~${formatted} · Estimated`;
  if (measurement === "derived") return `${formatted} · Derived`;
  return "UNKNOWN";
}

export function usageTotal(summary: UsageAccountingSummary): string {
  if (summary.requests === 0 && summary.pending_requests === 0) return "No usage receipts";
  return measuredUsage(summary.total_cost_usd, summary.cost_measurement, true);
}
