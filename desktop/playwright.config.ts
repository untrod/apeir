import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5184", viewport: { width: 1600, height: 1000 }, launchOptions: { chromiumSandbox: true } },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 5184", url: "http://127.0.0.1:5184", reuseExistingServer: false },
});
