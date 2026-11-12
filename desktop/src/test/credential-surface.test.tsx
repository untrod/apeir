import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CredentialSettings } from "../components/CredentialSettings";
import { setConfig } from "../lib/api";
import { bindNativeRuntimeSession, nativeRuntimeStatus } from "../lib/nativeRuntime";
import { invoke } from "@tauri-apps/api/core";

vi.mock("../lib/nativeRuntime", async original => ({ ...await original<typeof import("../lib/nativeRuntime")>(), nativeRuntimeStatus: vi.fn(), bindNativeRuntimeSession: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {}, configurable: true });
  vi.mocked(nativeRuntimeStatus).mockResolvedValue({ endpoint: "http://127.0.0.1:8770", ready: true, session_available: true });
  vi.mocked(invoke).mockResolvedValue([]);
});
afterEach(() => { Reflect.deleteProperty(window, "__TAURI_INTERNALS__"); });

it("does not list or enable local credentials while a remote Controller is selected", async () => {
  setConfig({ url: "https://controller.example.test", token: "fake-only" });
  render(<CredentialSettings locale="zh" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("请先连接本地运行时");
  expect(invoke).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "保存或更新" })).toBeDisabled();
});

it("blocks credential restart while another Studio panel has a draft, without discarding the input", async () => {
  setConfig({ url: "http://127.0.0.1:8770", token: "fake-only" });
  vi.mocked(invoke).mockResolvedValue([{ environment_name: "FAKE_PROVIDER_KEY", stored: true }]);
  render(<CredentialSettings hasOtherDrafts={() => true} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Store or Rotate" })).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fake-only-credential" } });
  fireEvent.click(screen.getByRole("button", { name: "Store or Rotate" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Save or cancel drafts in other panels");
  expect(screen.getByLabelText("Provider credential")).toHaveValue("fake-only-credential");
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm Remove" }));
  expect(bindNativeRuntimeSession).not.toHaveBeenCalled();
});

it("does not reveal local references after the Controller changes during a read", async () => {
  setConfig({ url: "http://127.0.0.1:8770", token: "fake-only" });
  let release!: (rows: unknown) => void;
  vi.mocked(invoke).mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
  render(<CredentialSettings />);
  await waitFor(() => expect(invoke).toHaveBeenCalledWith("list_provider_credentials", undefined));
  setConfig({ url: "https://other-controller.example.test", token: "other-fake-only" });
  await act(async () => release([{ environment_name: "PRIVATE_REFERENCE_NAME", stored: true }]));
  expect(screen.queryByText("PRIVATE_REFERENCE_NAME")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Store or Rotate" })).toBeDisabled();
});
