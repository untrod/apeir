import { describe, expect, it } from "vitest";
import { Actions, DockLocation, Model, TabNode } from "flexlayout-react";
import { captureStudioLayout, createStudioLayout, discardsProtectedPanel, dockStudioTab, focusStudioTab, loadStudioLayout, MAX_LAYOUT_BYTES, parseStudioLayout, STUDIO_TEMPLATES, studioModel } from "../lib/studioLayout";

describe("Studio presentation schema", () => {
  it("rejects grouped close actions that would discard a protected editor, while permitting moves", () => {
    const protectedIds = new Set(["draft"]);
    expect(discardsProtectedPanel(Actions.group([Actions.selectTab("other"), Actions.group([Actions.deleteTab("draft")])]), protectedIds)).toBe(true);
    expect(discardsProtectedPanel(Actions.deleteTab("other"), protectedIds)).toBe(false);
    expect(discardsProtectedPanel(Actions.moveNode("draft", "group", DockLocation.RIGHT, -1), protectedIds)).toBe(false);
  });
  it.each(Object.keys(STUDIO_TEMPLATES))("roundtrips actual FlexLayout model for %s", preset => {
    const original = createStudioLayout(preset);
    const model = Model.fromJson(studioModel(original));
    const saved = captureStudioLayout(model.toJson(), original);
    expect(parseStudioLayout(JSON.stringify(saved))).toEqual(saved);
    model.visitNodes(node => { if (node instanceof TabNode) { expect(node.isEnablePopout()).toBe(false); expect(node.isEnableFloat()).toBe(false); } });
  });
  it("preserves stable panel identity through horizontal/vertical moves, resize and maximize", () => {
    const source = createStudioLayout("software"); const model = Model.fromJson(studioModel(source));
    model.doAction(Actions.moveNode("panel-1", "group-1", DockLocation.BOTTOM, -1));
    model.doAction(Actions.maximizeToggle("group-1"));
    const saved = captureStudioLayout(model.toJson(), source);
    const reloaded = Model.fromJson(studioModel(parseStudioLayout(JSON.stringify(saved))));
    expect(reloaded.getNodeById("panel-1")?.getType()).toBe("tab");
    expect(JSON.stringify(saved)).not.toMatch(/permissions|session|token|url|config|extraData/);
  });
  it("reveals an existing tab behind a maximized sibling without making a new instance", () => {
    const model = Model.fromJson(studioModel(createStudioLayout()));
    model.doAction(Actions.maximizeToggle("group-1"));
    focusStudioTab(model, "panel-1");
    expect(model.getMaximizedTabset()).toBeUndefined();
    expect(model.getActiveTabset()?.getSelectedNode()?.getId()).toBe("panel-1");
    let count = 0; model.visitNodes(node => { if (node instanceof TabNode) count++; });
    expect(count).toBe(4);
  });
  it.each(["left", "right", "top", "bottom"] as const)("snaps to the %s edge, preserving every panel and the v1 schema", side => {
    const original = createStudioLayout(); const model = Model.fromJson(studioModel(original));
    const tab = model.getNodeById("panel-1");
    model.doAction(Actions.maximizeToggle("group-0"));
    dockStudioTab(model, "panel-1", side);
    expect(model.getMaximizedTabset()).toBeUndefined();
    expect(model.getNodeById("panel-1")).toBe(tab);
    const saved = captureStudioLayout(model.toJson(), original);
    expect(parseStudioLayout(JSON.stringify(saved))).toEqual(saved);
    expect(JSON.stringify(saved).match(/"component"/g)).toHaveLength(4);
  });
  it.each(["token", "credential", "grant", "permissions", "url", "__proto__", "constructor"])("rejects untrusted %s rather than forwarding it to FlexLayout", key => {
    const json = JSON.stringify(createStudioLayout());
    const malicious = json.replace('"schemaVersion":1', `"${key}":"untrusted","schemaVersion":1`);
    expect(() => parseStudioLayout(malicious)).toThrow(/Unsupported or sensitive/);
  });
  it("rejects script/module configuration nested in a panel", () => {
    const value = createStudioLayout();
    const model = studioModel(value);
    const panel = model.layout.children?.[0];
    expect(panel?.type).toBe("tabset");
    (panel as Record<string, unknown>).config = { entry: "javascript:untrusted" };
    expect(() => parseStudioLayout(JSON.stringify(value))).toThrow();
  });
  it("retains missing component references without resolving or loading any code", () => {
    const source = JSON.stringify(createStudioLayout()).replace('"component":"chat"', '"component":"example.telemetry"');
    expect(JSON.stringify(parseStudioLayout(source))).toContain("example.telemetry");
  });
  it("rejects duplicate identities, nonfinite sizes, excess input and unsupported versions", () => {
    const source = JSON.stringify(createStudioLayout());
    expect(() => parseStudioLayout(source.replace('"panel-2"', '"panel-1"'))).toThrow(/duplicate/);
    expect(() => parseStudioLayout(source.replace('"weight":65', '"weight":1e999'))).toThrow(/size/);
    expect(() => parseStudioLayout(" ".repeat(MAX_LAYOUT_BYTES + 1))).toThrow(/96 KiB/);
    expect(() => parseStudioLayout(source.replace('"schemaVersion":1', '"schemaVersion":900'))).toThrow(/schema/);
  });
  it("migrates presentation from the old Operations preference without deleting it or reading drafts", () => {
    localStorage.clear();
    const old = JSON.stringify({ tabs: ["works", "workspace"], locale: "zh" });
    localStorage.setItem("apeir.operations.layout.v1", old);
    localStorage.setItem("apeir.developer.panel.v1", '{"fontSize":18}');
    const next = loadStudioLayout(localStorage);
    expect(next.name).toBe("Software Development"); expect(next.locale).toBe("zh");
    expect(localStorage.getItem("apeir.operations.layout.v1")).toBe(old);
    expect(localStorage.getItem("apeir.developer.panel.v1")).toBe('{"fontSize":18}');
    expect(JSON.stringify(next)).not.toContain("fontSize");
  });
});
