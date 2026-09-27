import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const store = mkdtempSync(path.join(tmpdir(), "ps3-browser-"));
export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  workers: 1,
  fullyParallel: false,
  reporter: [
    ["list"],
    ["junit", { outputFile: "../../reports/tests_browser.xml" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:3018",
    viewport: { width: 1440, height: 1000 },
    headless: true,
    launchOptions: { args: ["--disable-gpu"] },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command:
        "../backend/.venv/bin/uvicorn main:app --app-dir ../backend --host 127.0.0.1 --port 8018",
      url: "http://127.0.0.1:8018/api/health",
      timeout: 30_000,
      reuseExistingServer: false,
      env: { SENTINEL_STORE: store },
    },
    {
      command: "npm run start -- --hostname 127.0.0.1 --port 3018",
      url: "http://127.0.0.1:3018/analyze",
      timeout: 60_000,
      reuseExistingServer: false,
      env: {
        NEXT_DIST_DIR: ".next-engineering",
        SENTINEL_API_ORIGIN: "http://127.0.0.1:8018",
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
