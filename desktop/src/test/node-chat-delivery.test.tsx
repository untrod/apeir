import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatView } from "../components/ChatView";
import { entityStore } from "../store/entityStore";

vi.mock("../components/Markdown", () => ({ Markdown: ({ content }: { content: string }) => <span>{content}</span> }));

afterEach(() => {
  cleanup();
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
  entityStore.clearStore(); vi.unstubAllGlobals();
});

describe("shared Runtime publication in Chat", () => {
  it("does not scroll on a Node refresh, but follows actual message changes", async () => {
    entityStore.clearStore();
    const scroll = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scroll });
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    render(<ChatView readOnly onCardClick={vi.fn()} onTraceClick={vi.fn()} />);
    await screen.findByRole("heading", { name: "What would you like to work on?" });
    const initial = scroll.mock.calls.length;
    act(() => entityStore.upsertNodes([]));
    expect(scroll).toHaveBeenCalledTimes(initial);
    act(() => entityStore.upsertMessages([{
      id: "owned-message", conversation_id: "", session_id: "owned-session", role: "assistant",
      content: "Original recorded message", cards: [], schema_version: "1.0.0",
      created_at: "2099-01-01T00:00:00Z", updated_at: "2099-01-01T00:00:00Z",
    }]));
    expect(await screen.findByText("Original recorded message")).toBeInTheDocument();
    expect(scroll.mock.calls.length).toBeGreaterThan(initial);
    const afterMessage = scroll.mock.calls.length;
    act(() => entityStore.upsertMessages([{
      id: "owned-message", conversation_id: "", session_id: "owned-session", role: "assistant",
      content: "Updated recorded message", cards: [], schema_version: "1.0.0",
      created_at: "2099-01-01T00:00:00Z", updated_at: "2099-01-01T00:00:01Z",
    }]));
    expect(await screen.findByText("Updated recorded message")).toBeInTheDocument();
    expect(scroll.mock.calls.length).toBeGreaterThan(afterMessage);
    expect(fetch).not.toHaveBeenCalled();
  });
});
