import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { StudioLayoutLibrary } from "../components/studio/StudioLayoutLibrary";
import { createStudioLayout } from "../lib/studioLayout";
import { STUDIO_LIBRARY_KEY } from "../lib/studioLibrary";
import { setConfig } from "../lib/api";

beforeEach(() => { localStorage.clear(); });
it("a queued library write cannot outlive its Controller session or modify a new view", async () => {
  let finish!: () => Promise<void>;
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: vi.fn((_name: string, callback: () => unknown) => new Promise((resolve, reject) => { finish = async () => { try { resolve(await callback()); } catch (error) { reject(error); } }; })) } });
  setConfig({ url: "http://controller-a.invalid", token: "library.fake.a" });
  const props = { current: () => createStudioLayout(), load: vi.fn(), exportLayout: vi.fn(), close: vi.fn(), locale: "en" as const };
  const view = render(<StudioLayoutLibrary key="a" {...props} />);
  fireEvent.change(screen.getByRole("textbox", { name: "Layout name" }), { target: { value: "Private A layout" } });
  fireEvent.click(screen.getByRole("button", { name: "Save current as new" }));
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  setConfig({ url: "http://controller-b.invalid", token: "library.fake.b" });
  view.rerender(<StudioLayoutLibrary key="b" {...props} />);
  await act(async () => { await finish(); });
  expect(localStorage.getItem(STUDIO_LIBRARY_KEY)).toBeNull();
  expect(view.container.textContent).not.toContain("Private A layout");
  expect(screen.getByRole("textbox", { name: "Layout name" })).toHaveValue("General");
  expect(props.load).not.toHaveBeenCalled();
});

it("a rejected current layout stays diagnosable without crashing or replacing the library", async () => {
  const props = { current: () => { throw new Error("Layout exceeds 96 KiB."); }, load: vi.fn(), exportLayout: vi.fn(), close: vi.fn(), locale: "en" as const };
  render(<StudioLayoutLibrary {...props} />);
  expect(screen.getByRole("textbox", { name: "Layout name" })).toHaveValue("Layout");
  fireEvent.click(screen.getByRole("button", { name: "Save current as new" }));
  await waitFor(() => expect(screen.getByText("Error: Layout exceeds 96 KiB.")).toBeVisible());
  expect(localStorage.getItem(STUDIO_LIBRARY_KEY)).toBeNull(); expect(props.load).not.toHaveBeenCalled();
});
