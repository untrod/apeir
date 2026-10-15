import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { NodesPage } from "../App";
import { setConfig } from "../lib/api";
import { entityStore } from "../store/entityStore";

const reply = (data: unknown) => ({ ok: true, json: async () => ({ ok: true, data }) });

describe("registered Node view", () => {
  beforeEach(() => { entityStore.clearStore(); setConfig({ url: "http://127.0.0.1:8770", token: "fake-node-page-service" }); });
  afterEach(() => { vi.unstubAllGlobals(); sessionStorage.clear(); entityStore.clearStore(); });
  it("shows unavailable Controller facts and supports a real read retry", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: false, error: { code: "NOUS_NODE_FACTS_UNAVAILABLE", message: "Controller identity has not been provisioned" } }) });
    vi.stubGlobal("fetch", fetch);
    render(<NodesPage onNodeClick={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Controller identity has not been provisioned");
    expect(screen.queryByText("No nodes registered.")).not.toBeInTheDocument();
    fetch.mockResolvedValue(reply([]));
    fireEvent.click(screen.getByRole("button", { name: "Reload Node facts" }));
    expect(await screen.findByText("No nodes registered.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("replaces the previous Controller's Nodes after a connection change", async () => {
    const node = { node_id: "former-node", node_name: "Former Node", platform: "Linux", arch: "arm64", capabilities: [], online: true, last_seen: "", status: "online", trust_status: "TRUSTED", connected: true, connectivity_state: "ONLINE", connectivity_lease_valid: true, resource_report_fresh: true, source: "node_runtime.controller-status" };
    let release!: (value: unknown) => void;
    const fetch = vi.fn().mockResolvedValueOnce(reply([node])).mockImplementation(() => new Promise(resolve => { release = resolve; }));
    vi.stubGlobal("fetch", fetch);
    render(<NodesPage onNodeClick={vi.fn()} />);
    expect(await screen.findByText("Former Node")).toBeInTheDocument();
    act(() => setConfig({ url: "http://127.0.0.1:8771", token: "fake-node-page-replacement" }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking current Controller Node facts");
    expect(screen.queryByText("Former Node")).not.toBeInTheDocument();
    await act(async () => { release(reply([])); });
    expect(await screen.findByText("No nodes registered.")).toBeInTheDocument();
    expect(screen.queryByText("Former Node")).not.toBeInTheDocument();
  });
  it("shows loading rather than an empty or stale successful list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(() => {})));
    render(<NodesPage onNodeClick={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Checking current Controller Node facts");
    expect(screen.queryByText("No nodes registered.")).not.toBeInTheDocument();
  });
});
