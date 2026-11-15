import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OnboardingWizard } from "../components/OnboardingWizard";
import { setConfig } from "../lib/api";

const endpoint = "http://127.0.0.1:8770";
const session = "setup.fake.local-session";
const native = vi.fn();
let workspace = "/qualification/original";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  workspace = "/qualification/original";
  setConfig({ url: endpoint, token: session });
  native.mockReset();
  native.mockImplementation(async (command: string, args?: { path?: string }) => {
    if (command === "get_runtime_process_status") return { endpoint, ready: true, session_available: true };
    if (command === "get_default_workspace_path") return workspace;
    if (command === "create_default_workspace") { workspace = args!.path!; return workspace; }
    if (command === "restart_runtime_api") return session;
    throw new Error("Unsupported qualification command");
  });
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke: native } });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify({ ok: true, data:
    url.endsWith("/health/detailed") ? {
      running: true, platform: "linux", architecture: "aarch64", workspace_available: true, workspace_path: workspace,
      provider_configured: false, kernel: { configured: true, connected: false, ready: false, state: "unavailable" },
    } : url.endsWith("/workspace/status") ? { exists: true, valid: true, path: workspace } :
    url.endsWith("/providers/validate") ? { ok: true, validation_scope: "configuration", authentication: "UNKNOWN", model_inference: "NOT_RUN" } :
    new URL(url).pathname.endsWith("/models") ? { models: [] } : {},
  }))));
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  localStorage.clear();
  sessionStorage.clear();
});

function begin(onComplete = vi.fn()) {
  render(<OnboardingWizard onComplete={onComplete} onSkip={vi.fn()} />);
  fireEvent.click(screen.getByText(/^(More options|更多选项)$/));
  fireEvent.click(screen.getByRole("button", { name: /Full setup|完整设置/ }));
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByRole("button", { name: /Start Setup/ }));
}

describe("first-use setup uses Runtime records", () => {
  it("opens the verified current workspace in one step without configuring or calling a model", async () => {
    const completed = vi.fn();
    localStorage.setItem("nous_provider_id", "saved-provider");
    render(<OnboardingWizard onComplete={completed} onSkip={vi.fn()} />);
    const open = await screen.findByRole("button", { name: /Open Studio|进入 Studio/ });
    await waitFor(() => expect(open).toBeEnabled());
    expect(screen.queryByRole("heading", { name: /Environment Check|环境检查/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Model Provider|模型服务商/ })).not.toBeInTheDocument();
    fireEvent.click(open);
    fireEvent.click(open);
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem("nous_onboarding_completed")).toBe("1");
    expect(localStorage.getItem("nous_workspace_path")).toBe(workspace);
    expect(localStorage.getItem("nous_provider_id")).toBe("saved-provider");
    expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    expect(native.mock.calls.some(([command]) => command === "restart_runtime_api" || command === "store_provider_credential")).toBe(false);
  });

  it("returns to the original default path after editing a new workspace and preserves the draft across languages", async () => {
    render(<OnboardingWizard onComplete={vi.fn()} onSkip={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Open Studio|进入 Studio/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Create New|新建工作空间/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/qualification/draft" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "zh-CN" } });
    expect(screen.getByRole("textbox")).toHaveValue("/qualification/draft");
    await waitFor(() => expect(screen.getByRole("button", { name: "进入 Studio" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /^当前位置/ }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
  });

  it("does not publish completion when workspace activation readback disagrees", async () => {
    const completed = vi.fn();
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (url, options) => String(url).endsWith("/workspace/status") ?
      new Response(JSON.stringify({ ok: true, data: { exists: true, valid: true, path: "/qualification/other" } })) : original(url, options));
    render(<OnboardingWizard onComplete={completed} onSkip={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Open Studio|进入 Studio/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Create New|新建工作空间/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/qualification/selected" } });
    fireEvent.click(screen.getByRole("button", { name: /Open Studio|进入 Studio/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/did not confirm/));
    expect(completed).not.toHaveBeenCalled();
    expect(localStorage.getItem("nous_onboarding_completed")).toBeNull();
    expect(native.mock.calls.filter(([command]) => command === "restart_runtime_api")).toHaveLength(1);
  });

  it("finishes quick setup after the selected workspace and rotated native session are confirmed", async () => {
    const original = native.getMockImplementation()!;
    native.mockImplementation(async (command: string, args?: { path?: string }) => command === "restart_runtime_api" ? "setup.fake.rotated-session" : original(command, args));
    const completed = vi.fn();
    render(<OnboardingWizard onComplete={completed} onSkip={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Open Studio|进入 Studio/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Create New|新建工作空间/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "/qualification/selected" } });
    fireEvent.click(screen.getByRole("button", { name: /Open Studio|进入 Studio/ }));
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
    expect(localStorage.getItem("nous_workspace_path")).toBe("/qualification/selected");
    expect(native.mock.calls.filter(([command]) => command === "create_default_workspace")).toHaveLength(1);
    expect(native.mock.calls.filter(([command]) => command === "restart_runtime_api")).toHaveLength(1);
    const readback = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/workspace/status")).at(-1);
    expect((readback?.[1]?.headers as Record<string, string>).Authorization).toBe("Bearer setup.fake.rotated-session");
  });

  it("retires a pending quick-setup read after Controller ABA without activating or completing it", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!;
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (url, options) => String(url).endsWith("/workspace/status") ? new Promise<Response>(resolve => { finish = resolve; }) : original(url, options));
    const completed = vi.fn();
    render(<OnboardingWizard onComplete={completed} onSkip={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Open Studio|进入 Studio/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Open Studio|进入 Studio/ }));
    await waitFor(() => expect(finish).toBeDefined());
    setConfig({ url: "https://other.example.test", token: "setup.fake.other" });
    setConfig({ url: endpoint, token: session });
    finish(new Response(JSON.stringify({ ok: true, data: { exists: true, valid: true, path: workspace } })));
    await waitFor(() => expect(screen.getAllByRole("alert").some(node => /changed|更改/.test(node.textContent || ""))).toBe(true));
    expect(completed).not.toHaveBeenCalled();
    expect(localStorage.getItem("nous_onboarding_completed")).toBeNull();
    expect(native.mock.calls.some(([command]) => command === "create_default_workspace" || command === "restart_runtime_api")).toBe(false);
  });

  it("offers only this Provider's exact vendor model IDs, preserving namespaces", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (url, options) => new URL(String(url)).pathname.endsWith("/models") ?
      new Response(JSON.stringify({ ok: true, data: { models: [
        { id: "ollama/catalog-entry", model_id: "ollama/catalog-entry", provider_id: "ollama", provider_model: "org/vendor-model" },
        { id: "other/unrelated", model_id: "other/unrelated", provider_id: "other", provider_model: "unrelated-vendor-model" },
        { id: "ollama/unknown-target", model_id: "ollama/unknown-target", provider_id: "ollama" },
      ] } })) : original(url, options));
    begin();
    await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^Ollama/ }));
    expect(screen.getByRole("button", { name: /^Google Gemini/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Anthropic/ })).toBeDisabled();
    expect(screen.getAllByText(/Native protocol unavailable/)).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(document.querySelector('#models-chat option[value="org/vendor-model"]')).not.toBeNull());
    expect(document.querySelector('#models-chat option[value="ollama/catalog-entry"]')).toBeNull();
    expect(document.querySelector('#models-chat option[value="unrelated-vendor-model"]')).toBeNull();
    expect(document.querySelector('#models-chat option[value="ollama/unknown-target"]')).toBeNull();
    fireEvent.change(screen.getByLabelText("Default Chat"), { target: { value: "org/vendor-model" } });
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/NOT_RUN — save configuration/)).toBeInTheDocument());
    const validation = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/providers/validate"));
    expect(JSON.parse(String(validation?.[1]?.body)).model).toBe("org/vendor-model");
  });

  it("reports observed Runtime architecture and blocked Kernel without fabricating WebView or sandbox success", async () => {
    begin();
    await waitFor(() => expect(screen.getByText(/aarch64/)).toBeInTheDocument());
    expect(screen.getByText(/BLOCKED.*unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/UNCONFIGURED/)).toBeInTheDocument();
    expect(screen.getByText(/NOT_RUN.*isolation/)).toBeInTheDocument();
    expect(screen.queryByText("WebView2")).not.toBeInTheDocument();
  });

  it("waits for original native workspace facts before enabling the next step", async () => {
    const original = native.getMockImplementation()!;
    let finish!: (value: string) => void;
    native.mockImplementation(async (command: string, args?: { path?: string }) => command === "get_default_workspace_path" ?
      new Promise<string>(resolve => { finish = resolve; }) : original(command, args));
    begin();
    await waitFor(() => expect(finish).toBeDefined());
    expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled();
    finish(workspace);
    await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeEnabled());
  });

  it("activates the exact selected local workspace before advancing to Provider configuration", async () => {
    begin();
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "get_default_workspace_path")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Create New/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter workspace path..."), { target: { value: "/qualification/selected" } });
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "create_default_workspace")).toBe(true));
    expect(native.mock.calls.filter(([command]) => command === "create_default_workspace").map(([, args]) => args)).toEqual([{ path: "/qualification/selected" }]);
    expect(native.mock.calls.filter(([command]) => command === "restart_runtime_api")).toHaveLength(1);
    await waitFor(() => expect(screen.getByRole("heading", { name: /Provider/ })).toBeInTheDocument());
    expect(workspace).toBe("/qualification/selected");
  });

  it("enters the workbench without a model while preserving explicit qualification limits", async () => {
    const completed = vi.fn();
    begin(completed);
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "get_default_workspace_path")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Configure model later" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure model later" }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Configuration Saved" })).toBeInTheDocument());
    expect(screen.getByText(/has not created a conversation or run inference/)).toBeInTheDocument();
    expect(localStorage.getItem("nous_onboarding_completed")).toBe("1");
    expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    expect(native.mock.calls.some(([command]) => command === "restart_runtime_api" || command === "store_provider_credential")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: /Open APEIR/ }));
    expect(completed).toHaveBeenCalledTimes(1);
  });

  it("saves Provider configuration exactly once before completion and leaves inference NOT_RUN", async () => {
    begin();
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "get_default_workspace_path")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Ollama/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^Ollama/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByText(/NOT_RUN — save configuration/)).toBeInTheDocument());
    expect(screen.queryByText(/Connected/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Configuration Saved" })).toBeInTheDocument());
    const posts = vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === "POST");
    expect(posts.filter(([url]) => String(url).endsWith("/providers"))).toHaveLength(1);
    expect(posts.filter(([url]) => String(url).endsWith("/providers/validate"))).toHaveLength(1);
    expect(posts.some(([url]) => String(url).endsWith("/models/test"))).toBe(false);
  });

  it("blocks stale setup after a Controller/address ABA change", async () => {
    begin();
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "get_default_workspace_path")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    const before = native.mock.calls.length;
    setConfig({ url: "https://other.example.test", token: "setup.fake.other-session" });
    setConfig({ url: endpoint, token: session });
    await waitFor(() => expect(screen.getByRole("button", { name: /Next/ })).toBeDisabled());
    expect(screen.getByText(/Controller changed. Reopen setup/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(native.mock.calls).toHaveLength(before);
  });

  it("retains workspace activation uncertainty without automatically repeating native mutations", async () => {
    const original = native.getMockImplementation()!;
    native.mockImplementation(async (command: string, args?: { path?: string }) => {
      if (command === "restart_runtime_api") throw new Error("Original restart response unavailable; inspect diagnostics");
      return original(command, args);
    });
    begin();
    await waitFor(() => expect(native.mock.calls.some(([command]) => command === "get_default_workspace_path")).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    fireEvent.click(screen.getByRole("button", { name: /Create New/ }));
    fireEvent.change(screen.getByPlaceholderText("Enter workspace path..."), { target: { value: "/qualification/selected" } });
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Original restart response unavailable/));
    expect(screen.getByRole("heading", { name: "Workspace" })).toBeInTheDocument();
    expect(native.mock.calls.filter(([command]) => command === "create_default_workspace")).toHaveLength(1);
    expect(native.mock.calls.filter(([command]) => command === "restart_runtime_api")).toHaveLength(1);
    expect(localStorage.getItem("nous_onboarding_completed")).toBeNull();
  });
});
