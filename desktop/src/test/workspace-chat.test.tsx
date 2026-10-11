import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatView } from "../components/ChatView";
import { fetchRunEvents, runPrompt, setConfig, subscribeRunEvents } from "../lib/api";

vi.mock("../lib/api", async importOriginal => ({ ...await importOriginal<typeof import("../lib/api")>(),
  runPrompt: vi.fn(), fetchRunEvents: vi.fn(), subscribeRunEvents: vi.fn(),
}));
vi.mock("../store", () => ({
  entityStore: { upsertConversations: vi.fn(), upsertMessages: vi.fn() },
  useMessages: () => [], useActiveTasks: () => [], useModels: () => [], useNodes: () => [], useStoreHydrated: () => false,
}));
vi.mock("../components/Markdown", () => ({ Markdown: ({ content }: { content: string }) => <span>{content}</span> }));
vi.mock("../components/Composer", () => ({ Composer: ({ onSend, readOnly }: { onSend: (text: string, attachments: [], constraints: { agent_mode: string }) => void; readOnly: boolean }) =>
  <button onClick={() => onSend("Explain the selected file", [], { agent_mode: "agent" })}>{readOnly ? "Send read-only request" : "Send request"}</button> }));

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
