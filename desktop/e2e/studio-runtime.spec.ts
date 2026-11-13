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
      cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: directory, NOUS_API_TOKEN: token }, stdio: ["ignore", "pipe", "pipe"],
    });
    let diagnostics = "";
    for (const output of [process.stdout, process.stderr]) output?.on("data", chunk => { diagnostics = (diagnostics + String(chunk)).slice(-8192); });
    process.on("error", error => { diagnostics = error.message; });
    const runtime = { process, directory, url: `http://127.0.0.1:${selected}` }; runtimes.push(runtime);
    await expect.poll(async () => {
      if (process.exitCode !== null) throw new Error(`Owned Runtime exited before readiness (${process.exitCode}): ${diagnostics}`);
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
  page.on("pageerror", error => console.error(error.stack || error.message));
  await page.addInitScript(({ url, token }) => {
    sessionStorage.setItem("nous_server_url", url); sessionStorage.setItem("nous_server_token", token);
  }, { url: runtimes[0].url, token });
  await page.goto("/");
  await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
}

async function workspaceMenu(page: Page) {
  const summary = page.getByLabel(/^(Workspace menu|工作区菜单)$/, { exact: true });
  if (!(await summary.evaluate(node => (node.parentElement as HTMLDetailsElement).open))) await summary.click();
}
async function settings(page: Page) {
  await page.keyboard.press("Control+Comma");
  const dialog = page.getByRole("dialog", { name: /^(Settings|设置)$/ });
  await expect(dialog).toBeVisible(); return dialog;
}
async function closeSettings(page: Page) {
  await page.getByRole("dialog").getByRole("button", { name: /^(Close settings|关闭设置)$/ }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
}
async function changeLanguage(page: Page, value: string) {
  const dialog = await settings(page); await dialog.getByLabel("Studio language", { exact: true }).selectOption(value); await closeSettings(page);
}
async function changeTheme(page: Page, value: string) {
  const dialog = await settings(page); await dialog.getByLabel("Studio theme", { exact: true }).selectOption(value); await closeSettings(page);
}
async function revealView(page: Page, name: string) {
  const target = page.getByRole("button", { name: `Open ${name}`, exact: true });
  if (await target.first().isVisible()) { await target.first().click(); return; }
  const group = name === "Chat" || name === "Workspace Editor" || name === "Project Files" ? "Develop" : name === "Workflow Builder" ? "Workflow" : ["Models", "Nodes", "Devices", "Environment"].includes(name) ? "Resources" : name === "Dashboard" || name === "Model Usage" ? "Overview" : "Run";
  await page.getByRole("navigation", { name: "Studio panels", exact: true }).getByRole("button", { name: group, exact: true }).click();
  await target.first().click();
}
async function dashboardMenu(page: Page) {
  const summary = page.getByLabel("Dashboard options", { exact: true });
  if (!(await summary.evaluate(node => (node.parentElement as HTMLDetailsElement).open))) await summary.click();
}

test("Overview v2 preserves v1 geometry and reads canonical progress without executing Work", async ({ page }, info) => {
  const fixture = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-c", `from nous_runtime.workflow import WorkflowRuntime
from nous_runtime.workflow.models import definition_from_dict
r=WorkflowRuntime(${JSON.stringify(runtimes[0].directory)})
d=definition_from_dict({"workflow_id":"overview.read-reference","version":"1.0.0","trigger":"manual","steps":[{"step_id":"result","step_type":"transform","params":{"value":"actual-result"}}]})
r.register(d)
print(r.start(d.workflow_id,d.version,idempotency_key="overview-original").run_id)`], { cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: runtimes[0].directory }, stdio: ["ignore", "pipe", "pipe"] });
  producers.push(fixture); let original = "";
  fixture.stdout?.on("data", chunk => { original += String(chunk); });
  expect(await new Promise(resolve => fixture.once("exit", resolve))).toBe(0);
  original = original.trim(); expect(original).toMatch(/^wfr_/);
  const mutations: string[] = [], errors: string[] = []; let reads = 0;
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/workflow" && request.method() === "GET") reads++;
    if (url.pathname.startsWith("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(url.pathname);
  });
  await open(page);
  const widgets = ["progress", "progress", "cache", "quick-actions"].map((type, i) => ({ id: `overview-${i}`, type, title: "", x: i % 2 * 6, y: Math.floor(i / 2) * 5, w: 6, h: 5, paused: false }));
  const legacy = { schemaVersion: 1, kind: "dashboard", name: "Overview v1", locale: "en", layout: { type: "row", id: "overview-root", children: [{ type: "tabset", id: "overview-group", children: [{ type: "tab", id: "overview-panel", component: "dashboard", config: { schemaVersion: 1, widgets } }] }] } };
  await page.getByLabel("Import Studio layout", { exact: true }).setInputFiles({ name: "overview-v1.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(legacy)) });
  await expect(page.getByText("overview.read-reference", { exact: true })).toHaveCount(2);
  await expect(page.getByText("Recorded steps: 1 / 1 · Skipped: 0", { exact: true })).toHaveCount(2);
  await expect(page.getByText(original, { exact: true })).toHaveCount(2);
  expect(reads).toBe(1);
  await page.getByRole("combobox", { name: "Overview mode", exact: true }).selectOption("professional");
  await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
  await page.getByRole("button", { name: "Settings Cache tokens", exact: true }).click();
  await page.getByRole("combobox", { name: "Widget accent", exact: true }).selectOption("info");
  await page.getByRole("combobox", { name: "Widget density", exact: true }).selectOption("compact");
  await page.getByRole("combobox", { name: "Widget icon", exact: true }).selectOption("model");
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  const grip = page.getByRole("button", { name: "Move Cache tokens", exact: true });
  await grip.focus(); await grip.press("ArrowLeft");
  await expect(page.getByRole("alert")).toContainText("Invalid widget position or size");
  await grip.press("Shift+ArrowDown");
  await dashboardMenu(page); await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  const saved = JSON.parse((await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1")))!);
  const configuration = saved.layout.children[0].children[0].config;
  expect(configuration).toMatchObject({ schemaVersion: 2, mode: "professional" });
  expect(configuration.widgets[2]).toMatchObject({ id: "overview-2", x: 0, y: 5, w: 6, h: 6, presentation: { accent: "info", density: "compact", icon: "model" } });
  expect(configuration.widgets[0]).toEqual(widgets[0]);
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Overview mode", exact: true })).toHaveValue("professional");
  await expect(page.locator('[data-widget-id="overview-2"]')).toHaveClass(/widget-accent-info/);
  await page.getByRole("button", { name: "Ask a model", exact: true }).click();
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Keep the original draft; no new model call");
  await revealView(page, "Dashboard");
  await page.getByRole("button", { name: "Ask a model", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("Keep the original draft; no new model call");
  expect(errors).toEqual([]); expect(mutations).toEqual([]);
  await writeFile(info.outputPath("overview-v2-real-runtime.json"), JSON.stringify({ original_run_id: original, data_source: "WorkflowStore; real model-disabled Runtime", layout: configuration, runtime_mutations_from_overview: mutations, live_model_calls: 0, native_installation: "NOT_TESTED" }, null, 2));
  await revealView(page, "Dashboard");
  const boxes = await page.locator(".studio-widget").evaluateAll(nodes => nodes.map(node => ({ id: node.getAttribute("data-widget-id"), inline: node.getAttribute("style"), className: node.className, rect: { x: node.getBoundingClientRect().x, y: node.getBoundingClientRect().y, width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height }, position: getComputedStyle(node).position, transform: getComputedStyle(node).transform, gridWidth: node.parentElement?.getBoundingClientRect().width })));
  await writeFile(info.outputPath("overview-visual-geometry.json"), JSON.stringify(boxes, null, 2));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].rect, b = boxes[j].rect;
    expect(a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y).toBe(false);
  }
  await page.screenshot({ path: info.outputPath("overview-v2-source-browser.png"), fullPage: true });
});

test("Chat stops waiting without claiming backend cancellation or resubmitting the original Run", async ({ page }, info) => {
  await open(page);
  await revealView(page, "Chat");
  const chat = page.getByRole("region", { name: "AI conversation", exact: true });
  let original = "", submissions = 0, stopped = false;
  let release!: () => void, received!: () => void, settled!: () => void;
  let transportError: unknown;
  const held = new Promise<void>(resolve => { release = resolve; });
  const responseReceived = new Promise<void>(resolve => { received = resolve; });
  const routeSettled = new Promise<void>(resolve => { settled = resolve; });
  await page.route("**/api/v1/chat", async route => {
    if (route.request().method() !== "POST") { await route.continue(); return; }
    submissions += 1; original = String(route.request().postDataJSON().request_id || "");
    try {
      // Hold an actual model-disabled Runtime response, not a fabricated reply.
      const response = await route.fetch(); received(); await held;
      try { await route.fulfill({ response }); } catch (error) { if (!stopped) throw error; }
    } catch (error) { transportError = error; received(); }
    finally { settled(); }
  });
  try {
    await chat.getByRole("textbox", { name: "Message", exact: true }).fill("Explain a pure function.");
    await chat.getByTitle("Send (Enter)", { exact: true }).click();
    await responseReceived;
    expect(transportError).toBeUndefined(); expect(original).toMatch(/^[0-9a-f-]{36}$/);
    const draft = chat.getByRole("textbox", { name: "Message", exact: true });
    await draft.fill("Keep this follow-up draft"); await draft.press("Enter");
    await expect(draft).toHaveValue("Keep this follow-up draft"); expect(submissions).toBe(1);
    const aborted = page.waitForEvent("requestfailed", { predicate: request => request.url().endsWith("/api/v1/chat") && request.method() === "POST" });
    stopped = true;
    await chat.getByRole("button", { name: "Stop waiting", exact: true }).click();
    expect((await aborted).failure()?.errorText).toContain("ERR_ABORTED");
    release(); await routeSettled;
    await expect(chat.getByText(/Runtime cancellation is unconfirmed/)).toBeVisible();
    await expect(chat.getByText(original, { exact: true })).toBeVisible();
    const inspected = page.waitForResponse(response => response.request().method() === "GET" && new URL(response.url()).pathname === `/api/v1/runtime/runs/${original}/events`);
    await chat.getByRole("button", { name: "Execution activity", exact: true }).click();
    const response = await inspected;
    expect(response.status()).toBe(200);
    const envelope = await response.json();
    expect(envelope.data.run_id).toBe(original);
    expect(envelope.data.events.length).toBeGreaterThan(0);
    expect(submissions).toBe(1);
    await expect(chat.getByRole("button", { name: "Stop waiting", exact: true })).toBeHidden();
    await writeFile(info.outputPath("chat-original-run-after-stop-source.json"), JSON.stringify({
      scope: "Actual model-disabled HTTP/Chromium; not live inference or backend cancellation",
      original_run_id: original, submissions, browser_request_aborted: true,
      backend_cancellation_confirmed: false, external_provider_calls: 0,
      event_types: (envelope.data.events as Array<{ event_type: string }>).map(event => event.event_type),
      follow_up_draft_retained: await draft.inputValue() === "Keep this follow-up draft",
    }, null, 2));
    await page.screenshot({ path: info.outputPath("chat-original-run-after-stop-source.png"), fullPage: true });
  } finally { release(); if (submissions) await routeSettled; }
});

test("Studio configures and inspects saved Providers through the real model-disabled Runtime", async ({ page }, info) => {
  await open(page);
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("Models");
  await page.getByRole("button", { name: "Models", exact: true }).click();
  const settings = page.getByRole("region", { name: "Provider settings", exact: true });
  await expect(settings).toBeVisible();
  await settings.getByRole("button", { name: "Add Provider", exact: true }).click();
  await settings.getByLabel("Protocol template", { exact: true }).selectOption("openai_compatible");
  await settings.getByLabel("Provider ID", { exact: true }).fill("studio-example");
  await settings.getByLabel("Name", { exact: true }).fill("Studio reference");
  await settings.getByLabel("Endpoint", { exact: true }).fill("http://127.0.0.1:9/v1");
  await settings.getByLabel("Vendor model ID", { exact: true }).fill("original-example");
  await settings.getByRole("button", { name: "Save Provider", exact: true }).click();
  await expect(settings.getByRole("button", { name: "Edit studio-example" })).toBeVisible();
  const before = JSON.parse(await readFile(join(runtimes[0].directory, ".nous", "providers.json"), "utf8"));
  expect(before["studio-example"].model).toBe("original-example");
  await settings.getByRole("button", { name: "Edit studio-example" }).click();
  await settings.getByLabel("Vendor model ID", { exact: true }).fill("reviewed-example");
  await settings.getByRole("button", { name: "Save Provider", exact: true }).click();
  await expect(settings.getByText("reviewed-example · http://127.0.0.1:9/v1")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("region", { name: "Provider settings", exact: true }).getByText("reviewed-example · http://127.0.0.1:9/v1")).toBeVisible();
  const settingsAfter = page.getByRole("region", { name: "Provider settings", exact: true });
  await expect(settingsAfter.getByRole("button", { name: "Run inference test" })).toBeDisabled();
  await settingsAfter.screenshot({ path: info.outputPath("studio-model-settings-source.png") });
  await settingsAfter.getByRole("button", { name: "Remove studio-example" }).click();
  await settingsAfter.getByRole("button", { name: "Confirm remove studio-example" }).click();
  await expect(settingsAfter.getByRole("alert")).toBeVisible();
  await expect(settingsAfter.getByRole("button", { name: "Edit studio-example" })).toBeVisible();
  const after = JSON.parse(await readFile(join(runtimes[0].directory, ".nous", "providers.json"), "utf8"));
  expect(after["studio-example"].model).toBe("reviewed-example");
  await page.screenshot({ path: info.outputPath("studio-model-settings-approval-denied.png"), fullPage: true });
  await info.attach("model-disabled-provider-acceptance", { body: JSON.stringify({ configuration_saved: true, updated: true, reload_same_configuration: true, denied_removal_preserved_original: true, model_inference: "NOT_RUN", external_model_calls: 0 }), contentType: "application/json" });
});

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
  await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(saved);
  await page.getByRole("button", { name: /example.py/ }).click();
  const editor = page.getByRole("textbox", { name: "Code editor", exact: true });
  await editor.fill("PRIVATE_DRAFT_CONTROLLER_A"); const originalReads = fileReads;
  await expect(page.getByRole("button", { name: "Customize Overview", exact: true })).toHaveCount(0);
  await page.locator(".flexlayout__tab_button").filter({ hasText: "Workspace Editor" }).first().dragTo(page.locator(".flexlayout__tab_button").filter({ hasText: "Chat" }).first());
  await expect(editor).toHaveValue("PRIVATE_DRAFT_CONTROLLER_A"); expect(fileReads).toBe(originalReads);
  await workspaceMenu(page);
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page.getByText("Save or resolve protected editor drafts", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: "Operations Console", exact: true }).click();
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
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
  await page.getByRole("combobox", { name: "Widget type", exact: true }).selectOption("events");
  await page.getByRole("button", { name: "Add widget", exact: true }).click();
  await expect(page.getByText("qualification.workspace-0", { exact: false })).toBeVisible();
  await expect(page.getByText("qualification.workspace-1", { exact: false })).toHaveCount(0);
  await dashboardMenu(page);
  await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: "Operations Console", exact: true }).click();
  await page.getByText("Controller connection", { exact: true }).click();
  await page.getByRole("textbox", { name: "API URL" }).fill(runtimes[1].url);
  await page.getByLabel("Service session token", { exact: true }).fill(token);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Controller connection changed.", { exact: false })).toBeVisible();
  await revealView(page, "Dashboard");
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
  await changeTheme(page, "dark");
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
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("region", { name: "Dashboard builder" })).toBeVisible();
  await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
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
  await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Move My authorized nodes", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
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
  await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.layout.v1")!).name)).toBe("Renamed template");
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("operations console");
  await page.getByRole("button", { name: "Operations Console", exact: true }).click();
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
    await changeTheme(page, theme);
    await page.keyboard.press("Escape");
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await expect.poll(() => page.getByRole("button", { name: "Customize Overview", exact: true }).evaluate(node => {
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
  await changeLanguage(page, "zh");
  await workspaceMenu(page); await page.getByRole("button", { name: "保存布局", exact: true }).click(); await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "自定义概览", exact: true })).toBeVisible();
  await expect(dashboard.getByText("尚无模型请求", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(card).toHaveCSS("position", "relative");
  await expect.poll(async () => { const bounds = await dashboard.locator(".studio-widget").evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect())); return bounds.every(bounds => bounds.x >= 0 && bounds.right <= 390); }).toBe(true);
  await page.screenshot({ path: info.outputPath("studio-overview-zh-small-source-browser.png"), fullPage: true, animations: "disabled" });
  await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "自定义概览", exact: true })).toBeVisible();
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
    await expect(page.getByLabel(/^(Workspace menu|工作区菜单)$/, { exact: true })).toBeFocused();
    await page.keyboard.press("Control+Shift+p");
    await expect(page.getByRole("textbox", { name: "Search panels" })).toBeFocused();
    await page.getByRole("textbox", { name: "Search panels" }).fill("dashboard");
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    await expect(page.locator('[data-widget-id="widget-1"] [data-state="ONLINE"]')).toBeVisible();
    await page.screenshot({ path: info.outputPath("studio-overview-2x-touch-source-browser.png"), fullPage: true, animations: "disabled" });
    expect(errors).toEqual([]); expect(mutations).toEqual([]);
  } finally { await context.close(); }
});

test("Workflow Builder registers and runs the canonical definition, retains the original run and rejects self-approval", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await open(page);
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("workflow");
  await page.getByRole("button", { name: "Workflow Builder", exact: true }).click();
  const builder = page.getByRole("region", { name: "Workflow Builder" });
  await expect(builder).toBeVisible();
  await expect(builder.locator(".react-flow__node")).toHaveCount(1);
  await builder.getByRole("textbox", { name: "Workflow ID", exact: true }).fill("studio.browser-real");
  await builder.getByRole("combobox", { name: "Step type" }).selectOption("transform");
  await builder.locator(".react-flow__pane").click({ button: "right", position: { x: 180, y: 220 } });
  await page.getByRole("menuitem", { name: "Value / transform", exact: true }).click();
  await builder.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(builder.getByRole("status")).toContainText("VALID");
  await expect(builder.locator(".react-flow__node")).toHaveCount(2);
  await builder.locator(".react-flow__node").first().locator(".react-flow__handle.source").dragTo(builder.locator(".react-flow__node").nth(1).locator(".react-flow__handle.target"));
  await expect(builder.locator(".react-flow__edge")).toHaveCount(1);
  await builder.locator(".react-flow__node").nth(1).click();
  await page.keyboard.press("Delete");
  await expect(builder.locator(".react-flow__node")).toHaveCount(1);
  await builder.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(builder.locator(".react-flow__node")).toHaveCount(2);
  await expect(builder.locator(".react-flow__edge")).toHaveCount(1);
  await builder.getByRole("button", { name: "Arrange", exact: true }).click();
  await builder.locator(".react-flow__node").first().click();
  await builder.locator("summary").filter({ hasText: /^Advanced parameters/ }).click();
  await builder.getByRole("textbox", { name: "Step parameters", exact: true }).fill("{");
  await expect(builder.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  await builder.getByRole("button", { name: "Apply parameters", exact: true }).click();
  await expect(builder.getByRole("alert")).toBeVisible();
  await builder.getByRole("textbox", { name: "Step parameters", exact: true }).fill('{"value":"Hello APEIR"}');
  await builder.getByRole("button", { name: "Apply parameters", exact: true }).click();
  await expect(builder.getByRole("button", { name: "Run", exact: true })).toBeEnabled();
  await builder.locator(".react-flow__node").nth(1).click();
  await builder.locator("summary").filter({ hasText: /^Data bindings/ }).click();
  await builder.getByLabel("Binding source", { exact: true }).selectOption("step:transform");
  await builder.getByLabel("Binding pointer", { exact: true }).fill("/value");
  await builder.getByRole("button", { name: "Bind input", exact: true }).click();
  await expect(builder.getByLabel("Step parameters", { exact: true })).toHaveValue("{}");
  const typedContract = { schema_version: 1, inputs: { value: { source: "step", step_id: "transform", pointer: "/value" } }, inputs_schema: { type: "object", properties: { value: { type: "string" } }, required: ["value"] }, outputs_schema: { properties: { value: { type: "string" } }, required: ["value"] } };
  await builder.getByLabel("Step data bindings", { exact: true }).fill(JSON.stringify(typedContract));
  await expect(builder.getByRole("button", { name: "Run", exact: true })).toBeDisabled();
  await expect(builder.getByRole("button", { name: "Add step", exact: true })).toBeDisabled();
  await builder.locator(".react-flow__pane").click({ position: { x: 400, y: 70 } });
  await page.keyboard.press("Delete");
  await expect(builder.locator(".react-flow__node")).toHaveCount(2);
  await expect(builder.getByLabel("Step data bindings", { exact: true })).toHaveValue(JSON.stringify(typedContract));
  await builder.getByRole("button", { name: "Apply parameters", exact: true }).click();
  await expect(builder.getByRole("button", { name: "Run", exact: true })).toBeEnabled();
  await builder.locator("summary").filter({ hasText: /^Draft/ }).click();
  const draftDownload = page.waitForEvent("download");
  await builder.getByRole("button", { name: "Save draft", exact: true }).click();
  const portableDraft = await draftDownload, draftPath = info.outputPath("workflow-draft.json"); await portableDraft.saveAs(draftPath);
  const savedDraft = JSON.parse(await readFile(draftPath, "utf8"));
  expect(savedDraft.definition.steps[1].depends_on).toEqual(["transform"]);
  expect(savedDraft.definition.steps[1].data_bindings).toEqual(typedContract);
  await builder.getByRole("textbox", { name: "Workflow ID", exact: true }).fill("unsaved.other");
  page.once("dialog", dialog => void dialog.accept());
  await builder.locator('input[type="file"]').setInputFiles(draftPath);
  await expect(builder.getByRole("textbox", { name: "Workflow ID", exact: true })).toHaveValue("studio.browser-real");
  const definitionDownload = page.waitForEvent("download");
  await builder.getByRole("button", { name: "Export definition", exact: true }).click();
  const exported = await definitionDownload, definitionPath = info.outputPath("workflow-definition.json"); await exported.saveAs(definitionPath);
  const definition = JSON.parse(await readFile(definitionPath, "utf8")); expect(definition).not.toHaveProperty("positions");
  const cli = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "workflow", "validate", definitionPath, "--json"], { cwd: runtimes[0].directory, env: { ...globalThis.process.env, PYTHONPATH: resolve(".."), NOUS_WORKSPACE_ROOT: runtimes[0].directory }, stdio: "ignore" });
  producers.push(cli); expect(await new Promise<number | null>((resolve, reject) => { cli.once("exit", resolve); cli.once("error", reject); })).toBe(0);

  async function approveRecordedProposal() {
    const message = await builder.getByRole("alert").textContent();
    const requestId = message?.match(/Approval: ([A-Za-z0-9_-]+)/)?.[1];
    expect(requestId).toBeTruthy();
    // The actual public CLI supplies the attested local OS-owner approval.
    // It remains separate from the browser/service subject, not a real-IdP claim.
    const child = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "approval", "approve", requestId!], { cwd: runtimes[0].directory, env: { ...globalThis.process.env, PYTHONPATH: resolve(".."), NOUS_WORKSPACE_ROOT: runtimes[0].directory }, stdio: "ignore" });
    producers.push(child);
    const result = await new Promise<number | null>((resolve, reject) => { child.once("exit", resolve); child.once("error", reject); });
    expect(result).toBe(0);
  }
  await builder.getByRole("button", { name: "Register", exact: true }).click();
  await expect(builder.getByRole("alert")).toContainText("Approval:");
  await approveRecordedProposal();
  await builder.getByRole("button", { name: "Register", exact: true }).click();
  await expect(builder.getByRole("status")).toContainText("REGISTERED");
  await builder.getByRole("button", { name: "Run", exact: true }).click();
  await expect(builder.getByRole("alert")).toContainText("Approval:");
  await approveRecordedProposal();
  await builder.getByRole("button", { name: "Run", exact: true }).click();
  await expect(builder.locator(".studio-workflow-result pre")).toContainText('"state": "completed"');
  await builder.getByText("Raw record / events", { exact: true }).click();
  const evidence = await builder.locator(".studio-workflow-result pre").textContent();
  expect(evidence).toContain("workflow.completed"); expect(evidence).toContain("Hello APEIR");
  const runId = JSON.parse(evidence!).run.run_id as string;
  const originalRecord = JSON.parse(evidence!);
  const consumerId = definition.steps[1].step_id;
  expect(originalRecord.run.outputs[consumerId].value).toBe("Hello APEIR");
  expect(originalRecord.step_bindings[consumerId].data_binding.params_digest).toMatch(/^[a-f0-9]{64}$/);
  await builder.getByText("Raw record / events", { exact: true }).click();
  await expect(builder.locator(".react-flow__node").first()).toContainText("completed");
  await expect.poll(async () => {
    const canvas = await builder.locator(".studio-workflow-canvas").boundingBox();
    const nodes = await builder.locator(".react-flow__node").evaluateAll(nodes => nodes.map(node => { const rect = node.getBoundingClientRect(); return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom }; }));
    return !!canvas && nodes.every(rect => rect.x >= canvas.x && rect.y >= canvas.y && rect.right <= canvas.x + canvas.width && rect.bottom <= canvas.y + canvas.height);
  }).toBe(true);
  await builder.locator(".react-flow__node").nth(1).click();
  await builder.locator("summary").filter({ hasText: /^Data bindings/ }).click();
  await page.screenshot({ path: info.outputPath("workflow-real-runtime-source-browser.png"), fullPage: true });
  // Restart the actual owned CLI process against its original durable workspace.
  const originalRuntime = runtimes[0];
  const exited = new Promise<void>((resolve, reject) => {
    const deadline = setTimeout(() => reject(new Error("Original Runtime did not stop")), 5000);
    originalRuntime.process.once("exit", () => { clearTimeout(deadline); resolve(); });
  });
  originalRuntime.process.kill("SIGTERM"); await exited;
  const restarted = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "runtime-api", "start", "--port", new URL(originalRuntime.url).port], { cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: originalRuntime.directory, NOUS_API_TOKEN: token }, stdio: "ignore" });
  restarted.on("error", () => {}); originalRuntime.process = restarted;
  await expect.poll(async () => { try { return (await fetch(`${originalRuntime.url}/api/v1/status`, { headers: { Authorization: `Bearer ${token}` } })).ok; } catch { return false; } }, { timeout: 10000 }).toBe(true);
  const unauthenticated = await fetch(`${originalRuntime.url}/api/v1/workflow`);
  expect(unauthenticated.status).toBe(401);
  const otherController = await fetch(`${runtimes[1].url}/api/v1/workflow/runs/${runId}`, { headers: { Authorization: `Bearer ${token}` } });
  expect((await otherController.json()).ok).toBe(false);
  await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /Add panel/ }).click();
  await page.getByRole("textbox", { name: "Search panels" }).fill("workflow");
  await page.getByRole("button", { name: "Workflow Builder", exact: true }).click();
  await builder.locator("summary").filter({ hasText: /^Inputs & history/ }).click();
  await page.getByRole("button", { name: new RegExp(runId) }).click();
  await expect(page.locator(".studio-workflow-result pre")).toContainText(runId);
  const recoveredRecord = JSON.parse((await page.locator(".studio-workflow-result pre").textContent())!);
  expect(recoveredRecord.step_bindings).toEqual(originalRecord.step_bindings);
  expect(recoveredRecord.run.outputs[consumerId].value).toBe("Hello APEIR");
  expect(errors).toEqual([]);
});

for (const profile of [
  { file: "nous.extension.json", panel: "System Monitor", widget: "Runtime Monitor", source: "runtime.status" },
  { file: "workflow-monitor.extension.json", panel: "Workflow Monitor", widget: "Workflow Summary", source: "workflow.summary" },
]) {
test(`Declarative UI extension uses public review and approval, real status, revocation and retained layout (${profile.panel})`, async ({ page }, info) => {
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  const acquired = await mkdtemp(join(tmpdir(), "apeir-external-widget-"));
  const manifestPath = join(acquired, "nous.extension.json");
  const original = JSON.parse(await readFile(resolve(`../examples/studio_system_monitor/${profile.file}`), "utf8"));
  await writeFile(manifestPath, JSON.stringify(original));
  const clientPath = join(acquired, "monitor_client.py");
  await writeFile(clientPath, await readFile(resolve("../examples/studio_system_monitor/monitor_client.py")));
  async function external(args: string[], directory = acquired) {
    const child = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", args, { cwd: directory, env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: runtimes[0].directory, NOUS_API_TOKEN: token }, stdio: ["ignore", "pipe", "pipe"] });
    producers.push(child); let stdout = "", stderr = "";
    child.stdout?.on("data", chunk => { stdout += String(chunk); }); child.stderr?.on("data", chunk => { stderr += String(chunk); });
    expect(await new Promise<number | null>((resolve, reject) => { child.once("exit", resolve); child.once("error", reject); }), stderr).toBe(0);
    return JSON.parse(stdout);
  }
  if (profile.source === "workflow.summary") {
    const definition = JSON.parse(await readFile(resolve("../examples/hello_workflow/workflow.json"), "utf8"));
    definition.workflow_id = "extension.monitor.reference";
    const definitionPath = join(acquired, "workflow.json"); await writeFile(definitionPath, JSON.stringify(definition));
    await external(["-m", "nous_runtime.cli.main", "--no-intelligence", "workflow", "register", definitionPath, "--json"], runtimes[0].directory);
    await external(["-m", "nous_runtime.cli.main", "--no-intelligence", "workflow", "run", definition.workflow_id, "--idempotency-key", "monitor-once", "--json"], runtimes[0].directory);
  }
  try {
    await open(page);
    await page.getByRole("button", { name: /Add panel/ }).click();
    await page.getByRole("textbox", { name: "Search panels" }).fill("UI Extensions");
    await page.getByRole("button", { name: "UI Extensions", exact: true }).click();
    const manager = page.getByRole("region", { name: "UI Extensions", exact: true });
    async function approveAndRetry(buttonName: string) {
      if (buttonName === "Remove") page.once("dialog", dialog => void dialog.accept());
      await manager.getByRole("button", { name: buttonName, exact: true }).click();
      await expect(manager.getByRole("status").filter({ hasText: "NOUS_APPROVAL_REQUIRED" })).toBeVisible();
      const message = await manager.getByRole("status").filter({ hasText: "NOUS_APPROVAL_REQUIRED" }).textContent();
      const id = message?.match(/"approval_request_id":"([A-Za-z0-9_-]+)"/)?.[1]; expect(id).toBeTruthy();
      const child = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "approval", "approve", id!], { cwd: runtimes[0].directory, env: { ...globalThis.process.env, PYTHONPATH: resolve(".."), NOUS_WORKSPACE_ROOT: runtimes[0].directory }, stdio: "ignore" });
      producers.push(child);
      expect(await new Promise<number | null>((resolve, reject) => { child.once("exit", resolve); child.once("error", reject); })).toBe(0);
      if (buttonName === "Remove") page.once("dialog", dialog => void dialog.accept());
      await manager.getByRole("button", { name: buttonName, exact: true }).click();
      await expect(manager.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible();
    }
    await manager.getByLabel("Import UI extension", { exact: true }).setInputFiles(manifestPath);
    await expect(manager.getByRole("button", { name: "Request install", exact: true })).toBeVisible();
    await approveAndRetry("Request install");
    await expect(manager.getByText("DISABLED", { exact: true })).toBeVisible();
    await approveAndRetry("Enable");
    await expect(manager.getByText("ENABLED", { exact: true })).toBeVisible();
    const response = await fetch(`${runtimes[0].url}/api/v1/studio/extensions`, { headers: { Authorization: `Bearer ${token}` } });
    const view = (await response.json()).data;
    const record = view.extensions.find((item: { extension_id: string }) => item.extension_id === original.extension_id);
    expect(record.authority).toBe("none"); expect(record.granted_capabilities).toEqual([]);
    const contract = await external([clientPath, "contract", "--endpoint", runtimes[0].url]);
    expect(contract.schema).toBe("apeir.studio-ui/v1");
    const sdkRead = await external([clientPath, "read", "--manifest", manifestPath, "--endpoint", runtimes[0].url]);
    expect(sdkRead.source).toBe(profile.source);
    if (profile.source === "workflow.summary") { expect(sdkRead.status).toBe("READY"); expect(sdkRead.values.runs_sampled).toBeGreaterThan(0); }
    const widgetType = record.contributions.find((item: { kind: string }) => item.kind === "widget").type;
    const unauthorized = await fetch(`${runtimes[0].url}/api/v1/studio/extensions`); expect(unauthorized.status).toBe(401);
    await page.getByRole("button", { name: /Add panel/ }).click();
    await page.getByRole("textbox", { name: "Search panels" }).fill(profile.panel);
    await page.getByRole("button", { name: profile.panel, exact: true }).click();
    await expect(page.getByRole("region", { name: profile.panel, exact: true }).getByText(profile.source === "runtime.status" ? "ONLINE" : "Recorded runs", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Add panel/ }).click();
    await page.getByRole("textbox", { name: "Search panels" }).fill("Dashboard");
    await page.getByRole("button", { name: "Dashboard", exact: true }).click();
    await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
    await page.getByRole("combobox", { name: "Widget type", exact: true }).selectOption(widgetType);
    await page.getByRole("button", { name: "Add widget", exact: true }).click();
    await expect(page.getByRole("region", { name: profile.widget, exact: true }).getByText(profile.source === "runtime.status" ? "ONLINE" : "Unknown", { exact: true })).toBeAttached();
    if (profile.source === "workflow.summary") await expect(page.getByRole("region", { name: profile.widget, exact: true }).getByText("Unknown", { exact: true })).toBeInViewport();
    await workspaceMenu(page); await page.getByRole("button", { name: "Save layout", exact: true }).click();
    const layout = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
    expect(layout).toContain(widgetType); expect(layout).not.toContain(record.digest); expect(layout).not.toContain(token);
    await page.screenshot({ path: info.outputPath("extension-runtime-dashboard-source-browser.png"), fullPage: true });
    await page.locator(".flexlayout__tab_button").filter({ hasText: "UI Extensions" }).first().click();
    await approveAndRetry("Disable");
    const denied = await fetch(`${runtimes[0].url}/api/v1/studio/extensions/data?${new URLSearchParams({ component_type: widgetType, expected_digest: record.digest, source: profile.source })}`, { headers: { Authorization: `Bearer ${token}` } });
    expect((await denied.json()).ok).toBe(false);
    await page.locator(".flexlayout__tab_button").filter({ hasText: "Dashboard" }).first().click();
    await expect(page.getByRole("status").filter({ hasText: "DISABLED" })).toBeVisible();
    await page.locator(".flexlayout__tab_button").filter({ hasText: "UI Extensions" }).first().click();
    await approveAndRetry("Enable");
    await writeFile(manifestPath, JSON.stringify({ ...original, description: "Conflicting same-version content" }));
    await manager.getByLabel("Import UI extension", { exact: true }).setInputFiles(manifestPath);
    await expect(manager.getByRole("status").filter({ hasText: /immutable|different|version/ })).toBeVisible();
    await manager.getByRole("button", { name: "Discard review", exact: true }).click();
    await writeFile(manifestPath, JSON.stringify({ ...original, version: "1.1.0" }));
    await manager.getByLabel("Import UI extension", { exact: true }).setInputFiles(manifestPath);
    await approveAndRetry("Request install");
    await expect(manager.getByText("DISABLED", { exact: true })).toBeVisible();
    await approveAndRetry("Enable");
    await expect.poll(() => page.evaluate(() => {
      const saved = JSON.parse(localStorage.getItem("apeir.studio.layout.v1") || "null");
      const groups = saved?.layout?.children || [];
      return groups.some((group: { selected?: number; children?: Array<{ component?: string }> }) => group.children?.[group.selected ?? 0]?.component === "extensions");
    })).toBe(true);
    const latestLayout = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
    const content = (raw: string | null) => JSON.parse(raw!, (key, value) => ["selected", "active"].includes(key) ? undefined : value);
    expect(content(latestLayout)).toEqual(content(layout));
    await page.reload(); await expect(page.getByRole("region", { name: "APEIR Studio", exact: true })).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).toBe(latestLayout);
    await page.locator(".flexlayout__tab_button").filter({ hasText: "UI Extensions" }).first().click();
    await expect(manager.getByText(/1.1.0 · UNVERIFIED/)).toBeVisible();
    async function switchController(index: number) {
      await page.getByRole("button", { name: /Add panel/ }).click();
      await page.getByRole("textbox", { name: "Search panels" }).fill("Operations Console");
      await page.getByRole("button", { name: "Operations Console", exact: true }).click();
      await page.getByText("Controller connection", { exact: true }).click();
      await page.getByRole("textbox", { name: "API URL" }).fill(runtimes[index].url);
      await page.getByLabel("Service session token", { exact: true }).fill(token);
      await page.getByRole("button", { name: "Connect", exact: true }).click();
      await expect(page.getByText("Controller connection changed.", { exact: false })).toBeVisible();
    }
    await switchController(1);
    await page.locator(".flexlayout__tab_button").filter({ hasText: "Dashboard" }).first().click();
    await expect(page.getByRole("status").filter({ hasText: "Missing Extension" })).toBeVisible();
    await switchController(0);
    await page.locator(".flexlayout__tab_button").filter({ hasText: "UI Extensions" }).first().click();
    await expect(manager.getByText(/1.1.0 · UNVERIFIED/)).toBeVisible();
    const runtime = runtimes[0];
    const exited = new Promise<void>((resolve, reject) => {
      const deadline = setTimeout(() => reject(new Error("Original extension Runtime did not stop")), 5000);
      runtime.process.once("exit", () => { clearTimeout(deadline); resolve(); });
    });
    runtime.process.kill("SIGTERM"); await exited;
    runtime.process = spawn(globalThis.process.env.APEIR_TEST_PYTHON || "python", ["-m", "nous_runtime.cli.main", "--no-intelligence", "runtime-api", "start", "--port", new URL(runtime.url).port], { cwd: resolve(".."), env: { ...globalThis.process.env, NOUS_WORKSPACE_ROOT: runtime.directory, NOUS_API_TOKEN: token }, stdio: ["ignore", "pipe", "pipe"] });
    let restartDiagnostics = "";
    for (const output of [runtime.process.stdout, runtime.process.stderr]) output?.on("data", chunk => { restartDiagnostics = (restartDiagnostics + String(chunk)).slice(-8192); });
    runtime.process.on("error", error => { restartDiagnostics = error.message; });
    await expect.poll(async () => {
      if (runtime.process.exitCode !== null) throw new Error(`Original extension Runtime restart failed (${runtime.process.exitCode}): ${restartDiagnostics}`);
      try { return (await fetch(`${runtime.url}/api/v1/status`, { headers: { Authorization: `Bearer ${token}` } })).ok; } catch { return false; }
    }, { timeout: 10000 }).toBe(true);
    await manager.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(manager.getByText(/1.1.0 · UNVERIFIED/)).toBeVisible();
    if (profile.source === "workflow.summary") {
      const restored = await fetch(`${runtime.url}/api/v1/studio/extensions`, { headers: { Authorization: `Bearer ${token}` } });
      expect((await restored.json()).data.sources["workflow.summary"].values).toEqual(sdkRead.values);
    }
    await approveAndRetry("Remove");
    await page.locator(".flexlayout__tab_button").filter({ hasText: "Dashboard" }).first().click();
    await expect(page.getByRole("status").filter({ hasText: "Missing Extension" })).toBeVisible();
    const foreign = await fetch(`${runtimes[1].url}/api/v1/studio/extensions/data?${new URLSearchParams({ component_type: widgetType, expected_digest: record.digest, source: profile.source })}`, { headers: { Authorization: `Bearer ${token}` } });
    expect((await foreign.json()).ok).toBe(false);
    expect(errors).toEqual([]);
  } finally { await rm(acquired, { recursive: true, force: true }); }
});

}

test("Empty Chat offers real setup panels without submitting work or losing a draft", async ({ page }) => {
  const mutations: string[] = [];
  page.on("request", request => {
    if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url());
  });
  await open(page);
  const chat = page.getByRole("region", { name: "AI conversation", exact: true });
  await expect(chat.getByText("Loading conversation...", { exact: true })).toBeHidden();
  await chat.getByRole("textbox", { name: "Message", exact: true }).fill("Keep this unsent project question");
  await chat.getByRole("button", { name: "Connect a model", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Models", exact: true })).toBeVisible();
  await revealView(page, "Chat");
  await chat.getByRole("button", { name: "Open project files", exact: true }).click();
  await page.getByRole("button", { name: "example.py", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Code editor", exact: true })).toHaveValue("def add(a, b):\n    return a + b\n");
  await revealView(page, "Chat");
  await chat.getByRole("button", { name: "Open Workflow", exact: true }).click();
  await expect(page.getByRole("region", { name: "Workflow Builder", exact: true })).toBeVisible();
  await revealView(page, "Chat");
  await expect(chat.getByRole("textbox", { name: "Message", exact: true })).toHaveValue("Keep this unsent project question");
  expect(mutations).toEqual([]);
});

test("Studio opens the conversation workspace and manages existing windows without replay or draft loss", async ({ page }, info) => {
  const mutations: string[] = []; const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  await open(page);
  const rail = page.getByRole("navigation", { name: "Studio panels", exact: true });
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  await expect(page.getByText("Loading conversation...", { exact: true })).toBeHidden();
  const prompt = page.getByRole("region", { name: "AI conversation", exact: true }).getByRole("textbox", { name: "Message", exact: true });
  expect((await prompt.boundingBox())!.height).toBeGreaterThanOrEqual(24);
  await expect(rail.getByRole("button", { name: "Develop", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Conversations", exact: true }).click();
  await expect(page.getByLabel("Conversation history", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Conversations", exact: true }).click();
  await page.getByRole("button", { name: /example.py/ }).click();
  const editor = page.getByRole("textbox", { name: "Code editor", exact: true });
  await expect(editor).toHaveValue("def add(a, b):\n    return a + b\n");
  await page.screenshot({ path: info.outputPath("studio-default-conversation-source.png"), fullPage: true });
  await prompt.fill("UNSENT_WINDOW_PROMPT");
  await editor.fill("UNSAVED_WINDOW_DRAFT");
  await page.locator(".flexlayout__tab_button").filter({ hasText: "Workspace Editor" }).first().dragTo(page.locator(".flexlayout__tab_button").filter({ hasText: "Chat" }).first());
  await expect(editor).toHaveValue("UNSAVED_WINDOW_DRAFT");
  // Snapping and maximizing are ordinary window actions; Edit layout remains off.
  await expect(page.getByRole("button", { name: "Customize Overview", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Arrange Workspace Editor", exact: true }).click();
  const windows = page.getByRole("menu", { name: "Window arrangement", exact: true });
  await expect(windows.getByRole("menuitem", { name: "Snap left", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(windows.getByRole("menuitem", { name: "Snap right", exact: true })).toBeFocused();
  await windows.getByRole("menuitem", { name: "Snap bottom", exact: true }).click();
  await expect(editor).toHaveValue("UNSAVED_WINDOW_DRAFT");
  await page.getByRole("button", { name: "Arrange Workspace Editor", exact: true }).click();
  await page.getByRole("menuitem", { name: "Maximize group", exact: true }).click();
  await expect(page.getByRole("button", { name: "Show all panels", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeHidden();
  // Navigation restores the obscured existing Chat, rather than adding duplicates.
  await revealView(page, "Chat");
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toHaveCount(1);
  await expect(prompt).toHaveValue("UNSENT_WINDOW_PROMPT");
  await expect(editor).toHaveValue("UNSAVED_WINDOW_DRAFT");
  await page.getByRole("button", { name: "Arrange Workspace Editor", exact: true }).click();
  await page.getByRole("menuitem", { name: "Close panel", exact: true }).click();
  await expect(page.getByText("Save or resolve this panel's draft", { exact: false })).toBeVisible();
  await expect(editor).toHaveValue("UNSAVED_WINDOW_DRAFT");
  await expect.poll(() => page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1") || "")).toContain('"component":"editor"');
  await expect.poll(() => page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1") || "")).toContain('"component":"chat"');
  const chatBounds = await page.getByRole("region", { name: "AI conversation", exact: true }).boundingBox();
  const editorBounds = await editor.boundingBox();
  expect(chatBounds!.y + chatBounds!.height).toBeLessThanOrEqual(editorBounds!.y);
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("UNSAVED_WINDOW_DRAFT");
  await page.screenshot({ path: info.outputPath("studio-conversation-window-management-source.png"), fullPage: true });
  expect(mutations).toEqual([]); expect(errors).toEqual([]);
});

test("Studio recovers a dashboard-only or empty saved workspace without deleting its legacy layout", async ({ page }, info) => {
  const legacy = { schemaVersion: 1, kind: "workspace", name: "My dashboard", locale: "en", layout: { type: "row", id: "root", children: [{ type: "tabset", id: "main", maximized: true, children: [{ type: "tab", id: "overview", component: "dashboard", name: "Dashboard" }] }] } };
  await page.addInitScript(value => { if (!localStorage.getItem("apeir.studio.layout.v1")) localStorage.setItem("apeir.studio.layout.v1", JSON.stringify(value)); }, legacy);
  await open(page);
  await expect(page.getByRole("region", { name: "Dashboard builder" })).toBeVisible();
  await revealView(page, "Chat");
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => JSON.stringify(JSON.parse(localStorage.getItem("apeir.studio.layout.v1") || "null")))).toContain('"id":"overview"');
  await expect.poll(() => page.evaluate(() => JSON.stringify(JSON.parse(localStorage.getItem("apeir.studio.layout.v1") || "null")))).toContain('"component":"chat"');
  await page.reload();
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  // A valid imported v1 layout may have no tabsets at all; opening a panel repairs presentation only.
  const empty = { ...legacy, name: "Empty", layout: { type: "row", id: "root", children: [] } };
  await workspaceMenu(page);
  await page.getByLabel("Import Studio layout", { exact: true }).setInputFiles({ name: "empty.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(empty)) });
  await expect(page.getByRole("region", { name: "Empty workspace", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start a conversation", exact: true }).click();
  await expect(page.getByRole("region", { name: "AI conversation", exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("studio-recovered-empty-workspace-source.png"), fullPage: true });
});

test("Studio periodic reads do not overlap or continue while the document is hidden", async ({ page }, info) => {
  const periodic = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/tasks" && url.searchParams.get("limit") === "50";
  }, { timeout: 7000 });
  await open(page);
  // Observe a completed periodic read, so holding a bootstrap request cannot
  // accidentally prevent connected polling and make this assertion vacuous.
  await (await periodic).finished();
  let reads = 0, release!: () => void, settled!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const finished = new Promise<void>(resolve => { settled = resolve; });
  await page.route("**/api/v1/tasks?**", async route => {
    reads++;
    if (reads !== 1) { await route.continue(); return; }
    try { const original = await route.fetch(); await held; await route.fulfill({ response: original }); }
    finally { settled(); }
  });
  try {
    await expect.poll(() => reads, { timeout: 7000 }).toBe(1);
    // One subsequent five-second refresh period: a slow read must stay singular.
    await page.waitForTimeout(6000); expect(reads).toBe(1);
    await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
    release(); await finished;
    await page.waitForTimeout(6000); expect(reads).toBe(1);
    await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" }); document.dispatchEvent(new Event("visibilitychange")); });
    await expect.poll(() => reads).toBe(2);
    await writeFile(info.outputPath("overview-periodic-read-admission.json"), JSON.stringify({ scope: "Real Runtime HTTP with one held read and instrumented document visibility", held_read_repeated: false, hidden_periodic_task_reads: 0, fresh_read_on_visibility: true, backend_cancellation_claimed: false }, null, 2));
  } finally { release(); if (reads) await finished; }
});

test("Overview history and selected fields use the actual dated ledger and survive reload", async ({ page }, info) => {
  await open(page); const days: string[] = [];
  page.on("request", request => { const url = new URL(request.url()); if (url.pathname === "/api/v1/usage" && url.searchParams.has("day")) days.push(url.searchParams.get("day")!); });
  const widgets = ["usage", "cache"].map((type, i) => ({ id: `history-${i}`, type, title: "", x: i * 6, y: 0, w: 6, h: 6, paused: false, presentation: { day: "2000-01-01", ...(type === "usage" ? { fields: ["tokens", "requests"] } : {}) } }));
  const layout = { schemaVersion: 1, kind: "dashboard", name: "Dated overview", locale: "en", layout: { type: "row", id: "r", children: [{ type: "tabset", id: "g", children: [{ type: "tab", id: "history", component: "dashboard", config: { schemaVersion: 2, mode: "standard", widgets } }] }] } };
  await page.getByLabel("Import Studio layout", { exact: true }).setInputFiles({ name: "dated.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(layout)) });
  await expect(page.getByText("2000-01-01 UTC · CostController", { exact: true })).toHaveCount(2);
  expect(days).toEqual(["2000-01-01"]);
  const usage = page.locator('[data-widget-id="history-0"]');
  expect(await usage.locator(".studio-usage-pairs dt").allTextContents()).toEqual(["Requests", "Token"]);
  await page.getByRole("button", { name: "Customize Overview", exact: true }).click();
  await page.getByRole("button", { name: "Settings Model Usage", exact: true }).click();
  await page.getByRole("checkbox", { name: "Usage field pending", exact: true }).check();
  await page.getByLabel("Usage UTC date", { exact: true }).fill("2000-01-02");
  await expect(usage.getByText("2000-01-02 UTC · CostController", { exact: true })).toBeVisible();
  expect(await usage.locator(".studio-usage-pairs dt").allTextContents()).toEqual(["Requests", "Token", "Pending"]);
  await page.getByRole("button", { name: "Close settings", exact: true }).click();
  await dashboardMenu(page); await page.getByRole("button", { name: "Save dashboard", exact: true }).click();
  const saved = await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"));
  expect(saved).toContain('"day":"2000-01-02"'); expect(saved).toContain('"fields":["tokens","requests","pending"]'); expect(saved).not.toContain(token);
  await page.reload();
  await expect(page.locator('[data-widget-id="history-0"]').getByText("2000-01-02 UTC · CostController", { exact: true })).toBeVisible();
  await expect(page.locator('[data-widget-id="history-1"]').getByText("2000-01-01 UTC · CostController", { exact: true })).toBeVisible();
  await writeFile(info.outputPath("overview-history-source.json"), JSON.stringify({ scope: "Actual dated CostController API with no model receipts; not live Provider usage", dates: days, fields_saved: true, reload_restored: true, model_calls: 0, source: "existing /api/v1/usage" }, null, 2));
  await page.screenshot({ path: info.outputPath("overview-history-source.png"), fullPage: true });
});

test("Grouped Studio controls preserve bilingual Provider drafts and add real Workflow modules without executing", async ({ page }, info) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  const mutations: string[] = [], errors: string[] = [];
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(request.url()); });
  page.on("pageerror", error => errors.push(error.message));
  await open(page);
  await changeLanguage(page, "zh");
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.layout.v1") || "{}").locale)).toBe("zh");
  await page.getByRole("button", { name: "添加面板", exact: true }).click();
  const library = page.getByRole("region", { name: "Panel library", exact: true });
  await expect(library.getByRole("button", { name: "模型", exact: true })).toBeHidden();
  await library.locator("summary").filter({ hasText: "资源" }).click();
  await library.getByRole("button", { name: "模型", exact: true }).click();
  const providers = page.getByRole("region", { name: "服务商设置", exact: true });
  await providers.getByRole("button", { name: "添加服务商" }).click();
  await providers.getByLabel("协议模板", { exact: true }).selectOption("deepseek");
  await expect(providers.getByLabel("端点", { exact: true })).toBeHidden();
  await providers.getByLabel("厂商模型 ID", { exact: true }).fill("deepseek-chat");
  await providers.getByLabel("凭据引用", { exact: true }).fill("env:FAKE_STUDIO_KEY");
  await providers.screenshot({ path: info.outputPath("models-essential-settings-zh-source.png") });
  await changeLanguage(page, "en");
  const english = page.getByRole("region", { name: "Provider settings", exact: true });
  await expect(english.getByLabel("Vendor model ID", { exact: true })).toHaveValue("deepseek-chat");
  await expect(english.getByLabel("Credential reference", { exact: true })).toHaveValue("env:FAKE_STUDIO_KEY");
  await english.getByLabel("Credential reference", { exact: true }).fill("sk-FAKE-NOT-A-REAL-CREDENTIAL");
  await english.getByRole("button", { name: "Save Provider", exact: true }).click();
  await expect(english.getByRole("alert")).toContainText("reference");
  await expect(english.getByRole("alert")).not.toContainText("sk-FAKE");
  expect(mutations).toEqual([]);
  await english.getByRole("button", { name: "Cancel editing" }).click();
  await english.getByRole("button", { name: "Manage credentials" }).click();
  await expect(page.getByRole("button", { name: "Store or Rotate", exact: true })).toBeDisabled();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("desktop application");
  await closeSettings(page);
  await revealView(page, "Workflow Builder");
  const builder = page.getByRole("region", { name: "Workflow Builder", exact: true });
  await expect(builder.getByRole("button", { name: "Add step", exact: true })).toBeEnabled();
  await builder.locator(".react-flow__pane").click({ button: "right", position: { x: 180, y: 220 } });
  const menu = page.getByRole("menu", { name: "Add workflow module" });
  await expect(menu).toBeVisible();
  await builder.screenshot({ path: info.outputPath("workflow-module-context-menu-source.png") });
  await expect(menu.getByRole("menuitem", { name: /Command/ })).toBeDisabled();
  await menu.getByRole("menuitem", { name: "Value / transform", exact: true }).click();
  await expect(builder.locator(".react-flow__node")).toHaveCount(2);
  await expect(builder.getByLabel("Transform value", { exact: true })).toBeVisible();
  await expect(builder.getByLabel("Step parameters", { exact: true })).toBeHidden();
  await builder.getByLabel("Transform value", { exact: true }).fill("readable-value");
  await builder.locator(".react-flow__pane").click({ button: "right", position: { x: 180, y: 220 } });
  await expect(menu).toBeFocused();
  expect(await menu.getByRole("menuitem").evaluateAll(items => items.every(item => (item as HTMLButtonElement).disabled))).toBe(true);
  await page.keyboard.press("Escape"); await expect(menu).toBeHidden();
  await expect(builder.getByLabel("Transform value", { exact: true })).toHaveValue("readable-value");
  await builder.getByRole("button", { name: "Apply parameters", exact: true }).click();
  await builder.getByRole("button", { name: "Validate", exact: true }).click();
  await expect(builder.getByRole("status")).toContainText("VALID");
  await builder.getByLabel("Workflow canvas", { exact: true }).focus(); await page.keyboard.press("Shift+F10");
  await expect(menu.getByRole("menuitem", { name: "Value / transform", exact: true })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(menu.getByRole("menuitem", { name: "Condition check", exact: true })).toBeFocused();
  await page.keyboard.press("Escape"); await expect(menu).toBeHidden();
  await expect(builder.getByLabel("Workflow canvas", { exact: true })).toBeFocused();
  await changeLanguage(page, "zh");
  await builder.getByRole("button", { name: "验证", exact: true }).click();
  await builder.screenshot({ path: info.outputPath("workflow-grouped-controls-zh-source.png") });
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("apeir.studio.layout.v1") || "{}").locale)).toBe("zh");
  await expect.poll(() => mutations.length).toBe(2);
  expect(mutations.map(url => new URL(url).pathname)).toEqual(["/api/v1/workflow/validate", "/api/v1/workflow/validate"]); expect(errors).toEqual([]);
  await info.attach("progressive-controls-scope", { body: JSON.stringify({ runtime: "real authenticated model-disabled Runtime", workflow_execution_requests: 0, validation_requests: 2, inference_calls: 0, bilingual_draft_preserved: true, raw_key_rejected: true, keyboard_context_menu: true, native_install: "NOT_RUN" }), contentType: "application/json" });
});

test("Settings and bounded splitters preserve original panel drafts and restore wide-screen geometry", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const mutations: string[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => { if (request.url().includes("/api/") && !["GET", "OPTIONS"].includes(request.method())) mutations.push(new URL(request.url()).pathname); });
  await open(page);
  await page.getByRole("button", { name: /example.py/ }).click();
  const editor = page.getByRole("textbox", { name: "Code editor", exact: true });
  const original = await editor.inputValue();
  await editor.fill("UNSAVED_BOUNDED_SPLIT_DRAFT");
  const chat = page.getByRole("region", { name: "AI conversation", exact: true });
  const prompt = chat.getByRole("textbox");
  await prompt.fill("UNSENT_BOUNDED_SPLIT_PROMPT");
  await expect(page.getByLabel("Studio language", { exact: true })).toHaveCount(0);
  await changeLanguage(page, "zh");
  await changeTheme(page, "dark");
  await (await settings(page)).screenshot({ path: info.outputPath("studio-settings-zh-source.png"), animations: "disabled" });
  await closeSettings(page);
  await changeLanguage(page, "en");
  await expect(editor).toHaveValue("UNSAVED_BOUNDED_SPLIT_DRAFT");
  await expect(prompt).toHaveValue("UNSENT_BOUNDED_SPLIT_PROMPT");
  const chatHost = page.locator(".studio-panel-host").filter({ has: chat });
  const editorHost = page.locator(".studio-panel-host").filter({ has: editor });
  for (const x of [0, 1500]) {
    const divider = await page.locator(".studio-dock .flexlayout__splitter").first().boundingBox();
    if (!divider) throw new Error("Expected the real docking splitter");
    await page.mouse.move(divider.x + divider.width / 2, divider.y + divider.height / 2);
    await page.mouse.down(); await page.mouse.move(x, divider.y + divider.height / 2, { steps: 8 }); await page.mouse.up();
    await expect.poll(async () => Math.round((await chatHost.boundingBox())?.width || 0)).toBeGreaterThanOrEqual(320);
    await expect.poll(async () => Math.round((await editorHost.boundingBox())?.width || 0)).toBeGreaterThanOrEqual(380);
  }
  await expect.poll(() => page.evaluate(() => !!localStorage.getItem("apeir.studio.layout.v1"))).toBe(true);
  const geometry = () => page.evaluate(() => {
    const root = JSON.parse(localStorage.getItem("apeir.studio.layout.v1")!).layout;
    return root.children.map((group: { id: string; weight: number }) => [group.id, group.weight]);
  });
  await page.keyboard.press("Control+Alt+s");
  const wide = await geometry();
  await page.setViewportSize({ width: 640, height: 800 });
  await expect(page.locator(".studio-compact-label")).toBeVisible();
  await revealView(page, "Workspace Editor");
  await expect(editor).toHaveValue("UNSAVED_BOUNDED_SPLIT_DRAFT");
  await revealView(page, "Chat");
  await expect(prompt).toHaveValue("UNSENT_BOUNDED_SPLIT_PROMPT");
  await expect(chat).toHaveCount(1);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.keyboard.press("Control+Alt+s");
  expect(await geometry()).toEqual(wide);
  expect(await page.evaluate(() => localStorage.getItem("apeir.studio.layout.v1"))).not.toContain('"maximized":true');
  await page.screenshot({ path: info.outputPath("studio-compact-navigation-source.png"), animations: "disabled" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.locator(".studio-compact-label")).toHaveCount(0);
  await expect(editor).toBeVisible(); await expect(chat).toBeVisible();
  await expect(editor).toHaveValue("UNSAVED_BOUNDED_SPLIT_DRAFT");
  await expect(prompt).toHaveValue("UNSENT_BOUNDED_SPLIT_PROMPT");
  await editor.fill(original); await prompt.fill("");
  await page.reload(); await expect(chat).toBeVisible(); await expect(editor).toBeVisible();
  expect(await geometry()).toEqual(wide);
  expect(mutations).toEqual([]); expect(errors).toEqual([]);
  await info.attach("bounded-layout-scope", { body: JSON.stringify({ runtime: "actual authenticated model-disabled API", settings_preserved_drafts: true, actual_splitter_limits: [320, 380], compact_did_not_replace_layout: true, mutations, native_gui: "NOT_RUN" }), contentType: "application/json" });
});
