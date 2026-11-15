import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, api, humanMutation, setConfig } from "../lib/api";
import { StudioSnapshot } from "../components/studio/StudioData";
import { StudioExtensions } from "../components/studio/StudioExtensions";
import type { PanelProps } from "../components/studio/StudioPanels";
vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), api: vi.fn(), humanMutation: vi.fn(), governedStudioMutation: vi.fn() }));

const digest = `sha256:${"b".repeat(64)}`;
const skill = { skill_key: "catalog:code-helper:one", skill_id: "code-helper", name: "Code helper", description: "Review project code", provider: "catalog", installable: true, version: "1.0.0", digest, catalog_source: "https://catalog.example.test/index.json", package_source: "https://catalog.example.test/code.zip", identity_status: "DECLARED", requested_capabilities: ["project.read"], enabled: true };
let skills: Record<string, unknown>[];
const view = () => ({ extensions: [], diagnostics: [], status: null, received_at: new Date().toISOString(), executable_ui: "BLOCKED", execution_scope: "runtime-service", tool_extensions: { records: [], diagnostics: [] } });
const props = (): PanelProps => ({ locale: "en", isVisible: () => true, updateConfig: vi.fn(), saveLayout: vi.fn(), onDraftChange: vi.fn(), onDraftSnapshot: vi.fn(), open: vi.fn(), inspect: vi.fn() });
beforeEach(() => {
  vi.clearAllMocks(); setConfig({ url: "http://localhost:8770", token: "APEIR_FAKE_ONLY_EXTENSION_MANAGER" }); skills = [{ ...skill }];
  vi.mocked(api).mockImplementation(async path => path === "/api/v1/control/operations" ? { skills, skill_catalogs: [], skill_diagnostics: [] } : view());
  vi.mocked(humanMutation).mockImplementation(async (_path, body) => {
    if (body.action === "install") skills = [...skills, { ...skill, provider: "installed", skill_key: "installed:code-helper", identity_status: "BOUND" }];
    if (body.action === "disable" || body.action === "enable") skills = skills.map(row => row.provider === "installed" ? { ...row, enabled: body.action === "enable" } : row);
    if (body.action === "remove") skills = skills.filter(row => row.provider !== "installed");
    return {};
  });
});
afterEach(() => { vi.restoreAllMocks(); });
const mount = (options: Partial<PanelProps> = {}) => render(<StudioSnapshot><StudioExtensions {...props()} {...options} /></StudioSnapshot>);

it("reviews exact Skill source then installs, toggles and uninstalls without a second owner", async () => {
  mount(); fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
  await waitFor(() => expect(screen.getByText("Code helper")).toBeVisible());
  fireEvent.click(within(screen.getByRole("region", { name: "Skills" })).getByRole("button", { name: "Install" }));
  expect(humanMutation).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Install reviewed package" }));
  await waitFor(() => expect(screen.getByRole("tab", { name: "Installed" })).toHaveAttribute("aria-selected", "true"));
  expect(humanMutation).toHaveBeenCalledWith("/api/v1/control/operations/actions", expect.objectContaining({ action: "install", digest, version: "1.0.0", catalog_source: skill.catalog_source, package_source: skill.package_source }), expect.any(Function));
  const section = within(screen.getByRole("region", { name: "Skills" }));
  fireEvent.click(await section.findByRole("button", { name: "Disable" }));
  await waitFor(() => expect(section.getByText("Disabled", { exact: true })).toBeVisible());
  fireEvent.click(section.getByRole("button", { name: "Enable" }));
  await waitFor(() => expect(section.getByText("Enabled", { exact: true })).toBeVisible());
  vi.spyOn(window, "confirm").mockReturnValue(true);
  fireEvent.click(section.getByRole("button", { name: "Uninstall" }));
  await waitFor(() => expect(section.getByText("No Skills installed")).toBeVisible());
  expect(vi.mocked(humanMutation).mock.calls.map(([, body]) => body.action)).toEqual(["install", "disable", "enable", "remove"]);
});

it("keeps a lost install response unresolved and never retries on refresh or tab changes", async () => {
  vi.mocked(humanMutation).mockRejectedValue(new Error("Connection lost after dispatch"));
  mount(); fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
  fireEvent.click(await within(screen.getByRole("region", { name: "Skills" })).findByRole("button", { name: "Install" }));
  fireEvent.click(screen.getByRole("button", { name: "Install reviewed package" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Outcome unconfirmed"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  fireEvent.click(screen.getByRole("tab", { name: "Installed" }));
  fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
  expect(screen.getByRole("button", { name: "Install reviewed package" })).toBeDisabled();
  expect(humanMutation).toHaveBeenCalledTimes(1);
});

it("preserves pending review across filters and language changes with keyboard tabs", async () => {
  const options = props(); const page = render(<StudioSnapshot><StudioExtensions {...options} /></StudioSnapshot>);
  const tab = screen.getByRole("tab", { name: "Installed" }); tab.focus(); fireEvent.keyDown(tab, { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: "Discover" })).toHaveFocus();
  fireEvent.click(await within(screen.getByRole("region", { name: "Skills" })).findByRole("button", { name: "Install" }));
  fireEvent.change(screen.getByLabelText("Type", { exact: true }), { target: { value: "tools" } });
  expect(screen.queryByRole("region", { name: "Skills" })).toBeNull();
  fireEvent.change(screen.getByLabelText("Type", { exact: true }), { target: { value: "all" } });
  expect(screen.getByRole("button", { name: "Install reviewed package" })).toBeVisible();
  page.rerender(<StudioSnapshot><StudioExtensions {...options} locale="zh" /></StudioSnapshot>);
  expect(screen.getByRole("tab", { name: "发现与安装" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "确认安装" })).toBeVisible();
  expect(options.onDraftChange).toHaveBeenLastCalledWith(true);
  expect(humanMutation).not.toHaveBeenCalled();
});

it("does not export rejected credential material into workspace drafts", async () => {
  const options = props(); mount(options); fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (path.endsWith("/tools/review")) throw new ApiError("NOUS_INVALID_REQUEST", "Embedded credential rejected");
    return original(path, init);
  });
  const file = new File(["{}"], "config.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => '{"api_key":"APEIR_FAKE_ONLY_REJECTED_SECRET"}' });
  fireEvent.change(screen.getByLabelText("Import tool extension", { exact: true }), { target: { files: [file] } });
  await waitFor(() => expect(screen.getByText(/Embedded credential rejected/)).toBeVisible());
  expect(JSON.stringify(vi.mocked(options.onDraftSnapshot).mock.calls)).not.toContain("APEIR_FAKE_ONLY_REJECTED_SECRET");
  expect(screen.queryByRole("button", { name: "Request install" })).toBeNull();
});

it("retires pending source work when Controller changes", async () => {
  let resolveReview!: (value: unknown) => void;
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation((path, init) => path.endsWith("/tools/review") ? new Promise(resolve => { resolveReview = resolve; }) : original(path, init));
  const options = props(); const page = render(<StudioSnapshot key="A"><StudioExtensions {...options} /></StudioSnapshot>);
  fireEvent.click(screen.getByRole("tab", { name: "Discover" }));
  const file = new File(["{}"], "config.json", { type: "application/json" }); Object.defineProperty(file, "text", { value: async () => "{}" });
  fireEvent.change(screen.getByLabelText("Import tool extension", { exact: true }), { target: { files: [file] } });
  await waitFor(() => expect(resolveReview).toBeTypeOf("function"));
  setConfig({ url: "http://localhost:8771", token: "APEIR_FAKE_ONLY_CONTROLLER_B" });
  page.rerender(<StudioSnapshot key="B"><StudioExtensions {...options} /></StudioSnapshot>);
  await act(async () => resolveReview({ extension_id: "foreign/tools", digest, version: "1.0.0", previous_digest: "", manifest: {} }));
  expect(screen.queryByText("foreign/tools")).toBeNull();
  expect(JSON.stringify(vi.mocked(options.onDraftSnapshot).mock.calls)).not.toContain("foreign/tools");
});
