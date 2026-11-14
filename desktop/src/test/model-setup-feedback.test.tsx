import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CredentialSettings } from "../components/CredentialSettings";
import { ProviderSettings } from "../components/ProviderSettings";
import { SettingsPage } from "../components/SettingsPage";
import { ThemeProvider } from "../theme";
import { ToastProvider } from "../components/Toast";
import { StudioShell } from "../components/studio/StudioShell";
import { api, fetchModelLab, getConfig, setConfig } from "../lib/api";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), api: vi.fn(), fetchModelLab: vi.fn() }));
const invoke = vi.fn();
const model = { model_id: "deepseek/deepseek-chat", provider_id: "deepseek", display_name: "DeepSeek Chat", endpoint_type: "cloud_api", state: "enabled", health: "unknown", capabilities: ["chat"], capability_scores: {} };
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value: function (this: HTMLDialogElement) { this.removeAttribute("open"); } });
  const Observer = class { observe() {} unobserve() {} disconnect() {} };
  vi.stubGlobal("ResizeObserver", Observer);
  Object.defineProperty(window, "ResizeObserver", { configurable: true, value: Observer });
  invoke.mockReset();
  vi.mocked(fetchModelLab).mockResolvedValue({ models: [model], summary: { total: 1, enabled: 1, healthy: 0, recoverable_operations: 0 }, rankings: [], recent_observations: [], costs: [], evidence_status: "awaiting_observations" });
  setConfig({ url: "http://127.0.0.1:9017", token: "fixture.model.setup" });
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke } });
  vi.mocked(api).mockImplementation(async path => (path === "/api/v1/providers" ? [] : { models: [model] }) as never);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__; });

it("shows why credentials cannot yet be submitted while the native status read is pending", async () => {
  let release!: (value: unknown) => void;
  invoke.mockReturnValue(new Promise(resolve => { release = resolve; }));
  render(<CredentialSettings />);
  expect(screen.getByRole("status")).toHaveTextContent(/loading|checking/i);
  await act(async () => { release({ endpoint: "http://127.0.0.1:9017", ready: true, session_available: true }); });
});

it("lists registered model identities independently of a saved key", async () => {
  render(<ProviderSettings models={[model]} onChanged={async () => {}} />);
  const list = await screen.findByRole("table", { name: "Registered models" });
  expect(list).toHaveTextContent("deepseek/deepseek-chat");
  expect(list).toHaveTextContent("DeepSeek Chat");
  expect(list).toHaveTextContent(/unknown/i);
});

it("manages model connections inside settings instead of requiring a second window", async () => {
  render(<ThemeProvider><SettingsPage initialSection="models" /></ThemeProvider>);
  expect(await screen.findByRole("button", { name: "Add Provider" })).toBeEnabled();
  await waitFor(() => expect(screen.getByRole("table", { name: "Registered models" })).toHaveTextContent("deepseek/deepseek-chat"));
  expect(invoke.mock.calls.some(([name]) => name === "store_provider_credential")).toBe(false);
});


it("keeps the selected settings page and shows one completion after a verified local token rotation", async () => {
  const fakeKey = "fixture-private-credential-value";
  let stored = false;
  invoke.mockImplementation(async command => {
    if (command === "get_runtime_process_status") return { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true };
    if (command === "list_provider_credentials") return stored ? [{ environment_name: "DEEPSEEK_API_KEY", stored: true }] : [];
    if (command === "store_provider_credential") { stored = true; return "fixture.rotated-session"; }
    throw new Error("Unexpected native request");
  });
  render(<ThemeProvider><ToastProvider><StudioShell /></ToastProvider></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: /^Settings$/ }));
  const dialog = screen.getByRole("region", { name: "Application settings" });
  fireEvent.click(within(dialog).getByRole("tab", { name: "Models & credentials" }));
  fireEvent.click(within(dialog).getByRole("tab", { name: "API keys" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(within(dialog).getByLabelText("Provider credential"), { target: { value: fakeKey } });
  fireEvent.submit(within(dialog).getByRole("form", { name: "API key form" }));
  await waitFor(() => expect(getConfig().token).toBe("fixture.rotated-session"));
  const current = screen.getByRole("region", { name: "Application settings" });
  expect(current).toBeVisible();
  await waitFor(() => expect(within(current).getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true"));
  expect(within(current).getByText("Key saved. Local Runtime reconnected.", { exact: true })).toBeVisible();
  expect(screen.queryByText(/Controller connection changed/)).not.toBeInTheDocument();
  expect(screen.queryByText("Key saved", { exact: true })).not.toBeInTheDocument();
  fireEvent.click(within(current).getByRole("button", { name: "Continue to Models" }));
  await waitFor(() => expect(within(current).getByRole("table", { name: "Registered models" })).toHaveTextContent(model.model_id));
  expect(invoke.mock.calls.filter(([name]) => name === "store_provider_credential")).toHaveLength(1);
  expect(JSON.stringify(localStorage)).not.toContain(fakeKey);
  expect(JSON.stringify(sessionStorage)).not.toContain(fakeKey);
});

it("shows saving progress and submits only once while a credential command is pending", async () => {
  let finish!: (value: string) => void;
  invoke.mockImplementation(async command => {
    if (command === "get_runtime_process_status") return { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true };
    if (command === "list_provider_credentials") return [];
    return new Promise<string>(resolve => { finish = resolve; });
  });
  render(<CredentialSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fixture-only-pending-key" } });
  const form = screen.getByRole("form", { name: "API key form" });
  fireEvent.submit(form); fireEvent.submit(form);
  await waitFor(() => expect(invoke.mock.calls.filter(([name]) => name === "store_provider_credential")).toHaveLength(1));
  expect(screen.getByRole("status")).toHaveTextContent(/restarting/);
  expect(screen.getByLabelText("Provider credential")).toHaveValue("");
  await act(async () => { finish("fixture.next-session"); });
});

it("keeps an unfinished key on its own tab when visiting another settings category", async () => {
  invoke.mockImplementation(async command => command === "get_runtime_process_status" ? { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true } : []);
  render(<ThemeProvider><StudioShell /></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: /^Settings$/ }));
  fireEvent.click(screen.getByRole("tab", { name: "Models & credentials" }));
  fireEvent.click(screen.getByRole("tab", { name: "API keys" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fixture-unsent-private-key" } });
  fireEvent.click(screen.getByRole("tab", { name: "General" }));
  fireEvent.click(screen.getByRole("tab", { name: "Models & credentials" }));
  expect(screen.getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("Provider credential")).toBeVisible();
  expect(screen.getByLabelText("Provider credential")).toHaveValue("fixture-unsent-private-key");
  expect(invoke.mock.calls.some(([name]) => name === "store_provider_credential")).toBe(false);
  expect(JSON.stringify(localStorage)).not.toContain("fixture-unsent-private-key");
});

it("prevents new configuration drafts during an admitted local credential restart", async () => {
  let finish!: (value: string) => void;
  invoke.mockImplementation(async command => {
    if (command === "get_runtime_process_status") return { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true };
    if (command === "list_provider_credentials") return [];
    if (command === "store_provider_credential") return new Promise<string>(resolve => { finish = resolve; });
    throw new Error("Unexpected native request");
  });
  render(<ThemeProvider><StudioShell /></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: /^Settings$/ }));
  fireEvent.click(screen.getByRole("tab", { name: "Models & credentials" }));
  fireEvent.click(screen.getByRole("tab", { name: "API keys" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fixture-private-key-pending" } });
  fireEvent.submit(screen.getByRole("form", { name: "API key form" }));
  await waitFor(() => expect(finish).toBeDefined());
  expect(screen.getByRole("button", { name: "Close settings" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Develop" })).toBeDisabled();
  expect(screen.getByRole("tab", { name: "General" })).toBeDisabled();
  fireEvent.keyDown(window, { key: ",", code: "Comma", ctrlKey: true });
  expect(screen.getByRole("region", { name: "Application settings" })).toBeVisible();
  await act(async () => { finish("fixture.credential-restart-complete"); });
  expect(await screen.findByText("Key saved. Local Runtime reconnected.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Develop" })).toBeEnabled();
  expect(invoke.mock.calls.filter(([name]) => name === "store_provider_credential")).toHaveLength(1);
});

it("reports a verified removal on the API keys page without offering the removed reference", async () => {
  let removed = false;
  invoke.mockImplementation(async command => {
    if (command === "get_runtime_process_status") return { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true };
    if (command === "list_provider_credentials") return removed ? [] : [{ environment_name: "DEEPSEEK_API_KEY", stored: true }];
    if (command === "remove_provider_credential") { removed = true; return "fixture.removed-key-session"; }
    throw new Error("Unexpected native request");
  });
  render(<ThemeProvider><ToastProvider><StudioShell /></ToastProvider></ThemeProvider>);
  fireEvent.click(screen.getByRole("button", { name: /^Settings$/ }));
  fireEvent.click(screen.getByRole("tab", { name: "Models & credentials" }));
  fireEvent.click(screen.getByRole("tab", { name: "API keys" }));
  fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
  await waitFor(() => expect(getConfig().token).toBe("fixture.removed-key-session"));
  expect(screen.getByRole("tab", { name: "API keys" })).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText("Key removed. Local Runtime reconnected.", { exact: true })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Continue to Models" })).not.toBeInTheDocument();
  expect(screen.queryByText(/Controller connection changed/)).not.toBeInTheDocument();
  expect(invoke.mock.calls.filter(([name]) => name === "remove_provider_credential")).toHaveLength(1);
});

it("selects a newly saved local reference without exposing the actual API key to Provider configuration", async () => {
  invoke.mockImplementation(async command => command === "get_runtime_process_status" ? { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true } : [{ environment_name: "DEEPSEEK_API_KEY_2", stored: true }]);
  render(<ProviderSettings models={[model]} onChanged={async () => {}} preferredCredential={{ environmentName: "DEEPSEEK_API_KEY_2", providerId: "deepseek", endpoint: "http://127.0.0.1:9017", version: (await import("../lib/api")).getRuntimeConfigVersion() }} />);
  fireEvent.click(await screen.findByRole("button", { name: "Add Provider" }));
  await waitFor(() => expect(screen.getByLabelText("Saved API key")).toHaveValue("env:DEEPSEEK_API_KEY_2"));
  expect(screen.getByLabelText("Vendor model ID")).toHaveValue("deepseek-chat");
  expect(screen.getByLabelText("Credential reference")).toHaveValue("env:DEEPSEEK_API_KEY_2");
  expect(invoke.mock.calls.some(([name]) => name === "store_provider_credential")).toBe(false);
});

it("assigns a different name when adding a key instead of silently replacing an existing key", async () => {
  invoke.mockImplementation(async command => command === "get_runtime_process_status" ? { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true } : [{ environment_name: "DEEPSEEK_API_KEY", stored: true }]);
  render(<CredentialSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  expect(screen.getByLabelText("Environment name")).toHaveValue("DEEPSEEK_API_KEY_2");
  expect(screen.getByText("DEEPSEEK_API_KEY", { exact: true })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Update" }));
  expect(screen.getByLabelText("Environment name")).toHaveValue("DEEPSEEK_API_KEY");
  expect(screen.getByLabelText("Environment name")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Update key" })).toBeEnabled();
  expect(invoke.mock.calls.some(([name]) => name === "store_provider_credential")).toBe(false);
});

it("retains an unconfirmed save as uncertain and refuses another submission", async () => {
  invoke.mockImplementation(async command => {
    if (command === "get_runtime_process_status") return { endpoint: "http://127.0.0.1:9017", ready: true, session_available: true };
    if (command === "list_provider_credentials") return [];
    if (command === "store_provider_credential") throw new Error("fixture: response lost after dispatch");
    throw new Error("Unexpected native command");
  });
  render(<CredentialSettings />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fixture-only-uncertain-key" } });
  fireEvent.submit(screen.getByRole("form", { name: "API key form" }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/may have been saved/));
  expect(screen.getByRole("button", { name: "Save key" })).toBeDisabled();
  fireEvent.submit(screen.getByRole("form", { name: "API key form" }));
  expect(invoke.mock.calls.filter(([name]) => name === "store_provider_credential")).toHaveLength(1);
  expect(getConfig().token).toBe("fixture.model.setup");
});
