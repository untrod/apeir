import { describe, expect, it } from "vitest";
import { Model } from "flexlayout-react";
import { compactDashboard, defaultDashboard, validateDashboard, upgradeDashboard, moveDashboardWidget } from "../lib/studioDashboard";
import { captureStudioLayout, createStudioLayout, parseStudioLayout, studioModel } from "../lib/studioLayout";

const layout = (config: unknown) => {
  const source = createStudioLayout("blank"); source.kind = "dashboard";
  source.layout.children = [{ type: "tabset", id: "group", children: [{ type: "tab", id: "panel", component: "dashboard", config }] }];
  return source;
};
it("keeps legacy implicit geometry while making only newly created dashboards compact", () => {
  expect(defaultDashboard().widgets.every(widget => widget.h === 6)).toBe(true);
  const compact = compactDashboard();
  expect(compact.widgets.every(widget => widget.h === 4)).toBe(true);
  expect(validateDashboard(compact)).toEqual(compact);
  const legacy = layout(undefined); delete (legacy.layout.children![0] as { children: Array<{ config?: unknown }> }).children[0].config;
  expect(parseStudioLayout(JSON.stringify(legacy))).toEqual(legacy);
  const network = createStudioLayout("network");
  expect(JSON.stringify(network)).toContain('"type":"topology"');
  expect(JSON.stringify(network)).toContain('"type":"resources"');
});

describe("Dashboard shares the bounded Studio presentation contract", () => {
  it("preserves exact widget identities, settings and positions through the real dock model", () => {
    const config = defaultDashboard(); config.widgets[0] = { ...config.widgets[0], title: "User layout", paused: true, x: 2, y: 12, w: 6 };
    const original = layout(config);
    const saved = captureStudioLayout(Model.fromJson(studioModel(original)).toJson(), original);
    expect(parseStudioLayout(JSON.stringify(saved))).toEqual(original);
    expect(JSON.stringify(saved)).not.toMatch(/token|permission|credential|grant|work_id|node_id/);
  });
  it.each(["credential", "token", "url", "permission", "script", "data", "node_id", "__proto__"])("rejects nested %s rather than rendering or persisting it", key => {
    const json = JSON.stringify(defaultDashboard()).replace('"schemaVersion":1', `"${key}":"untrusted","schemaVersion":1`);
    expect(() => parseStudioLayout(JSON.stringify(layout(JSON.parse(json))))).toThrow(/sensitive/);
  });
  it("rejects credentials, capabilities and executable entries in individual widgets", () => {
    const config = defaultDashboard();
    Object.assign(config.widgets[0], { entry: "https://untrusted.invalid/widget.js", permissions: ["shell"] });
    expect(() => validateDashboard(config)).toThrow(/sensitive/);
  });
  it.each([{ x: 4 }, { x: -1 }, { x: 11, w: 2 }, { y: 199 }, { y: NaN }, { h: 31 }, { w: Infinity }, { id: "../../module.js" }, { paused: "yes" }, { type: "https://untrusted.invalid" }])("rejects invalid widget bounds or types %j", fields => {
    const config = defaultDashboard(); Object.assign(config.widgets[0], fields);
    expect(() => validateDashboard(config)).toThrow();
  });
  it("bounds count, preserves unknown types as missing, rejects identity collisions", () => {
    const config = defaultDashboard(); config.widgets[0].type = "example.telemetry";
    expect(validateDashboard(config).widgets[0].type).toBe("example.telemetry");
    config.widgets[1].id = config.widgets[0].id;
    expect(() => validateDashboard(config)).toThrow(/duplicate/);
    expect(() => validateDashboard({ schemaVersion: 1, widgets: Array.from({ length: 33 }, () => config.widgets[0]) })).toThrow(/limit/);
  });
  it("does not admit Dashboard configuration into an executable or unknown panel", () => {
    const source = JSON.stringify(layout(defaultDashboard()));
    expect(() => parseStudioLayout(source.replace('"component":"dashboard"', '"component":"editor"'))).toThrow(/does not accept/);
  });
});


describe("Overview v2 presentation compatibility", () => {
  it("upgrades explicitly, retaining every v1 widget identity, position and size", () => {
    const legacy = defaultDashboard(), original = structuredClone(legacy);
    const upgraded = upgradeDashboard(legacy, "professional");
    expect(legacy).toEqual(original);
    expect(upgraded.widgets).toEqual(legacy.widgets);
    upgraded.widgets[0].presentation = { density: "compact", accent: "info", icon: "tasks", style: "plain" };
    const source = layout(upgraded);
    const saved = captureStudioLayout(Model.fromJson(studioModel(source)).toJson(), source);
    expect(parseStudioLayout(JSON.stringify(saved))).toEqual(source);
    expect(validateDashboard(legacy).schemaVersion).toBe(1);
    expect(upgraded.schemaVersion).toBe(2);
  });
  it.each(["credential", "script", "endpoint", "permission", "source", "html", "__proto__"])("refuses sensitive or executable widget setting %s", key => {
    const value = upgradeDashboard(defaultDashboard());
    value.widgets[0].presentation = JSON.parse(`{"${key}":"untrusted"}`);
    expect(() => validateDashboard(value)).toThrow(/sensitive/);
  });
  it.each([{ density: "tiny" }, { accent: "#bad" }, { icon: "<script>" }, { style: "javascript" }, { sort: "price" }])("refuses unsupported presentation values %j", presentation => {
    const value = upgradeDashboard(defaultDashboard());
    Object.assign(value.widgets[0], { presentation });
    expect(() => validateDashboard(value)).toThrow();
  });
  it("rejects implicit v1 presentation, unknown modes, and accidental overlap from keyboard input", () => {
    const legacy = defaultDashboard(); legacy.widgets[0].presentation = { density: "compact" };
    expect(() => validateDashboard(legacy)).toThrow(/sensitive/);
    delete legacy.widgets[0].presentation;
    expect(() => validateDashboard({ ...upgradeDashboard(legacy), mode: "execute" })).toThrow(/mode/);
    expect(() => moveDashboardWidget(legacy, "widget-1", "ArrowRight")).toThrow(/overlap/);
    const value = validateDashboard({ schemaVersion: 2, mode: "simple", widgets: [legacy.widgets[0]] });
    const moved = moveDashboardWidget(value, "widget-1", "ArrowRight");
    const resized = moveDashboardWidget(moved, "widget-1", "ArrowDown", true);
    expect(resized.widgets[0]).toMatchObject({ id: "widget-1", x: 1, w: 4, h: 7 });
    expect(resized.schemaVersion).toBe(2); expect(value.widgets[0].x).toBe(0);
  });
});

it("retains bounded accounting presentation through layout capture without granting data access", () => {
  const value = upgradeDashboard(compactDashboard(["usage", "cache"]));
  value.widgets[0].presentation = { day: "2000-02-29", fields: ["tokens", "unknown_cost"] };
  const parsed = validateDashboard(value);
  expect(parseStudioLayout(JSON.stringify(layout(parsed)))).toEqual(layout(parsed));
  parsed.widgets[0].presentation!.fields!.push("requests");
  expect(value.widgets[0].presentation!.fields).toEqual(["tokens", "unknown_cost"]);
  for (const fields of [[], ["tokens", "tokens"], ["credential"], "cost"]) {
    const invalid = structuredClone(value); Object.assign(invalid.widgets[0].presentation!, { fields });
    expect(() => validateDashboard(invalid)).toThrow(/fields/);
  }
  for (const day of ["2001-02-29", "2000-13-01", "https://example.invalid", "9999-01-01", "1969-01-01"]) {
    const invalid = structuredClone(value); invalid.widgets[0].presentation!.day = day;
    expect(() => validateDashboard(invalid)).toThrow(/UTC/);
  }
  value.widgets[0].type = "nodes";
  expect(() => validateDashboard(value)).toThrow(/UTC/);
});
