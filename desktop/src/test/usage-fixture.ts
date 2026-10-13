import type { UsageAccountingSummary, UsageCounters } from "../store/types";

export const counters: UsageCounters = {
  input_tokens: 12, output_tokens: 4, cached_input_tokens: 2, cache_miss_input_tokens: 10,
  reasoning_tokens: 1, total_tokens: 16, cache_creation_input_tokens: 0,
};
const zeroCounters = {
  input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, cache_miss_input_tokens: 0,
  reasoning_tokens: 0, total_tokens: 0, cache_creation_input_tokens: 0,
};

export function usageFixture(overrides: Partial<UsageAccountingSummary> = {}): UsageAccountingSummary {
  return {
    schema_version: 1, day: "2026-10-12", requests: 1, ...counters,
    known_totals: { ...counters } as UsageAccountingSummary["known_totals"],
    estimated_totals: { ...zeroCounters }, unknown_counters: { ...zeroCounters },
    total_cost_usd: 0.25, reported_cost_usd: 0.25, estimated_cost_usd: 0, derived_cost_usd: 0,
    reported_cost_requests: 1, estimated_cost_requests: 0, derived_cost_requests: 0, unknown_cost_requests: 0,
    cost_measurement: "reported", uncertain_calls: 0, pending_requests: 0,
    reserved_tokens: 0, reserved_cost_usd: 0, remaining: { tokens: 999984, cost_usd: 4.75 },
    policy: {
      max_input_tokens: 65536, max_output_tokens: 4096, max_request_tokens: 69632,
      max_daily_tokens: 1000000, max_daily_cost_usd: 5, max_attempts: 3,
      max_retry_tokens: 32768, max_retry_cost_usd: 1, budget_mode: "usd",
      pricing: { configured: true, loaded: true, status: "configured", model_entries: 1, priced_models: 1,
        source: "file", environment_variable: "APEIR_MODEL_PRICING_FILE" },
    },
    items: [], reservations: [], receipts_truncated: false,
    receipts: [{
      schema_version: 1, receipt_id: "receipt-original", request_id: "request-original", reservation_id: "reservation-original",
      task_id: "task-original", provider_id: "fixture", model_id: "model", attempt: 2,
      created_at: "2026-10-12T00:00:00Z", status: "completed", cost_usd: 0.25, cost_measurement: "reported",
      usage: { ...counters, counter_measurements: {
        input_tokens: "reported", output_tokens: "reported", cached_input_tokens: "reported", cache_miss_input_tokens: "derived",
        reasoning_tokens: "reported", total_tokens: "derived", cache_creation_input_tokens: "reported",
      } },
    }],
    ...overrides,
  };
}
