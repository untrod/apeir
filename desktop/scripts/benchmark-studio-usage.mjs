/** Owned model-disabled Runtime + two actual static frontend revisions. No native/model claim. */
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { mkdir } from "node:fs/promises";
import { chromium, expect } from "@playwright/test";
import { spawn, execFileSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile, access } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";

const flags = new Map();
const names = new Set(["--baseline-checkout", "--candidate-checkout", "--runtime-checkout", "--python", "--output", "--scenario"]);
for (let i = 2; i < process.argv.length; i += 2) {
  if (!names.has(process.argv[i]) || flags.has(process.argv[i]) || !process.argv[i + 1]) throw Error("Invalid or repeated qualification argument");
  flags.set(process.argv[i], process.argv[i + 1]);
}
const required = name => { const value = flags.get(name); if (!value) throw Error(`Missing ${name}`); return value; };
const scenario = flags.get("--scenario") || "usage";
if (!["usage", "overview"].includes(scenario)) throw Error("Unsupported benchmark scenario");
const baseline = resolve(required("--baseline-checkout")), candidate = resolve(required("--candidate-checkout"));
const backend = resolve(required("--runtime-checkout")), python = resolve(required("--python")), output = resolve(required("--output"));
try { await access(output); throw Error("Output exists; choose a new evidence file"); } catch (error) { if (error.code !== "ENOENT") throw error; }
const sha = root => execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim();
for (const root of [baseline, candidate, backend]) if (execFileSync("git", ["-C", root, "status", "--porcelain"], { encoding: "utf8" }).trim()) throw Error("Qualification requires clean candidate and Runtime checkouts");
const harnessDigest = createHash("sha256").update(await readFile(new URL(import.meta.url))).digest("hex");
const modules = fileURLToPath(new URL("../node_modules/", import.meta.url));
const directory = await mkdtemp(join(tmpdir(), "apeir-usage-benchmark-"));
const token = `APEIR_FAKE_ONLY_USAGE_BENCH_${randomUUID()}`;
const children = [];
let browser;
async function port() { const server = createServer(); await new Promise(r => server.listen(0, "127.0.0.1", r)); const value = server.address().port; await new Promise(r => server.close(r)); return value; }
function launch(args, cwd, env) { const child = spawn(python, args, { cwd, env, stdio: "ignore" }); child.on("error", () => {}); children.push(child); return child; }
async function ready(url, headers = {}) { const until = performance.now() + 10000; while (performance.now() < until) { try { if ((await fetch(url, { headers, signal: AbortSignal.timeout(500) })).ok) return; } catch { /* Only readiness GETs retry, never model or effect operations. */ } await new Promise(r => setTimeout(r, 50)); } throw Error("Owned service startup failed"); }
async function stop(child) { if (child.exitCode !== null) return; await new Promise((resolve, reject) => { const timeout = setTimeout(() => { child.kill("SIGKILL"); reject(Error("Owned service needed forced cleanup")); }, 5000); child.once("exit", () => { clearTimeout(timeout); resolve(); }); child.kill("SIGTERM"); }); }
async function fixture(root, name) {
  const folder = join(directory, name); await mkdir(folder);
  if (scenario === "overview") {
    await build({ configFile: false, root: join(root, "desktop"), plugins: [react()], envPrefix: "APEIR_BENCH_NO_ENV_", logLevel: "silent", build: { outDir: join(folder, "dist"), target: "esnext" } });
    return join(folder, "dist");
  }
  await writeFile(join(folder, "index.html"), '<!doctype html><html><body><div id="root"></div><script type="module" src="/entry.tsx"></script></body></html>');
  await writeFile(join(folder, "entry.tsx"), `import React from "react"; import {createRoot} from "react-dom/client"; import {StatusBar} from ${JSON.stringify(join(root, "desktop/src/components/StatusBar.tsx"))}; import {ThemeProvider} from ${JSON.stringify(join(root, "desktop/src/theme.tsx"))}; createRoot(document.getElementById("root")!).render(<ThemeProvider><p>Qualification fixture: two existing status bars, not the full Desktop.</p><StatusBar/><StatusBar/></ThemeProvider>);`);
  await build({ configFile: false, root: folder, plugins: [react()], envPrefix: "APEIR_BENCH_NO_ENV_", logLevel: "silent", resolve: { alias: { react: join(modules, "react"), "react-dom": join(modules, "react-dom") } }, build: { outDir: "dist", target: "esnext" } });
  return join(folder, "dist");
}
try {
  const baselineApp = await fixture(baseline, "baseline"), candidateApp = await fixture(candidate, "candidate");
  const apiPort = await port(), api = `http://127.0.0.1:${apiPort}`;
  // Initialize only the owned fixture's canonical Controller identity. An
  // unprovisioned Controller remains UNKNOWN in the product, not an empty mesh.
  if (scenario === "overview") execFileSync(python, ["-c", "from pathlib import Path; from nous_runtime.node_runtime.relay import NodeRelayServer; import sys; NodeRelayServer(state_dir=Path(sys.argv[1]) / '.nous' / 'relay')", directory], { cwd: backend, env: { ...process.env, NOUS_WORKSPACE_ROOT: directory }, stdio: "pipe" });
  launch(["-m", "nous_runtime.cli.main", "--no-intelligence", "runtime-api", "start", "--port", String(apiPort)], backend, { ...process.env, NOUS_WORKSPACE_ROOT: directory, NOUS_API_TOKEN: token });
  await ready(`${api}/api/v1/status`, { Authorization: `Bearer ${token}` });
  const addresses = {};
  for (const [name, path] of [["baseline", baselineApp], ["candidate", candidateApp]]) {
    const selected = await port(); addresses[name] = `http://127.0.0.1:${selected}`;
    launch(["-m", "http.server", String(selected), "--bind", "127.0.0.1", "--directory", path], directory, process.env); await ready(addresses[name]);
  }
  browser = await chromium.launch({ headless: true, chromiumSandbox: true });
  const samples = [];
  const browserCDP = await browser.newBrowserCDPSession();
  const processCPU = async () => new Map((await browserCDP.send("SystemInfo.getProcessInfo")).processInfo.map(item => [item.id, { type: item.type, seconds: item.cpuTime }]));
  for (let pair = 0; pair < 3; pair++) for (const name of pair % 2 ? ["candidate", "baseline"] : ["baseline", "candidate"]) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    try {
      const page = await context.newPage(); let requests = 0, usageResponses = 0, mutations = 0; const errors = [], failures = [], apiReads = {}; let interaction = {};
      page.on("pageerror", error => errors.push(error.message));
      page.on("request", request => { if (request.url().startsWith(api) && request.method() === "GET") { const path = new URL(request.url()).pathname; apiReads[path] = (apiReads[path] || 0) + 1; } if (request.url() === `${api}/api/v1/usage`) requests++; if (request.url().startsWith(api) && !["GET", "OPTIONS"].includes(request.method())) mutations++; });
      page.on("response", response => { if (response.url() === `${api}/api/v1/usage`) usageResponses++; if (response.url().startsWith(api) && response.status() >= 400) failures.push({ path: new URL(response.url()).pathname, status: response.status() }); });
      await page.addInitScript(({ api, token, scenario }) => { sessionStorage.setItem("nous_server_url", api); sessionStorage.setItem("nous_server_token", token);
        if (scenario === "overview") localStorage.setItem("apeir.studio.layout.v1", JSON.stringify({ schemaVersion: 1, kind: "dashboard", name: "Measured Overview", locale: "en", layout: { type: "row", id: "root", children: [{ type: "tabset", id: "main", children: [{ type: "tab", id: "overview", component: "dashboard", config: { schemaVersion: 1, widgets: ["runtime", "kernel", "nodes", "works", "usage", "evidence"].map((type, i) => ({ id: `widget-${i + 1}`, type, title: "", x: i % 3 * 4, y: Math.floor(i / 3) * 4, w: 4, h: 4, paused: false })) } }] }] } }));
      }, { api, token, scenario });
      await page.goto(addresses[name]);
      if (scenario === "overview") {
        const online = page.locator('[data-widget-id="widget-1"] [data-state="ONLINE"]');
        await expect(online).toBeVisible();
        let started = performance.now(); await page.reload(); await expect(online).toBeVisible(); const warm_restore_ms = performance.now() - started;
        started = performance.now(); await page.getByRole("button", { name: "Open Chat", exact: true }).click();
        const composer = page.getByRole("textbox", { name: "Message", exact: true }); await expect(composer).toBeVisible(); const overview_to_chat_ms = performance.now() - started;
        started = performance.now(); await composer.fill("Benchmark draft; never submit"); const composer_fill_ms = performance.now() - started;
        started = performance.now(); await page.getByRole("button", { name: "Open Dashboard", exact: true }).click(); await expect(online).toBeVisible(); const chat_to_overview_ms = performance.now() - started;
        await page.getByRole("button", { name: "Edit layout", exact: true }).click();
        const grip = page.getByRole("button", { name: "Move Runtime", exact: true }), bounds = await grip.boundingBox();
        if (!bounds) throw Error("Runtime card missing");
        started = performance.now(); await grip.hover(); await page.mouse.down(); await page.mouse.move(bounds.x + bounds.width / 2 + 1000, bounds.y + bounds.height / 2, { steps: 12 }); await page.mouse.up();
        await expect.poll(async () => (await grip.boundingBox()).x).toBeGreaterThan(bounds.x + 400); const pointer_move_ms = performance.now() - started;
        await page.getByRole("button", { name: "Done editing", exact: true }).click();
        interaction = { warm_restore_ms, overview_to_chat_ms, composer_fill_ms, chat_to_overview_ms, pointer_move_ms };
      } else await expect(page.getByText("Runtime API", { exact: true })).toHaveCount(2);
      await expect.poll(() => usageResponses).toBeGreaterThan(0);
      await expect.poll(() => requests - usageResponses).toBe(0);
      const cdp = await context.newCDPSession(page); await cdp.send("Performance.enable");
      const metrics = async () => Object.fromEntries((await cdp.send("Performance.getMetrics")).metrics.map(item => [item.name, item.value]));
      const before = await metrics(), cpuBefore = await processCPU(), initial = requests, started = performance.now();
      // Explicit measurement window, unrelated to execution deadlines or retry semantics.
      await new Promise(r => setTimeout(r, 11000));
      const after = await metrics(), cpuAfter = await processCPU();
      const missingProcesses = [...cpuBefore.keys()].filter(id => !cpuAfter.has(id)).length;
      const cpuDelta = [...cpuAfter].reduce((sum, [id, item]) => sum + Math.max(0, item.seconds - (cpuBefore.get(id)?.seconds ?? 0)), 0);
      const visibleWindow = performance.now() - started;
      let hidden = {};
      if (scenario === "overview") {
        const beforeHidden = { ...apiReads }, hiddenStarted = performance.now();
        await page.evaluate(() => { Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" }); document.dispatchEvent(new Event("visibilitychange")); });
        await new Promise(resolve => setTimeout(resolve, 6000));
        hidden = { instrumented_hidden_window_ms: performance.now() - hiddenStarted, hidden_api_reads: Object.fromEntries(Object.entries(apiReads).map(([path, count]) => [path, count - (beforeHidden[path] || 0)])) };
      }
      if (errors.length || failures.length || mutations) { await writeFile(`${output}.failure.json`, JSON.stringify({ pair, frontend: name, completed_samples: samples, errors, failures, mutations }, null, 2), { flag: "wx" }); throw Error("Sample had browser/API errors or Runtime mutations; no valid improvement result"); }
      const sample = { pair, frontend: name, window_ms: visibleWindow, actual_total_window_ms: performance.now() - started, initial_usage_reads: initial, polling_usage_reads: requests - initial, total_usage_reads: requests, browser_process_cpu_seconds: missingProcesses ? null : cpuDelta, missing_process_cpu_samples: missingProcesses, renderer_task_seconds: after.TaskDuration - before.TaskDuration, renderer_heap_bytes_after: after.JSHeapUsedSize, api_failures: failures.length, runtime_mutations: mutations, api_reads: apiReads, ...interaction, ...hidden };
      samples.push(sample); console.log(JSON.stringify(sample));
    } finally { await context.close(); }
  }
  const rank = (values, fraction) => [...values].sort((a, b) => a - b)[Math.ceil(values.length * fraction) - 1];
  const interactionSummary = Object.fromEntries(["baseline", "candidate"].map(name => [name, Object.fromEntries(["warm_restore_ms", "overview_to_chat_ms", "composer_fill_ms", "chat_to_overview_ms", "pointer_move_ms"].filter(key => samples.some(row => row.frontend === name && key in row)).map(key => {
    const values = samples.filter(row => row.frontend === name).map(row => row[key]);
    return [key, { p50: rank(values, 0.5), p95: rank(values, 0.95), p99: rank(values, 0.99), n: values.length }];
  }))]));
  const summary = Object.fromEntries(["baseline", "candidate"].map(name => { const rows = samples.filter(row => row.frontend === name); return [name, { n: rows.length, usage_reads: rows.map(row => row.total_usage_reads), renderer_task_seconds_p50: rank(rows.map(row => row.renderer_task_seconds), 0.5), renderer_task_seconds_p95: rank(rows.map(row => row.renderer_task_seconds), 0.95), renderer_task_seconds_p99: rank(rows.map(row => row.renderer_task_seconds), 0.99), browser_cpu_seconds: rows.map(row => row.browser_process_cpu_seconds), browser_cpu_p50: rows.every(row => row.browser_process_cpu_seconds !== null) ? rank(rows.map(row => row.browser_process_cpu_seconds), 0.5) : null, browser_cpu_p95: rows.every(row => row.browser_process_cpu_seconds !== null) ? rank(rows.map(row => row.browser_process_cpu_seconds), 0.95) : null, browser_cpu_p99: rows.every(row => row.browser_process_cpu_seconds !== null) ? rank(rows.map(row => row.browser_process_cpu_seconds), 0.99) : null, renderer_heap_bytes_max: Math.max(...rows.map(row => row.renderer_heap_bytes_after)) }]; }));
  await writeFile(output, JSON.stringify({ baseline_sha: sha(baseline), harness_sha256: harnessDigest, candidate_sha: sha(candidate), runtime_sha: sha(backend), node: process.version, platform: `${process.platform}/${process.arch}`, chromium: browser.version(), scenario: scenario === "overview" ? "Actual production-built Studio App, equivalent v1 Overview, warm reload, Chat switch, unsubmitted composer draft, pointer move and idle window; same model-disabled Runtime with an owned provisioned Controller identity and no connected Nodes, alternating paired order" : "Isolated qualification fixture with two actual existing collapsed StatusBar components, same Vite/React compiler, same owned model-disabled Runtime, alternating paired order; not full Desktop", limitation: "Exploratory n=3 per build; p95/p99 are sample maxima, not stable tail estimates. Renderer TaskDuration is not CPU time. SystemInfo CPU covers this owned browser process group, not the Runtime or whole host; process exits make the CPU sample unknown. Heap-after is not peak memory. Browser mode only: no Tauri/Windows/native process tree, installation size, model latency/load, Provider cost or Token saving qualification. Composer fill and pointer timing include browser automation overhead. Hidden-document sampling explicitly instruments visibilityState; it is not OS window-minimization or native process-tree qualification.", samples, summary, interaction_summary: interactionSummary }, null, 2), { flag: "wx" });
} finally { if (browser) await browser.close(); const results = await Promise.allSettled(children.map(stop)); await rm(directory, { recursive: true, force: true }); if (results.some(result => result.status === "rejected")) throw Error("Owned benchmark process cleanup failed"); }
