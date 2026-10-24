import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { StudioPanelSlot } from "../components/studio/StudioShell";

it("moving a panel's host preserves its unsaved React state without replaying mount work", () => {
  const mounted = vi.fn(); const disposed = vi.fn();
  function Editor() {
    const [draft, setDraft] = useState("");
    useEffect(() => { mounted(); return disposed; }, []);
    return <input aria-label="Private draft" value={draft} onChange={event => setDraft(event.target.value)} />;
  }
  const host = document.createElement("div");
  function Workspace({ group }: { group: string }) {
    return <><StudioPanelSlot key={group} host={host} />{createPortal(<Editor />, host, "stable-instance")}</>;
  }
  const view = render(<Workspace group="left" />);
  fireEvent.change(screen.getByLabelText("Private draft"), { target: { value: "unsaved content" } });
  view.rerender(<Workspace group="bottom" />);
  expect(screen.getByLabelText("Private draft")).toHaveValue("unsaved content");
  expect(mounted).toHaveBeenCalledTimes(1); expect(disposed).not.toHaveBeenCalled();
  view.unmount(); expect(disposed).toHaveBeenCalledTimes(1);
});
