import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProviderSettings } from "../components/ProviderSettings";
import { ApiError, api, governedStudioMutation, setConfig, testModel, type ModelLabSnapshot } from "../lib/api";

vi.mock("../lib/api", async original => ({ ...await original<typeof import("../lib/api")>(), api: vi.fn(), governedStudioMutation: vi.fn(), testModel: vi.fn() }));
const provider = { id: "example", name: "Example", health: { status: "unknown" }, configuration: { name: "Example", api_base_url: "https://example.test/v1", model: "original", has_reference: true } };
const models: ModelLabSnapshot["models"] = [{ model_id: "example/original", provider_id: "example", display_name: "Original", endpoint_type: "cloud_api", state: "enabled", health: "unknown", capabilities: ["chat"], capability_scores: {} }];
const changed = vi.fn().mockResolvedValue(undefined);
beforeEach(() => {
  vi.clearAllMocks();
  setConfig({ url: "http://localhost:8770", token: "fake.provider.settings" });
  vi.mocked(api).mockResolvedValue([provider]);
  vi.mocked(governedStudioMutation).mockResolvedValue({});
});
const open = (onOpenApprovals?: () => void) => render(<ProviderSettings models={models} onChanged={changed} onOpenApprovals={onOpenApprovals} />);

describe("Studio Provider configuration", () => {
  it("reads existing metadata without mutation, inference or browser persistence", async () => {
    open();
    expect(await screen.findByRole("button", { name: "Edit example" })).toBeEnabled();
    expect(screen.getByText(/original · https:\/\/example.test/)).toBeInTheDocument();
    expect(governedStudioMutation).not.toHaveBeenCalled();
    expect(testModel).not.toHaveBeenCalled();
    expect(JSON.stringify(localStorage)).not.toContain("example.test");
    expect(screen.getByRole("button", { name: "Run inference test" })).toBeDisabled();
  });
  it("patches only changed fields and preserves the hidden credential reference", async () => {
    open(); fireEvent.click(await screen.findByRole("button", { name: "Edit example" }));
    expect(screen.getByLabelText("Credential reference")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Vendor model ID"), { target: { value: "changed-model" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Provider" }));
    await waitFor(() => expect(governedStudioMutation).toHaveBeenCalledWith("/api/v1/providers/example", { model: "changed-model" }, expect.any(Function), "PATCH"));
    expect(testModel).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("Inference has not been tested");
  });
  it("rejects a pasted key without sending or storing it", async () => {
    open(); fireEvent.click(await screen.findByRole("button", { name: "Edit example" }));
    fireEvent.change(screen.getByLabelText("Credential reference"), { target: { value: "PRIVATE_NOT_A_REFERENCE" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Provider" }));
    expect(await screen.findByRole("alert")).not.toHaveTextContent("PRIVATE_NOT_A_REFERENCE");
    expect(governedStudioMutation).not.toHaveBeenCalled();
  });
  it("validates a new configuration before its governed creation, without testing inference", async () => {
    open(); await screen.findByRole("button", { name: "Edit example" });
    fireEvent.click(screen.getByRole("button", { name: "Add Provider" }));
    fireEvent.change(screen.getByLabelText("Vendor model ID"), { target: { value: "chosen-model" } });
    fireEvent.change(screen.getByLabelText("Credential reference"), { target: { value: "env:FAKE_OWNER_KEY" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Provider" }));
    await waitFor(() => expect(governedStudioMutation).toHaveBeenCalledTimes(2));
    expect(vi.mocked(governedStudioMutation).mock.calls.map(call => call[0])).toEqual(["/api/v1/providers/validate", "/api/v1/providers"]);
    expect(vi.mocked(governedStudioMutation).mock.calls[1][1]).toMatchObject({ provider_id: "openai", model: "chosen-model", credential_ref: "env:FAKE_OWNER_KEY" });
    expect(testModel).not.toHaveBeenCalled();
  });
  it("does not create after the panel closes during validation", async () => {
    let release!: (value: unknown) => void;
    vi.mocked(governedStudioMutation).mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    const view = open(); await screen.findByRole("button", { name: "Edit example" });
    fireEvent.click(screen.getByRole("button", { name: "Add Provider" }));
    fireEvent.change(screen.getByLabelText("Vendor model ID"), { target: { value: "chosen-model" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Provider" }));
    await waitFor(() => expect(governedStudioMutation).toHaveBeenCalledTimes(1));
    view.unmount(); await act(async () => { release({}); });
    expect(governedStudioMutation).toHaveBeenCalledTimes(1);
  });
  it("keeps the original provider and opens the authoritative approval surface", async () => {
    const openApprovals = vi.fn();
    vi.mocked(governedStudioMutation).mockRejectedValueOnce(new ApiError("NOUS_HUMAN_APPROVAL_REQUIRED", "Original operation requires approval"));
    open(openApprovals); await screen.findByRole("button", { name: "Edit example" });
    fireEvent.click(screen.getByRole("button", { name: "Remove example" }));
    expect(governedStudioMutation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Confirm remove example" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("requires approval");
    expect(screen.getByRole("button", { name: "Edit example" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open original approvals" }));
    expect(openApprovals).toHaveBeenCalledOnce();
    expect(governedStudioMutation).toHaveBeenCalledTimes(1);
    expect(governedStudioMutation).toHaveBeenCalledWith("/api/v1/providers/example", {}, expect.any(Function), "DELETE");
  });
  it("fails closed on malformed projected metadata and removes stale rows", async () => {
    open();
    await screen.findByRole("button", { name: "Edit example" });
    vi.mocked(api).mockResolvedValueOnce([{ ...provider, configuration: { ...provider.configuration, has_reference: "yes" } }]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh Providers" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider metadata is unavailable");
    expect(screen.queryByRole("button", { name: "Edit example" })).not.toBeInTheDocument();
    expect(governedStudioMutation).not.toHaveBeenCalled();
  });
  it("runs only an explicit selected-model test and keeps missing usage/cost UNKNOWN", async () => {
    vi.mocked(testModel).mockResolvedValueOnce({ model_id: "example/original", selected_model_id: "example/original", instance_id: "instance", request_id: "modelreq_original", response_id: "response", healthy: true, latency_ms: 1, cost_usd: 0, cost_measurement: "unknown" });
    open(); await screen.findByRole("button", { name: "Edit example" });
    fireEvent.change(screen.getByLabelText("Model to test"), { target: { value: "example/original" } });
    expect(testModel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Run inference test" }));
    const result = await screen.findByLabelText("Model test result");
    expect(result).toHaveTextContent("Tokens: UNKNOWN · USD: UNKNOWN");
    expect(result).toHaveTextContent("modelreq_original");
    expect(testModel).toHaveBeenCalledOnce();
    expect(testModel).toHaveBeenCalledWith("example/original");
  });
  it("clears private drafts and rejects a late read on a Controller switch", async () => {
    let release!: (value: unknown) => void;
    open(); fireEvent.click(await screen.findByRole("button", { name: "Edit example" }));
    fireEvent.change(screen.getByLabelText("Vendor model ID"), { target: { value: "PRIVATE_OLD_DRAFT" } });
    vi.mocked(api).mockReturnValueOnce(new Promise(resolve => { release = resolve; }));
    fireEvent.click(screen.getByRole("button", { name: "Refresh Providers" }));
    vi.mocked(api).mockResolvedValueOnce([]);
    act(() => setConfig({ url: "http://other-controller:8770", token: "fake.other.owner" }));
    await waitFor(() => expect(screen.queryByDisplayValue("PRIVATE_OLD_DRAFT")).not.toBeInTheDocument());
    await act(async () => { release([provider]); });
    expect(screen.queryByRole("button", { name: "Edit example" })).not.toBeInTheDocument();
    expect(governedStudioMutation).not.toHaveBeenCalled();
  });
});
