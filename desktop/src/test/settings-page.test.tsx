import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { SettingsPage } from "../components/SettingsPage";
import { LOCALE_STORAGE_KEY, readAppLocale, ThemeProvider } from "../theme";

beforeEach(() => localStorage.clear());

it("adopts the previous Studio language without altering the original layout", () => {
  const original = '{"schemaVersion":1,"locale":"zh","layout":{"id":"original"}}';
  localStorage.setItem("apeir.studio.layout.v1", original);
  expect(readAppLocale(localStorage)).toBe("zh");
  expect(localStorage.getItem("apeir.studio.layout.v1")).toBe(original);
  localStorage.setItem(LOCALE_STORAGE_KEY, "en");
  expect(readAppLocale(localStorage)).toBe("en");
});

it("preserves rejected layout bytes and understands the existing native wizard language", () => {
  localStorage.setItem("apeir.studio.layout.v1", "unreadable-original");
  localStorage.setItem("nous_language", "zh-CN");
  expect(readAppLocale(localStorage)).toBe("zh");
  expect(localStorage.getItem("apeir.studio.layout.v1")).toBe("unreadable-original");
});

it("keeps application preferences when an imported layout has another locale", () => {
  localStorage.setItem(LOCALE_STORAGE_KEY, "en");
  render(<ThemeProvider><SettingsPage /></ThemeProvider>);
  fireEvent.change(screen.getByLabelText("Studio language"), { target: { value: "zh" } });
  expect(screen.getByRole("heading", { name: "设置" })).toBeInTheDocument();
  expect(localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("zh");
  localStorage.setItem("apeir.studio.layout.v1", '{"locale":"en"}');
  expect(readAppLocale(localStorage)).toBe("zh");
  fireEvent.change(screen.getByLabelText("Studio theme"), { target: { value: "dark" } });
  expect(screen.getByLabelText("Studio theme")).toHaveValue("dark");
  expect(document.documentElement.lang).toBe("zh-CN");
});

it("offers the original credential boundary only on demand and blocks a protected UI reset", () => {
  const reset = vi.spyOn(window, "confirm");
  render(<ThemeProvider><SettingsPage hasProtectedChanges={() => true} /></ThemeProvider>);
  expect(screen.queryByRole("button", { name: "Store or Rotate" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "Advanced" }));
  expect(screen.getByRole("button", { name: "Reset…" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reset…" }));
  expect(reset).not.toHaveBeenCalled();
  reset.mockRestore();
});
