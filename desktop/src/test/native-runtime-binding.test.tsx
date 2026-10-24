import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectScreen } from "../components/ConnectScreen";
import { CredentialSettings } from "../components/CredentialSettings";
import { getConfig, setConfig, subscribeRuntimeConfig } from "../lib/api";
import { bindNativeRuntimeSession } from "../lib/nativeRuntime";
import App from "../App";
import { eventClient } from "../store";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

const native = vi.hoisted(() => ({ invoke: vi.fn() }));
const endpoint = "http://127.0.0.1:9017";
const localSession = "native.fake.local-session";
const remoteSession = "native.fake.remote-session";
const status = { endpoint, ready: true, session_available: true };

beforeEach(() => {
  native.invoke.mockReset();
  Object.defineProperty(window, "__TAURI_INTERNALS__", { configurable: true, value: { invoke: native.invoke } });
  setConfig({ url: endpoint, token: "" });
  native.invoke.mockImplementation(async (command: string) => {
    if (command === "get_runtime_process_status") return status;
    if (command === "load_runtime_session_token") throw new Error("No initial session");
    if (command === "list_provider_credentials") return [];
    return localSession;
  });
});
afterEach(() => {
  eventClient.stop();
  vi.unstubAllGlobals();
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
  sessionStorage.clear();
  localStorage.clear();
});

describe("native Runtime session destination", () => {
  it("starts the local Runtime using its reported endpoint instead of the remote form address", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true, data: {} })));
    vi.stubGlobal("fetch", fetcher);
    const connected = vi.fn();
    render(<ConnectScreen onConnected={connected} />);
    fireEvent.change(screen.getByPlaceholderText("http://localhost:8770"), { target: { value: "https://controller.example.test" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Local Runtime" }));
    await waitFor(() => expect(connected).toHaveBeenCalledTimes(1));
    expect(getConfig()).toEqual({ url: endpoint, token: localSession });
    expect(fetcher).toHaveBeenCalled();
    for (const [url, options] of fetcher.mock.calls) {
      expect(String(url)).toBe(`${endpoint}/api/v1/status`);
      expect(options.headers.Authorization).toBe(`Bearer ${localSession}`);
    }
  });

  it("does not overwrite a selected Controller when automatic native session loading finishes late", async () => {
    let finish!: (value: string) => void;
    native.invoke.mockImplementation(async (command: string) => {
      if (command === "get_runtime_process_status") return status;
      if (command === "load_runtime_session_token") return new Promise<string>(resolve => { finish = resolve; });
      return [];
    });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<ConnectScreen onConnected={vi.fn()} />);
    await waitFor(() => expect(finish).toBeDefined());
    const selected = { url: "https://controller.example.test", token: remoteSession };
    setConfig(selected);
    await act(async () => { finish(localSession); });
    expect(getConfig()).toEqual(selected);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refuses local credential mutation while a remote Controller is selected", async () => {
    const selected = { url: "https://controller.example.test", token: remoteSession };
    setConfig(selected);
    render(<CredentialSettings />);
    fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: "fixture-only-provider-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Store or Rotate" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/local Runtime/i));
    expect(native.invoke.mock.calls.some(([command]) => command === "store_provider_credential")).toBe(false);
    expect(getConfig()).toEqual(selected);
  });

  it("stores a local credential once, clears the input and binds the returned session to the native endpoint", async () => {
    render(<CredentialSettings />);
    const fakeCredential = "fixture-only-provider-value";
    fireEvent.change(screen.getByLabelText("Provider credential"), { target: { value: fakeCredential } });
    fireEvent.click(screen.getByRole("button", { name: "Store or Rotate" }));
    await waitFor(() => expect(screen.getByText(/Credential stored/)).toBeInTheDocument());
    expect(getConfig()).toEqual({ url: endpoint, token: localSession });
    expect(screen.getByLabelText("Provider credential")).toHaveValue("");
    expect(native.invoke.mock.calls.filter(([command]) => command === "store_provider_credential")).toEqual([
      ["store_provider_credential", { environmentName: "DEEPSEEK_API_KEY", secret: fakeCredential }, undefined],
    ]);
    for (const storage of [localStorage, sessionStorage]) {
      for (let index = 0; index < storage.length; index++) {
        expect(storage.getItem(storage.key(index)!)).not.toContain(fakeCredential);
      }
    }
  });

  it.each(["restart_runtime_api", "remove_provider_credential", "load_runtime_session_token"] as const)(
    "refuses %s for a selected remote Controller before mutating the local process", async command => {
      const selected = { url: "https://controller.example.test", token: remoteSession };
      setConfig(selected);
      await expect(bindNativeRuntimeSession(command)).rejects.toThrow(/Select the local Runtime/);
      expect(native.invoke.mock.calls.map(([name]) => name)).toEqual(["get_runtime_process_status"]);
      expect(getConfig()).toEqual(selected);
    },
  );

  it.each([
    "https://controller.example.test", "http://127.0.0.1:9017/api", "http://127.0.0.1:9017?target=remote",
    "http://user@127.0.0.1:9017", "http://127.0.0.1:9017#fragment", "https://127.0.0.1:9017",
  ])("refuses an invalid native session destination %s before invoking a session command", async invalid => {
    native.invoke.mockResolvedValue({ ...status, endpoint: invalid });
    const original = getConfig();
    await expect(bindNativeRuntimeSession("start_runtime_api", undefined, { activateLocal: true })).rejects.toThrow();
    expect(native.invoke.mock.calls.map(([name]) => name)).toEqual(["get_runtime_process_status"]);
    expect(getConfig()).toEqual(original);
  });

  it.each(["ready", "session_available", "endpoint", "token"] as const)("does not publish an unverified %s after a native action", async invalid => {
    let reads = 0;
    native.invoke.mockImplementation(async (command: string) => {
      if (command === "get_runtime_process_status") {
        reads++;
        return reads === 1 ? status : {
          ...status,
          ...(invalid === "endpoint" ? { endpoint: "http://127.0.0.1:9018" } : {}),
          ...(invalid === "ready" || invalid === "session_available" ? { [invalid]: false } : {}),
        };
      }
      return invalid === "token" ? "" : localSession;
    });
    const original = getConfig();
    await expect(bindNativeRuntimeSession("restart_runtime_api")).rejects.toThrow(/may have completed/);
    expect(native.invoke.mock.calls.filter(([command]) => command === "restart_runtime_api")).toHaveLength(1);
    expect(getConfig()).toEqual(original);
  });

  it("refuses a late native credential response after an address/token ABA change without retrying the action", async () => {
    let finish!: (value: string) => void;
    native.invoke.mockImplementation(async (command: string) => command === "get_runtime_process_status" ? status :
      new Promise<string>(resolve => { finish = resolve; }));
    const original = getConfig();
    const fakeCredential = "fixture-only-value";
    const result = bindNativeRuntimeSession("store_provider_credential", { environmentName: "TEST_PROVIDER_KEY", secret: fakeCredential });
    const rejected = expect(result).rejects.toThrow(/connection changed/);
    await waitFor(() => expect(finish).toBeDefined());
    setConfig({ url: "https://controller.example.test", token: remoteSession });
    setConfig(original);
    finish(localSession);
    await rejected;
    expect(getConfig()).toEqual(original);
    expect(native.invoke.mock.calls.filter(([command]) => command === "store_provider_credential")).toHaveLength(1);
  });

  it("does not send a native session after its Connect view closes", async () => {
    let finish!: (value: string) => void;
    native.invoke.mockImplementation(async (command: string) => command === "get_runtime_process_status" ? status :
      new Promise<string>(resolve => { finish = resolve; }));
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const connected = vi.fn();
    const view = render(<ConnectScreen onConnected={connected} />);
    await waitFor(() => expect(finish).toBeDefined());
    const original = getConfig();
    view.unmount();
    await act(async () => { finish(localSession); });
    expect(getConfig()).toEqual(original);
    expect(connected).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("requires the native host instead of using a browser/HTTP credential fallback", async () => {
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
    await expect(bindNativeRuntimeSession("start_runtime_api")).rejects.toThrow(/desktop application/);
    expect(native.invoke).not.toHaveBeenCalled();
  });

  it("refuses another connection change while publishing the native session", async () => {
    const other = { url: "https://controller.example.test", token: remoteSession };
    let changed = false;
    const unsubscribe = subscribeRuntimeConfig(() => {
      if (!changed) { changed = true; setConfig(other); }
    });
    try {
      await expect(bindNativeRuntimeSession("start_runtime_api")).rejects.toThrow(/changed while publishing/);
      expect(getConfig()).toEqual(other);
      expect(native.invoke.mock.calls.filter(([command]) => command === "start_runtime_api")).toHaveLength(1);
    } finally {
      unsubscribe();
    }
  });

  it("boots the real App against the selected remote Controller without loading a local session or changing local workspace", async () => {
    const selected = { url: "https://controller.example.test", token: remoteSession };
    setConfig(selected);
    const fetcher = vi.fn().mockImplementation(async (url: string) => new Response(JSON.stringify({
      ok: true, data: url.endsWith("/workspace") ? { active: { root: "selected-project" } } :
        url.endsWith("/providers") ? { providers: [] } : { running: true, version: "0.1.0-rc1" },
    })));
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await waitFor(() => expect(screen.getByRole("heading", { name: /Welcome to APEIR|欢迎使用 APEIR/ })).toBeInTheDocument());
    expect(getConfig()).toEqual(selected);
    const commands = native.invoke.mock.calls.map(([command]) => command);
    expect(commands).toContain("get_runtime_process_status");
    for (const forbidden of ["load_runtime_session_token", "start_runtime_api", "create_default_workspace"]) {
      expect(commands).not.toContain(forbidden);
    }
    expect(fetcher).toHaveBeenCalled();
    for (const [url, options] of fetcher.mock.calls) {
      expect(String(url)).toMatch(/^https:\/\/controller\.example\.test\//);
      expect(options.headers.Authorization).toBe(`Bearer ${remoteSession}`);
    }
  });

  it("uses the original authenticated HTTP client against only the native endpoint on real loopback sockets", async () => {
    const calls: string[] = [];
    const otherCalls: string[] = [];
    const server = createServer((request, response) => {
      calls.push(request.headers.authorization || "");
      const authorized = request.headers.authorization === `Bearer ${localSession}`;
      response.writeHead(authorized ? 200 : 401, { "Content-Type": "application/json" });
      response.end(JSON.stringify(authorized ? { ok: true, data: { running: true } } : { ok: false }));
    });
    const other = createServer((request, response) => {
      otherCalls.push(request.headers.authorization || "");
      response.end(JSON.stringify({ ok: true, data: {} }));
    });
    await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
    await new Promise<void>(resolve => other.listen(0, "127.0.0.1", resolve));
    const actualEndpoint = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    const otherEndpoint = `http://127.0.0.1:${(other.address() as AddressInfo).port}`;
    native.invoke.mockImplementation(async (command: string) => command === "get_runtime_process_status" ?
      { ...status, endpoint: actualEndpoint } : localSession);
    setConfig({ url: otherEndpoint, token: remoteSession });
    const connected = vi.fn();
    const view = render(<ConnectScreen onConnected={connected} />);
    try {
      fireEvent.change(screen.getByPlaceholderText("http://localhost:8770"), { target: { value: otherEndpoint } });
      fireEvent.click(screen.getByRole("button", { name: "Start Local Runtime" }));
      await waitFor(() => expect(connected).toHaveBeenCalledTimes(1));
      expect(getConfig()).toEqual({ url: actualEndpoint, token: localSession });
      expect(calls).toEqual([`Bearer ${localSession}`]);
      expect(otherCalls).toEqual([]);
    } finally {
      view.unmount();
      for (const owner of [server, other]) {
        owner.closeAllConnections();
        await new Promise<void>((resolve, reject) => owner.close(error => error ? reject(error) : resolve()));
      }
    }
  });
});
