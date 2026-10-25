import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { DeviceTopology, ResourceRow, WorkOutcome } from "../components/studio/StudioDashboard";

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
