import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CredentialSettings } from "../components/CredentialSettings";
import { setConfig } from "../lib/api";
import { bindNativeRuntimeSession } from "../lib/nativeRuntime";
import { invoke } from "@tauri-apps/api/core";

vi.mock("../lib/nativeRuntime", async original => ({ ...await original<typeof import("../lib/nativeRuntime")>(), bindNativeRuntimeSession: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
  vi.mocked(invoke).mockImplementation(async command => command === "get_runtime_process_status" ? { endpoint: "http://127.0.0.1:8770", ready: true, session_available: true } : []);
});
afterEach(() => { Reflect.deleteProperty(window, "__TAURI_INTERNALS__"); });

it("does not list or enable local credentials while a remote Controller is selected", async () => {
  setConfig({ url: "https://controller.example.test", token: "fake-only" });
  render(<CredentialSettings locale="zh" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("请先连接本机运行时");
  expect(vi.mocked(invoke).mock.calls.map(([command]) => command)).toEqual(["get_runtime_process_status"]);
  expect(screen.getByRole("button", { name: "保存密钥" })).toBeDisabled();
});

it("blocks credential restart while another Studio panel has a draft, without discarding the input", async () => {
  setConfig({ url: "http://127.0.0.1:8770", token: "fake-only" });
  vi.mocked(invoke).mockImplementation(async command => command === "get_runtime_process_status" ? { endpoint: "http://127.0.0.1:8770", ready: true, session_available: true } : [{ environment_name: "FAKE_PROVIDER_KEY", stored: true }]);
  render(<CredentialSettings hasOtherDrafts={() => true} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Save key" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fake-only-credential" } });
  fireEvent.click(screen.getByRole("button", { name: "Save key" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Save or cancel drafts in other panels");
  expect(screen.getByLabelText("Provider credential")).toHaveValue("fake-only-credential");
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm remove" }));
  expect(bindNativeRuntimeSession).not.toHaveBeenCalled();
});

it("does not reveal local references after the Controller changes during a read", async () => {
  setConfig({ url: "http://127.0.0.1:8770", token: "fake-only" });
  let release!: (rows: unknown) => void;
  vi.mocked(invoke).mockImplementation(command => command === "get_runtime_process_status" ? Promise.resolve({ endpoint: "http://127.0.0.1:8770", ready: true, session_available: true }) : new Promise(resolve => { release = resolve; }));
  render(<CredentialSettings />);
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("list_provider_credentials"));
  setConfig({ url: "https://other-controller.example.test", token: "other-fake-only" });
  await act(async () => release([{ environment_name: "PRIVATE_REFERENCE_NAME", stored: true }]));
  expect(screen.queryByText("PRIVATE_REFERENCE_NAME")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save key" })).toBeDisabled();
});
