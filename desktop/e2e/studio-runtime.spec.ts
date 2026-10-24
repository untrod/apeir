/** Actual CLI/HTTP/Chromium integration; explicit model-disabled scope, no native claim. */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createServer } from "node:net";

const token = "APEIR_FAKE_ONLY_STUDIO_BROWSER_9342";
const producers: ChildProcess[] = [];
const runtimes: Array<{ process: ChildProcess; directory: string; url: string }> = [];

async function port() {
  const server = createServer();
  await new Promise<void>(resolve => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Loopback port unavailable");
  await new Promise<void>(resolve => server.close(() => resolve()));
  return address.port;
}

test.beforeAll(async () => {
  for (let i = 0; i < 2; i++) {
    const directory = await mkdtemp(join(tmpdir(), "apeir-studio-e2e-"));
    await writeFile(join(directory, "example.py"), "def add(a, b):\n    return a + b\n");
    const selected = await port();
    const process = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "runtime-api", "start", "--port", String(selected)], {
      cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: directory, NOUS_API_TOKEN: token }, stdio: "ignore",
    });
    process.on("error", () => {});
    const runtime = { process, directory, url: `http://127.0.0.1:${selected}` }; runtimes.push(runtime);
    await expect.poll(async () => {
      if (process.exitCode !== null) throw new Error("Owned Runtime exited before readiness");
      try { return (await fetch(`${runtime.url}/api/v1/status`, { headers: { Authorization: `Bearer ${token}` } })).ok; } catch { return false; }
    }, { message: "Actual model-disabled Runtime startup", timeout: 10000 }).toBe(true);
  }
});
test.afterAll(async () => {
  const failures: string[] = [];
  for (const process of [...producers, ...runtimes.map(runtime => runtime.process)]) {
    if (process.exitCode === null && process.signalCode === null) {
      const completed = await new Promise<boolean>(resolve => {
        const timeout = setTimeout(() => resolve(false), 5000);
        process.once("exit", () => { clearTimeout(timeout); resolve(true); });
        process.kill("SIGTERM");
      });
      if (!completed) {
        const exited = new Promise<void>(resolve => process.once("exit", () => resolve()));
        process.kill("SIGKILL"); await exited;
        failures.push("Owned Runtime failed normal test teardown");
      }
    }
  }
  for (const runtime of runtimes) await rm(runtime.directory, { recursive: true, force: true });
  expect(failures).toEqual([]);
});

async function open(page: Page) {
  await page.addInitScript(({ url, token }) => {
    sessionStorage.setItem("nous_server_url", url); sessionStorage.setItem("nous_server_token", token);
  }, { url: runtimes[0].url, token });
  await page.goto("/");
  await page.getByRole("button", { name: /APEIR Studio/ }).click();
  await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
}

async function workspaceMenu(page: Page) {
  const summary = page.getByLabel("Workspace menu", { exact: true });
  if (!(await summary.evaluate(node => (node.parentElement as HTMLDetailsElement).open))) await summary.click();
}
async function dashboardMenu(page: Page) {
  const summary = page.getByLabel("Dashboard options", { exact: true });
  if (!(await summary.evaluate(node => (node.parentElement as HTMLDetailsElement).open))) await summary.click();
}

test("Studio restores safe layouts, preserves drafts while docking and isolates Controller changes", async ({ page }, info) => {
  const errors: string[] = []; const mutations: string[] = []; let fileReads = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!request.url().includes("/api/")) return;
    if (!["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url());
    if (request.url().includes("developer/workspace/file")) fileReads++;
  });
  await open(page);
  await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("software");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  const saved = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(saved);
  await page.getByRole("button", { name: /example.py/ }).click();
  const editor = page.getByRole("textbox", { name: "Code editor", exact: true });
  await editor.fill("PRIVATE_DRAFT_CONTROLLER_A"); const originalReads = fileReads;
  await page.getByRole("button", { name: "Edit layout", exact: true }).click();
  await page.locator(".flexlayout__tab_button").filter({ hasText: "Workspace Editor" }).first().dragTo(page.locator(".flexlayout__tab_button").filter({ hasText: "Chat" }).first());
  await expect(editor).toHaveValue("PRIVATE_DRAFT_CONTROLLER_A"); expect(fileReads).toBe(originalReads);
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page.getByText("Save or resolve protected editor drafts", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: /Operations Console/ }).click();
  await page.getByText("Controller connection", { exact: true }).click();
  await page.getByRole("textbox", { name: "API URL" }).fill(runtimes[1].url);
  await page.getByLabel("Service session token", { exact: true }).fill(token);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Controller connection changed.", { exact: false })).toBeVisible();
  expect(await page.content()).not.toContain("PRIVATE_DRAFT_CONTROLLER_A");
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("PRIVATE_DRAFT_CONTROLLER_A");
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export previous private drafts", exact: true }).click();
  const file = await downloaded; const path = await file.path();
  expect(await readFile(path!, "utf8")).toContain("PRIVATE_DRAFT_CONTROLLER_A");
  await page.screenshot({ path: info.outputPath("studio-controller-isolation-source-browser.png"), fullPage: true });
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("EventStream widgets retain their authenticated workspace owner across Controller changes", async ({ page }, info) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  for (const [index, runtime] of runtimes.entries()) {
    // Trusted test producer, separate process. This is diagnostic fixture data, not Work evidence.
    const producer = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-c", `from nous_runtime.events.bus import get_event_bus; b=get_event_bus(); b.publish("qualification.workspace-${index}"); b.shutdown()`], { cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: runtime.directory }, stdio: "ignore" });
    producers.push(producer);
    const exit = await new Promise<number | null>((resolve, reject) => {
      const timer = setTimeout(() => { producer.kill("SIGTERM"); reject(new Error("Owned diagnostic producer startup deadline exceeded")); }, 10000);
      producer.once("error", error => { clearTimeout(timer); reject(error); });
      producer.once("exit", code => { clearTimeout(timer); resolve(code); });
    });
    expect(exit).toBe(0);
  }
  await open(page); await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("blank");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
  await page.getByRole("button", { name: /Dashboard/ }).click();
  await page.getByRole("button", { name: "Edit layout", exact: true }).click();
  await page.getByRole("combobox", { name: "Widget type", exact: true }).selectOption("events");
  await page.getByRole("button", { name: "Add widget", exact: true }).click();
  await expect(page.getByText("qualification.workspace-0", { exact: false })).toBeVisible();
  await expect(page.getByText("qualification.workspace-1", { exact: false })).toHaveCount(0);
  await dashboardMenu(page);
  await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: /Operations Console/ }).click();
  await page.getByText("Controller connection", { exact: true }).click();
  await page.getByRole("textbox", { name: "API URL" }).fill(runtimes[1].url);
  await page.getByLabel("Service session token", { exact: true }).fill(token);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Controller connection changed.", { exact: false })).toBeVisible();
  await expect(page.getByText("qualification.workspace-1", { exact: false })).toBeVisible();
  await expect(page.getByText("qualification.workspace-0", { exact: false })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("studio-event-workspace-owner-source-browser.png"), fullPage: true });
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("malicious layouts fail closed and missing components never load executable code", async ({ page }, info) => {
  const mutations: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page);
  const layout = { schemaVersion: 1, kind: "workspace", name: "Example", locale: "en", layout: { type: "row", id: "root", children: [{ type: "tabset", id: "g", children: [{ type: "tab", id: "p", component: "example.telemetry" }] }] } };
  const input = page.getByLabel("Import Studio layout", { exact: true });
  await input.setInputFiles({ name: "rejected.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({ ...layout, token: "FAKE_UNTRUSTED_FIELD" })) });
  await expect(page.getByText("Unsupported or sensitive layout field.", { exact: false })).toBeVisible();
  await input.setInputFiles({ name: "missing.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(layout)) });
  await expect(page.getByText("Missing Component / 缺失组件", { exact: true })).toBeVisible();
  await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Studio theme" }).selectOption("dark");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("studio-mobile-dark-source-browser.png"), fullPage: true });
  expect(mutations).toEqual([]);
});

test("Dashboard uses real Runtime reads, moves/resizes widgets and restores safe settings", async ({ page }, info) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page);
  await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("blank");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
  await page.getByRole("button", { name: /Dashboard/ }).click();
  await expect(page.getByRole("region", { name: "Dashboard builder" })).toBeVisible();
  await page.getByRole("button", { name: "Edit layout", exact: true }).click();
  // A pre-polish version-1 Dashboard keeps its exact six-row geometry.
  const legacy = { schemaVersion: 1, kind: "dashboard", name: "Legacy Dashboard", locale: "en", layout: { type: "row", id: "root", children: [{ type: "tabset", id: "g", children: [{ type: "tab", id: "p", component: "dashboard", config: { schemaVersion: 1, widgets: ["runtime", "kernel", "nodes", "works", "usage", "evidence"].map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: (i % 3) * 4, y: Math.floor(i / 3) * 6, w: 4, h: 6, paused: false })) } }] }] } };
  await page.getByLabel("Import dashboard", { exact: true }).setInputFiles({ name: "legacy.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(legacy)) });
  await expect(page.locator('[data-widget-id="widget-1"] [data-state="ONLINE"]')).toBeVisible();
  await expect(page.getByText("No records reported", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Settings Nodes", exact: true }).click();
  await page.getByRole("textbox", { name: "Widget title" }).fill("My authorized nodes");
  await page.getByRole("spinbutton", { name: "Widget w", exact: true }).fill("5");
  await expect(page.getByRole("alert")).toContainText("bounds"); // x=8,w=5 cannot fit the 12-column grid.
  await page.getByRole("spinbutton", { name: "Widget y", exact: true }).fill("12");
  await page.getByRole("spinbutton", { name: "Widget x", exact: true }).fill("0");
  await page.getByRole("spinbutton", { name: "Widget w", exact: true }).fill("5");
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  const handle = page.getByRole("button", { name: "Move Runtime", exact: true });
  const before = await handle.boundingBox(); expect(before).not.toBeNull();
  await handle.hover(); await page.mouse.down(); await page.mouse.move(before!.x + before!.width / 2 + 1000, before!.y + before!.height / 2, { steps: 12 }); await page.mouse.up();
  await expect.poll(async () => (await handle.boundingBox())!.x).toBeGreaterThan(before!.x + 400);
  const nodeResize = page.locator('[data-widget-id="widget-3"] .react-resizable-handle');
  await nodeResize.hover(); const corner = await nodeResize.boundingBox(); expect(corner).not.toBeNull();
  await page.mouse.down(); await page.mouse.move(corner!.x + 110, corner!.y + 60, { steps: 12 }); await page.mouse.up();
  await dashboardMenu(page);
  await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  const saved = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  const persisted = JSON.parse(saved!);
  const configurations: Array<{ widgets: Array<{ id: string; x: number; y: number; w: number; h: number }> }> = [];
  const visit = (node: { config?: { widgets: Array<{ id: string; x: number; y: number; w: number; h: number }> }; children?: unknown[] }) => { if (node.config) configurations.push(node.config); node.children?.forEach(child => visit(child as typeof node)); }; visit(persisted.layout);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-1")!.x).toBeGreaterThan(0);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-3")!.w).toBeGreaterThan(5);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-3")!.h).toBeGreaterThan(6);
  expect(saved).toContain("My authorized nodes"); expect(saved).not.toContain(token);
  await dashboardMenu(page);
  const downloaded = page.waitForEvent("download"); await page.getByRole("button", { name: "Export dashboard", exact: true }).click();
  const file = await downloaded; const path = await file.path(); const exported = await readFile(path!, "utf8");
  expect(JSON.parse(exported).kind).toBe("dashboard");
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  await expect(page.getByRole("button", { name: "Move My authorized nodes", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Edit layout", exact: true }).click();
  await expect(page.getByRole("button", { name: "Move My authorized nodes", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(saved);
  await page.getByLabel("Import dashboard", { exact: true }).setInputFiles({ name: "dashboard.json", mimeType: "application/json", buffer: Buffer.from(exported) });
  await expect(page.getByText("Dashboard imported. No Runtime operation was executed.", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Widget type", exact: true }).selectOption("gpu");
  await page.getByRole("button", { name: "Add widget", exact: true }).click();
  await expect(page.getByText("No metric source", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Settings GPU Metrics", exact: true }).click();
  await page.getByRole("checkbox", { name: "Pause display", exact: true }).check();
  await expect(page.getByText("Updates paused", { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("studio-dashboard-real-runtime-source-browser.png"), fullPage: true });
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("named templates and Workspace layouts persist without crossing Controller scope", async ({ page }, info) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page);
  await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("network");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Layout library", exact: true }).click();
  const library = page.getByRole("dialog", { name: "Saved layout library", exact: true });
  await library.getByRole("combobox", { name: "Layout scope", exact: true }).selectOption("workspace");
  await library.getByRole("textbox", { name: "Layout name", exact: true }).fill("Workspace A layout");
  await library.getByRole("button", { name: "Save current as new", exact: true }).click();
  await expect(library.getByRole("button", { name: "Workspace A layout · workspace", exact: true })).toBeVisible();
  const original = await page.evaluate(() => localStorage.getItem("apeir.studio.library.v1"));
  expect(original).not.toContain(runtimes[0].directory); expect(original).not.toContain(token); expect(original).not.toContain(runtimes[0].url);
  const workspaceA = JSON.parse(original!).entries[0].scope.workspace;
  await library.getByRole("combobox", { name: "Layout scope", exact: true }).selectOption("template");
  await library.getByRole("textbox", { name: "Layout name", exact: true }).fill("Reusable template");
  await library.getByRole("button", { name: "Save current as new", exact: true }).click();
  await expect(library.getByRole("button", { name: "Reusable template · template", exact: true })).toBeVisible();
  await library.getByRole("button", { name: "Duplicate selected", exact: true }).click();
  await expect(library.getByRole("button", { name: "Reusable template copy · template", exact: true })).toBeVisible();
  await library.getByRole("textbox", { name: "Layout name", exact: true }).fill("Renamed template");
  await library.getByRole("button", { name: "Rename selected", exact: true }).click();
  await expect(library.getByRole("button", { name: "Renamed template · template", exact: true })).toBeVisible();
  const download = page.waitForEvent("download"); await library.getByRole("button", { name: "Export selected", exact: true }).click();
  const exportedFile = await download; const exported = JSON.parse(await readFile((await exportedFile.path())!, "utf8"));
  expect(exported.kind).toBe("template"); expect(exported.name).toBe("Renamed template"); expect(JSON.stringify(exported)).not.toContain(workspaceA);
  await library.getByRole("button", { name: "Load selected", exact: true }).click();
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.layout.v1")!).name)).toBe("Renamed template");
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: /Operations Console/ }).click();
  await page.getByText("Controller connection", { exact: true }).click();
  await page.getByRole("textbox", { name: "API URL" }).fill(runtimes[1].url);
  await page.getByLabel("Service session token", { exact: true }).fill(token);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Controller connection changed.", { exact: false })).toBeVisible();
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Layout library", exact: true }).click();
  await expect(library.getByRole("button", { name: "Workspace A layout · workspace", exact: true })).toHaveCount(0);
  await expect(library.getByRole("button", { name: "Renamed template · template", exact: true })).toBeVisible();
  await library.getByRole("combobox", { name: "Layout scope", exact: true }).selectOption("workspace");
  await library.getByRole("textbox", { name: "Layout name", exact: true }).fill("Workspace B layout");
  await library.getByRole("button", { name: "Save current as new", exact: true }).click();
  await expect(library.getByRole("button", { name: "Workspace B layout · workspace", exact: true })).toBeVisible();
  const records = await page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.library.v1")!).entries);
  expect(records.find((entry: { document: { name: string } }) => entry.document.name === "Workspace B layout").scope.workspace).not.toBe(workspaceA);
  expect(records.find((entry: { document: { name: string } }) => entry.document.name === "Workspace A layout").scope.workspace).toBe(workspaceA);
  await expect(library.getByRole("button", { name: "Workspace A layout · workspace", exact: true })).toHaveCount(0);
  const other = await page.context().newPage();
  other.on("pageerror", error => errors.push(error.message));
  other.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(other); await workspaceMenu(other); await other.getByRole("button", { name: "Layout library", exact: true }).click();
  const otherLibrary = other.getByRole("dialog", { name: "Saved layout library", exact: true });
  await otherLibrary.getByRole("textbox", { name: "Layout name", exact: true }).fill("Concurrent global layout");
  await otherLibrary.getByRole("button", { name: "Save current as new", exact: true }).click();
  await expect(otherLibrary.getByRole("button", { name: "Concurrent global layout · global", exact: true })).toBeVisible();
  await expect(library.getByText("Library changed in another window.", { exact: false })).toBeVisible();
  await library.getByRole("button", { name: "Rename selected", exact: true }).click();
  await expect(library.getByText("Library changed in another window.", { exact: false })).toBeVisible();
  await library.getByRole("button", { name: "Reload library", exact: true }).click();
  await expect(library.getByRole("button", { name: "Concurrent global layout · global", exact: true })).toBeVisible();
  await expect(library.getByRole("button", { name: "Workspace B layout · workspace", exact: true })).toBeVisible();
  await other.close();
  await page.screenshot({ path: info.outputPath("studio-layout-library-source-browser.png"), fullPage: true });
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("Studio keeps the everyday view compact and layout editing explicit across themes and small screens", async ({ page }, info) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page); await workspaceMenu(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("blank");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await page.getByRole("button", { name: "Add panel", exact: true }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  const dashboard = page.getByRole("region", { name: "Dashboard builder" });
  await expect(dashboard.locator('[data-state="ONLINE"]')).toBeVisible();
  await expect(dashboard.locator('[data-state="UNCONFIGURED"]')).toBeVisible();
  await expect(dashboard.getByText("No model requests yet", { exact: true })).toBeVisible();
  await expect(dashboard.getByRole("button", { name: /Settings|Remove|Move / })).toHaveCount(0);
  await expect(page.locator(".studio-toolbar-actions > button")).toHaveCount(2);
  await workspaceMenu(page); await page.getByRole("button", { name: "Save layout", exact: true }).click();
  const original = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  expect(original).toContain('"h":4');
  await page.keyboard.press("Escape");
  const card = dashboard.locator('[data-widget-id="widget-1"]');
  const before = await card.boundingBox(); expect(before).not.toBeNull();
  await card.locator("header").hover(); await page.mouse.down(); await page.mouse.move(before!.x + 300, before!.y + 100, { steps: 8 }); await page.mouse.up();
  const after = await card.boundingBox(); expect(after!.x).toBe(before!.x); expect(after!.y).toBe(before!.y);
  await workspaceMenu(page); await page.getByRole("button", { name: "Save layout", exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(original);
  for (const theme of ["light", "dark"]) {
    await workspaceMenu(page); await page.getByRole("combobox", { name: "Studio theme" }).selectOption(theme);
    await page.keyboard.press("Escape");
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await expect.poll(() => page.getByRole("button", { name: "Edit layout", exact: true }).evaluate(node => {
      const probe = document.createElement("span"); probe.style.backgroundColor = "var(--nous-surface)"; document.body.appendChild(probe);
      const expected = getComputedStyle(probe).backgroundColor; probe.remove();
      return getComputedStyle(node).backgroundColor === expected;
    })).toBe(true);
    const contrasts = await dashboard.locator(".studio-service-state .studio-status").evaluateAll(nodes => {
      const rgb = (color: string) => { const values = color.match(/[\d.]+/g)!.map(Number); return color.startsWith("color(") ? values.slice(0, 3) : values.slice(0, 3).map(value => value / 255); };
      const luminance = (values: number[]) => values.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0);
      return nodes.map(node => { const foreground = luminance(rgb(getComputedStyle(node).color)); const background = luminance(rgb(getComputedStyle(node.closest(".studio-widget")!).backgroundColor)); return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05); });
    });
    expect(contrasts.length).toBe(2); expect(contrasts.every(ratio => ratio >= 4.5)).toBe(true);
    await page.screenshot({ path: info.outputPath(`studio-overview-${theme}-source-browser.png`), fullPage: true, animations: "disabled" });
  }
  await page.keyboard.press("Control+Alt+l");
  await expect(page.getByRole("button", { name: "Done editing", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Settings Runtime", exact: true }).focus();
  expect(await page.getByRole("button", { name: "Settings Runtime", exact: true }).evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Enter"); await expect(page.getByRole("form", { name: "Widget settings" })).toBeVisible();
  await page.keyboard.press("Escape"); await expect(page.getByRole("form", { name: "Widget settings" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Done editing", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("Control+Alt+l"); await expect(page.getByRole("form", { name: "Widget settings" })).toHaveCount(0);
  await workspaceMenu(page); await page.getByRole("combobox", { name: "Studio language" }).selectOption("zh");
  await page.getByRole("button", { name: "保存布局", exact: true }).click(); await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "编辑布局", exact: true })).toBeVisible();
  await expect(dashboard.getByText("尚无模型请求", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(card).toHaveCSS("position", "relative");
  await expect.poll(async () => { const bounds = await dashboard.locator(".studio-widget").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect())); return bounds.every(bounds => bounds.x >= 0 && bounds.right <= 390); }).toBe(true);
  await page.screenshot({ path: info.outputPath("studio-overview-zh-small-source-browser.png"), fullPage: true, animations: "disabled" });
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  await expect(page.getByRole("button", { name: "编辑布局", exact: true })).toBeVisible();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.layout.v1")!).schemaVersion)).toBe(1);
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("Studio retains readable controls at browser 2x DPI with touch and keyboard access", async ({ browser }, info) => {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, hasTouch: true });
  const page = await context.newPage(); const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  try {
    await open(page); await workspaceMenu(page);
    await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("blank");
    await page.getByRole("button", { name: "Apply preset", exact: true }).click();
    const add = page.getByRole("button", { name: "Add panel", exact: true });
    expect((await add.boundingBox())!.height).toBeGreaterThanOrEqual(40);
    await add.focus(); await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Edit layout", exact: true })).toBeFocused();
    await page.keyboard.press("Control+Shift+p");
    await expect(page.getByRole("textbox", { name: "Search panels" })).toBeFocused();
    await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    await expect(page.locator('[data-widget-id="widget-1"] [data-state="ONLINE"]')).toBeVisible();
    await page.screenshot({ path: info.outputPath("studio-overview-2x-touch-source-browser.png"), fullPage: true, animations: "disabled" });
    expect(errors).toEqual([]); expect(mutations).toEqual([]);
  } finally { await context.close(); }
});
