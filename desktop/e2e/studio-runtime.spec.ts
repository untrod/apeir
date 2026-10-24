/** Actual CLI/HTTP/Chromium integration; explicit model-disabled scope, no native claim. */
import { test, expect, type Page } from "@playwright/test";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createServer } from "node:net";

const token = "APEIR_FAKE_ONLY_STUDIO_BROWSER_9342";
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
  for (const runtime of runtimes) {
    if (runtime.process.exitCode === null) {
      const completed = await new Promise<boolean>(resolve => {
        const timeout = setTimeout(() => resolve(false), 5000);
        runtime.process.once("exit", () => { clearTimeout(timeout); resolve(true); });
        runtime.process.kill("SIGTERM");
      });
      if (!completed) {
        const exited = new Promise<void>(resolve => runtime.process.once("exit", () => resolve()));
        runtime.process.kill("SIGKILL"); await exited;
        failures.push("Owned Runtime failed normal test teardown");
      }
    }
    await rm(runtime.directory, { recursive: true, force: true });
  }
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

test("Studio restores safe layouts, preserves drafts while docking and isolates Controller changes", async ({ page }, info) => {
  const errors: string[] = []; const mutations: string[] = []; let fileReads = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    if (!request.url().includes("/api/")) return;
    if (!["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url());
    if (request.url().includes("developer/workspace/file")) fileReads++;
  });
  await open(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("software");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await page.getByRole("button", { name: "Save layout", exact: true }).click();
  const saved = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(saved);
  await page.getByRole("button", { name: /example.py/ }).click();
  const editor = page.getByRole("textbox", { name: "Code editor", exact: true });
  await editor.fill("PRIVATE_DRAFT_CONTROLLER_A"); const originalReads = fileReads;
  await page.locator(".flexlayout__tab_button").filter({ hasText: "editor" }).first().dragTo(page.locator(".flexlayout__tab_button").filter({ hasText: "chat" }).first());
  await expect(editor).toHaveValue("PRIVATE_DRAFT_CONTROLLER_A"); expect(fileReads).toBe(originalReads);
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
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("blank");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
  await page.getByRole("button", { name: /Dashboard.*Existing Runtime/ }).click();
  await expect(page.getByRole("region", { name: "Dashboard builder" })).toBeVisible();
  await expect(page.getByText("ONLINE · Runtime API", { exact: true })).toBeVisible();
  await expect(page.getByText("No records reported / 暂无记录", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Settings Node Status", exact: true }).click();
  await page.getByRole("textbox", { name: "Widget title" }).fill("My authorized nodes");
  await page.getByRole("spinbutton", { name: "Widget w", exact: true }).fill("5");
  await expect(page.getByRole("alert")).toContainText("bounds"); // x=8,w=5 cannot fit the 12-column grid.
  await page.getByRole("spinbutton", { name: "Widget y", exact: true }).fill("12");
  await page.getByRole("spinbutton", { name: "Widget x", exact: true }).fill("0");
  await page.getByRole("spinbutton", { name: "Widget w", exact: true }).fill("5");
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  const handle = page.getByRole("button", { name: "Move Runtime Status", exact: true });
  const before = await handle.boundingBox(); expect(before).not.toBeNull();
  await handle.hover(); await page.mouse.down(); await page.mouse.move(before!.x + before!.width / 2 + 1000, before!.y + before!.height / 2, { steps: 12 }); await page.mouse.up();
  await expect.poll(async () => (await handle.boundingBox())!.x).toBeGreaterThan(before!.x + 400);
  const nodeResize = page.locator('[data-widget-id="widget-3"] .react-resizable-handle');
  await nodeResize.hover(); const corner = await nodeResize.boundingBox(); expect(corner).not.toBeNull();
  await page.mouse.down(); await page.mouse.move(corner!.x + 110, corner!.y + 60, { steps: 12 }); await page.mouse.up();
  await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  const saved = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  const persisted = JSON.parse(saved!);
  const configurations: Array<{ widgets: Array<{ id: string; x: number; y: number; w: number; h: number }> }> = [];
  const visit = (node: { config?: { widgets: Array<{ id: string; x: number; y: number; w: number; h: number }> }; children?: unknown[] }) => { if (node.config) configurations.push(node.config); node.children?.forEach(child => visit(child as typeof node)); }; visit(persisted.layout);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-1")!.x).toBeGreaterThan(0);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-3")!.w).toBeGreaterThan(5);
  expect(configurations[0].widgets.find(widget => widget.id === "widget-3")!.h).toBeGreaterThan(6);
  expect(saved).toContain("My authorized nodes"); expect(saved).not.toContain(token);
  const downloaded = page.waitForEvent("download"); await page.getByRole("button", { name: "Export dashboard", exact: true }).click();
  const file = await downloaded; const path = await file.path(); const exported = await readFile(path!, "utf8");
  expect(JSON.parse(exported).kind).toBe("dashboard");
  await page.reload(); await page.getByRole("button", { name: /APEIR Studio/ }).click();
  await expect(page.getByRole("button", { name: "Move My authorized nodes", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(saved);
  await page.getByLabel("Import dashboard", { exact: true }).setInputFiles({ name: "dashboard.json", mimeType: "application/json", buffer: Buffer.from(exported) });
  await expect(page.getByText("Dashboard imported. No Runtime operation was executed.", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Widget type", exact: true }).selectOption("gpu");
  await page.getByRole("button", { name: "Add widget", exact: true }).click();
  await expect(page.getByText("UNSUPPORTED · No qualified Runtime metric source", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Settings GPU Metrics", exact: true }).click();
  await page.getByRole("checkbox", { name: "Pause display", exact: true }).check();
  await expect(page.getByText("PAUSED · Display subscription stopped", { exact: false })).toBeVisible();
  await page.screenshot({ path: info.outputPath("studio-dashboard-real-runtime-source-browser.png"), fullPage: true });
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
});

test("named templates and Workspace layouts persist without crossing Controller scope", async ({ page }, info) => {
  const errors: string[] = [], mutations: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page);
  await page.getByRole("combobox", { name: "Template", exact: true }).selectOption("network");
  await page.getByRole("button", { name: "Apply preset", exact: true }).click();
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
  await open(other); await other.getByRole("button", { name: "Layout library", exact: true }).click();
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
