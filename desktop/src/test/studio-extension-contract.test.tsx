import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api, setConfig } from "../lib/api";
import { availableContributions, parseStudioUIView } from "../lib/studioExtensions";
import { StudioSnapshot, useStudioSnapshot } from "../components/studio/StudioData";
import { StudioExtensionView } from "../components/studio/StudioExtensionView";
vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), api: vi.fn() }));
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); });
const component = `ui:${"a".repeat(32)}:test`;
function snapshot(enabled = true) {
  return { extensions: [{ extension_id: "example/test", version: "1.0.0", digest: `sha256:${"b".repeat(64)}`, enabled, state: "installed", authority: "none", signature_status: "Unknown", publisher_trust: "UNVERIFIED", contributions: [{ type: component, id: "test", kind: "widget", title: "Test Widget", subscriptions: ["runtime.status"], view: { kind: "stack", children: [{ kind: "text", text: '<img src=x onerror="alert(1)">' }, { kind: "metric", source: "runtime.status", field: "jobs_pending", label: "Pending" }] } }] }], diagnostics: [], status: { jobs_pending: 0, running: true }, received_at: "2026-10-25T00:00:00Z", executable_ui: "BLOCKED", execution_scope: "runtime-service" };
}
it("accepts only bounded declared views, rejects script and module configuration", () => {
  const value = snapshot();
  expect(availableContributions(parseStudioUIView(value), "widget")).toHaveLength(1);
  expect(availableContributions(parseStudioUIView(snapshot(false)), "widget")).toHaveLength(0);
  for (const view of [{ kind: "html", html: "<script>" }, { kind: "text", text: "x", module: "https://untrusted.invalid/a.js" }]) {
    const modified = { ...value, extensions: [{ ...value.extensions[0], contributions: [{ ...value.extensions[0].contributions[0], view }] }] };
    expect(() => parseStudioUIView(modified)).toThrow();
  }
});
it("renders third-party text as text, preserves numeric zero and fails closed on disable", async () => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_EXTENSION_VIEW" });
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/studio/extensions" ? snapshot() : {});
  let shared!: ReturnType<typeof useStudioSnapshot>;
  function Reader() { shared = useStudioSnapshot(); return <StudioExtensionView type={component} isVisible={() => true} />; }
  const result = render(<StudioSnapshot><Reader /></StudioSnapshot>);
  await waitFor(() => expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeVisible());
  expect(result.container.querySelector("img")).toBeNull();
  expect(screen.getByText("0")).toBeVisible();
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/studio/extensions" ? snapshot(false) : {});
  await act(async () => shared.invalidateExtensions());
  await waitFor(() => expect(screen.getByText(/DISABLED/)).toBeVisible());
  expect(screen.queryByText("0")).toBeNull();
});
it("shares one extension read and prevents superseded reads restoring revoked data", async () => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_EXTENSION_GENERATION" });
  let late!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/studio/extensions" ? new Promise(resolve => { late = resolve; }) : {});
  let shared!: ReturnType<typeof useStudioSnapshot>;
  function Reader() { shared = useStudioSnapshot(); return <p>{shared.extensions.data?.extensions[0]?.enabled ? "ENABLED" : "NOT_ENABLED"}</p>; }
  const view = render(<StudioSnapshot><Reader /></StudioSnapshot>);
  const original = late;
  const originalSignal = vi.mocked(api).mock.calls.find(([path]) => path.endsWith("/extensions"))?.[1]?.signal;
  act(() => { shared.refresh(["extensions"]); shared.refresh(["extensions"]); });
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/extensions"))).toHaveLength(1);
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/studio/extensions" ? snapshot(false) : {});
  await act(async () => { shared.invalidateExtensions(); });
  await waitFor(() => expect(shared.extensions.data?.extensions[0].enabled).toBe(false));
  expect(originalSignal?.aborted).toBe(true);
  await act(async () => original(snapshot(true)));
  expect(view.container.textContent).toBe("NOT_ENABLED");
  expect(shared.extensions.data?.extensions[0].enabled).toBe(false);
});
it("uses the selected host language without reacquiring data or changing publisher content", async () => {
  setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_EXTENSION_LOCALE" });
  const original = snapshot();
  const value = { ...original, extensions: [{ ...original.extensions[0], contributions: [{ ...original.extensions[0].contributions[0], events: ["runtime.started"], view: { kind: "chart", source: "runtime.status", field: "jobs_pending", label: "Publisher chart title" } }] }] };
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/studio/extensions" ? value : {});
  const visible = () => true;
  const renderView = (locale: "en" | "zh") => <StudioSnapshot><StudioExtensionView type={component} isVisible={visible} locale={locale} /></StudioSnapshot>;
  const view = render(renderView("en"));
  await waitFor(() => expect(screen.getByText("1 sample · current session")).toBeVisible());
  expect(screen.getByText("Lifecycle events", { exact: true })).toBeVisible();
  expect(screen.getByText("Source", { exact: true })).toBeVisible();
  const reads = vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/extensions")).length;
  view.rerender(renderView("zh"));
  expect(screen.getByText("1 个样本 · 当前会话")).toBeVisible();
  expect(screen.getByText("生命周期事件", { exact: true })).toBeVisible();
  expect(screen.getByText("来源", { exact: true })).toBeVisible();
  expect(screen.getByText("Publisher chart title", { exact: true })).toBeVisible();
  expect(screen.queryByText("Lifecycle events", { exact: true })).toBeNull();
  expect(vi.mocked(api).mock.calls.filter(([path]) => path.endsWith("/extensions"))).toHaveLength(reads);
  expect(vi.mocked(api).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
});
it("admits a bounded valid multi-package catalog without accepting malformed record primitives", () => {
  const value = snapshot();
  const view = { kind: "stack", children: Array.from({ length: 3 }, () => ({ kind: "stack", children: Array.from({ length: 10 }, () => ({ kind: "text", text: "x".repeat(2048) })) })) };
  const extensions = Array.from({ length: 20 }, (_, i) => ({ ...value.extensions[0], extension_id: `example/test-${i}`, contributions: [{ ...value.extensions[0].contributions[0], type: `ui:${i.toString(16).padStart(32, "0")}:test`, view }] }));
  expect(JSON.stringify(extensions).length).toBeGreaterThan(1024 * 1024);
  expect(parseStudioUIView({ ...value, extensions }).extensions).toHaveLength(20);
  expect(() => parseStudioUIView({ ...value, extensions: [{ ...value.extensions[0], authority: { code: "not text" } }] })).toThrow();
  expect(() => parseStudioUIView({ ...value, extensions: Array(65).fill(value.extensions[0]) })).toThrow();
});
