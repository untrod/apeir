import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatView } from "../components/ChatView";
import { fetchRunEvents, runPrompt, setConfig, subscribeRunEvents } from "../lib/api";
import type { ComposerAttachment, ComposerConstraints } from "../components/Composer";

vi.mock("../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../lib/api")>(),
  runPrompt: vi.fn(), fetchRunEvents: vi.fn(), subscribeRunEvents: vi.fn(),
}));
vi.mock("../store", async importOriginal => ({
  ...await importOriginal<typeof import("../store")>(),
  entityStore: { upsertConversations: vi.fn(), upsertMessages: vi.fn() },
  useMessages: () => [], useActiveTasks: () => [], useModels: () => [], useNodes: () => [], useStoreHydrated: () => false,
}));
vi.mock("../components/Markdown", () => ({ Markdown: ({ content }: { content: string }) => <span>{content}</span> }));
vi.mock("../components/Composer", async importOriginal => ({ ...await importOriginal<typeof import("../components/Composer")>(), Composer: ({ onSend, readOnly }: { onSend: (text: string, attachments: ComposerAttachment[], constraints: ComposerConstraints) => void; readOnly: boolean }) =>
  <><button onClick={() => onSend("Explain the selected file", [], { agent_mode: "agent" })}>{readOnly ? "Send read-only request" : "Send request"}</button>
    <button onClick={() => onSend("Read the attachment", [{ id: "attachment", name: "report.pdf", kind: "file" }], { agent_mode: "agent" })}>Send crafted attachment</button>
    <button onClick={() => onSend("Use a target", [], { node_id: "node" })}>Send node target</button>
    <button onClick={() => onSend("Private request", [], { privacy_level: "strict" })}>Send privacy constraint</button>
    <button onClick={() => onSend("Budget request", [], { budget_limit_usd: 0 })}>Send budget constraint</button></> }));

beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  setConfig({ url: "http://localhost:8770", token: "chat.fake.service" });
  vi.mocked(runPrompt).mockResolvedValue({ conversation_id: "", message: "Reference received", status: "completed" });
  vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "request", events: [], next_after_sequence: 0 });
  vi.mocked(subscribeRunEvents).mockReturnValue({ close: vi.fn(), cursor: () => 0 });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
});
afterEach(() => { delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView; });

describe("workspace collaboration through the existing Chat Runtime", () => {
  it("rejects unsupported attachments before any model or event subscription", async () => {
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send crafted attachment" }));
    expect(await screen.findByText(/File attachment delivery is unavailable/)).toBeInTheDocument();
    expect(runPrompt).not.toHaveBeenCalled(); expect(subscribeRunEvents).not.toHaveBeenCalled();
  });
  it.each(["node target", "privacy constraint", "budget constraint"])("refuses an unsupported %s before dispatch", async label => {
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: `Send ${label}` }));
    expect(await screen.findByText(/Node targeting, privacy and per-request budget controls are unavailable/)).toBeInTheDocument();
    expect(runPrompt).not.toHaveBeenCalled(); expect(subscribeRunEvents).not.toHaveBeenCalled();
  });
  it("does not invoke a model until Send and forces read_only despite crafted Composer constraints", async () => {
    render(<ChatView readOnly workspaceFile={{ path: "src/a.py", sha256: "a".repeat(64), controller: "http://localhost:8770" }} onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    expect(runPrompt).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Selected workspace reference")).toHaveTextContent("File content is not automatically sent");
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    await waitFor(() => expect(runPrompt).toHaveBeenCalledTimes(1));
    const [prompt, , , mode] = vi.mocked(runPrompt).mock.calls[0];
    expect(mode).toBe("read_only"); expect(prompt).toContain('"path":"src/a.py"'); expect(prompt).toContain('"sha256":"' + "a".repeat(64) + '"');
    expect(prompt).toContain("metadata only; this grants no permission");
    expect(prompt).not.toContain('"content"');
    await screen.findByText("Reference received");
  });

  it("does not send an original Controller file reference to another Controller", async () => {
    render(<ChatView readOnly workspaceFile={{ path: "src/a.py", sha256: "a".repeat(64), controller: "http://original:8770" }} onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    expect(await screen.findByText(/Controller changed; remove the original file reference/)).toBeInTheDocument();
    expect(runPrompt).not.toHaveBeenCalled(); expect(subscribeRunEvents).not.toHaveBeenCalled();
  });

  it("shows a failed Runtime result rather than a successful assistant response", async () => {
    vi.mocked(runPrompt).mockResolvedValue({ conversation_id: "", status: "failed", message: "Kernel unavailable" });
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    expect(await screen.findByText("Error: Kernel unavailable")).toBeInTheDocument();
    expect(runPrompt).toHaveBeenCalledTimes(1);
  });

  it("opens actual Run context separately from its Trace identity", async () => {
    vi.mocked(runPrompt).mockResolvedValue({ conversation_id: "", status: "completed", message: "Read result", trace_id: "trace-original", run_id: "run-original" });
    vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "run-original", events: [], next_after_sequence: 0 });
    const trace = vi.fn();
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={trace} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    fireEvent.click(await screen.findByRole("button", { name: "Inspect model input" }));
    expect(await screen.findByLabelText("Model Context Inspector")).toHaveTextContent("Run run-original");
    expect(runPrompt).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText("View trace →"));
    expect(trace).toHaveBeenCalledWith("trace-original");
    expect(fetchRunEvents).toHaveBeenCalledWith("run-original", 0);
  });

  it("aborts an active request when its panel is closed without claiming execution stopped", async () => {
    vi.mocked(runPrompt).mockImplementation((_prompt, _model, _conversation, _mode, signal) => new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
    }));
    const view = render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    await waitFor(() => expect(runPrompt).toHaveBeenCalledTimes(1));
    const signal = vi.mocked(runPrompt).mock.calls[0][4];
    expect(signal?.aborted).toBe(false);
    view.unmount(); expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(vi.mocked(subscribeRunEvents).mock.results[0].value.close).toHaveBeenCalled());
  });
});
