import { describe, expect, it } from "vitest";
import { Model } from "flexlayout-react";
import { compactDashboard, defaultDashboard, validateDashboard } from "../lib/studioDashboard";
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
