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
