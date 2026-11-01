import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { CacheMetrics, DeviceTopology, ResourceRow, WorkOutcome } from "../components/studio/StudioDashboard";

import { usageFixture } from "./usage-fixture";
import { cacheShare, parseWorkflowProgress, widgetSourceUnavailable } from "../lib/studioOverview";

const report = { node_id: "fixture-node", connected: true, trust_status: "TRUSTED", resource_report_current: true, resource_report_fresh: true, resources: { cpu_logical: 8, memory_available_bytes: 3 * 1073741824, memory_total_bytes: 8 * 1073741824 } };
it("plots only a current trusted memory report and distinguishes CPU capacity from utilization", () => {
  const view = render(<ResourceRow row={report} locale="en" />);
  const meter = screen.getByRole("meter", { name: "Memory used" });
  expect(meter).toHaveAttribute("value", String(5 * 1073741824));
  expect(meter).toHaveAttribute("max", String(8 * 1073741824));
  expect(screen.getByText("8 logical")).toBeInTheDocument();
  view.rerender(<ResourceRow row={{ ...report, resource_report_fresh: false }} locale="en" />);
  expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  expect(screen.queryByText("8 logical")).not.toBeInTheDocument();
  expect(view.container.textContent).toContain("UNKNOWN");
});
it.each([{ connected: false }, { trust_status: "REVOKED" }, { resource_report_current: false }, { resources: { memory_total_bytes: 8, memory_available_bytes: 9 } }, { resources: { memory_total_bytes: Infinity, memory_available_bytes: 4 } }])("does not draw misleading resource values for %j", fields => {
  render(<ResourceRow row={{ ...report, ...fields }} locale="en" />);
  expect(screen.queryByRole("meter")).not.toBeInTheDocument();
});
it("shows only exact reported node/device bindings, retaining unknown or missing bindings separately", () => {
  const view = render(<DeviceTopology nodes={[report]} devices={[{ device_id: "bound", node_id: "fixture-node", lifecycle: "TRUSTED" }, { device_id: "orphan", node_id: "absent-node" }, { device_id: "no-binding" }]} locale="en" />);
  const bound = screen.getByText("bound").closest("li")!;
  expect(within(bound).getByText("TRUSTED")).toBeInTheDocument();
  const unknown = screen.getByText("Node binding: UNKNOWN").parentElement!;
  expect(within(unknown).getByText("orphan")).toBeInTheDocument();
  expect(within(unknown).getByText("no-binding")).toBeInTheDocument();
  expect(within(unknown).queryByText("bound")).not.toBeInTheDocument();
  view.rerender(<DeviceTopology nodes={[]} devices={[]} locale="zh" />);
  expect(screen.getByText("暂无节点或设备")).toBeInTheDocument();
});

it.each(["UNKNOWN", "MISMATCH"])("does not show receipt-VERIFIED as effect success for %s", verdict => {
  const view = render(<WorkOutcome row={{ state: "VERIFIED", effect_verification: { verdict } }} locale="en" />);
  expect(screen.getByText("RECEIPT_VERIFIED")).toBeVisible();
  expect(screen.getByText(verdict)).toBeVisible();
  expect(view.container.querySelector(".studio-status-success")).toBeNull();
});
it("keeps digest integrity distinct from an absent physical effect verdict", () => {
  const view = render(<WorkOutcome row={{ state: "VERIFIED", integrity: "MATCH" }} locale="zh" />);
  expect(screen.getByText("UNKNOWN")).toBeVisible();
  expect(view.container.querySelector(".studio-status-success")).toBeNull();
  view.rerender(<WorkOutcome row={{ state: "VERIFIED", effect_verification: { verdict: "MATCH" } }} locale="en" />);
  expect(screen.getByText("MATCH")).toBeVisible();
  expect(screen.getByText("RECEIPT_VERIFIED")).not.toHaveClass("studio-status-success");
});


it("labels cached input separately from fees and does not turn absent counters into zero", () => {
  const view = render(<CacheMetrics summary={usageFixture({ input_tokens: 100, cached_input_tokens: 25 })} locale="en" />);
  expect(screen.getByText("25.0%")).toBeVisible();
  expect(view.container.textContent).toContain("does not measure money saved");
  view.rerender(<CacheMetrics summary={usageFixture({ input_tokens: null, cached_input_tokens: null, cache_creation_input_tokens: null })} locale="zh" />);
  expect(screen.getAllByText("UNKNOWN")).toHaveLength(3);
  expect(view.container.textContent).not.toContain("0%");
  for (const [input, cached] of [[0, 0], [10, 11], [-1, 0], [100, NaN], [Infinity, 10]]) expect(cacheShare(input, cached)).toBeNull();
});
it("keeps older Workflow state readable but rejects inconsistent new progress counters", () => {
  const run = { run_id: "original", workflow_id: "review", state: "unknown" };
  expect(parseWorkflowProgress({ runs: [run] })).toEqual([run]);
  const counts = { total: 2, completed: 1, skipped: 0, failed: 0, unknown: 1, waiting_approval: 0, started: 0, running: 0, pending: 0, cancelled: 0 };
  expect(parseWorkflowProgress({ runs: [{ ...run, step_counts: counts }] })[0].state).toBe("unknown");
  expect(() => parseWorkflowProgress({ runs: [{ ...run, step_counts: { ...counts, completed: 2 } }] })).toThrow(/counts/);
  expect(() => parseWorkflowProgress({ runs: [{ ...run, step_counts: { ...counts, total: Infinity } }] })).toThrow();
});

it("does not project a failed Controller's fallback empty list as zero nodes", () => {
  const failed = { degraded: true, components: [{ component: "controller", status: "UNKNOWN" }] };
  for (const widget of ["nodes", "resources", "topology"]) expect(widgetSourceUnavailable(widget, failed)).toBe(true);
  expect(widgetSourceUnavailable("devices", failed)).toBe(false);
  expect(widgetSourceUnavailable("nodes", { components: [] })).toBe(false);
  expect(widgetSourceUnavailable("nodes", {})).toBe(true);
  expect(widgetSourceUnavailable("evidence", { components: [{ component: "works", status: "UNKNOWN" }] })).toBe(true);
});
