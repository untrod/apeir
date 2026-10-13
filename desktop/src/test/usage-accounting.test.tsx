import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModelLab } from "../components/DeveloperPlatform";
import { StatusBar } from "../components/StatusBar";
import { UsageAccounting } from "../components/UsageAccounting";
import { setConfig, type ModelLabSnapshot } from "../lib/api";
import { entityStore } from "../store";
import { usageFixture } from "./usage-fixture";

const models: ModelLabSnapshot = {
  models: [{ model_id: "model", display_name: "Fixture model", provider_id: "fixture", endpoint_type: "remote",
    state: "enabled", health: "healthy", capabilities: ["chat"], capability_scores: {} }],
  summary: { total: 1, enabled: 1, healthy: 1, recoverable_operations: 0 },
  rankings: [{ model_id: "model", provider_id: "fixture", sample_count: 1, success_rate: 1, avg_latency_ms: 8, avg_cost_usd: 0 }],
  recent_observations: [], costs: [{ cost_usd: 0 }], evidence_status: "awaiting_observations",
};
const envelope = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });
const runtime = { version: "fixture", running: true, providers: 1, capabilities: 1, packs: 0, devices: 0, events: 0, jobs_pending: 0 };

beforeEach(() => {
  entityStore.clearStore();
  setConfig({ url: "http://localhost:8770", token: "fake.usage.service" });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); sessionStorage.clear(); });

describe("real usage and cost projection", () => {
  it("does not treat legacy observation zero cost as billing evidence", () => {
    render(<ModelLab data={models} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Spend UNKNOWN");
    expect(screen.getByText(/Samples 1/)).toBeInTheDocument();
    expect(screen.queryByText(/Cost \$/)).not.toBeInTheDocument();
  });

  it("renders provider, estimate, derived and unknown provenance with original refs", () => {
    const summary = usageFixture({
      requests: 2, total_cost_usd: null, cost_measurement: "unknown", unknown_cost_requests: 1,
      estimated_cost_requests: 1, estimated_cost_usd: 0.1, receipts_truncated: true,
    });
    summary.receipts.push({ ...summary.receipts[0], receipt_id: "receipt-unknown", cost_usd: null, cost_measurement: "unknown",
      usage: { ...summary.receipts[0].usage, output_tokens: 8, reasoning_tokens: null,
        counter_measurements: { ...summary.receipts[0].usage.counter_measurements, output_tokens: "estimated", reasoning_tokens: "unknown" } } });
    Object.assign(summary.receipts[0], { raw_prompt: "PRIVATE-PROMPT", credential: "PRIVATE-KEY" });
    render(<ModelLab data={{ ...models, usage_accounting: summary, usage_accounting_status: "available" }} />);
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("Provider reported: $0.250000");
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("Estimated cost: $0.100000");
    expect(screen.getByText(/Receipt: receipt-original · request: request-original · attempt: 2/)).toBeInTheDocument();
    expect(screen.getByText(/Output tokens: ~8 · Estimated/)).toBeInTheDocument();
    expect(screen.getAllByText(/Total tokens: 16 · Derived/).length).toBeGreaterThan(0);
    expect(screen.getByText(/most recent 256 receipts/)).toBeInTheDocument();
    expect(screen.getByText(/not independently verified invoices/)).toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE-PROMPT|PRIVATE-KEY/)).not.toBeInTheDocument();
  });

  it("shows no measurement for an empty ledger", () => {
    const summary = usageFixture({ requests: 0, receipts: [], total_cost_usd: 0, cost_measurement: "no_receipts",
      reported_cost_requests: 0, reported_cost_usd: 0 });
    render(<ModelLab data={{ ...models, usage_accounting: summary, usage_accounting_status: "available" }} />);
    expect(screen.getByText("No usage receipts")).toBeInTheDocument();
    expect(screen.getByText(/No cost measurement has been recorded/)).toBeInTheDocument();
    expect(screen.queryByText(/\$0\.000000/)).not.toBeInTheDocument();
  });

  it("preserves an explicitly reported zero instead of treating it as unknown or absent", () => {
    const summary = usageFixture({ total_cost_usd: 0, reported_cost_usd: 0 });
    summary.receipts[0] = { ...summary.receipts[0], cost_usd: 0 };
    render(<ModelLab data={{ ...models, usage_accounting: summary, usage_accounting_status: "available" }} />);
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("$0.000000 · Provider reported");
    expect(screen.getByText("Provider reported: $0.000000 (1 receipts)")).toBeInTheDocument();
    expect(screen.queryByText(/No cost measurement has been recorded/)).not.toBeInTheDocument();
  });

  it("shows pending spend as unknown and preserves reservation, policy and price readiness", () => {
    const summary = usageFixture({
      requests: 0, receipts: [], total_cost_usd: null, cost_measurement: "unknown",
      reported_cost_requests: 0, reported_cost_usd: 0, pending_requests: 1,
      reserved_tokens: 90, reserved_cost_usd: null, remaining: { tokens: 999910, cost_usd: null },
      reservations: [{ reservation_id: "pending-reservation", request_id: "pending-request", task_id: "pending-task",
        provider_id: "fixture", model_id: "model", attempt: 2, status: "pending", receipt_recorded: false,
        estimated_tokens: 90, estimated_cost_usd: null }],
    });
    summary.policy = { ...summary.policy, max_daily_cost_usd: null, max_retry_cost_usd: null, budget_mode: "token_only",
      pricing: { configured: true, loaded: false, status: "missing", model_entries: 0, priced_models: 0,
        source: "file", environment_variable: "APEIR_MODEL_PRICING_FILE" } };
    render(<UsageAccounting summary={summary} />);
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("UNKNOWN");
    expect(screen.getByText(/Reserved estimates: 90 tokens · UNKNOWN/)).toBeInTheDocument();
    expect(screen.getByText(/Request: pending-request · attempt: 2 · reservation: pending-reservation/)).toBeInTheDocument();
    expect(screen.getByText(/Token-only policy/)).toBeInTheDocument();
    expect(screen.getByText(/Pricing: missing · not loaded/)).toBeInTheDocument();
    expect(screen.getByText(/Remaining USD budget: Disabled by the configured policy/)).toBeInTheDocument();
    expect(screen.queryByText(/No cost measurement has been recorded/)).not.toBeInTheDocument();
  });

  it("fails closed for an unsupported Model Lab accounting projection", () => {
    const summary = { ...usageFixture(), schema_version: 2 } as unknown as ReturnType<typeof usageFixture>;
    render(<ModelLab data={{ ...models, usage_accounting: summary, usage_accounting_status: "available" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Spend UNKNOWN");
    expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument();
  });

  it("reads status cost from the journal API while legacy cached usage remains non-authoritative", async () => {
    entityStore.upsertUsage([{ id: "legacy-cost", model_id: "legacy-model", cost_usd: 99, tokens_in: 1, tokens_out: 1,
      period_start: "", period_end: "", created_at: "", updated_at: "", schema_version: "1.0.0" }]);
    const fetchMock = vi.fn().mockImplementation(async (url: string) => envelope(url.endsWith("/usage") ? usageFixture() : runtime));
    vi.stubGlobal("fetch", fetchMock);
    render(<StatusBar />);
    fireEvent.click(screen.getByText("Runtime API"));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("$0.250000 · Provider reported");
    expect(screen.queryByText(/99\.000000/)).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8770/api/v1/usage", expect.anything());
  });

  it("clears previous billing on a refresh failure and keeps spend unknown", async () => {
    vi.useFakeTimers();
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith("/usage")) {
        if (calls++ > 0) throw new Error("PRIVATE_EXCEPTION");
        return envelope(usageFixture());
      }
      return envelope(runtime);
    }));
    render(<StatusBar />);
    fireEvent.click(screen.getByText("Runtime API"));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("$0.250000");
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByRole("alert")).toHaveTextContent("Spend remains UNKNOWN");
    expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument();
    expect(screen.queryByText(/PRIVATE_EXCEPTION/)).not.toBeInTheDocument();
  });

  it("discards a late response after switching Controllers", async () => {
    let resolveOld!: (value: ReturnType<typeof envelope>) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (url === "http://localhost:8770/api/v1/usage") return new Promise(value => { resolveOld = value; });
      return envelope(url.endsWith("/usage") ? usageFixture({ total_cost_usd: 0.5, reported_cost_usd: 0.5 }) : runtime);
    }));
    render(<StatusBar />);
    fireEvent.click(screen.getByText("Runtime API"));
    expect(screen.getByRole("status")).toHaveTextContent("Spend UNKNOWN");
    act(() => setConfig({ url: "http://other-controller:8770", token: "fake.other.service" }));
    expect(await screen.findByLabelText("Usage accounting")).toHaveTextContent("$0.500000");
    await act(async () => { resolveOld(envelope(usageFixture())); });
    await waitFor(() => expect(screen.getByLabelText("Usage accounting")).toHaveTextContent("$0.500000"));
    expect(screen.getByLabelText("Usage accounting")).not.toHaveTextContent("$0.250000");
  });

  it("keeps the latest failure unknown when an earlier polling read arrives late", async () => {
    vi.useFakeTimers();
    let resolveOld!: (value: ReturnType<typeof envelope>) => void;
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => {
      if (!url.endsWith("/usage")) return envelope(runtime);
      if (calls++ === 0) return new Promise(value => { resolveOld = value; });
      throw new Error("PRIVATE_LATE_FAILURE");
    }));
    render(<StatusBar />);
    fireEvent.click(screen.getByText("Runtime API"));
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(screen.getByRole("alert")).toHaveTextContent("Spend remains UNKNOWN");
    await act(async () => { resolveOld(envelope(usageFixture())); });
    expect(screen.queryByLabelText("Usage accounting")).not.toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Spend remains UNKNOWN");
  });
});
