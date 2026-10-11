import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextInspector } from "../components/ContextInspector";
import { fetchRunEvents, runPrompt, setConfig } from "../lib/api";

vi.mock("../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../lib/api")>(), fetchRunEvents: vi.fn(), runPrompt: vi.fn() }));
const controller = "http://localhost:8770";
const manifest = {
  schema_version: 1, scope: "admitted-gateway-input", input_sha256: "a".repeat(64),
  message_count: 2, estimated_input_tokens: 24, tool_count: 1,
  tools: [{ name: "read_file" }],
  messages: [
    { index: 0, role: "system", content_characters: 42, estimated_tokens: 14, sha256: "b".repeat(64), source: { kind: "instruction" } },
    { index: 1, role: "tool", content_characters: 12, estimated_tokens: 7, sha256: "c".repeat(64), source: { kind: "tool_result", tool: "read_file", ok: true, path: "main.py", start_line: 1, end_line: 4, file_sha256: "d".repeat(64) } },
  ],
};
const started = { event_id: "start-1", sequence: 1, event_type: "model.invocation.started", payload: { iteration: 1, input_manifest: manifest } };
const props = { runId: "run-original", controller, onClose: vi.fn() };
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear(); setConfig({ url: controller, token: "fake.inspection.service" });
  vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [started], next_after_sequence: 1 });
});

describe("persisted actual-input inspection", () => {
  it("distinguishes estimates, actual usage and verified effects without any model invocation", async () => {
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [started, { event_type: "model.invocation.completed", payload: { iteration: 1, model_id: "fixture/model", provider_id: "fixture", usage: { input_tokens: 31, cached_input_tokens: 10 }, cost_usd: 0, latency_ms: 8 } }], next_after_sequence: 2 });
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/Recorded input tokens: 31/)).toBeInTheDocument();
    expect(screen.getByText(/Estimated input tokens: 24/)).toBeInTheDocument();
    expect(screen.getByText(/not effect verification/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/#1 · tool/));
    expect(screen.getByText(/File: main.py · lines 1–4/)).toBeInTheDocument();
    expect(screen.getByText(/Tool declarations do not grant permission/)).toBeInTheDocument();
    expect(runPrompt).not.toHaveBeenCalled();
  });

  it("shows UNKNOWN for absent legacy evidence and missing terminal usage", async () => {
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/Recorded input tokens: UNKNOWN/)).toBeInTheDocument();
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [{ ...started, payload: { iteration: 1 } }], next_after_sequence: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Reload evidence" }));
    expect(await screen.findByText(/no supported input manifest/)).toBeInTheDocument();
    expect(screen.queryByText(/Estimated input tokens/)).not.toBeInTheDocument();
  });

  it("does not confuse absent model events with an empty model context", async () => {
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [], next_after_sequence: 0 });
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/does not mean that the model saw no context/)).toBeInTheDocument();
  });

  it("does not render unrecognized raw prompt fields or certify malformed manifests", async () => {
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [{ ...started, payload: { iteration: 1, input_manifest: { ...manifest, tools: [], raw_prompt: "PRIVATE-PROMPT-CONTENT" } } }], next_after_sequence: 1 });
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/no supported input manifest/)).toBeInTheDocument();
    expect(screen.queryByText("PRIVATE-PROMPT-CONTENT")).not.toBeInTheDocument();
    expect(screen.queryByText("None declared")).not.toBeInTheDocument();
  });

  it("shows partial/omitted context chunks and failed reads without inventing a blocked-file list", async () => {
    const messages = [
      { ...manifest.messages[0], source: { kind: "selected_context", item_count: 2, items: [{ source_type: "memory", status: "partial", included_characters: 20, total_characters: 30 }, { source_type: "device", status: "omitted", included_characters: 0, total_characters: 9 }] } },
      { ...manifest.messages[1], source: { kind: "tool_result", tool: "read_file", ok: false } },
    ];
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: props.runId, events: [{ ...started, payload: { iteration: 1, input_manifest: { ...manifest, messages } } }], next_after_sequence: 1 });
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/memory · partial · 20\/30/)).toBeInTheDocument();
    expect(screen.getByText(/device · omitted · 0\/9/)).toBeInTheDocument();
    expect(screen.getByText(/failed; no successful read claimed/)).toBeInTheDocument();
    expect(screen.queryByText(/File: /)).not.toBeInTheDocument();
  });

  it("replays the next page and selects later tool turns", async () => {
    vi.mocked(fetchRunEvents).mockResolvedValueOnce({ run_id: props.runId, events: [started, ...Array.from({ length: 199 }, (_, i) => ({ sequence: i + 2, event_type: "step.progress" }))], next_after_sequence: 200 })
      .mockResolvedValueOnce({ run_id: props.runId, events: [{ ...started, event_id: "start-2", sequence: 201, payload: { iteration: 2, input_manifest: { ...manifest, estimated_input_tokens: 90 } } }], next_after_sequence: 201 });
    render(<ContextInspector {...props} />);
    const selector = await screen.findByRole("combobox", { name: "Model invocation" });
    fireEvent.change(selector, { target: { value: "1" } });
    expect(screen.getByText(/Estimated input tokens: 90/)).toBeInTheDocument();
    expect(fetchRunEvents).toHaveBeenNthCalledWith(2, props.runId, 200);
  });

  it("clears stale data on a different Run and surfaces read errors", async () => {
    const view = render(<ContextInspector {...props} />);
    await screen.findByText(/Estimated input tokens: 24/);
    vi.mocked(fetchRunEvents).mockRejectedValue(new Error("persisted evidence unavailable"));
    view.rerender(<ContextInspector {...props} runId="other-run" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("persisted evidence unavailable");
    expect(screen.queryByText(/Estimated input tokens/)).not.toBeInTheDocument();
  });

  it("fails closed on a wrong Controller or mismatched Run response", async () => {
    const view = render(<ContextInspector {...props} controller="http://original:8770" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Controller changed");
    expect(fetchRunEvents).not.toHaveBeenCalled();
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "wrong-run", events: [started], next_after_sequence: 1 });
    view.rerender(<ContextInspector {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match");
  });

  it("bounds replay instead of pretending later events were inspected", async () => {
    vi.mocked(fetchRunEvents).mockImplementation(async (_id, after = 0) => ({ run_id: props.runId, events: Array.from({ length: 200 }, (_, i) => ({ sequence: after + i + 1, event_type: "step.progress" })), next_after_sequence: after + 200 }));
    render(<ContextInspector {...props} />);
    expect(await screen.findByText(/1,600-event inspection bound/)).toBeInTheDocument();
    expect(fetchRunEvents).toHaveBeenCalledTimes(8);
  });

  it("ignores a response from a closed or replaced inspector", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof fetchRunEvents>>) => void;
    vi.mocked(fetchRunEvents).mockReturnValueOnce(new Promise(value => { resolve = value; }));
    const view = render(<ContextInspector {...props} />);
    vi.mocked(fetchRunEvents).mockResolvedValueOnce({ run_id: "new-run", events: [], next_after_sequence: 0 });
    view.rerender(<ContextInspector {...props} runId="new-run" />);
    await screen.findByText(/no recorded model input/);
    resolve({ run_id: props.runId, events: [started], next_after_sequence: 1 });
    await waitFor(() => expect(screen.queryByText(/Estimated input tokens/)).not.toBeInTheDocument());
  });
});
