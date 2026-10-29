import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatView } from "../components/ChatView";
import { fetchConversation, fetchRunEvents, runPrompt, setConfig, subscribeRunEvents } from "../lib/api";
import type { ComposerAttachment, ComposerConstraints } from "../components/Composer";

vi.mock("../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../lib/api")>(),
  runPrompt: vi.fn(), fetchConversation: vi.fn(), fetchRunEvents: vi.fn(), subscribeRunEvents: vi.fn(),
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
  vi.mocked(fetchConversation).mockResolvedValue({ id: "conversation", messages: [] } as unknown as Awaited<ReturnType<typeof fetchConversation>>);
  vi.mocked(fetchRunEvents).mockResolvedValue({ run_id: "request", events: [], next_after_sequence: 0 });
  vi.mocked(subscribeRunEvents).mockReturnValue({ close: vi.fn(), cursor: () => 0 });
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: vi.fn() });
});
afterEach(() => { delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView; vi.unstubAllGlobals(); });

describe("workspace collaboration through the existing Chat Runtime", () => {
  it("retains recorded tool activity after the response without claiming verification", async () => {
    vi.mocked(fetchRunEvents).mockResolvedValue({
      run_id: "original-run", next_after_sequence: 1,
      events: [{ event_id: "read-one", event_type: "tool.completed", sequence: 1, payload: { tool: "read_file", ok: true } }],
    } as unknown as Awaited<ReturnType<typeof fetchRunEvents>>);
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    await screen.findByText("Reference received");
    expect(screen.getByText("read_file completed")).toBeInTheDocument();
    expect(screen.getByText("1 tools completed")).toBeInTheDocument();
    expect(screen.queryByText(/tools verified/)).not.toBeInTheDocument();
  });

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
    const [prompt, , , mode, , , refs] = vi.mocked(runPrompt).mock.calls[0];
    expect(mode).toBe("read_only"); expect(prompt).toBe("Explain the selected file");
    expect(refs).toEqual([{ path: "src/a.py", sha256: "a".repeat(64) }]);
    expect(JSON.stringify(refs)).not.toContain('"content"');
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
  it.each(["token", "ABA", "unmount", "conversation"] as const)("rejects a late model result after %s changes the original Chat view", async change => {
    let finish!: (value: Awaited<ReturnType<typeof runPrompt>>) => void;
    vi.mocked(runPrompt).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const created = vi.fn(), proposal = vi.fn();
    const props = { readOnly: true, onCardClick: vi.fn(), onTraceClick: vi.fn(), onConversationCreated: created, onProposalCreated: proposal };
    const view = render(<ChatView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    await waitFor(() => expect(runPrompt).toHaveBeenCalledTimes(1));
    await act(async () => {
      if (change === "unmount") view.unmount();
      else if (change === "conversation") view.rerender(<ChatView {...props} conversationId="other-conversation" />);
      else if (change === "token") setConfig({ url: "http://localhost:8770", token: "chat.fake.changed" });
      else {
        setConfig({ url: "https://temporary.example.test", token: "chat.fake.temporary" });
        setConfig({ url: "http://localhost:8770", token: "chat.fake.service" });
      }
    });
    // Commit the navigation before delivering the old network result.
    await act(async () => {
      finish({ conversation_id: "old-conversation", message: "Old private reply", status: "waiting_approval", result: { proposal_id: "old-proposal" } });
    });
    expect(proposal).not.toHaveBeenCalled();
    expect(created).not.toHaveBeenCalled();
    expect(fetchRunEvents).not.toHaveBeenCalled();
    expect(screen.queryByText("Old private reply")).not.toBeInTheDocument();
  });

  it("does not publish a reply when its event replay finishes after connection rotation", async () => {
    let finish!: (value: Awaited<ReturnType<typeof fetchRunEvents>>) => void;
    vi.mocked(runPrompt).mockResolvedValueOnce({ conversation_id: "", message: "Old replay reply", status: "completed" });
    vi.mocked(fetchRunEvents).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    await waitFor(() => expect(fetchRunEvents).toHaveBeenCalledTimes(1));
    await act(async () => {
      setConfig({ url: "http://localhost:8770", token: "chat.fake.changed" });
      finish({ run_id: "old-run", events: [], next_after_sequence: 0 });
    });
    expect(screen.queryByText("Old replay reply")).not.toBeInTheDocument();
  });

  it("does not ingest old history after a same-URL token change", async () => {
    const { entityStore } = await import("../store");
    let finish!: (value: Awaited<ReturnType<typeof fetchConversation>>) => void;
    vi.mocked(fetchConversation).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    render(<ChatView conversationId="original" readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    await waitFor(() => expect(fetchConversation).toHaveBeenCalledTimes(1));
    await act(async () => {
      setConfig({ url: "http://localhost:8770", token: "chat.fake.changed" });
      finish({ id: "original", messages: [{ id: "old-message", content: "Old history" }] } as unknown as Awaited<ReturnType<typeof fetchConversation>>);
    });
    expect(vi.mocked(entityStore.upsertMessages).mock.calls.some(([rows]) => rows.some(row => row.id === "old-message"))).toBe(false);
  });

  it.each(["unmount", "conversation", "token"] as const)("does not approve after %s while its human nonce is pending", async change => {
    vi.mocked(fetchRunEvents).mockResolvedValueOnce({ run_id: "request", next_after_sequence: 1, events: [{
      event_id: "approval-event", sequence: 1, event_type: "approval.requested", payload: { request_id: "apr_original_chat" },
    }] } as unknown as Awaited<ReturnType<typeof fetchRunEvents>>);
    let finish!: (value: unknown) => void;
    const fetcher = vi.fn().mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const props = { readOnly: true, onCardClick: vi.fn(), onTraceClick: vi.fn() };
    const view = render(<ChatView {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    fireEvent.click(await screen.findByText("apr_original_chat"));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    expect(fetcher.mock.calls[0][0]).toContain("/api/v1/control/human/nonce");
    await act(async () => {
      if (change === "unmount") view.unmount();
      else if (change === "conversation") view.rerender(<ChatView {...props} conversationId="other" />);
      else setConfig({ url: "http://localhost:8770", token: "chat.fake.changed" });
    });
    await act(async () => { finish({ ok: true, json: async () => ({ ok: true, data: { nonce: "chat-fake-nonce" } }) }); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("✓ Done")).not.toBeInTheDocument();
  });

  it("keeps a replacement request active when the old request finishes", async () => {
    let finishOld!: (value: Awaited<ReturnType<typeof runPrompt>>) => void;
    let finishNew!: (value: Awaited<ReturnType<typeof runPrompt>>) => void;
    const oldClose = vi.fn(), newClose = vi.fn();
    vi.mocked(runPrompt).mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }))
      .mockReturnValueOnce(new Promise(resolve => { finishNew = resolve; }));
    vi.mocked(subscribeRunEvents).mockReturnValueOnce({ close: oldClose, cursor: () => 0 })
      .mockReturnValueOnce({ close: newClose, cursor: () => 0 });
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    fireEvent.click(screen.getByRole("button", { name: "Send read-only request" }));
    expect(vi.mocked(runPrompt).mock.calls[0][4]?.aborted).toBe(true);
    expect(oldClose).toHaveBeenCalled();
    await act(async () => { finishOld({ conversation_id: "", status: "completed", message: "Superseded reply" }); });
    expect(screen.getByText("Running", { exact: true })).toBeInTheDocument();
    expect(screen.queryByText("Superseded reply")).not.toBeInTheDocument();
    expect(newClose).not.toHaveBeenCalled();
    await act(async () => { finishNew({ conversation_id: "", status: "completed", message: "Current reply" }); });
    expect(await screen.findByText("Current reply")).toBeInTheDocument();
    expect(screen.queryByText("Running", { exact: true })).not.toBeInTheDocument();
    expect(newClose).toHaveBeenCalledTimes(1);
    expect(runPrompt).toHaveBeenCalledTimes(2);
  });

});
