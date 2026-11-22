import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    const box = screen.getByLabelText("Conversation messages");
    let top = 0;
    const localScroll = vi.fn((value: number) => { top = value; });
    Object.defineProperties(box, {
      scrollHeight: { configurable: true, value: 2000 },
      clientHeight: { configurable: true, value: 300 },
      scrollTop: { configurable: true, get: () => top, set: localScroll },
    });
    const initial = localScroll.mock.calls.length;
    act(() => entityStore.upsertNodes([]));
    expect(localScroll).toHaveBeenCalledTimes(initial);
    act(() => entityStore.upsertMessages([{
      id: "owned-message", conversation_id: "", session_id: "owned-session", role: "assistant",
      content: "Original recorded message", cards: [], schema_version: "1.0.0",
      created_at: "2099-01-01T00:00:00Z", updated_at: "2099-01-01T00:00:00Z",
    }]));
    expect(await screen.findByText("Original recorded message")).toBeInTheDocument();
    expect(localScroll.mock.calls.length).toBeGreaterThan(initial);
    const afterMessage = localScroll.mock.calls.length;
    act(() => entityStore.upsertMessages([{
      id: "owned-message", conversation_id: "", session_id: "owned-session", role: "assistant",
      content: "Updated recorded message", cards: [], schema_version: "1.0.0",
      created_at: "2099-01-01T00:00:00Z", updated_at: "2099-01-01T00:00:01Z",
    }]));
    expect(await screen.findByText("Updated recorded message")).toBeInTheDocument();
    expect(localScroll.mock.calls.length).toBeGreaterThan(afterMessage);
    expect(scroll).not.toHaveBeenCalled();
    top = 100; fireEvent.scroll(box);
    const reading = localScroll.mock.calls.length;
    act(() => entityStore.upsertMessages([{
      id: "newer-message", conversation_id: "", session_id: "owned-session", role: "assistant",
      content: "A later message must not move the reader", cards: [], schema_version: "1.0.0",
      created_at: "2099-01-01T00:00:02Z", updated_at: "2099-01-01T00:00:02Z",
    }]));
    expect(localScroll).toHaveBeenCalledTimes(reading);
    expect(top).toBe(100);;
    expect(fetch).not.toHaveBeenCalled();
  });
});
